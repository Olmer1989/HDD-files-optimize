"""Results folders, disk registry and export of jobs (moved verbatim from portable.py)."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

import rescan
from portable_base import (ID_PATTERN, KIND_TITLES, REQUIRED_EXPORTS, OPTIONAL_EXPORTS, id_number, lock, media_kind,
                           policy_version, write_json)

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

def append_run(job, event):
    with (job / 'runs.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')

def is_partial_job(manifest):
    return str(manifest.get('scan_scope') or '').lower() == 'partial'

def prior_sources(manifest):
    """Previous jobs of this disk fixed at job creation (rescan.find_sources), oldest first."""
    return [{**s, 'dir': Path(s['dir'])} for s in manifest.get('prior_sources') or []]

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
