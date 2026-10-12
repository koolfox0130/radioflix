"""Owned, no-replace directory publication on the destination filesystem."""
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import wave
from pathlib import Path


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('invalid_job_id')
    return value


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def audio_info(path, expected):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('invalid_audio')
    with wave.open(str(path), 'rb') as audio:
        frames = audio.getnframes()
        duration = frames / audio.getframerate()
        if audio.getnchannels() not in (1, 2) or not frames or abs(duration - expected) > 2:
            raise ValueError('invalid_duration')
        size = 0
        while chunk := audio.readframes(65536):
            size += len(chunk)
        if size != frames * audio.getnchannels() * audio.getsampwidth():
            raise ValueError('truncated_audio')
    return {'sha256': digest(path), 'size': path.stat().st_size, 'duration': duration}


def rename_noreplace(source, target):
    # Linux/NAS: fail closed if RENAME_NOREPLACE is unsupported. Never fall back
    # to os.rename (which can overwrite an existing empty directory).
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, 'renameat2', None)
    if fn is None:
        raise OSError(errno.ENOTSUP, 'atomic no-replace unavailable')
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        number = ctypes.get_errno()
        raise OSError(number, 'atomic publish failed')


class Publisher:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    def prepare_root(self):
        if self.root.absolute() != self.root.resolve():
            raise ValueError('root_symlink')
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / '.staging'
        if staging.is_symlink():
            raise ValueError('staging_symlink')
        staging.mkdir(exist_ok=True, mode=0o700)
        return staging

    def publish(self, row, output, expected):
        ident = job_id(row['job_id'])
        staging = self.prepare_root()
        stage = staging / (ident + '-' + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        target = stage / 'audio.wav'
        # Stage remains hidden on every failure; recovery never guesses from it.
        with output.open('rb') as source, target.open('xb') as dest:
            shutil.copyfileobj(source, dest)
            dest.flush()
            os.fsync(dest.fileno())
        info = audio_info(target, expected)
        manifest = {**info, 'job_id': ident, 'publication_id': uuid.uuid4().hex,
                    'broadcast': row['broadcast'], 'execution_kind': row['execution_kind'],
                    'relative_path': ident + '/audio.wav'}
        with (stage / 'manifest.json').open('x') as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_dir(stage)
        fsync_dir(staging)
        self.store.save_publication(ident, manifest)  # Durable ownership proof before rename.
        rename_noreplace(stage, self.root / ident)
        fsync_dir(self.root)
        fsync_dir(staging)
        return manifest

    def verify(self, row):
        ident = job_id(row['job_id'])
        if self.root.absolute() != self.root.resolve():
            raise ValueError('root_symlink')
        dest = self.root / ident
        if dest.is_symlink() or not dest.is_dir():
            raise ValueError('missing_output')
        path = dest / 'manifest.json'
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 65536:
            raise ValueError('invalid_manifest')
        manifest = json.loads(path.read_text())
        intent = self.store.publication(ident)
        if not intent or manifest != intent or manifest['broadcast'] != row['broadcast'] or manifest['execution_kind'] != row['execution_kind']:
            raise ValueError('unowned_output')
        from datetime import datetime
        expected = (datetime.fromisoformat(row['end_at']) - datetime.fromisoformat(row['start_at'])).total_seconds()
        info = audio_info(dest / 'audio.wav', expected)
        if any(manifest[k] != v for k, v in info.items()) or manifest['relative_path'] != ident + '/audio.wav':
            raise ValueError('output_mismatch')
        if row['state'] == 'completed' and any(row[k] != manifest[v] for k, v in
                (('output_path', 'relative_path'), ('output_sha256', 'sha256'),
                 ('output_size', 'size'), ('duration', 'duration'))):
            raise ValueError('database_output_mismatch')
        return manifest
