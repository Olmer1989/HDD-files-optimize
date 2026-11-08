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
import uuid

from inventory import inventory, volume, discover_disk, MEDIA, MIN_BYTES, EXCLUDED_DIRS
from build_selection import select, THRESHOLDS_V1, THRESHOLDS_V2, CAMERA_IMAGES, VIDEO
from hash_files import hash_one, signature

# VERSION is the job format/algorithm. It is unchanged, so jobs started by
# 1.0.x continue with this program. APP_VERSION is the program release.
VERSION = '1.0.0'
APP_VERSION = '1.2.0'
STOP_FILE = None
PROGRESS_FILE = None
JOB_LOG = None
# POLICY_V1 must stay byte-for-byte equal to the policy stored by 1.0.x jobs.
POLICY_V1 = {'algorithm': 'sha256', 'min_bytes': MIN_BYTES,
             'media_extensions': sorted(MEDIA), 'excluded_dirs': sorted(EXCLUDED_DIRS)}
POLICY_V2 = {'version': 2, 'algorithm': 'sha256', 'thresholds_bytes': THRESHOLDS_V2,
             'camera_image_extensions': sorted(CAMERA_IMAGES), 'video_extensions': sorted(VIDEO),
             'media_extensions': sorted(MEDIA), 'excluded_dirs': sorted(EXCLUDED_DIRS)}
POLICY = POLICY_V2  # for new jobs; version 1 jobs are upgraded by a top-up pass
POLICY_TEXT = 'фото JPEG/HEIC от 50 КБ, прочие изображения и RAW от 150 КБ, видео любого размера'

def policy_version(policy):
    if policy == POLICY_V2:
        return 2
    if policy == POLICY_V1:
        return 1
    return None
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

def inspect(letter):
    letter = check_letter(letter)
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               f"$p=Get-Partition -DriveLetter '{letter}'; $d=Get-Disk -Number $p.DiskNumber; "
               "[pscustomobject]@{hardware_serial=([string]$d.SerialNumber).Trim(); "
               "physical_bytes=$d.Size; model=[string]$d.FriendlyName} | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            check=True, capture_output=True, encoding='utf-8-sig')
    record = json.loads(result.stdout)
    root = letter + ':\\'
    serial, label, filesystem = volume(root)
    record.update(volume_serial=serial, volume_bytes=shutil.disk_usage(root).total,
                  label_at_registration=label, filesystem=filesystem)
    if not record['hardware_serial']:
        raise RuntimeError('No hardware serial: manual identification required')
    return record

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
#   <results root>/<HDDxx - model - capacity - label>/<job_id>/
#   <results root>/Реестр дисков.md and .csv, rebuilt after each scan/import.
JOB_ID = re.compile(r'HDD[0-9]{2,}_[0-9a-f]{32}')
INDEX_NAME = 'Реестр дисков'

def capacity(size):
    if not size:
        return 'размер неизвестен'
    if size >= 1e12:
        return f'{size / 1e12:.1f}'.replace('.0', '').replace('.', ',') + ' ТБ'
    return f'{round(size / 1e9)} ГБ'

def disk_folder_name(disk_id, record):
    parts = [disk_id, (record.get('model') or 'модель неизвестна').strip(), capacity(record.get('physical_bytes'))]
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
        'Номер': manifest.get('disk_id', '?'), 'Модель': record.get('model', ''), 'Ёмкость': capacity(record.get('physical_bytes')),
        'Метка тома': record.get('label_at_registration', ''), 'Серийный номер устройства': record.get('hardware_serial', ''),
        'Серийный номер тома': record.get('volume_serial', ''), 'Метка на диске (GUID/MBR)': marker or '',
        'Тип': identity.get('media_type') if identity.get('media_type') in ('HDD', 'SSD') else '',
        'Подключение': identity.get('bus_type', ''), 'Последняя буква': identity.get('letter', ''),
        'Компьютер': identity.get('computer', ''), 'Состояние': status,
        'Файлов на диске': summary.get('files', ''), 'Занято файлами, ГБ': round(summary['bytes'] / 1e9, 1) if summary.get('bytes') else '',
        'Фото/видео с хешем': result.get('selected_files', ''),
        'Их объём, ГБ': round(result['selected_bytes'] / 1e9, 1) if result.get('selected_bytes') else '',
        'Ошибок описи': summary.get('errors', ''),
        'Правила': {2: 'v2', 1: 'v1 — нужен добор'}.get(policy_version(manifest.get('policy')), 'другие'),
        'Дата': (last_run.get('utc') or manifest.get('created_utc', ''))[:10],
        'Папка': str(job.relative_to(root)),
    }

def write_index(root):
    import csv
    rows = [job_row(job, root) for job in find_jobs(root)]
    rows.sort(key=lambda r: (int(r['Номер'][3:]) if r['Номер'][3:].isdigit() else 0, r['Дата']))
    warnings = []
    by_id, by_serial = {}, {}
    for r in rows:
        by_id.setdefault(r['Номер'], set()).add((r['Серийный номер устройства'], r['Серийный номер тома']))
        by_serial.setdefault((r['Серийный номер устройства'], r['Серийный номер тома']), set()).add(r['Номер'])
    warnings += [f'Номер {k} назначен разным дискам — нужно разобраться вручную.' for k, v in by_id.items() if len(v) > 1]
    warnings += [f'Один диск (серийный номер {k[0]}) записан под номерами {", ".join(sorted(v))}.' for k, v in by_serial.items() if len(v) > 1]
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
                   'interrupted': 'остановлен', 'error': 'ошибка', 'running': 'не завершён'}
    short = ['Номер', 'Модель', 'Ёмкость', 'Метка тома', 'Тип', 'Подключение', 'Состояние', 'Правила', 'Фото/видео с хешем', 'Их объём, ГБ', 'Дата', 'Папка']
    lines = [f'# {INDEX_NAME}', '', f'Создан автоматически {datetime.now():%d.%m.%Y %H:%M}. Не редактировать вручную: '
             'файл пересоздаётся после каждого сканирования и импорта. Полные сведения, включая серийные номера, — в '
             f'«{INDEX_NAME}.csv» (открывается в Excel).', '',
             f'Заданий: {len(rows)} · дисков: {len(by_id)} · фото/видео с хешем: '
             + f'{sum(r["Фото/видео с хешем"] or 0 for r in rows):,}'.replace(',', ' ') + ' файлов, '
             + f'{sum(r["Их объём, ГБ"] or 0 for r in rows):,.1f}'.replace(',', ' ') + ' ГБ', '']
    if warnings:
        lines += ['## Требует внимания', '', *[f'- {w}' for w in warnings], '']
    lines += ['| ' + ' | '.join(short) + ' |', '|' + '---|' * len(short)]
    for r in rows:
        values = {**r, 'Состояние': status_text.get(r['Состояние'], r['Состояние']), 'Папка': r['Папка'].replace('\\', '/')}
        lines.append('| ' + ' | '.join(str(values[c]).replace('|', '/') for c in short) + ' |')
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
    if manifest.get('version') != VERSION or policy_version(manifest['policy']) is None:
        raise RuntimeError('Different scan policy; use the original worker version')
    disk_id, record = manifest['disk_id'], manifest['record']
    base_state = {'job': str(job), 'disk_id': disk_id, 'model': record.get('model', ''),
                  'hardware_serial': record.get('hardware_serial', ''), 'volume_serial': record.get('volume_serial', '')}
    publish({**base_state, 'phase': 'identify', 'phase_title': 'Проверка диска'})
    root, physical = discover_disk(record)
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
        if policy_version(manifest['policy']) == 1:
            # Top-up: the inventory already lists small files, so only the newly
            # selected ones are read; all saved hashes are reused. Recorded first,
            # so an older program refuses to continue this job under old rules.
            manifest.setdefault('policy_history', []).append({'from': 1, 'to': 2, 'utc': utc(), 'app_version': APP_VERSION})
            manifest['policy'] = POLICY_V2
            write_json(job / 'job.json', manifest)
            append_run(job, {'event': 'policy_upgrade', 'run_id': run_id, 'utc': utc(), 'from': 1, 'to': 2})
            say('Правила выборки обновлены с версии 1 (всё от 1 МиБ) до версии 2: ' + POLICY_TEXT +
                '. Готовые хеши сохраняются, дочитываются только новые мелкие файлы.')
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
            cached = hashed = finished = read = 0
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
                        'bytes_done': position, 'bytes_total': total, 'files_done': cached + hashed,
                        'files_total': len(rows), 'reused_files': cached, 'new_files': hashed,
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
                        f'файлов {current["files_done"]:,} из {len(rows):,} (готовых хешей {cached:,}, новых {hashed:,}) · '
                        f'{(speed or 0) / 1e6:.0f} МБ/с · осталось {duration(current["eta_seconds"])}',
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
                    current = signature(path.stat())
                    if old == (*expected, 'verified') and current[:2] == expected[:2] and (expected[2] == '0' or current[2] == expected[2]):
                        cached += 1
                        finished += size
                        progress()
                        continue
                    try:
                        digest = hash_one(path, expected, progress)
                        check()
                    except (OSError, RuntimeError) as exc:
                        target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, None, 'error', str(exc)))
                        target.commit()
                        say(f'ОШИБКА чтения: {rel}: {exc}')
                        raise
                    target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, digest, 'verified', ''))
                    target.commit()
                    hashed += 1; finished += size; read += size
                    progress()
                report['status'] = 'complete_with_inventory_errors' if summary['errors'] else 'complete'
            except KeyboardInterrupt:
                report.update(status='interrupted', error='Stopped by user')
            except (OSError, RuntimeError) as exc:
                report.update(status='error', error=str(exc))
            finally:
                report.update(hashed_files=hashed, cached_files=cached, newly_read_bytes=read,
                              seconds=round(time.monotonic()-started, 2), app_version=APP_VERSION)
                write_json(job / 'result.json', report)
                progress(force=True)
                phase = {'complete': 'done', 'complete_with_inventory_errors': 'done', 'interrupted': 'stopped'}.get(report['status'], 'error')
                titles = {'done': 'Сканирование завершено', 'stopped': 'Остановлено с сохранением', 'error': 'Остановлено из-за ошибки'}
                final = state(phase=phase, title=titles[phase])
                if phase != 'done':
                    final['eta_seconds'] = None
                final['status'] = report['status']
                publish(final)
                append_run(job, {'event': 'finish', 'run_id': run_id, 'utc': utc(), 'status': report['status'],
                                 'hashed_files': hashed, 'cached_files': cached, 'newly_read_bytes': read,
                                 'seconds': report['seconds'], 'error': report.get('error', '')})
                say(f'=== Итог: {report["status"]} · новых хешей {hashed:,}, готовых {cached:,} · '
                    f'прочитано {read / 1e9:,.1f} ГБ за {duration(time.monotonic() - started)}'
                    + (f' · {report["error"]}' if report.get('error') else ''))
                print(json.dumps(report, ensure_ascii=False, indent=2))
    refresh_index(results_root(job))
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
    if not re.fullmatch('HDD[0-9]{2,}', manifest['disk_id']):
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
            values = ['start', '--disk', ask('Central disk ID (HDD03 etc): '), '--letter', ask('Source drive letter: ')]
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
        if not re.fullmatch('HDD[0-9]{2,}', args.disk) or int(args.disk[3:]) < 3:
            parser.error('Assign a new central disk ID, HDD03 or higher; HDD01/02 already exist')
        record = inspect(args.letter)
        output = args.output.resolve()
        if output.drive.upper() == args.letter.rstrip(':\\').upper() + ':':
            parser.error('Output must not be on source volume')
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
