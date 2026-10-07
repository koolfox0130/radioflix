"""Public XML only. Never calls the recording gateway."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import urlopen
from xml.etree.ElementTree import ParseError

from radioflix.adapters.rfriends import RfriendsAdapter, MAX_SCHEDULE_BYTES
from radioflix.schemas.reservations import Broadcast, JST, RecordingError


class ScheduleAdapter(RfriendsAdapter):
    def _xml(self, path):
        if not re.fullmatch(r"JP(?:[1-9]|[1-3][0-9]|4[0-7])", self.area):
            raise RecordingError("configuration", "番組表の地域設定を確認してください。")
        for attempt in range(2):
            try:
                with urlopen("https://radiko.jp/v3/" + path, timeout=10) as response:
                    return self._parse_xml(response.read(MAX_SCHEDULE_BYTES + 1))
            except HTTPError as error:
                if error.code == 404:
                    raise RecordingError("not_available", "この日の番組表を取得できませんでした") from None
            except (OSError, ValueError, ParseError):
                pass
            if attempt == 0:
                time.sleep(0.2)
        raise RecordingError("fetch_failed", "この日の番組表を取得できませんでした")

    def stations(self):
        with self._lock:
            cached = self._cache.get("stations")
            if cached and cached[0] > time.monotonic():
                return cached[1]
        root = self._xml(f"station/list/{self.area}.xml")
        items = [{"id": s.findtext("id"), "name": s.findtext("name") or s.findtext("id")}
                 for s in root.findall(".//station") if re.fullmatch(r"[A-Z0-9_-]{1,24}", s.findtext("id", ""))]
        if not items:
            raise RecordingError("fetch_failed", "放送局一覧を取得できませんでした")
        with self._lock:
            self._cache["stations"] = (time.monotonic() + 3600, items)
        return items

    def day(self, date, fresh=False):
        key = date.isoformat()
        with self._lock:
            cached = self._cache.get(key)
            if not fresh and cached and cached[0] > time.monotonic():
                return cached[1]
        result = {"radio_date": key, "timezone": "Asia/Tokyo", "fetched_at": datetime.now(JST).isoformat(),
                  "stale": False, "availability": "ok", "broadcasts": [], "stations": []}
        try:
            root = self._xml(f"program/date/{date:%Y%m%d}/{self.area}.xml")
            for station in root.findall(".//station"):
                sid = station.attrib["id"]
                result["stations"].append(sid)
                for prog in station.findall("./progs/prog"):
                    start = datetime.strptime(prog.attrib["ft"], "%Y%m%d%H%M%S").replace(tzinfo=JST)
                    end = datetime.strptime(prog.attrib["to"], "%Y%m%d%H%M%S").replace(tzinfo=JST)
                    bid = hashlib.sha256(f"{sid}:{start.isoformat()}:{end.isoformat()}".encode()).hexdigest()
                    b = Broadcast(id=bid, station=sid, region=self.area, title=prog.findtext("title", ""), starts_at=start, ends_at=end)
                    metadata = {name: prog.findtext(name) for name in ("pfm", "desc", "info", "img", "genre", "failed_record", "ts_in_ng", "ts_out_ng")}
                    item = {**b.model_dump(mode="json"), "station_name": station.findtext("name", sid),
                            "performer": metadata["pfm"], "provider_program_id": prog.get("id"), "metadata": metadata}
                    item["schedule_revision"] = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    result["broadcasts"].append(item)
            result["broadcasts"].sort(key=lambda b: (b["starts_at"], b["station"]))
            if not result["broadcasts"]:
                result["availability"] = "not_available"
        except RecordingError as error:
            result["availability"] = error.code
        except (ValueError, KeyError):
            result["availability"] = "fetch_failed"
            result["broadcasts"] = []
        with self._lock:
            self._cache[key] = (time.monotonic() + (300 if result["availability"] == "ok" else 15), result)
            self._cache = {k: v for k, v in self._cache.items() if v[0] > time.monotonic()}
        return result

    def days(self, dates):
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(self.day, dates))
