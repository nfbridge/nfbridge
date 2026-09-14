# SPDX-License-Identifier: GPL-3.0-only
"""Explicit scan/frame mapping and staged metadata writes. No camera access."""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import exports


SUPPORTED = frozenset(('.jpg', '.jpeg', '.tif', '.tiff'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def natural_key(path):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', path.name)) + ((2, path.name),)


@dataclass(frozen=True)
class Pair:
    path: Path
    frame_number: int
    sha256: str
    tags: tuple


@dataclass(frozen=True)
class Mapping:
    pairs: tuple
    unmatched_files: tuple
    unmatched_frames: tuple
    ignored_files: tuple
    iso_unchanged_confirmed: bool = False


def make_mapping(folder, roll, *, reverse=False, start=None, metadata=None):
    folder = Path(folder).expanduser().resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('스캔 폴더를 선택하세요.')
    files = sorted((p for p in folder.iterdir() if p.is_file() and
                    not p.is_symlink() and p.suffix.lower() in SUPPORTED), key=natural_key)
    ignored = tuple(sorted(p.name for p in folder.iterdir() if p not in files))
    if reverse:
        files.reverse()
    frames = roll['frames']
    numbers = [f['frame_number'] for f in frames]
    if len(set(numbers)) != len(numbers):
        raise ValueError('컷 번호가 중복됩니다. 원본 촬영기록을 확인하세요.')
    if start is None and numbers:
        start = numbers[0]
    if start not in numbers:
        raise ValueError('시작 컷 번호가 기록에 없습니다. 목록에 있는 번호를 선택하세요.')
    selected = frames[numbers.index(start):]
    pairs = []
    for path, frame in zip(files, selected):
        values = dict(zip(exports.EXIF_COLUMNS, exports.exif_row(roll, frame, metadata or {})))
        values.pop('SourceFile')
        # Empty is unknown/unavailable, never a request to delete an existing tag.
        tags = tuple((key if key.startswith('XMP-') else 'EXIF:' + key, str(value))
                     for key, value in values.items() if value != '')
        pairs.append(Pair(path, frame['frame_number'], digest(path), tags))
    mapped = {p.frame_number for p in pairs}
    return Mapping(tuple(pairs), tuple(str(p) for p in files[len(pairs):]),
                   tuple(n for n in numbers if n not in mapped), ignored,
                   (metadata or {}).get('iso_unchanged_confirmed') is True)


def _same_value(expected, actual):
    # ExifTool -n reports rational EXIF values as decimal numbers.
    try:
        return abs(float(Fraction(expected)) - float(actual)) <= max(1e-6, abs(float(Fraction(expected))) * 1e-5)
    except (ValueError, TypeError, ZeroDivisionError):
        return str(expected) == str(actual)


def write_mapping(mapping, executable, *, confirmed=False, runner=subprocess.run):
    if confirmed is not True:
        raise ValueError('파일 대응표를 확인하고 쓰기를 선택하세요.')
    if not mapping.pairs:
        raise ValueError('대응된 스캔 파일이 없습니다.')
    executable = Path(executable).resolve(strict=True)
    # Preflight the entire reviewed selection before changing any image.
    for pair in mapping.pairs:
        if pair.path.is_symlink() or digest(pair.path) != pair.sha256:
            raise ValueError('미리보기 이후 파일이 바뀌었습니다. 폴더를 다시 선택하세요.')
        backup = Path(str(pair.path) + '_original')
        if backup.exists() or backup.is_symlink():
            raise ValueError('이전에 남겨둔 수정 전 사진이 있습니다. 기존 폴더는 보관하고, 작업할 JPEG/TIFF만 새 폴더로 복사해 선택하세요: ' + backup.name)
    results = []
    for pair in mapping.pairs:
        backup = Path(str(pair.path) + '_original')
        staging = None
        try:
            if pair.path.is_symlink() or digest(pair.path) != pair.sha256:
                raise ValueError('쓰기 전에 파일이 변경되었습니다.')
            fd, name = tempfile.mkstemp(prefix='.nfbridge-', suffix=pair.path.suffix, dir=pair.path.parent)
            os.close(fd)
            staging = Path(name)
            shutil.copy2(pair.path, staging)
            kind = runner([str(executable), '-config', '', '-j', '-FileType', '--', str(staging)],
                          capture_output=True, text=True, timeout=120)
            if kind.returncode or kind.stderr.strip() or json.loads(kind.stdout)[0].get('FileType') not in ('JPEG', 'TIFF'):
                raise ValueError('파일 내용이 지원하는 JPEG/TIFF 형식이 아닙니다.')
            args = [str(executable), '-config', '', '-overwrite_original']
            args += ['-' + key + '=' + value for key, value in pair.tags]
            result = runner(args + ['--', str(staging)], capture_output=True, text=True, timeout=120)
            if result.returncode or result.stderr.strip():
                raise ValueError('메타데이터 쓰기 결과를 확인하지 못했습니다: ' + result.stderr.strip())
            check = runner([str(executable), '-config', '', '-j', '-n'] +
                           ['-' + key.rstrip('#') for key, _ in pair.tags] + ['--', str(staging)],
                           capture_output=True, text=True, timeout=120)
            if check.returncode or check.stderr.strip():
                raise ValueError('쓴 메타데이터를 다시 읽지 못했습니다.')
            actual = json.loads(check.stdout)[0]
            for key, value in pair.tags:
                name = key.split(':')[-1].rstrip('#')
                if not _same_value(value, actual.get(name)):
                    raise ValueError('메타데이터 검증 불일치: ' + name)
            if pair.path.is_symlink() or digest(pair.path) != pair.sha256:
                raise ValueError('검증 중 원본 파일이 변경되었습니다.')
            with pair.path.open('rb') as src, backup.open('xb') as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            if digest(backup) != pair.sha256:
                raise ValueError('원본 백업 검증에 실패했습니다.')
            if pair.path.is_symlink() or digest(pair.path) != pair.sha256:
                raise ValueError('원본 파일이 변경되어 교체하지 않았습니다.')
            os.replace(staging, pair.path)
            staging = None
            results.append({'file': str(pair.path), 'frame': pair.frame_number, 'status': 'verified',
                            'iso_unchanged_confirmed': mapping.iso_unchanged_confirmed,
                            'backup': str(backup), 'before_sha256': pair.sha256, 'after_sha256': digest(pair.path)})
        except Exception as exc:
            results.append({'file': str(pair.path), 'frame': pair.frame_number, 'status': 'failed', 'error': str(exc)})
            break  # no automatic retry or automatic rollback
        finally:
            if staging is not None:
                staging.unlink(missing_ok=True)
    for pair in mapping.pairs[len(results):]:
        results.append({'file': str(pair.path), 'frame': pair.frame_number, 'status': 'not_attempted'})
    return results
