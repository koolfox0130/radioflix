"""Trusted Radiko station-to-area metadata source."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, bounded_timeout
from radioflix.timefree.capture.source.transport import HttpTransport


STATION_REGION_URL = 'https://radiko.jp/v3/station/region/full.xml'
MAX_STATION_REGION_BYTES = 2 * 1024 * 1024
_STATION_ID = re.compile(r'[A-Z0-9_-]{1,24}')


def valid_area_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'JP(?:0[1-9]|[1-3][0-9]|4[0-7])', value) is not None


class StationAreaSource:
    """Fetch official station region metadata through the shared safe transport."""

    def __init__(self, transport: HttpTransport, *, timeout: RequestTimeout = RequestTimeout()):
        self.transport = transport
        self.timeout = timeout

    def load(self, *, timeout_seconds=15) -> dict[str, str]:
        return dict(self.load_catalog(timeout_seconds=timeout_seconds).area_by_station)

    def load_catalog(self, *, timeout_seconds=15) -> 'StationAreaCatalog':
        try:
            response = self.transport.request(HttpRequest(
                'GET', STATION_REGION_URL,
                timeout=bounded_timeout(self.timeout, timeout_seconds),
                max_response_bytes=MAX_STATION_REGION_BYTES,
            ))
        except SourceFailure:
            raise
        except Exception:
            raise SourceFailure(SourceCode.INVALID_RESPONSE) from None
        if response.status != 200 or not response.body or len(response.body) > MAX_STATION_REGION_BYTES:
            raise SourceFailure(SourceCode.HTTP_REJECTED)
        upper = response.body.upper()
        if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
            raise SourceFailure(SourceCode.INVALID_RESPONSE)
        try:
            root = ET.fromstring(response.body)
        except (ET.ParseError, ValueError, UnicodeError):
            raise SourceFailure(SourceCode.INVALID_RESPONSE) from None
        if root.tag.rsplit('}', 1)[-1] != 'region':
            raise SourceFailure(SourceCode.INVALID_RESPONSE)

        mapping: dict[str, str] = {}
        station_ids: set[str] = set()
        ambiguous: set[str] = set()
        for node in root.iter():
            if node.tag.rsplit('}', 1)[-1] != 'station':
                continue
            station = next((child.text.strip() for child in node
                            if child.tag.rsplit('}', 1)[-1] == 'id' and child.text), None)
            area = next((child.text.strip() for child in node
                         if child.tag.rsplit('}', 1)[-1] == 'area_id' and child.text), None)
            if station is None and area is None:
                continue
            # Region metadata contains entries that are not usable for a
            # normal-area decision. Keep those stations unresolved rather
            # than discarding unrelated, well-formed official mappings.
            if station is None or not _STATION_ID.fullmatch(station):
                continue
            station_ids.add(station)
            if not valid_area_id(area):
                mapping.pop(station, None)
                ambiguous.add(station)
                continue
            if station in ambiguous:
                continue
            if station in mapping:
                mapping.pop(station, None)
                ambiguous.add(station)
                continue
            mapping[station] = area
        if not mapping:
            raise SourceFailure(SourceCode.INVALID_RESPONSE)
        return StationAreaCatalog(mapping, frozenset(station_ids))


@dataclass(frozen=True)
class StationAreaCatalog:
    """Official station IDs and only unambiguous, valid station-area pairs."""

    area_by_station: dict[str, str]
    station_ids: frozenset[str]
