"""Offline Windows worker. Only reads archive disks; writes local results."""
import argparse
from collections import deque
from contextlib import contextmanager, closing
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import string
import uuid

from inventory import inventory, volume, discover_disk, MEDIA, MIN_BYTES, EXCLUDED_DIRS
from build_selection import select, THRESHOLDS_V1, THRESHOLDS_V2, CAMERA_IMAGES, VIDEO
from hash_files import hash_one, signature, ReadFailure
import rescan

# VERSION is the job format/algorithm. It is unchanged, so jobs started by
# 1.0.x continue with this program. APP_VERSION is the program release.
VERSION = '1.0.0'
# Partial (selected folders) jobs have their own format version, so that a program
# before 1.4.0 refuses to continue them as a full scan of the whole disk.
VERSION_PARTIAL = '1.1.0'
APP_VERSION = '1.6.0'
STOP_FILE = None
PROGRESS_FILE = None
JOB_LOG = None
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
    if isinstance(exc, (RuntimeError, PermissionError, FileNotFoundError)):
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

def say(message, to_file=True):
    """Print for the window/console and keep a permanent copy inside the job folder."""
    print(message, flush=True)
    if to_file and JOB_LOG:
        try:
            with JOB_LOG.open('a', encoding='utf-8') as handle:
                handle.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')
        except OSError:
            pass  # the log is a convenience; results are kept in the databases

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

def publish(state):
    if not PROGRESS_FILE:
        return
    try:
        write_json(PROGRESS_FILE, {**state, 'app_version': APP_VERSION, 'updated_utc': utc()})
    except OSError:
        pass  # a reader may hold the file briefly; the next update replaces it

@contextmanager
def awake():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    if not kernel.SetThreadExecutionState(0x80000001):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(0x80000000)

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

def inspect(letter, kind='disk'):
    letter = check_letter(letter)
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               f"$p=Get-Partition -DriveLetter '{letter}'; $d=Get-Disk -Number $p.DiskNumber; "
               "[pscustomobject]@{hardware_serial=([string]$d.SerialNumber).Trim(); "
               "physical_bytes=$d.Size; model=[string]$d.FriendlyName} | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                check=True, capture_output=True, encoding='utf-8-sig')
        record = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        if kind != 'flash':
            raise
        # A memory card without a partition table: its volume is enough.
        record = {'hardware_serial': '', 'physical_bytes': None, 'model': ''}
    root = letter + ':\\'
    serial, label, filesystem = volume(root)
    record.update(volume_serial=serial, volume_bytes=shutil.disk_usage(root).total,
                  label_at_registration=label, filesystem=filesystem)
    if kind == 'flash':
        if serial == '00000000':
            raise RuntimeError('The volume has no serial number: manual identification required')
        record['identify_by'] = 'volume'
    elif not record['hardware_serial']:
        raise RuntimeError('No hardware serial: manual identification required')
    return record

def discover_volume(record):
    """Finds a flash volume under any letter by its volume serial and size."""
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    previous = kernel.SetErrorMode(1)  # no "insert a disk" dialogs for empty card readers
    matches = []
    try:
        for index, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << index):
                continue
            root = letter + ':\\'
            try:
                if volume(root)[0] == record['volume_serial'] and shutil.disk_usage(root).total == record['volume_bytes']:
                    matches.append(root)
            except OSError:
                continue
    finally:
        kernel.SetErrorMode(previous)
    if len(matches) != 1:
        raise RuntimeError('Registered flash volume absent, or several volumes have the same serial and size. No scan started.')
    return matches[0], {'letter': matches[0][0], 'volume_serial': record['volume_serial'], 'bytes': record.get('physical_bytes')}

def locate(record):
    if record.get('identify_by') == 'volume':
        return discover_volume(record)
    return discover_disk(record)

# Read-only description of the device. GPT partition/disk GUIDs and the MBR
# signature are written on the disk itself, so they survive a new drive letter,
# another computer and usually another USB adapter.
DESCRIBE = r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8
$p=Get-Partition -DriveLetter '@L@'; $d=Get-Disk -Number $p.DiskNumber; $v=Get-Volume -DriveLetter '@L@'
$m=@(Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object { ([string]$_.SerialNumber).Trim() -eq ([string]$d.SerialNumber).Trim() -and $_.Size -eq $d.Size })
$x=$null; if ($m.Count -eq 1) { $x=$m[0] }
[pscustomobject]@{
 model=[string]$d.FriendlyName; manufacturer=([string]$d.Manufacturer).Trim(); hardware_serial=([string]$d.SerialNumber).Trim()
 firmware=([string]$d.FirmwareVersion).Trim(); physical_bytes=$d.Size; bus_type=[string]$d.BusType
 media_type=$(if ($x) { [string]$x.MediaType } else { '' }); spindle_rpm=$(if ($x) { $x.SpindleSpeed } else { $null })
 health=$(if ($x) { [string]$x.HealthStatus } else { [string]$d.HealthStatus })
 partition_style=[string]$d.PartitionStyle; disk_guid=[string]$d.Guid; mbr_signature=$d.Signature
 disk_number=$d.Number; disk_unique_id=[string]$d.UniqueId; location=[string]$d.Location; device_path=[string]$d.Path
 partition_number=$p.PartitionNumber; partition_offset=$p.Offset; partition_bytes=$p.Size
 partition_guid=[string]$p.Guid; partition_type=[string]$p.Type
 volume_label=[string]$v.FileSystemLabel; filesystem=[string]$v.FileSystem; volume_bytes=$v.Size
 volume_free_bytes=$v.SizeRemaining; volume_path=[string]$v.Path; allocation_unit=$v.AllocationUnitSize
} | ConvertTo-Json -Compress"""

def describe(letter):
    """Never fails the scan: identity checks are done separately by discover_disk."""
    letter = check_letter(letter)
    info = {'letter': letter, 'computer': os.environ.get('COMPUTERNAME', ''), 'observed_utc': utc()}
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                 DESCRIBE.replace('@L@', letter)],
                                check=True, capture_output=True, encoding='utf-8-sig', timeout=120)
        info.update(json.loads(result.stdout))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        info['describe_error'] = str(exc)
    try:
        info['volume_serial'] = volume(letter + ':\\')[0]
    except OSError as exc:
        info['volume_serial_error'] = str(exc)
    return info

def identity_text(disk_id, info):
    def gb(value):
        return f'{value / 1e9:,.1f} ГБ'.replace(',', ' ') if isinstance(value, (int, float)) else '?'
    kind = info.get('media_type') if info.get('media_type') in ('HDD', 'SSD', 'SCM') else 'тип HDD/SSD не сообщён'
    if media_kind(disk_id) == 'flash':
        kind = 'флешка или карта памяти'
    signature_mbr = info.get('mbr_signature')
    signature_mbr = f'{signature_mbr:08X}' if isinstance(signature_mbr, int) and signature_mbr else '—'
    lines = [
        f'Носитель {disk_id}: {info.get("model", "?")} · серийный номер {info.get("hardware_serial", "?")} · '
        f'{gb(info.get("physical_bytes"))} · {kind} · подключение {info.get("bus_type", "?")}',
        f'Том: метка «{info.get("volume_label", "")}» · серийный номер тома {info.get("volume_serial", "?")} · '
        f'{info.get("filesystem", "?")} · {gb(info.get("volume_bytes"))} · буква {info.get("letter")}: (буква временная)',
        f'Метки на самом диске: разметка {info.get("partition_style", "?")} · GUID раздела {info.get("partition_guid") or "—"} · '
        f'GUID диска {info.get("disk_guid") or "—"} · подпись MBR {signature_mbr}',
        f'Компьютер: {info.get("computer") or "?"} · прошивка {info.get("firmware") or "?"} · состояние {info.get("health") or "?"}',
    ]
    if info.get('describe_error'):
        lines.append('Не удалось получить часть сведений Windows: ' + info['describe_error'])
    return lines

# Uniform results layout, the same on every computer:
#   <results root>/<HDDxx|Flashxx - model - capacity - label>/<job_id>/
#   <results root>/Реестр дисков.md and .csv, rebuilt after each scan/import.
JOB_ID = re.compile(ID_PATTERN + r'_[0-9a-f]{32}')
INDEX_NAME = 'Реестр дисков'

def capacity(size):
    if not size:
        return 'размер неизвестен'
    if size >= 1e12:
        return f'{size / 1e12:.1f}'.replace('.0', '').replace('.', ',') + ' ТБ'
    return f'{round(size / 1e9)} ГБ'

def disk_folder_name(disk_id, record):
    parts = [disk_id, (record.get('model') or 'модель неизвестна').strip(), capacity(record.get('physical_bytes') or record.get('volume_bytes'))]
    if (record.get('label_at_registration') or '').strip():
        parts.append(record['label_at_registration'].strip())
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', ' - '.join(parts)).strip(' .')
    return name[:120].rstrip(' .')

def disk_folder(root, disk_id, record):
    # The folder of an already known disk is reused even if its label changed.
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name.startswith(disk_id + ' - '):
                return child
    return root / disk_folder_name(disk_id, record)

def results_root(job):
    return job.parent.parent if job.parent.name.startswith(job.name.split('_')[0] + ' - ') else job.parent

def find_jobs(root):
    found = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith('_'):
            continue  # _Входящие, _Архив… are not part of the catalogue
        for folder in [child, *sorted(p for p in child.iterdir() if p.is_dir())]:
            if (folder / 'job.json').is_file():
                found.append(folder)
    return found

def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default

# Versions up to 1.3.1 recorded a damaged sector as this text: the error came from
# reading an opened file, so unlike a refused open it carries no file name.
LEGACY_READ_ERROR = '[Errno 13] Permission denied'

def unread_count(job, damaged_only=False):
    """Skipped files of a job: status 'error' — file-level cause, 'damaged' — read error of the medium."""
    condition = "status='damaged' or (status='error' and error=?)" if damaged_only else "status in ('error','damaged')"
    try:
        with closing(sqlite3.connect((job / 'hashes.sqlite').as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute(f'select count(*) from hashes where {condition}',
                              (LEGACY_READ_ERROR,) if damaged_only else ()).fetchone()[0]
    except sqlite3.Error:
        return 0

def job_row(job, root):
    manifest = read_json(job / 'job.json', {})
    record = manifest.get('record', {})
    result = read_json(job / 'result.json', {})
    summary = read_json(job / 'inventory_summary.json', {})
    identity = dict(manifest.get('identity_at_registration') or {})
    last_run = {}
    if (job / 'runs.jsonl').exists():
        for line in (job / 'runs.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event.get('identity'):
                identity.update({k: v for k, v in event['identity'].items() if v not in (None, '')})
            last_run = event if event.get('event') in ('start', 'finish') else last_run
    status = result.get('status', 'running')
    marker = identity.get('partition_guid') or identity.get('disk_guid')
    if not marker and isinstance(identity.get('mbr_signature'), int) and identity['mbr_signature']:
        marker = f'MBR {identity["mbr_signature"]:08X}'
    return {
        'Номер': manifest.get('disk_id', '?'),
        'Вид носителя': KIND_TITLES[media_kind(manifest.get('disk_id', ''))], 'Модель': record.get('model', ''), 'Ёмкость': capacity(record.get('physical_bytes') or record.get('volume_bytes')),
        'Метка тома': record.get('label_at_registration', ''), 'Серийный номер устройства': record.get('hardware_serial', ''),
        'Серийный номер тома': record.get('volume_serial', ''), 'Метка на диске (GUID/MBR)': marker or '',
        'Тип': identity.get('media_type') if identity.get('media_type') in ('HDD', 'SSD') else '',
        'Подключение': identity.get('bus_type', ''), 'Последняя буква': identity.get('letter', ''),
        'Компьютер': identity.get('computer', ''), 'Состояние': status,
        'Файлов на диске': summary.get('files', ''), 'Занято файлами, ГБ': round(summary['bytes'] / 1e9, 1) if summary.get('bytes') else '',
        'Фото/видео с хешем': result.get('selected_files', ''),
        'Их объём, ГБ': round(result['selected_bytes'] / 1e9, 1) if result.get('selected_bytes') else '',
        'Ошибок описи': summary.get('errors', ''),
        'Не прочитано': unread_count(job),
        'Из них — повреждения диска': unread_count(job, damaged_only=True),
        'Правила': {3: 'v3', 2: 'v2 — добор .m2t/.dv', 1: 'v1 — нужен добор'}.get(policy_version(manifest.get('policy')), 'другие'),
        'Дата': (last_run.get('utc') or manifest.get('created_utc', ''))[:10],
        'Папка': str(job.relative_to(root)),
    }

def write_index(root):
    import csv
    rows = [job_row(job, root) for job in find_jobs(root)]
    rows.sort(key=lambda r: (media_kind(r['Номер']) == 'flash', id_number(r['Номер']), r['Дата']))
    warnings = []
    by_id, by_serial = {}, {}
    for r in rows:
        by_id.setdefault(r['Номер'], set()).add((r['Серийный номер устройства'], r['Серийный номер тома']))
        by_serial.setdefault((r['Серийный номер устройства'], r['Серийный номер тома']), set()).add(r['Номер'])
    warnings += [f'Номер {k} назначен разным носителям — нужно разобраться вручную.' for k, v in by_id.items() if len(v) > 1]
    warnings += [f'Один носитель (серийный номер {k[0] or "—"}, том {k[1]}) записан под номерами {", ".join(sorted(v))}.'
                 for k, v in by_serial.items() if len(v) > 1]
    damaged_disks = [f'{r["Номер"]} ({r["Из них — повреждения диска"]})' for r in rows if r['Из них — повреждения диска']]
    if damaged_disks:
        warnings.append('ПОВРЕЖДЕНИЯ НОСИТЕЛЯ — файлы не читаются из-за ошибок самого диска (CRC, сектор не найден), '
                        'в скобках — сколько: ' + ', '.join(damaged_disks) + '. Проверьте SMART (например, '
                        'CrystalDiskInfo), не сканируйте такой носитель повторно без необходимости и в первую '
                        'очередь перенесите с него данные. Список файлов — в log.txt задания.')
    unread_disks = [f'{r["Номер"]} ({r["Не прочитано"] - r["Из них — повреждения диска"]})' for r in rows
                    if r['Не прочитано'] > r['Из них — повреждения диска']]
    if unread_disks:
        warnings.append('Есть непрочитанные файлы (в скобках — сколько): ' + ', '.join(unread_disks) +
                        '. Причины — в log.txt задания. Исправьте доступ и продолжите сканирование: '
                        'дочитаются только эти файлы.')
    old_rules = sorted({r['Номер'] for r in rows if r['Правила'] != 'v2'})
    if old_rules:
        warnings.append(f'Сканированы по старым правилам (всё от 1 МиБ): {", ".join(old_rules)}. Подключите диск и нажмите '
                        '«Начать сканирование» — программа предложит продолжить и дочитает только мелкие фото и видео.')
    columns = list(rows[0]) if rows else ['Номер']
    temporary = root / (INDEX_NAME + '.csv.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, columns, delimiter=';')
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(root / (INDEX_NAME + '.csv'))
    status_text = {'complete': 'завершён', 'complete_with_inventory_errors': 'завершён, есть недоступные папки',
                   'complete_with_unread_files': 'завершён, есть непрочитанные файлы',
                   'interrupted': 'остановлен', 'error': 'ошибка', 'running': 'не завершён'}
    short = ['Номер', 'Модель', 'Ёмкость', 'Метка тома', 'Тип', 'Подключение', 'Состояние', 'Правила', 'Не прочитано', 'Фото/видео с хешем', 'Их объём, ГБ', 'Дата', 'Папка']
    lines = [f'# {INDEX_NAME}', '', f'Создан автоматически {datetime.now():%d.%m.%Y %H:%M}. Не редактировать вручную: '
             'файл пересоздаётся после каждого сканирования и импорта. Полные сведения, включая серийные номера, — в '
             f'«{INDEX_NAME}.csv» (открывается в Excel).', '',
             f'Заданий: {len(rows)} · дисков: {len({r["Номер"] for r in rows if media_kind(r["Номер"]) == "disk"})} · '
             f'флешек и карт: {len({r["Номер"] for r in rows if media_kind(r["Номер"]) == "flash"})} · фото/видео с хешем: '
             + f'{sum(r["Фото/видео с хешем"] or 0 for r in rows):,}'.replace(',', ' ') + ' файлов, '
             + f'{sum(r["Их объём, ГБ"] or 0 for r in rows):,.1f}'.replace(',', ' ') + ' ГБ', '']
    if warnings:
        lines += ['## Требует внимания', '', *[f'- {w}' for w in warnings], '']
    for kind, title in KIND_TITLES.items():
        group = [r for r in rows if media_kind(r['Номер']) == kind]
        if not group:
            continue
        lines += [f'## {title}', '', '| ' + ' | '.join(short) + ' |', '|' + '---|' * len(short)]
        for r in group:
            damaged = r['Из них — повреждения диска']
            values = {**r, 'Состояние': status_text.get(r['Состояние'], r['Состояние']), 'Папка': r['Папка'].replace('\\', '/')}
            if damaged:
                values['Состояние'] += '; ПОВРЕЖДЕНИЯ ДИСКА — см. «Требует внимания»'
                values['Не прочитано'] = f'{r["Не прочитано"]} (повреждения: {damaged})'
            lines.append('| ' + ' | '.join(str(values[c]).replace('|', '/') for c in short) + ' |')
        lines.append('')
    temporary = root / (INDEX_NAME + '.md.tmp')
    temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary.replace(root / (INDEX_NAME + '.md'))
    return rows

def refresh_index(root):
    try:
        write_index(root)
        say(f'Реестр дисков обновлён: {root / (INDEX_NAME + ".md")}', to_file=False)
    except (OSError, ValueError, KeyError) as exc:
        say(f'Реестр дисков не обновлён (результаты сохранены): {exc}', to_file=False)

def safe_relative(rel):
    p = PureWindowsPath(rel)
    if not p.parts or p.is_absolute() or p.drive or any(x in ('.', '..') or ':' in x for x in p.parts):
        raise ValueError('Unsafe relative path')
    return p.parts

def append_run(job, event):
    with (job / 'runs.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')

def process(job):
    global JOB_LOG
    manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
    JOB_LOG = job / 'log.txt'  # early, so that a refusal is also kept with the job
    partial = is_partial_job(manifest)
    allowed = (VERSION, VERSION_PARTIAL) if partial else (VERSION,)
    if manifest.get('version') not in allowed or policy_version(manifest['policy']) is None:
        raise RuntimeError('Different scan policy; use the original worker version')
    disk_id, record = manifest['disk_id'], manifest['record']
    base_state = {'job': str(job), 'disk_id': disk_id, 'model': record.get('model', ''),
                  'hardware_serial': record.get('hardware_serial', ''), 'volume_serial': record.get('volume_serial', '')}
    publish({**base_state, 'phase': 'identify', 'phase_title': 'Проверка диска'})
    root, physical = locate(record)
    require_separate_output(job, root)
    def check():
        if STOP_FILE and STOP_FILE.exists():
            raise KeyboardInterrupt()
        if volume(root)[0] != record['volume_serial'] or shutil.disk_usage(root).total != record['volume_bytes']:
            raise RuntimeError('Source disconnected or replaced')
    with lock(job / 'worker.lock'), awake():
        run_id = uuid.uuid4().hex
        info = describe(root[0])
        base_state.update(letter=root[0], bus_type=info.get('bus_type', ''), media_type=info.get('media_type', ''))
        say(f'=== Запуск {datetime.now():%d.%m.%Y %H:%M} · программа {APP_VERSION} · задание {job.name}')
        for line in identity_text(disk_id, info):
            say(line)
        append_run(job, {'event': 'start', 'run_id': run_id, 'utc': utc(), 'app_version': APP_VERSION,
                         'disk_id': disk_id, 'letter': root[0], 'physical': physical, 'identity': info})
        check()
        started = time.monotonic()
        if partial:      # selected folders: own pass, the register of full scans is not touched
            return run_partial(job, manifest, root, check, run_id, base_state, physical, started)
        inv = job / 'inventory.sqlite'
        if not inv.exists() or not manifest.get('inventory_finished'):
            # An interrupted metadata pass is rebuilt; hashes are never discarded.
            if inv.exists():
                inv.rename(job / ('inventory_interrupted_' + uuid.uuid4().hex + '.sqlite'))
            used = max(shutil.disk_usage(root).used, 1)
            last_publish = [0.0]
            def inventory_progress(summary):
                now = time.monotonic()
                if now - last_publish[0] < 2:
                    return
                last_publish[0] = now
                # Used space includes service folders, so this is an approximation.
                publish({**base_state, 'phase': 'inventory', 'phase_title': 'Этап 1 из 2: опись файлов',
                         'percent': min(99.0, round(100 * summary['bytes'] / used, 1)),
                         'files_done': summary['files'], 'bytes_done': summary['bytes'], 'bytes_total': used,
                         'errors': summary['errors'], 'elapsed_seconds': round(now - started)})
            say('Этап 1 из 2: опись файлов (только имена, размеры и даты)')
            with closing(sqlite3.connect(inv)) as db:
                summary = inventory(root, db, check, inventory_progress)
            write_json(job / 'inventory_summary.json', summary)
            if summary['status'] not in ('complete', 'complete_with_errors'):
                append_run(job, {'event': 'finish', 'run_id': run_id, 'utc': utc(), 'status': 'inventory_interrupted'})
                publish({**base_state, 'phase': 'stopped', 'phase_title': 'Опись остановлена'})
                raise RuntimeError('Inventory interrupted; resume this job')
            manifest['inventory_finished'] = True
            write_json(job / 'job.json', manifest)
            say(f'Опись завершена: {summary["files"]:,} файлов, {summary["bytes"] / 1e9:,.1f} ГБ, ошибок {summary["errors"]}')
        else:
            summary = json.loads((job / 'inventory_summary.json').read_text(encoding='utf-8'))
        was = policy_version(manifest['policy'])
        if was in (1, 2):
            # Top-up: the inventory already lists every file, so only the newly
            # selected ones are read; all saved hashes are reused. Recorded first,
            # so an older program refuses to continue this job under old rules.
            manifest.setdefault('policy_history', []).append({'from': was, 'to': 3, 'utc': utc(), 'app_version': APP_VERSION})
            manifest['policy'] = POLICY_V3
            write_json(job / 'job.json', manifest)
            append_run(job, {'event': 'policy_upgrade', 'run_id': run_id, 'utc': utc(), 'from': was, 'to': 3})
            say(f'Правила выборки обновлены с версии {was} до версии 3: ' + POLICY_TEXT +
                '. Готовые хеши сохраняются, дочитываются только новые выбранные файлы.')
        with closing(sqlite3.connect(inv.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(job / 'hashes.sqlite')) as target:
            target.execute('create table if not exists hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,status text,error text,primary key(disk_id,path))')
            # Selection uses precisely the same function as the main project.
            rows = [(p, s, m, i) for p, s, m, i in source.execute('select path,size,mtime_ns,file_id from files order by size,path')
                    if select(p, s, THRESHOLDS_V2)]
            total = sum(r[1] for r in rows)
            # Saved hashes that will probably be reused are excluded from the forecast.
            known = {p: (s, m, i) for p, s, m, i, st in target.execute(
                'select path,size,mtime_ns,file_id,status from hashes where disk_id=?', (disk_id,)) if st == 'verified'}
            to_read = total - sum(s for p, s, m, i in rows if known.get(p) == (s, str(m), str(i)))
            cached = hashed = finished = read = unread = unread_bytes = device_in_row = damaged = damaged_bytes = 0
            hash_started = last_line = last_file_line = last_publish = time.monotonic()
            rate = Rate()
            report = {'disk_id': disk_id, 'status': 'running', 'selected_files': len(rows),
                      'selected_bytes': total, 'inventory_errors': summary['errors'], 'physical': physical}
            write_json(job / 'result.json', report)
            say(f'Этап 2 из 2: контрольные суммы SHA-256 — {len(rows):,} файлов, {total / 1e9:,.1f} ГБ; '
                f'прочитать предстоит {to_read / 1e9:,.1f} ГБ')
            def state(count=0, phase='hashing', title='Этап 2 из 2: контрольные суммы'):
                now = time.monotonic()
                position, newly = finished + count, read + count
                rate.add(now, newly)
                speed = rate.value()
                remaining = max(0, to_read - newly)
                eta = 0 if position >= total else (remaining / speed if speed else None)
                return {**base_state, 'phase': phase, 'phase_title': title,
                        'percent': round(100 * position / total, 2) if total else 100.0,
                        'bytes_done': position, 'bytes_total': total, 'files_done': cached + hashed + unread,
                        'files_total': len(rows), 'reused_files': cached, 'new_files': hashed, 'unread_files': unread, 'damaged_files': damaged,
                        'read_bytes': newly, 'to_read_bytes': to_read, 'rate_bytes_per_second': speed,
                        'eta_seconds': round(eta) if eta is not None else None,
                        'elapsed_seconds': round(now - started), 'errors': summary['errors']}
            def progress(count=0, force=False):
                nonlocal last_line, last_file_line, last_publish
                if not force and STOP_FILE and STOP_FILE.exists():
                    raise KeyboardInterrupt()
                now = time.monotonic()
                if not force and now - last_publish < 2:
                    return
                last_publish = now
                current = state(count)
                publish(current)
                if force or now - last_line >= 10:
                    speed = current['rate_bytes_per_second']
                    say(f'{disk_id}: {current["percent"]:.1f}% · {current["bytes_done"] / 1e9:,.1f} из {total / 1e9:,.1f} ГБ · '
                        f'файлов {current["files_done"]:,} из {len(rows):,} (готовых хешей {cached:,}, новых {hashed:,}'
                        + (f', не прочитано {unread:,}' if unread else '')
                        + (f', из них повреждения диска {damaged:,}' if damaged else '') + ') · '
                        + f'{(speed or 0) / 1e6:.0f} МБ/с · осталось {duration(current["eta_seconds"])}',
                        to_file=force or now - last_file_line >= 60)
                    last_line = now
                    if force or now - last_file_line >= 60:
                        last_file_line = now
            try:
                for rel, size, mtime, file_id in rows:
                    path = Path(root).joinpath(*safe_relative(rel))
                    expected = size, str(mtime), str(file_id)
                    check()
                    old = target.execute('select size,mtime_ns,file_id,status from hashes where disk_id=? and path=?', (disk_id, rel)).fetchone()
                    try:
                        current = signature(path.stat())
                        if old == (*expected, 'verified') and current[:2] == expected[:2] and (expected[2] == '0' or current[2] == expected[2]):
                            cached += 1
                            finished += size
                            progress()
                            continue
                        digest = hash_one(path, expected, progress)
                    except (OSError, RuntimeError) as exc:
                        # One unreadable file is skipped and recorded; it is read
                        # again on the next resume. A vanished disk (check below)
                        # or several device errors in a row stop the scan.
                        kind = error_kind(exc)
                        target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)',
                                       (disk_id, rel, *expected, None, 'damaged' if kind == 'device' else 'error', str(exc)))
                        target.commit()
                        unread += 1; unread_bytes += size; finished += size
                        if kind == 'device':
                            damaged += 1; damaged_bytes += size
                        check()
                        say(f'ПРОПУЩЕН ({"нет доступа к файлу" if kind == "file" else "ПОВРЕЖДЕНИЕ НОСИТЕЛЯ"}): {rel}: {exc}')
                        if kind == 'device':
                            device_in_row += 1
                            if device_in_row >= MAX_DEVICE_ERRORS_IN_ROW:
                                raise RuntimeError(f'{device_in_row} ошибок чтения устройства подряд — возможно, диск '
                                                   'неисправен. Остановлено; готовые хеши сохранены.')
                        progress()
                        continue
                    check()
                    target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, digest, 'verified', ''))
                    target.commit()
                    hashed += 1; finished += size; read += size
                    device_in_row = 0
                    progress()
                if unread:
                    report['status'] = 'complete_with_unread_files'
                else:
                    report['status'] = 'complete_with_inventory_errors' if summary['errors'] else 'complete'
            except KeyboardInterrupt:
                report.update(status='interrupted', error='Stopped by user')
            except (OSError, RuntimeError) as exc:
                report.update(status='error', error=str(exc))
            finally:
                report.update(hashed_files=hashed, cached_files=cached, newly_read_bytes=read,
                              unread_files=unread, unread_bytes=unread_bytes,
                              damaged_files=damaged, damaged_bytes=damaged_bytes,
                              seconds=round(time.monotonic()-started, 2), app_version=APP_VERSION)
                write_json(job / 'result.json', report)
                progress(force=True)
                phase = 'stopped' if report['status'] == 'interrupted' else ('done' if report['status'].startswith('complete') else 'error')
                titles = {'done': 'Сканирование завершено', 'stopped': 'Остановлено с сохранением', 'error': 'Остановлено из-за ошибки'}
                if unread and phase == 'done':
                    titles['done'] = f'Завершено, не прочитано файлов: {unread:,}'.replace(',', ' ')
                if damaged and phase == 'done':
                    titles['done'] = f'Завершено. ДИСК ПОВРЕЖДЁН: не читаются {damaged:,} файл(ов)'.replace(',', ' ')
                final = state(phase=phase, title=titles[phase])
                if phase != 'done':
                    final['eta_seconds'] = None
                final['status'] = report['status']
                publish(final)
                append_run(job, {'event': 'finish', 'run_id': run_id, 'utc': utc(), 'status': report['status'],
                                 'hashed_files': hashed, 'cached_files': cached, 'newly_read_bytes': read,
                                 'unread_files': unread, 'damaged_files': damaged, 'seconds': report['seconds'], 'error': report.get('error', '')})
                say(f'=== Итог: {report["status"]} · новых хешей {hashed:,}, готовых {cached:,} · '
                    f'прочитано {read / 1e9:,.1f} ГБ за {duration(time.monotonic() - started)}'
                    + (f' · НЕ ПРОЧИТАНО файлов: {unread:,} ({unread_bytes / 1e9:,.2f} ГБ) — список в hashes.sqlite '
                       '(status=error или damaged) и выше в журнале; при продолжении они читаются заново' if unread else '')
                    + (f' · ИЗ НИХ ПОВРЕЖДЕНИЯ НОСИТЕЛЯ: {damaged:,} ({damaged_bytes / 1e9:,.2f} ГБ) — ошибки чтения '
                       'самого диска; проверьте SMART и в первую очередь перенесите с него данные' if damaged else '')
                    + (f' · {report["error"]}' if report.get('error') else ''))
                print(json.dumps(report, ensure_ascii=False, indent=2))
    refresh_index(results_root(job))
    return 0 if report['status'].startswith('complete') else 2

def is_partial_job(manifest):
    return str(manifest.get('scan_scope') or '').lower() == 'partial'

def prior_sources(manifest):
    """Previous jobs of this disk fixed at job creation (rescan.find_sources), oldest first."""
    return [{**s, 'dir': Path(s['dir'])} for s in manifest.get('prior_sources') or []]

def run_partial(job, manifest, root, check, run_id, base_state, physical, started):
    """Selected folders of a disk (1.4.0). The inventory of the folders is made anew on every run; a file is read
    only if its previous hash cannot be trusted (rescan.decide); every hash row keeps the earliest moment when it
    was certainly not yet measured (hash_info.bound_ns), also along a chain of reuse."""
    disk_id, folders = manifest['disk_id'], manifest['folders']
    rehash_all = bool(manifest.get('rehash_all'))
    rule = rescan.hash_rule(manifest)    # 1.6.0: хеш только у выбранных типов (None - у всех, как раньше)
    run_start_ns = time.time_ns()
    inv = job / 'inventory.sqlite'
    if inv.exists():
        inv.unlink()                     # a new inventory of the folders on every run: no stale paths
    manifest['inventory_finished'] = False
    write_json(job / 'job.json', manifest)
    last_publish = [0.0]
    def inventory_progress(summary):
        now = time.monotonic()
        if now - last_publish[0] >= 2:
            last_publish[0] = now
            publish({**base_state, 'phase': 'inventory', 'phase_title': 'Этап 1 из 2: опись выбранных папок',
                     'files_done': summary['files'], 'bytes_done': summary['bytes'], 'errors': summary['errors'],
                     'elapsed_seconds': round(now - started)})
    say('Папки: ' + '; '.join(folders))
    say('Этап 1 из 2: опись выбранных папок (только имена, размеры и даты)')
    with closing(sqlite3.connect(inv)) as db:
        summary = inventory(root, db, check, inventory_progress, folders=folders)
    write_json(job / 'inventory_summary.json', summary)
    report = {'disk_id': disk_id, 'scan_scope': 'partial', 'folders': folders,
              'hash_scope': 'selected_types' if rule else 'all_regular_files',
              'hash_types': manifest.get('hash_types') if rule else 'all', 'rehash_all': rehash_all, 'status': 'running', 'inventory_errors': summary['errors'], 'physical': physical,
              'app_version': APP_VERSION}
    if summary['status'] == 'interrupted':
        report['status'] = 'interrupted' if STOP_FILE and STOP_FILE.exists() else 'error'
        report['error'] = 'Опись папок прервана'
    elif summary['errors']:
        # A folder that could not be listed must not look empty: the database would drop its records.
        report['status'] = 'inventory_incomplete'
        report['error'] = (f'Недоступно мест при описи: {summary["errors"]}. База такой скан не примет; '
                           'исправьте доступ и продолжите сканирование.')
    if report['status'] != 'running':
        write_json(job / 'result.json', report)
        append_run(job, {'event': 'finish', 'run_id': run_id, 'utc': utc(), 'status': report['status'],
                         'error': report['error']})
        publish({**base_state, 'phase': 'stopped' if report['status'] == 'interrupted' else 'error',
                 'phase_title': report['error'], 'status': report['status']})
        say(f'=== Итог: {report["status"]} · {report["error"]}')
        return 2
    manifest['inventory_finished'] = True
    write_json(job / 'job.json', manifest)
    say(f'Опись завершена: {summary["files"]:,} файлов, {summary["bytes"] / 1e9:,.1f} ГБ')
    ntfs = volume(root)[2].upper() == 'NTFS'
    sources = prior_sources(manifest)
    # При «перечитать всё» с выбором типов прежние хеши нужны невыбранным типам (их не читаем, но и не теряем).
    prior = {} if rehash_all and not rule else rescan.prior_map(sources, folders)
    with closing(sqlite3.connect(inv.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(job / 'hashes.sqlite')) as target:
        target.execute('create table if not exists hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,status text,error text,primary key(disk_id,path))')
        # How each hash was obtained: read in this job, or reused (from_job, its basis). bound_ns: before this moment
        # the hash was certainly not yet measured - the start of the run (or job) that really read the file.
        target.execute('create table if not exists hash_info(path text primary key,how text,from_job text,bound_ns integer,'
                       'change_ns integer,reason text)')
        rows = source.execute('select path,size,mtime_ns,ctime_ns,file_id from files order by size,path').fetchall()
        present = {r[0] for r in rows}
        stale = [p for (p,) in target.execute('select path from hashes where disk_id=?', (disk_id,)) if p not in present]
        target.executemany('delete from hashes where disk_id=? and path=?', [(disk_id, p) for p in stale])
        target.executemany('delete from hash_info where path=?', [(p,) for p in stale])
        target.commit()
        own = {p: (s, str(m), str(i), st, sha) for p, s, m, i, st, sha in target.execute(
            'select path,size,mtime_ns,file_id,status,sha256 from hashes where disk_id=?', (disk_id,))}
        own_info = {p: (fj, b) for p, fj, b in target.execute('select path,from_job,bound_ns from hash_info')}
        gone = [p for p in prior if p not in present]
        by_id = {}
        for p in gone:
            r = prior[p]
            if r['file_id'] not in ('', '0'):
                by_id.setdefault((r['file_id'], r['size'], r['mtime_ns']), []).append(p)
        total = sum(r[1] for r in rows)
        def usable(rel, size, mtime, ctime, file_id):
            o = own.get(rel)
            if o and o[3] == 'verified' and o[4] and o[:2] == (size, str(mtime)) and rel in own_info:
                fj, b = own_info[rel]
                return dict(size=size, mtime_ns=str(mtime), file_id=o[2], ctime_ns=str(ctime or '0'), sha=o[4],
                            status='verified', job=fj, bound_ns=b, own=True)
            return prior.get(rel)
        def same(r):
            c = usable(*r)
            return c and c['sha'] and c['size'] == r[1] and c['mtime_ns'] == str(r[2])
        to_read = sum(r[1] for r in rows if rescan.wants_hash(r[0], rule, r[1]) and (not same(r) or (rehash_all and not usable(*r).get('own'))))
        cached = reused = hashed = unread = damaged = 0
        skipped = skipped_bytes = 0      # тип не выбран и прежнего годного хеша нет: файл не читается, строки хеша нет
        reused_bytes = finished = read = unread_bytes = damaged_bytes = device_in_row = 0
        reasons = {}
        bounds = []                      # bound_ns of reused hashes: «measured not earlier than» dates
        rate = Rate()
        last = [time.monotonic(), time.monotonic()]
        report.update(selected_files=len(rows), selected_bytes=total)
        write_json(job / 'result.json', report)
        say(f'Этап 2 из 2: контрольные суммы SHA-256 — {len(rows):,} файлов, {total / 1e9:,.1f} ГБ; '
            f'прочитать предстоит около {to_read / 1e9:,.1f} ГБ' + (' (перечитать всё)' if rehash_all else ''))
        def state(count=0, phase='hashing', title='Этап 2 из 2: контрольные суммы'):
            now = time.monotonic()
            newly = read + count
            rate.add(now, newly)
            speed = rate.value()
            remaining = max(0, to_read - newly)
            return {**base_state, 'phase': phase, 'phase_title': title,
                    'percent': round(100 * (finished + count) / total, 2) if total else 100.0,
                    'bytes_done': finished + count, 'bytes_total': total, 'files_done': cached + reused + hashed + unread + skipped,
                    'files_total': len(rows), 'reused_files': cached + reused, 'new_files': hashed, 'unread_files': unread,
                    'skipped_files': skipped,
                    'damaged_files': damaged, 'read_bytes': newly, 'to_read_bytes': to_read, 'rate_bytes_per_second': speed,
                    'eta_seconds': round(remaining / speed) if speed else (0 if not remaining else None),
                    'elapsed_seconds': round(now - started), 'errors': summary['errors']}
        def progress(count=0, force=False):
            if not force and STOP_FILE and STOP_FILE.exists():
                raise KeyboardInterrupt()
            now = time.monotonic()
            if not force and now - last[0] < 2:
                return
            last[0] = now
            current = state(count)
            publish(current)
            if force or now - last[1] >= 30:
                last[1] = now
                say(f'{disk_id}: {current["percent"]:.1f}% · файлов {current["files_done"]:,} из {len(rows):,} '
                    f'(из описи {cached + reused:,}, прочитано {hashed:,}) · прочитано {current["read_bytes"] / 1e9:,.1f} '
                    f'из ~{to_read / 1e9:,.1f} ГБ · осталось {duration(current["eta_seconds"])}', to_file=force)
        try:
            for rel, size, mtime, ctime, file_id in rows:
                path = Path(root).joinpath(*safe_relative(rel))
                expected = size, str(mtime), str(file_id)
                check()
                cand = usable(rel, size, mtime, ctime, file_id)
                change_ns = None
                wanted = rescan.wants_hash(rel, rule, size)
                # «перечитать всё» - только выбранные типы; прочитанное уже в ЭТОМ задании (own) при продолжении
                # не перечитывается - проверяется тем же правилом доверия
                again = rehash_all and wanted and not (cand and cand.get('own'))
                try:
                    if again or not cand or not cand['sha'] or not ntfs:
                        how, why = rescan.decide(None, cand, again, ntfs)
                    else:
                        try:
                            cur = rescan.file_info(path, exclusive=True)   # nobody writes while it is checked
                            change_ns = cur['change_ns']
                            if (cur['size'], str(cur['mtime_ns'])) != expected[:2] or \
                                    (expected[2] != '0' and cur['file_id'] != expected[2]):
                                how, why = 'read', 'changed'
                            else:
                                how, why = rescan.decide(cur, cand, False, ntfs)
                        except rescan.Busy:
                            how, why = 'read', 'busy'
                    if how == 'reuse':
                        target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)',
                                       (disk_id, rel, *expected, cand['sha'], 'verified', ''))
                        target.execute('insert or replace into hash_info values (?,?,?,?,?,?)',
                                       (rel, 'own' if cand.get('own') else 'reused', cand['job'], cand['bound_ns'], change_ns, ''))
                        target.commit()
                        if cand.get('own'):
                            cached += 1
                        else:
                            reused += 1; reused_bytes += size
                        if cand.get('bound_ns'):
                            b = int(cand['bound_ns'])
                            bounds[:] = [min(bounds[0], b), max(bounds[1], b)] if bounds else [b, b]
                        finished += size
                        progress()
                        continue
                    if not wanted:       # тип не выбран: не читаем; строки в hashes нет (это не ошибка чтения)
                        target.execute('delete from hashes where disk_id=? and path=?', (disk_id, rel))
                        target.execute('delete from hash_info where path=?', (rel,))
                        target.commit()
                        skipped += 1; skipped_bytes += size; finished += size
                        progress()
                        continue
                    if why == 'new' and len(by_id.get((str(file_id), size, str(mtime)), [])) == 1:
                        why = 'renamed'
                    digest = hash_one(path, expected, progress)
                except (OSError, RuntimeError) as exc:
                    kind = error_kind(exc)
                    target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)',
                                   (disk_id, rel, *expected, None, 'damaged' if kind == 'device' else 'error', str(exc)))
                    target.execute('delete from hash_info where path=?', (rel,))
                    target.commit()
                    unread += 1; unread_bytes += size; finished += size
                    if kind == 'device':
                        damaged += 1; damaged_bytes += size
                    check()
                    say(f'ПРОПУЩЕН ({"нет доступа к файлу" if kind == "file" else "ПОВРЕЖДЕНИЕ НОСИТЕЛЯ"}): {rel}: {exc}')
                    if kind == 'device':
                        device_in_row += 1
                        if device_in_row >= MAX_DEVICE_ERRORS_IN_ROW:
                            raise RuntimeError(f'{device_in_row} ошибок чтения устройства подряд — возможно, диск '
                                               'неисправен. Остановлено; готовые хеши сохранены.')
                    progress()
                    continue
                check()
                target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, digest, 'verified', ''))
                target.execute('insert or replace into hash_info values (?,?,?,?,?,?)', (rel, 'read', job.name, run_start_ns, change_ns, why))
                target.commit()
                r = reasons.setdefault(why, [0, 0])
                r[0] += 1; r[1] += size
                hashed += 1; finished += size; read += size
                device_in_row = 0
                progress()
            report['status'] = 'complete_with_unread_files' if unread else 'complete'
        except KeyboardInterrupt:
            report.update(status='interrupted', error='Stopped by user')
        except (OSError, RuntimeError) as exc:
            report.update(status='error', error=str(exc))
        finally:
            # Honest record of where the hashes came from (degree S in the database: measured by the scanner;
            # for reused ones - at the time of the previous scan, see reuse_sources and hash_info).
            report.update(hashed_files=hashed, cached_files=cached, reused_files=reused, reused_bytes=reused_bytes,
                          newly_read_bytes=read, read_reasons=reasons, gone_files=len(gone), gone_examples=sorted(gone)[:20],
                          unread_files=unread, unread_bytes=unread_bytes, damaged_files=damaged, damaged_bytes=damaged_bytes,
                          skipped_files=skipped, skipped_bytes=skipped_bytes,
                          reuse_basis=rescan.BASIS if not rehash_all else (
                              'перечитать всё: у выбранных типов прежние хеши не использовались; у невыбранных - '
                              + rescan.BASIS if rule else 'перечитать всё: прежние хеши не использовались'),
                          reuse_sources=[{'job': s['dir'].name, 'kind': s['kind'], 'created_utc': rescan.ns_utc(s['created_ns'])}
                                         for s in sources] if not rehash_all or rule else [],
                          reused_measured_utc=[rescan.ns_utc(b) for b in bounds],
                          filesystem_ntfs=ntfs, seconds=round(time.monotonic() - started, 2), app_version=APP_VERSION)
            write_json(job / 'result.json', report)
            progress(force=True)
            phase = 'stopped' if report['status'] == 'interrupted' else ('done' if report['status'].startswith('complete') else 'error')
            titles = {'done': 'Сканирование папок завершено', 'stopped': 'Остановлено с сохранением', 'error': 'Остановлено из-за ошибки'}
            if unread and phase == 'done':
                titles['done'] = f'Завершено, не прочитано файлов: {unread:,}'.replace(',', ' ')
            final = state(phase=phase, title=titles[phase])
            final['status'] = report['status']
            if phase != 'done':
                final['eta_seconds'] = None
            publish(final)
            append_run(job, {'event': 'finish', 'run_id': run_id, 'utc': utc(), 'status': report['status'],
                             'hashed_files': hashed, 'cached_files': cached, 'reused_files': reused, 'reused_bytes': reused_bytes,
                             'read_reasons': reasons, 'gone_files': len(gone), 'newly_read_bytes': read,
                             'unread_files': unread, 'damaged_files': damaged, 'skipped_files': skipped,
                             'reuse_basis': report['reuse_basis'],
                             'reuse_sources': report['reuse_sources'], 'seconds': report['seconds'], 'error': report.get('error', '')})
            why = ', '.join(f'{rescan.REASONS.get(k, k)} {v[0]:,}' for k, v in reasons.items())
            say(rescan.summary_text(report))
            say(f'=== Итог: {report["status"]} · файлов {len(rows):,}: хеш из прежней описи {reused:,}'
                + (f', из прошлого запуска {cached:,}' if cached else '')
                + f', прочитано {hashed:,} ({read / 1e9:,.2f} ГБ' + (f'; {why}' if why else '') + ')'
                + f', исчезли {len(gone):,}' + (f', не прочитано {unread:,}' if unread else '')
                + (f', без хеша (тип не выбран) {skipped:,}' if skipped else '')
                + (f', из них повреждения носителя {damaged:,}' if damaged else '')
                + f' · за {duration(time.monotonic() - started)}' + (f' · {report["error"]}' if report.get('error') else ''))
            print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'].startswith('complete') else 2

def require_separate_output(job, root):
    if job.resolve().drive.upper() == Path(root).drive.upper():
        raise RuntimeError('Results must not be stored on the source volume')

def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def export(job, destination, name=None):
    with lock(job / 'worker.lock'):
        result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        if not result['status'].startswith('complete'):
            raise RuntimeError('Only completed jobs can be exported')
        names = REQUIRED_EXPORTS + [n for n in OPTIONAL_EXPORTS if (job / n).exists()]
        folder = destination / (name or job.name)
        folder.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for name in names:
            original = checksum(job / name)
            shutil.copy2(job / name, folder / name)
            hashes[name] = checksum(folder / name)
            if hashes[name] != original:
                raise RuntimeError('Export copy checksum mismatch: ' + name)
        write_json(folder / 'checksums.json', hashes)
        print('Exported:', folder)

def export_all(root, destination):
    """Export every completed job of a results folder; unchanged exports are skipped."""
    done = skipped = failed = 0
    for job in find_jobs(root):
        status = read_json(job / 'result.json', {}).get('status', '')
        if not status.startswith('complete'):
            print(f'Пропущено (сканирование не завершено): {job.name}')
            skipped += 1
            continue
        try:
            names = REQUIRED_EXPORTS + [n for n in OPTIONAL_EXPORTS if (job / n).exists()]
            target = destination / job.name
            if target.exists():
                saved = read_json(target / 'checksums.json', {})
                if set(saved) == set(names) and all(checksum(job / n) == saved[n] for n in names):
                    print(f'Уже на флешке, без изменений: {job.name}')
                    skipped += 1
                    continue
                # Updated since the previous export (e.g. a top-up pass): a new copy beside it.
                export(job, destination, f'{job.name}_{datetime.now():%Y%m%d_%H%M%S}')
            else:
                export(job, destination)
            done += 1
        except (OSError, RuntimeError, ValueError) as exc:
            print(f'ОШИБКА экспорта {job.name}: {exc}', file=sys.stderr)
            failed += 1
    print(f'Экспорт: выгружено {done}, пропущено {skipped}, ошибок {failed}')
    return 2 if failed else 0

def verified_count(folder):
    try:
        with closing(sqlite3.connect((folder / 'hashes.sqlite').as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute("select count(*) from hashes where status='verified'").fetchone()[0]
    except sqlite3.Error:
        return -1

def import_any(folder, destination):
    """Import one exported job, or every exported job inside a folder (a whole USB stick)."""
    folders = [folder] if (folder / 'checksums.json').exists() else sorted(p for p in folder.iterdir() if (p / 'checksums.json').exists())
    if not folders:
        raise ValueError('No exported jobs (checksums.json) in ' + str(folder))
    failed = 0
    for item in folders:
        try:
            import_result(item, destination, refresh=False)
        except (OSError, ValueError, sqlite3.Error) as exc:
            print(f'ОШИБКА импорта {item.name}: {exc}', file=sys.stderr)
            failed += 1
    refresh_index(destination)
    print(f'Импорт: обработано {len(folders)}, ошибок {failed}')
    return 2 if failed else 0

def import_result(folder, destination, refresh=True):
    hashes = json.loads((folder / 'checksums.json').read_text(encoding='utf-8'))
    if not set(REQUIRED_EXPORTS) <= set(hashes) <= set(REQUIRED_EXPORTS + OPTIONAL_EXPORTS):
        raise ValueError('Unexpected export file list')
    for name, digest in hashes.items():
        if checksum(folder / name) != digest:
            raise ValueError('Transfer checksum mismatch: ' + name)
    manifest = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    if not re.fullmatch(ID_PATTERN, manifest['disk_id']):
        raise ValueError('Invalid disk ID')
    job_id = str(manifest.get('job_id', ''))
    if not JOB_ID.fullmatch(job_id) or not job_id.startswith(manifest['disk_id'] + '_'):
        raise ValueError('Invalid job ID')
    # Filed into the folder of its disk under the original job ID. Nothing is
    # overwritten: a newer version of the same job moves the old one to _Архив.
    output = disk_folder(destination, manifest['disk_id'], manifest.get('record', {})) / job_id
    if output.exists():
        if all((output / n).exists() and checksum(output / n) == d for n, d in hashes.items()):
            print('Уже импортировано, без изменений:', output)
            return output
        if verified_count(folder) < verified_count(output):
            raise ValueError('Импортируемое задание старее уже имеющегося (меньше хешей); ничего не изменено: ' + str(output))
        archived = destination / '_Архив' / 'Заменённые задания' / f'{job_id}_{datetime.now():%Y%m%d_%H%M%S}'
        archived.parent.mkdir(parents=True, exist_ok=True)
        output.rename(archived)
        print('Прежняя версия задания перенесена в', archived)
    output.mkdir(parents=True, exist_ok=False)
    for name in [*hashes, 'checksums.json']:
        shutil.copy2(folder / name, output / name)
    for name, digest in hashes.items():
        if checksum(output / name) != digest:
            raise ValueError('Imported copy checksum mismatch: ' + name)
    print('Imported for review:', output)
    if refresh:
        refresh_index(destination)
    return output

def source_root(letter):
    return check_letter(letter) + ':\\'

def hash_types_of(args):
    """'all' (хеш у всех обычных файлов, как до 1.6.0) или {'mode': 'only'|'skip', 'ext': [...]} по ключам
    --hash-ext / --hash-skip-ext. Список расширений собирает окно каталога из правила «что копировать»."""
    only, skip = getattr(args, 'hash_ext', None), getattr(args, 'hash_skip_ext', None)
    if only is None and skip is None:
        return 'all'
    mode, text = ('only', only) if only is not None else ('skip', skip)
    ext = rescan.parse_ext(text)
    names = rescan.parse_list(getattr(args, 'hash_skip_names', None))
    path_re = getattr(args, 'hash_skip_path_re', None) or ''
    if mode == 'skip' and not ext and not names and not path_re:
        return 'all'                     # пропускать нечего - это все типы
    return {'mode': mode, 'ext': sorted(ext), 'junk_names': names, 'junk_path_re': path_re}

def start_partial(args, record, output):
    """New job of selected folders: identity checked against the previous full inventory of this disk ID."""
    roots = [p.resolve() for p in args.prior_root] if args.prior_root else \
        [output.parent if output.name == rescan.PARTIAL_DIR else output]
    sources = rescan.find_sources(roots, args.disk)
    if not sources:
        raise RuntimeError(f'Нет завершённой полной описи {args.disk} в {"; ".join(map(str, roots))}: '
                           'сначала полное сканирование носителя')
    full = sources[0]['record']
    if str(full.get('volume_serial', '')).upper() != str(record['volume_serial']).upper() or \
            (full.get('hardware_serial') and full.get('hardware_serial') != record.get('hardware_serial')):
        raise RuntimeError(f'Подключён не тот носитель: серийные номера не совпадают с полной описью {args.disk}. '
                           'Ничего не сканировалось.')
    folders = rescan.normalize_folders(source_root(args.letter), args.folder)
    types = hash_types_of(args)
    print(json.dumps({'disk_id': args.disk, 'folders': folders, 'rehash_all': args.rehash_all, 'hash_types': types, **record},
                     ensure_ascii=False, indent=2))
    if not args.yes and input('Check disk ID, device and folders. Type YES to scan: ').strip() != 'YES':
        return 1
    job = disk_folder(output, args.disk, record) / (args.disk + '_' + uuid.uuid4().hex)
    job.mkdir(parents=True, exist_ok=False)
    write_json(job / 'job.json', {'version': VERSION_PARTIAL, 'job_id': job.name, 'disk_id': args.disk,
                'record': record, 'policy': POLICY, 'created_utc': utc(), 'app_version': APP_VERSION,
                'identity_at_registration': describe(args.letter),
                'scan_scope': 'partial', 'hash_scope': 'all_regular_files' if types == 'all' else 'selected_types',
                'folders': folders, 'rehash_all': bool(args.rehash_all), 'hash_types': types,
                'hash_all_types_flag': bool(getattr(args, 'hash_all_types', False)),
                'prior_sources': [{'dir': str(s['dir']), 'kind': s['kind'], 'folders': s['folders'],
                                   'created_ns': s['created_ns']} for s in sources]})
    print('JOB (save this path for resume):', job, flush=True)
    return process(job)

def main():
    global STOP_FILE, PROGRESS_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--progress-file', type=Path, help='Machine-readable progress for the window')
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start')
    start.add_argument('--disk', required=True)
    start.add_argument('--letter', required=True)
    start.add_argument('--yes', action='store_true', help='Confirmation already obtained by graphical launcher')
    start.add_argument('--output', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.')) / 'HDDScanner' / 'results')
    start.add_argument('--folder', action='append', help='Only this folder (from the volume root); repeat for several. '
                       'Result: a partial scan; the previous full inventory of the disk is required')
    start.add_argument('--rehash-all', action='store_true', help='With --folder: read every file, trust no previous hash')
    start.add_argument('--hash-all-types', action='store_true',
                       help='With --folder: SHA-256 of every regular file (documents, projects, archives), not only photo '
                            'and video. This is the rule of folder rescans since 1.4.0; the flag records it explicitly')
    start.add_argument('--hash-ext', metavar='LIST',
                       help='With --folder (1.6.0): SHA-256 only of files with these extensions (comma separated, '
                            'e.g. ".jpg,.mp4"). Others keep a still valid previous hash or stay without hash')
    start.add_argument('--hash-skip-ext', metavar='LIST',
                       help='With --folder (1.6.0): SHA-256 of every regular file except these extensions')
    start.add_argument('--hash-skip-names', metavar='LIST',
                       help='With --hash-ext/--hash-skip-ext: no SHA-256 for these file names (service and temporary '
                            'files, e.g. "thumbs.db,~$*"; * at the end - name start)')
    start.add_argument('--hash-skip-path-re', metavar='REGEX',
                       help='With --hash-ext/--hash-skip-ext: no SHA-256 for paths matching this regular expression '
                            '(editing cache), case insensitive')
    start.add_argument('--prior-root', type=Path, action='append',
                       help='Where previous jobs of the disk are (default: the parent of «Повторное сканирование»)')
    resume = sub.add_parser('resume'); resume.add_argument('job', type=Path)
    exp = sub.add_parser('export'); exp.add_argument('job', type=Path); exp.add_argument('destination', type=Path)
    exa = sub.add_parser('export-all', help='Export all completed jobs of a results folder')
    exa.add_argument('root', type=Path); exa.add_argument('destination', type=Path)
    imp = sub.add_parser('import', help='One exported job or a folder with several')
    imp.add_argument('folder', type=Path); imp.add_argument('destination', type=Path)
    idx = sub.add_parser('index', help='Rebuild the disk register of a results folder'); idx.add_argument('root', type=Path)
    if len(sys.argv) == 1:
        print('HDD Scanner ' + APP_VERSION)
        print('1 - New disk scan\n2 - Resume\n3 - Export to USB\n4 - Import on main PC')
        choice = input('Choose 1-4: ').strip()
        def ask(prompt):
            return input(prompt).strip().strip('"')
        if choice == '1':
            values = ['start', '--disk', ask('Central disk ID (HDD03… or Flash01…): '), '--letter', ask('Source drive letter: ')]
        elif choice == '2':
            values = ['resume', ask('Local JOB folder path: ')]
        elif choice == '3':
            values = ['export', ask('Local JOB folder path: '), ask('USB destination folder: ')]
        elif choice == '4':
            values = ['import', ask('Exported JOB folder on USB: '), ask('Local import destination folder: ')]
        else:
            return 1
        args = parser.parse_args(values)
    else:
        args = parser.parse_args()
    STOP_FILE, PROGRESS_FILE = args.stop_file, args.progress_file
    if args.command == 'start':
        try:
            check_disk_id(args.disk)
        except ValueError as exc:
            parser.error(str(exc))
        if args.rehash_all and not args.folder:
            parser.error('--rehash-all only with --folder')
        if args.hash_all_types and not args.folder:
            parser.error('--hash-all-types only with --folder (a full scan hashes photo and video only)')
        chosen = [n for n, v in (('--hash-all-types', args.hash_all_types), ('--hash-ext', args.hash_ext is not None),
                                 ('--hash-skip-ext', args.hash_skip_ext is not None)) if v]
        if len(chosen) > 1:
            parser.error(' and '.join(chosen) + ': choose one')
        if (args.hash_ext is not None or args.hash_skip_ext is not None) and not args.folder:
            parser.error('--hash-ext / --hash-skip-ext only with --folder')
        if args.hash_ext is not None and not rescan.parse_ext(args.hash_ext):
            parser.error('--hash-ext: empty list of extensions')
        if (args.hash_skip_names or args.hash_skip_path_re) and args.hash_ext is None and args.hash_skip_ext is None:
            parser.error('--hash-skip-names / --hash-skip-path-re only with --hash-ext or --hash-skip-ext')
        if args.hash_skip_path_re:
            try:
                re.compile(args.hash_skip_path_re)
            except re.error as exc:
                parser.error(f'--hash-skip-path-re: {exc}')
        record = inspect(args.letter, media_kind(args.disk))
        output = args.output.resolve()
        if output.drive.upper() == args.letter.rstrip(':\\').upper() + ':':
            parser.error('Output must not be on source volume')
        if args.folder:
            return start_partial(args, record, output)
        print(json.dumps({'disk_id': args.disk, **record}, ensure_ascii=False, indent=2))
        if not args.yes and input('Check central disk ID and device. Type YES to scan: ').strip() != 'YES':
            return 1
        job = disk_folder(output, args.disk, record) / (args.disk + '_' + uuid.uuid4().hex)
        job.mkdir(parents=True, exist_ok=False)
        # The full description is kept beside the identity record used for checks.
        write_json(job / 'job.json', {'version': VERSION, 'job_id': job.name, 'disk_id': args.disk,
                    'record': record, 'policy': POLICY, 'created_utc': utc(), 'app_version': APP_VERSION,
                    'identity_at_registration': describe(args.letter)})
        print('JOB (save this path for resume/export):', job, flush=True)
        return process(job)
    if args.command == 'resume':
        return process(args.job.resolve())
    if args.command == 'export':
        export(args.job.resolve(), args.destination.resolve())
    elif args.command == 'export-all':
        return export_all(args.root.resolve(), args.destination.resolve())
    elif args.command == 'index':
        rows = write_index(args.root.resolve())
        print(f'{INDEX_NAME}: {len(rows)} jobs ->', args.root.resolve() / (INDEX_NAME + '.md'))
    else:
        return import_any(args.folder.resolve(), args.destination.resolve())
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('STOP:', exc, file=sys.stderr)
        if JOB_LOG:
            try:
                with JOB_LOG.open('a', encoding='utf-8') as handle:
                    handle.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + f'ОСТАНОВКА: {exc}\n')
            except OSError:
                pass
        sys.exit(2)
