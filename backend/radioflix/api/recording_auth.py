"""Fail closed when real recording writes are enabled.

An authenticated reverse proxy may inject this server-side credential. Never
publish it to JavaScript. Without configured authentication, real writes fail.
"""
import os
import secrets
from pathlib import Path
from fastapi import HTTPException, Request


def recording_authorization(service):
    def authorize(request: Request):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return
        token_file = os.getenv('RADIOFLIX_WRITE_TOKEN_FILE', '')
        if not token_file and not getattr(service, 'writes_enabled', False):
            return  # Existing local waiting-write mode; no recorder access.
        try:
            token = Path(token_file).read_text().strip() if token_file else ''
        except (OSError, UnicodeError):
            token = ''
        header = request.headers.get('authorization', '')
        if len(token) < 32 or not secrets.compare_digest(header.encode(), ('Bearer ' + token).encode()):
            raise HTTPException(403, detail={'code': 'authentication', 'message': '予約操作の認証を確認してください。'})
        # Browsers must go through the same authenticated origin; proxy strips
        # client credentials and injects its own only after user authorization.
        origin = request.headers.get('origin')
        allowed = os.getenv('RADIOFLIX_WRITE_ORIGIN', '')
        if origin and (not allowed or origin != allowed):
            raise HTTPException(403, detail={'code': 'origin', 'message': '予約操作の接続元を確認してください。'})
    return authorize
