"""Read-only catalogue facade for normal files and verified timefree assets."""
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from radioflix.timefree.preflight import _parse_recording_name
from radioflix.timefree.worker import completed_assets, safe_file


_TIMEFREE_PROGRAM_ID = re.compile(r"^tf~[0-9a-f]{32}$")
_TIMEFREE_FILENAME = re.compile(r"^20\d{6}_\d{4}_\d{4}_tf-([a-f0-9]{64})\.wav$")


class RecordingCatalog:
    """Keep the legacy filesystem catalogue intact and add verified timefree assets."""

    def __init__(self, programs, timefree_store=None, timefree_root=None, *, include_fixture=False):
        self.programs_service = programs
        self.timefree_store = timefree_store
        self.timefree_root = Path(timefree_root) if timefree_root else None
        self.include_fixture = include_fixture

    @staticmethod
    def _program_id(station, title):
        digest = hashlib.sha256(f"{station}\0{title}".encode("utf-8")).hexdigest()[:32]
        # '~' is URL-safe but outside the legacy Base64url program-ID alphabet.
        return f"tf~{digest}"

    @staticmethod
    def _filename(asset):
        start, end = asset["start"], asset["end"]
        return (f"{start:%Y%m%d}_{start:%H%M}_{end:%H%M}_tf-"
                f"{asset['episode_id']}.wav")

    def _assets(self):
        if self.timefree_store is None or self.timefree_root is None:
            return []
        return completed_assets(self.timefree_store, self.timefree_root,
                                include_fixture=self.include_fixture)

    def _normal_intervals(self):
        """Index canonical normal filenames so normal recordings win duplicates."""
        root = self.programs_service.radiko_dir
        result = []
        try:
            root_info = root.lstat()
        except FileNotFoundError:
            return result
        except OSError:
            return None
        if not Path(root).is_dir() or Path(root).is_symlink():
            return None
        uncertain = False

        def onerror(_error):
            nonlocal uncertain
            uncertain = True

        for folder, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            if any((Path(folder) / name).is_symlink() for name in dirs):
                uncertain = True
                break
            dirs[:] = list(dirs)
            for name in files:
                path = Path(folder) / name
                if path.suffix.lower() not in {".m4a", ".mp3", ".aac", ".wav"}:
                    continue
                if path.is_symlink():
                    uncertain = True
                    break
                parsed = _parse_recording_name(name)
                if parsed is None:
                    # An unparsed ordinary recording could be the same broadcast;
                    # never expose a timefree duplicate while overlap is unknown.
                    uncertain = True
                    break
                result.append(parsed)
            if uncertain:
                break
        if uncertain:
            return None
        return result

    @staticmethod
    def _broadcast(asset):
        broadcast = asset.get("broadcast")
        if not isinstance(broadcast, dict):
            return None
        station = broadcast.get("station")
        title = broadcast.get("title")
        starts = broadcast.get("starts_at")
        ends = broadcast.get("ends_at")
        ident = broadcast.get("id")
        station_name = broadcast.get("station_name")
        if (not isinstance(station, str) or not re.fullmatch(r"[A-Z0-9_-]{1,16}", station)
                or not isinstance(title, str) or not title.strip() or len(title) > 300
                or not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{64}", ident)):
            return None
        try:
            start = datetime.fromisoformat(starts)
            end = datetime.fromisoformat(ends)
        except (TypeError, ValueError):
            return None
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            return None
        return broadcast, start, end, station, title, ident, (station_name if isinstance(station_name, str) else station)

    def _visible_assets(self):
        normal = self._normal_intervals()
        # If the normal inventory cannot be established safely, do not risk
        # surfacing a duplicate timefree copy.
        if normal is None:
            return []
        visible = []
        for asset in self._assets():
            parsed = self._broadcast(asset)
            if not parsed:
                continue
            broadcast, start, end, station, title, ident, station_name = parsed
            if (asset.get("broadcast_episode_id") != ident or asset.get("station") != station
                    or asset.get("title") != title or asset.get("start_at") != broadcast.get("starts_at")
                    or asset.get("end_at") != broadcast.get("ends_at")):
                continue
            # Existing normal recordings remain the canonical visible copy.
            if any(s == station and ns < end and start < ne for s, ns, ne in normal):
                continue
            try:
                audio = safe_file(self.timefree_root, asset["relative_path"])
            except (OSError, ValueError, TypeError, KeyError):
                continue
            visible.append({**asset, "broadcast": broadcast, "start": start, "end": end,
                            "station": station, "title": title, "episode_id": ident,
                            "station_name": station_name, "audio_path": audio})
        return visible

    def _timefree_programs(self):
        groups = {}
        for asset in self._visible_assets():
            key = (asset["station"], asset["title"])
            groups.setdefault(key, []).append(asset)
        result = []
        for (station, title), assets in groups.items():
            station_name = assets[0]["station_name"]
            ident = self._program_id(station, title)
            result.append({"id": ident, "title": title, "station": station,
                           "network": station_name,
                           "category": "タイムフリー", "raw_name": f"timefree:{station}:{title}",
                           "thumbnail_url": None, "source": "timefree"})
        return sorted(result, key=lambda p: (p["title"], p["network"], p["id"]))

    def get_recorded_programs(self):
        # Do not mutate or re-sort the legacy service's records relative to each other.
        normal = [{**item, "source": "normal"} for item in self.programs_service.get_recorded_programs()]
        return normal + self._timefree_programs()

    def find_program(self, program_id):
        for program in self.get_recorded_programs():
            if program["id"] == program_id:
                return program
        return None

    def is_timefree_program_id(self, value):
        return isinstance(value, str) and _TIMEFREE_PROGRAM_ID.fullmatch(value) is not None

    def episodes(self, program_id):
        if not self.is_timefree_program_id(program_id):
            return None
        episodes = []
        for asset in self._visible_assets():
            if self._program_id(asset["station"], asset["title"]) != program_id:
                continue
            filename = self._filename(asset)
            completed_at = asset.get("completed_at")
            try:
                updated_at = datetime.fromisoformat(completed_at).timestamp()
            except (TypeError, ValueError):
                updated_at = asset["end"].timestamp()
            episodes.append({"episode_id": f"timefree-{asset['episode_id']}",
                             "source": "timefree", "filename": filename,
                             "title": asset["title"], "size": asset["size"],
                             "station": asset["station"],
                             "updated_at": updated_at,
                             "start_at": asset["broadcast"]["starts_at"],
                             "end_at": asset["broadcast"]["ends_at"],
                             "duration": asset["duration"],
                             "audio_url": f"/audio/{program_id}/{quote(filename, safe='')}"})
        return sorted(episodes, key=lambda item: (item["start_at"], item["episode_id"]), reverse=True)

    def audio_path(self, program_id, filename):
        if not self.is_timefree_program_id(program_id):
            return None
        match = _TIMEFREE_FILENAME.fullmatch(filename) if isinstance(filename, str) else None
        if not match:
            return None
        for asset in self._visible_assets():
            if (asset["episode_id"] != match[1]
                    or self._program_id(asset["station"], asset["title"]) != program_id
                    or filename != self._filename(asset)):
                continue
            try:
                row = self.timefree_store.get(asset["asset_id"])
                if not row or row["state"] != "completed":
                    return None
                return safe_file(self.timefree_root, row["output_path"])
            except (OSError, ValueError, TypeError, KeyError):
                return None
        return None
