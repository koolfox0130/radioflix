"""Current pc_html5 full-key extraction contract, with the upstream fallback."""

import re

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure


# This value is the public fallback used by current yt-dlp and rec_radiko_ts.
# It is key material: callers must not log or include it in exceptions.
_UPSTREAM_FALLBACK = b'bcd151073c03b352e1ef2fd66c32209da9ca0afa'
_PC_HTML5_KEY = re.compile(
    r"RadikoJSPlayer\([^,]*,\s*(['\"])pc_html5\1,\s*(['\"])(?P<fullkey>[0-9a-f]+)\2,\s*{"
)
MAX_PLAYER_JS_BYTES = 2 * 1024 * 1024
MAX_FULL_KEY_BYTES = 4096


def extract_pc_html5_full_key(player_js: bytes) -> bytes:
    """Extract the pc_html5 key from current player JS or use upstream fallback.

    The raw JavaScript document is never sliced using auth offsets. Offsets are
    applied later to this extracted ASCII full key.
    """
    if not isinstance(player_js, bytes) or not player_js or len(player_js) > MAX_PLAYER_JS_BYTES:
        raise SourceFailure(SourceCode.INVALID_RESPONSE)
    try:
        text = player_js.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise SourceFailure(SourceCode.INVALID_RESPONSE) from None
    match = _PC_HTML5_KEY.search(text)
    full_key = match.group('fullkey').encode('ascii') if match else _UPSTREAM_FALLBACK
    if not full_key or len(full_key) > MAX_FULL_KEY_BYTES:
        raise SourceFailure(SourceCode.INVALID_RESPONSE)
    return full_key
