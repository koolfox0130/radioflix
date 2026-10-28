"""Trusted Radiko station-to-area metadata source."""

import re
import xml.etree.ElementTree as ET

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, bounded_timeout
from radioflix.timefree.capture.source.transport import HttpTransport


STATION_REGION_URL = 'https://radiko.jp/v3/station/region/full.xml'
MAX_STATION_REGION_BYTES = 2 * 1024 * 1024
_STATION_ID = re.compile(r'[A-Z0-9-]{2,24}')


def valid_area_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'JP(?:0[1-9]|[1-3][0-9]|4[0-7])', value) is not None


class StationAreaSource:
    """Fetch official station region metadata through the shared safe transport."""

    def __init__(self, transport: HttpTransport, *, timeout: RequestTimeout = RequestTimeout()):
        self.transport = transport
        self.timeout = timeout

    def load(self, *, timeout_seconds=15) -> dict[str, str]:
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
        for node in root.iter():
            if node.tag.rsplit('}', 1)[-1] != 'station':
                continue
            station = next((child.text.strip() for child in node
                            if child.tag.rsplit('}', 1)[-1] == 'id' and child.text), None)
            area = next((child.text.strip() for child in node
                         if child.tag.rsplit('}', 1)[-1] == 'area_id' and child.text), None)
            if station is None and area is None:
                continue
            if (station is None or not _STATION_ID.fullmatch(station)
                    or not valid_area_id(area) or station in mapping):
                raise SourceFailure(SourceCode.INVALID_RESPONSE)
            mapping[station] = area
        if not mapping:
            raise SourceFailure(SourceCode.INVALID_RESPONSE)
        return mapping
