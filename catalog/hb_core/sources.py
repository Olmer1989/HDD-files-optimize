"""Чтение первоисточников: описи, частичные сканы, журналы, таблицы владельца."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import csv
import glob
import io
import json
import os
import re
import time
from pathlib import Path
import build_pilot as bp
from hb_core import paths
from hb_core.paths import journal_paths
from hb_core.consts import DECISION_HEAD, EXCLUSION_HEAD, MANUAL_HEAD, PARTIAL_DIR, SEP
from hb_core.util import complete_lines, sha1, stat_sig, tsv_rows


# ---------- сборка ----------

def find_partials():
    """Частичные сканы папок (result.json с scan_scope=partial) - и в «Повторное сканирование», и рядом с описями."""
    res, seen = [], set()
    for root in bp.SCAN_ROOTS:
        for pattern in (('*', '*', 'result.json'), (PARTIAL_DIR, '*', '*', 'result.json')):
            for result in sorted(glob.glob(str(Path(root).joinpath(*pattern)))):
                job = Path(result).parent
                if '_Архив' in str(job) or job in seen:
                    continue
                try:
                    info = json.loads(Path(result).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if not bp.is_partial(info):
                    continue
                seen.add(job)
                inv = job / 'inventory.sqlite'
                res.append(dict(dir=job, name=job.name, disk=info.get('disk_id') or job.name.split('_')[0],
                                folders=[str(f) for f in info.get('folders') or []], status=info.get('status', '?'),
                                info=info, time=os.path.getmtime(inv) if inv.exists() else os.path.getmtime(result)))
    return sorted(res, key=lambda p: (p['time'], p['name']))


def ensure_tables():
    paths.BASE_DIR.mkdir(parents=True, exist_ok=True)
    paths.ANSWERS.mkdir(exist_ok=True)
    if not paths.MANUAL.exists():
        paths.MANUAL.write_text(MANUAL_HEAD + '\n', encoding='utf-8-sig')
    if not paths.DECISIONS.exists():
        paths.DECISIONS.write_text(DECISION_HEAD + '\n', encoding='utf-8-sig')
    if not paths.EXCLUSIONS.exists():
        paths.EXCLUSIONS.write_text(EXCLUSION_HEAD + '\n', encoding='utf-8-sig')


def read_exclusions():
    """Папки, которые база не учитывает: диск -> [папка]. Строка заголовка необязательна."""
    res = collections.defaultdict(list)
    for f in read_table(paths.EXCLUSIONS):
        f = [x.strip() for x in f] + ['', '']
        if not f[0] or f[0].lower() == 'диск' or not f[1].strip(SEP):
            continue
        res[f[0]].append(f[1].strip(SEP))
    return res


def read_tsv(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE) if r and any(x.strip() for x in r)]


def read_table(path):
    """Таблица владельца (ручные операции, решения, исключения): только ЦЕЛЫЕ строки. Строка, которую
    кто-то ещё дописывает (нет перевода строки), не читается: обрезанный путь «Фото» вместо «Фотоархив»
    задел бы чужую ветку."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    return tsv_rows(data[:data.rfind(b'\n') + 1])


def serial_map(jobs):
    m = {}
    for d, j in jobs.items():
        try:
            ser = json.loads((j['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
            m[str(ser).upper()] = d
        except (OSError, ValueError, KeyError):
            pass
    return m


def log_time(log):
    """Когда шёл запуск: время из имени журнала (его ставит скрипт при старте), иначе время файла."""
    m = re.search(r'(\d{4})-(\d\d)-(\d\d) (\d\d)-(\d\d)(?:-(\d\d))?', Path(log).name)
    if m:
        try:
            return time.mktime(tuple(int(x or 0) for x in m.groups()) + (0, 0, -1))
        except (ValueError, OverflowError):
            pass
    return os.path.getmtime(log)


def manual_time(date):
    """'12.11.2026' -> конец этого дня; непонятная дата -> сейчас (операция считается свежей)."""
    try:
        d, m, y = (int(x) for x in date.split('.')[:3])
        return time.mktime((y, m, d, 23, 59, 59, 0, 0, -1))
    except (ValueError, OverflowError):
        return time.time()


def manual_rows():
    """Строки таблицы ручных операций: (номер строки в файле, поля)."""
    return [(line_no, [x.strip() for x in f] + [''] * 7) for line_no, f in enumerate(read_table(paths.MANUAL)[1:], 2)]


def event_stream():
    """Все поправки к описям одним потоком по времени: (время, порядок, имя, вид, данные).
    Журнал скрипта - время запуска; частичный скан - время его описи; ручная операция - конец её дня."""
    ev = [(log_time(p), 0, p, 'log', p) for p in journal_paths()]
    ev += [(pj['time'], 1, str(pj['dir']), 'partial', pj) for pj in find_partials()]
    ev += [(manual_time(f[0]), 2, f'{n:09d}', 'manual', (n, f)) for n, f in manual_rows()]
    return sorted(ev, key=lambda e: e[:3])


def discover(jobs):
    """Все модули - первоисточники базы: ключ -> dict(kind, time, size, mtime_ns, checksum, data)."""
    mods = {}
    for d, j in jobs.items():
        sig = [str(j['dir'])]
        for fn in ('result.json', 'inventory.sqlite', 'hashes.sqlite'):
            p = j['dir'] / fn
            if p.exists():
                sig.append([fn, *stat_sig(p)])
        ip = j['dir'] / 'inventory.sqlite'
        size, mt = stat_sig(ip) if ip.exists() else (0, 0)
        mods[f'опись: {d}'] = dict(kind='опись', time=os.path.getmtime(ip) if ip.exists() else j.get('mtime', 0),
                                   size=size, mtime_ns=mt, checksum=sha1(json.dumps(sig, ensure_ascii=False).encode()),
                                   data=(d, j))
    for pj in find_partials():
        sig = [str(pj['dir'])] + [[fn, *stat_sig(pj['dir'] / fn)] for fn in ('result.json', 'inventory.sqlite', 'hashes.sqlite')
                                  if (pj['dir'] / fn).exists()]
        mods[f'частичный скан: {pj["dir"].parent.name}\\{pj["name"]}'] = dict(
            kind='частичный скан', time=pj['time'], size=0, mtime_ns=0,
            checksum=sha1(json.dumps(sig, ensure_ascii=False).encode()), data=pj)
    for p in journal_paths():
        size, mt = stat_sig(p)
        mods[f'журнал: {Path(p).parent.name}\\{Path(p).name}'] = dict(kind='журнал', time=log_time(p), size=size,
                                                                      mtime_ns=mt, checksum=None, data=p)
    for n, f in manual_rows():
        mods[f'ручная операция: строка {n:05d}'] = dict(kind='ручная операция', time=manual_time(f[0]), size=0, mtime_ns=0,
                                                       checksum=sha1('\t'.join(f).strip().encode()), data=(n, f))
    for n, f in enumerate(read_table(paths.EXCLUSIONS), 1):
        f = [x.strip() for x in f] + ['', '']
        if f[0] and f[0].lower() != 'диск' and f[1].strip(SEP):
            mods[f'исключение: строка {n:05d}'] = dict(kind='исключение', time=0, size=0, mtime_ns=0,
                                                       checksum=sha1('\t'.join(f).strip().encode()), data=(f[0], f[1].strip(SEP)))
    return mods


def read_log(m, done=None):
    """Журнал: целые строки, их размер в байтах, контрольная сумма. done=(размер, сумма) уже учтённой части:
    если журнал только дописан - возвращает и число уже учтённых строк, иначе None (журнал изменён)."""
    data = complete_lines(Path(m['data']).read_bytes())
    m.update(size=len(data), checksum=sha1(data))
    rows = tsv_rows(data)
    m['rows'] = rows
    if done is None:
        return 0
    size, checksum, n = done
    if len(data) < size or sha1(data[:size]) != checksum:
        return None
    return n
