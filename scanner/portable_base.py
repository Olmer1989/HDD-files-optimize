"""Constants and small helpers of the portable scanner (moved verbatim from portable.py)."""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re

from inventory import MEDIA, MIN_BYTES, EXCLUDED_DIRS
from build_selection import THRESHOLDS_V2, CAMERA_IMAGES, VIDEO
from hash_files import ReadFailure
# POLICY_V1 must stay byte-for-byte equal to the policy stored by 1.0.x jobs.
# Versions 1 and 2 did not treat .m2t and .dv as video; their stored policies keep the old lists.
_NEW_VIDEO = {'.m2t', '.dv'}
MEDIA_OLD, VIDEO_OLD = sorted(set(MEDIA) - _NEW_VIDEO), sorted(set(VIDEO) - _NEW_VIDEO)
POLICY_V1 = {'algorithm': 'sha256', 'min_bytes': MIN_BYTES,
             'media_extensions': MEDIA_OLD, 'excluded_dirs': sorted(EXCLUDED_DIRS)}
POLICY_V2 = {'version': 2, 'algorithm': 'sha256', 'thresholds_bytes': THRESHOLDS_V2,
             'camera_image_extensions': sorted(CAMERA_IMAGES), 'video_extensions': VIDEO_OLD,
             'media_extensions': MEDIA_OLD, 'excluded_dirs': sorted(EXCLUDED_DIRS)}
# Version 3 (1.5.0): .m2t and .dv are video too (any size). Older jobs are upgraded by a top-up pass.
POLICY_V3 = {**POLICY_V2, 'version': 3, 'video_extensions': sorted(VIDEO), 'media_extensions': sorted(MEDIA)}
POLICY = POLICY_V3  # for new jobs
POLICY_TEXT = 'фото JPEG/HEIC от 50 КБ, прочие изображения и RAW от 150 КБ, видео любого размера (в том числе .m2t, .dv)'

# An unreadable file is skipped; only these signs of a failing disk stop the scan.
MAX_DEVICE_ERRORS_IN_ROW = 5
# Windows codes that concern one file, not the device: access denied, sharing and
# lock violations, file cannot be accessed by the system, file or path not found.
FILE_WINERRORS = {2, 3, 5, 32, 33, 1920}
# Windows codes of a damaged or failing medium: not ready, CRC error, seek error,
# sector not found, read fault, general failure, hardware and I/O device errors.
DEVICE_WINERRORS = {21, 23, 25, 27, 30, 31, 483, 1117, 1167}

def error_kind(exc):
    """'file' — this file only (access, changed since inventory); 'device' — read failure.

    A read that fails after the file was opened is a device error unless Windows
    names a file-level cause: Python reports a CRC error there as "Permission denied".
    """
    code = getattr(exc, 'windows_code', None) or getattr(exc, 'winerror', None)
    if code in DEVICE_WINERRORS:
        return 'device'
    if isinstance(exc, ReadFailure):
        return 'file' if code in FILE_WINERRORS else 'device'
    if isinstance(exc, (RuntimeError, ValueError, PermissionError, FileNotFoundError)):   # ValueError: путь (1.6.2)
        return 'file'
    return 'file' if code in FILE_WINERRORS else 'device'

def policy_version(policy):
    if policy == POLICY_V3:
        return 3
    if policy == POLICY_V2:
        return 2
    if policy == POLICY_V1:
        return 1
    return None
# Two kinds of media, each with its own numbering: disks HDD03…, and USB flash
# drives and memory cards Flash01…. A flash medium is identified by its volume
# (serial and size): a card reader reports its own serial for every card.
ID_PATTERN = r'(?:HDD|Flash)[0-9]{2,}'
KIND_TITLES = {'disk': 'Диски HDD и SSD', 'flash': 'Флешки и карты памяти'}

def media_kind(disk_id):
    return 'flash' if str(disk_id).startswith('Flash') else 'disk'

def id_number(disk_id):
    digits = re.sub('^(HDD|Flash)', '', str(disk_id))
    return int(digits) if digits.isdigit() else 0

def check_disk_id(disk_id):
    if not re.fullmatch(ID_PATTERN, disk_id):
        raise ValueError('Номер носителя — HDD03, HDD04… для дисков или Flash01, Flash02… для флешек и карт')
    if media_kind(disk_id) == 'disk' and id_number(disk_id) < 3:
        raise ValueError('HDD01 и HDD02 уже заняты; назначьте HDD03 или больше')
    if media_kind(disk_id) == 'flash' and id_number(disk_id) < 1:
        raise ValueError('Номера флешек начинаются с Flash01')
    return disk_id

REQUIRED_EXPORTS = ['job.json', 'result.json', 'inventory_summary.json', 'inventory.sqlite', 'hashes.sqlite']
OPTIONAL_EXPORTS = ['runs.jsonl', 'log.txt']  # absent in exports made by 1.0.x

def utc():
    return datetime.now(timezone.utc).isoformat()

def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def duration(seconds):
    if seconds is None:
        return 'оценивается…'
    seconds = int(seconds)
    if seconds < 60:
        return 'меньше минуты'
    hours, minutes = divmod(seconds // 60, 60)
    return f'{hours} ч {minutes:02d} мин' if hours else f'{minutes} мин'

class Rate:
    """Read speed over a sliding window. Files go from small to large, so an
    early forecast is pessimistic and becomes shorter as large files start."""
    def __init__(self, window=600, minimum=30):
        self.window, self.minimum, self.samples = window, minimum, deque()

    def add(self, now, read_bytes):
        self.samples.append((now, read_bytes))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.window:
            self.samples.popleft()

    def value(self):
        if len(self.samples) < 2:
            return None
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        if t1 - t0 < self.minimum or b1 <= b0:
            return None
        return (b1 - b0) / (t1 - t0)

@contextmanager
def lock(path):
    # Windows byte lock is released by the OS even after a crash.
    import msvcrt
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('This job is already running')
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

def check_letter(letter):
    letter = letter.rstrip(':\\').upper()
    if not re.fullmatch('[A-Z]', letter):
        raise ValueError('Expected one drive letter')
    return letter
