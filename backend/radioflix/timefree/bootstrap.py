"""Fail-closed preflight boundary for a future rfriends3 capture bridge.

The reviewed rfriends3 functions are not invoked here: the upstream timefree
batch function mutates its input queue, while its downloader builds shell
command strings and moves output through normal-recording hooks. A verified
source bundle is necessary, but not sufficient, to make those calls safe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path


class BootstrapBlocked(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Source:
    relative_path: str
    purpose: str
    sha256: str
    required: bool
    functions: tuple[str, ...]


def read_manifest(path: Path) -> tuple[Source, ...]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1 or not isinstance(data.get('sources'), list):
            raise ValueError
        result, seen = [], set()
        for item in data['sources']:
            relative, digest, functions = item['relative_path'], item['sha256'], item['functions']
            if (not isinstance(relative, str) or relative.startswith('/') or
                    any(part in ('', '.', '..') for part in relative.split('/')) or
                    not re.fullmatch(r'[a-f0-9]{64}', digest) or
                    not isinstance(item['purpose'], str) or not item['purpose'] or
                    type(item['required']) is not bool or not isinstance(functions, list) or
                    not all(isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name)
                            for name in functions) or relative in seen):
                raise ValueError
            seen.add(relative)
            result.append(Source(relative, item['purpose'], digest, item['required'], tuple(functions)))
        return tuple(result)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise BootstrapBlocked('source_manifest_invalid') from None


def verify_sources(root: Path, manifest: Path) -> None:
    root = root.resolve(strict=True)
    for source in read_manifest(manifest):
        path = root / source.relative_path
        try:
            if path.is_symlink() or not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
                if source.required:
                    raise BootstrapBlocked('source_missing')
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            if source.required:
                raise BootstrapBlocked('source_missing') from None
            continue
        if not hmac.compare_digest(digest, source.sha256):
            raise BootstrapBlocked('source_fingerprint')


class ProductionBootstrap:
    """Production capture is unavailable until upstream effects are bounded."""

    kind = 'live'
    ready = False
    bridge_approved = False

    def __init__(self, *, source_root: Path, manifest: Path, php: str = 'php',
                 ffmpeg: str = 'ffmpeg', work_root: Path = Path('/timefree/.staging'),
                 publish_root: Path = Path('/timefree'), native_root: Path = Path('/native-reservations'),
                 secret_file: Path = Path('/run/secrets/rfriends_radiko'), native_check=None):
        self.source_root, self.manifest = Path(source_root), Path(manifest)
        self.php, self.ffmpeg = php, ffmpeg
        self.work_root, self.publish_root = Path(work_root), Path(publish_root)
        self.native_root, self.secret_file = Path(native_root), Path(secret_file)
        self.native_check = native_check

    @staticmethod
    def _gates_enabled() -> bool:
        return os.getenv('RADIOFLIX_TIMEFREE_ENABLE_WRITES') == '1'

    def preflight(self, row: dict, work: Path) -> None:
        if not self._gates_enabled():
            raise BootstrapBlocked('writes_disabled')
        if not re.fullmatch(r'[a-f0-9]{32}', row.get('job_id', '')):
            raise BootstrapBlocked('job_invalid')
        if row.get('execution_kind') != 'live' or row.get('state') != 'running':
            raise BootstrapBlocked('job_state')
        if not row.get('broadcast') or not row.get('start_at') or not row.get('end_at'):
            raise BootstrapBlocked('metadata_invalid')
        verify_sources(self.source_root, self.manifest)
        if not shutil.which(self.php) or not shutil.which(self.ffmpeg):
            raise BootstrapBlocked('runtime_missing')
        try:
            work_real = work.resolve(strict=True)
            if work.is_symlink() or not work_real.is_relative_to(self.work_root.resolve(strict=True)):
                raise BootstrapBlocked('work_path')
            if not os.access(work_real, os.W_OK) or not self.publish_root.is_dir():
                raise BootstrapBlocked('storage_unavailable')
            if self.publish_root.is_symlink() or not self.publish_root.resolve(strict=True).is_dir():
                raise BootstrapBlocked('publish_path')
            flags = os.statvfs(self.native_root).f_flag
            if not stat.S_ISDIR(self.native_root.stat().st_mode) or not (flags & getattr(os, 'ST_RDONLY', 1)):
                raise BootstrapBlocked('native_not_readonly')
            secret_stat = self.secret_file.lstat()
            if stat.S_ISLNK(secret_stat.st_mode) or not stat.S_ISREG(secret_stat.st_mode):
                raise BootstrapBlocked('secret_missing')
        except OSError:
            raise BootstrapBlocked('preflight_failed') from None
        if self.native_check is None:
            raise BootstrapBlocked('native_state_unknown')
        try:
            self.native_check(row)
        except Exception:
            raise BootstrapBlocked('native_state_unknown') from None
        if not self.bridge_approved:
            raise BootstrapBlocked('bridge_not_approved')

    def run(self, row: dict, work: Path) -> Path:
        self.preflight(row, work)
        raise BootstrapBlocked('bridge_not_approved')
