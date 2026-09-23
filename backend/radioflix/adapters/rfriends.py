"""rfriends dependencies stop here. Never include/execute its PHP initializers."""
import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from xml.etree import ElementTree

from radioflix.schemas.reservations import Broadcast, JST, RecordingError


SCHEDULE_UNAVAILABLE_MESSAGE = "放送予定を取得できません。時間をおいて再度お試しください。"
logger = logging.getLogger(__name__)


class NoGatewayRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Never forward the private gateway credential to a redirect target.
        return None


def gateway_open(request, timeout):
    return build_opener(NoGatewayRedirect()).open(request, timeout=timeout)


def normalized_title(value):
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("オールナイトニッポン", "ANN").replace("(ZERO)", "").replace("(クロス)", "").replace("ANNZERO", "ANN0")
    return re.sub(r"[\W_]+", "", value).removeprefix("JUNK").casefold()


class RfriendsAdapter:
    def __init__(self, url=None, token_file=None, area=None):
        self.url = (url if url is not None else os.getenv("RFRIENDS_GATEWAY_URL", "")).rstrip("/")
        self.token_file = token_file or os.getenv("RFRIENDS_TOKEN_FILE", "")
        self.area = area or os.getenv("RFRIENDS_AREA", "JP13")
        self._cache = {}
        self._lock = threading.Lock()

    def _call(self, operation, job):
        if not self.url or not self.token_file:
            raise RecordingError("not_configured", "録音連携が未設定です。管理者に設定を依頼してください。")
        try:
            token = Path(self.token_file).read_text().strip()
            if len(token) < 32:
                raise ValueError("invalid token")
        except (OSError, ValueError):
            raise RecordingError("not_configured", "録音連携の認証設定を確認してください。") from None
        request = Request(self.url + "/execute", json.dumps({"operation": operation, "job": job}).encode(),
                          {"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
        try:
            with gateway_open(request, timeout=45) as response:
                result = json.loads(response.read(65537))
            if not isinstance(result, dict) or result.get("state") not in {"scheduled", "running", "elapsed", "absent", "cancelled"}:
                raise ValueError("invalid response")
            return result
        except HTTPError as error:
            if error.code in (401, 403):
                raise RecordingError("authentication", "録音連携の認証設定を確認してください。") from None
            # Only accept our bounded error codes, never reflect upstream text.
            try:
                code = json.loads(error.read(65537)).get("detail", {}).get("code", "unknown")
                if not isinstance(code, str):
                    code = "unknown"
            except (ValueError, AttributeError):
                code = "unknown"
            messages = {
                "conflict": "同じ時間帯・放送局の予約が既にあります。既存予約は変更していません。",
                "too_late": "開始直前または録音中のため操作できません。",
                "incompatible": "rfriends3の構成が対応条件と異なります。管理者に確認してください。",
                "ownership": "予約データが外部で変更されています。安全のため操作を停止しました。",
                "writes_disabled": "録音側への書き込みが無効です。管理者による連携の有効化が必要です。",
            }
            raise RecordingError(code, messages.get(code, "録音側の結果を確認できません。状態を再確認してください。"),
                                 code not in messages or code == "ownership") from None
        except (OSError, URLError, ValueError):
            raise RecordingError("unreachable", "録音側に接続できないか、結果が不明です。「状態を再確認」を押してください。", True) from None

    def create(self, job):
        return self._call("create", job)

    def inspect(self, job):
        return self._call("inspect", job)

    def cancel(self, job):
        return self._call("cancel", job)

    def _log_schedule_failure(self, date, error, retried):
        status = error.code if isinstance(error, HTTPError) else None
        logger.warning("radiko schedule fetch failed date=%s status=%s exception=%s retry=%s",
                       date, status, type(error).__name__, retried)

    def _fetch_day(self, date):
        url = f"https://radiko.jp/v3/program/date/{date}/{self.area}.xml"
        with urlopen(url, timeout=10) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("invalid XML")
        root = ElementTree.fromstring(data)
        items = []
        for station in root.findall(".//station"):
            for prog in station.findall("./progs/prog"):
                start = datetime.strptime(prog.attrib["ft"], "%Y%m%d%H%M%S").replace(tzinfo=JST)
                end = datetime.strptime(prog.attrib["to"], "%Y%m%d%H%M%S").replace(tzinfo=JST)
                station_id = station.attrib["id"]
                key = hashlib.sha256(f"{station_id}:{start.isoformat()}:{end.isoformat()}".encode()).hexdigest()
                items.append(Broadcast(id=key, station=station_id, region=self.area, title=prog.findtext("title", ""), starts_at=start, ends_at=end))
        return items

    def _day(self, date):
        with self._lock:
            cached = self._cache.get(date)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        if not re.fullmatch(r"JP(?:[1-9]|[1-3][0-9]|4[0-7])", self.area):
            raise RecordingError("configuration", "番組表の地域設定を確認してください。")
        for retried in (False, True):
            try:
                items = self._fetch_day(date)
                break
            except HTTPError as error:
                if error.code == 404:
                    return []
                self._log_schedule_failure(date, error, retried)
                if not retried:
                    time.sleep(0.2)
                    continue
                raise RecordingError("schedule_unavailable", SCHEDULE_UNAVAILABLE_MESSAGE) from None
            except (OSError, URLError) as error:
                self._log_schedule_failure(date, error, retried)
                if not retried:
                    time.sleep(0.2)
                    continue
                raise RecordingError("schedule_unavailable", SCHEDULE_UNAVAILABLE_MESSAGE) from None
            except (ValueError, KeyError, ElementTree.ParseError) as error:
                self._log_schedule_failure(date, error, retried)
                raise RecordingError("schedule_unavailable", SCHEDULE_UNAVAILABLE_MESSAGE) from None
        with self._lock:
            self._cache[date] = (time.monotonic() + 300, items)
            self._cache = {key: value for key, value in self._cache.items() if value[0] > time.monotonic()}
        return items

    def _safe_day(self, date):
        try:
            return self._day(date)
        except RecordingError as error:
            if error.code != "schedule_unavailable":
                raise
            return error

    def broadcasts(self, program):
        match = re.match(r"^(FM_(?:OITA|OKINAWA)|[A-Z0-9-]{2,24})_", program.get("raw_name", ""))
        if not match:
            return []
        station = match[1]
        now = datetime.now(JST)
        # Before 05:00, the current broadcast belongs to yesterday's radio day.
        day = (now - timedelta(hours=5)).date()
        dates = [(day + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self._safe_day, dates))
        failures = [date for date, result in zip(dates, results) if isinstance(result, RecordingError)]
        days = [result for result in results if not isinstance(result, RecordingError)]
        if failures:
            logger.warning("radiko schedule fetch skipped failed days dates=%s", ",".join(failures))
        if not days and failures:
            raise RecordingError("schedule_unavailable", SCHEDULE_UNAVAILABLE_MESSAGE) from None
        title = normalized_title(program["title"])
        unique = {item.id: item for items in days for item in items
                  if item.station == station and normalized_title(item.title) == title
                  and item.starts_at > now + timedelta(minutes=3)}
        return sorted(unique.values(), key=lambda item: item.starts_at)
