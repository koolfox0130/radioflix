"""Fail-closed candidate policy for ordinary authenticated-area captures."""

from dataclasses import dataclass
from datetime import datetime

from radioflix.timefree.capture.source.station_area import valid_area_id


@dataclass(frozen=True)
class NormalAreaCandidate:
    station_id: str
    starts_at: datetime
    ends_at: datetime
    timefree_expires_at: datetime
    areafree: int = 0


def configured_area_mismatch(configured_area: str, authenticated_area: str) -> bool:
    if not valid_area_id(configured_area) or not valid_area_id(authenticated_area):
        raise ValueError('area_unknown')
    return configured_area != authenticated_area


def select_normal_area_candidates(candidates, station_areas, authenticated_area, now):
    """Return ended, in-window, areafree=0 candidates in ascending duration order."""
    if not valid_area_id(authenticated_area) or not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('area_or_time_unknown')
    selected = []
    for candidate in candidates:
        if (not isinstance(candidate, NormalAreaCandidate)
                or isinstance(candidate.areafree, bool)
                or not isinstance(candidate.areafree, int) or candidate.areafree != 0):
            continue
        station = candidate.station_id
        station_area = station_areas.get(station) if isinstance(station_areas, dict) else None
        if not isinstance(station, str) or not station or not valid_area_id(station_area):
            continue
        if station_area != authenticated_area:
            continue
        starts, ends, expires = candidate.starts_at, candidate.ends_at, candidate.timefree_expires_at
        if not all(isinstance(value, datetime) and value.tzinfo is not None
                   for value in (starts, ends, expires)):
            continue
        duration = (ends - starts).total_seconds()
        if not 180 <= duration <= 600 or ends > now or now >= expires:
            continue
        selected.append((duration, starts, station, candidate))
    selected.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in selected)
