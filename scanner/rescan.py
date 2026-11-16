"""Пересканирование выбранных папок (сканер 1.4.0): когда прежнему хешу можно доверять без чтения файла.

Правило (Дискуссия с GPT 15.11.2026, «Проверка Архитектуры сортировки файлов\\Пересканирование_папок_v1.md»).
Хеш берётся из прежнего измерения сканера без повторного чтения, только если ВСЁ сразу:
  1. прежняя запись - измерение сканера (status verified) в последней полной описи этого носителя или в более
     новом частичном скане; для пути действует самый свежий источник, чья область его покрывает (если в нём пути
     нет - старые источники для него не используются). Записи журналов копирования (C), «со слов» (U), Z, X, N
     для этого не годятся никогда - такие файлы читаются;
  2. тот же путь, размер и mtime_ns; тот же номер файла NTFS (file ID) и время создания, если они записаны;
     строка хешей прежнего задания совпадает с его описью;
  3. время изменения записи NTFS (ChangeTime: меняется при любой записи, переименовании, смене атрибутов, и
     обычные программы его не восстанавливают) раньше момента, когда прежний хеш заведомо ещё не был посчитан:
     начала задания (или запуска), которое прочитало файл. По цепочке наследования граница остаётся исходной;
  4. том NTFS с тем же серийным номером; часы в порядке (граница и ChangeTime не в будущем).
Иначе файл читается. Переименованный файл хеш не наследует. Гарантия - против обычных изменений через Windows
при верных часах, не против умышленной подмены и не против тихой порчи носителя (это - только --rehash-all).

Здесь же - предпросмотр по оглавлению (содержимое файлов не читается) и поиск прежних заданий носителя.
"""
import ctypes
from ctypes import wintypes
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
import time

from inventory import EXCLUDED_DIRS, excluded_file
from build_selection import THRESHOLDS_V2, select

PARTIAL_DIR = 'Повторное сканирование'
EPOCH_DIFF = 116444736000000000             # FILETIME (100 нс с 1601) -> Unix
FUTURE_NS = 24 * 3600 * 10**9               # ChangeTime позже «сейчас + сутки» - часы не в порядке
REASONS = {'new': 'новые', 'changed': 'изменились (размер, дата или номер файла)',
           'change_time': 'запись файла менялась после прежнего скана (ChangeTime)',
           'renamed': 'возможно переименованы или перемещены', 'unread_before': 'в прошлый раз не прочитаны',
           'rehash_all': 'перечитать всё', 'not_ntfs': 'не NTFS: прежним хешам не доверяем',
           'clock': 'даты в будущем: часы не в порядке', 'busy': 'файл занят другой программой',
           'nohash': 'в прежней описи без хеша (не фото и не видео, или .m2t/.dv)'}
BASIS = ('путь, размер, mtime, номер файла NTFS и время создания совпали с прежней описью; запись файла (ChangeTime) '
         'не менялась с момента до прежнего чтения')


# ---------- выбор типов файлов для хеша (сканер 1.6.0) ----------
# Сканер категорий файлов не знает: окно каталога собирает правило из своего «что копировать» (derived.copy_kind) и
# передаёт его ключами. Правило в job.json (hash_types): 'all' - хеш у всех обычных файлов (как до 1.6.0), или
# {'mode': 'only'|'skip', 'ext': [...], 'junk_names': [...], 'junk_path_re': '...'}:
#   only - хеш только у этих расширений; skip - у всех, кроме этих («Другие» - остаток, перечислить его нельзя);
#   junk_names / junk_path_re - служебные и временные файлы по имени (thumbs.db, «~$*» - начало имени) и по пути (кэш
#   монтажа): хеш не считается при любом расширении - они не входят ни в один выбираемый тип.
# Расширение - последнее, нижний регистр, с точкой; без расширения - ''. Пустой файл (0 байт) - «Другие» (как в
# copy_kind; базе хеш пустого файла не нужен).

def parse_list(text):
    """'a, b,,c' -> ['a', 'b', 'c'] (нижний регистр, без пробелов по краям)."""
    return [x.strip().lower() for x in str(text or '').replace(';', ',').split(',') if x.strip()]


def parse_ext(text):
    """'.JPG, jpeg,.Mp4' -> frozenset({'.jpg', '.jpeg', '.mp4'}). Пусто - пустое множество."""
    return frozenset(x if x.startswith('.') else '.' + x for x in parse_list(text))


def ext_of(path):
    """Последнее расширение имени файла в нижнем регистре ('' - без расширения) - как в derived.copy_kind."""
    return os.path.splitext(PureWindowsPath(str(path)).name.lower())[1]


def hash_rule(manifest):
    """Правило из job.json: None (все файлы) или dict(mode, ext, names, prefixes, path_re)."""
    t = (manifest or {}).get('hash_types')
    if not isinstance(t, dict) or t.get('mode') not in ('only', 'skip'):
        return None
    names = [str(n).lower() for n in t.get('junk_names') or []]
    return dict(mode=t['mode'], ext=frozenset(str(e).lower() for e in t.get('ext') or []),
                names=frozenset(n for n in names if not n.endswith('*')),
                prefixes=tuple(n[:-1] for n in names if n.endswith('*') and len(n) > 1),
                path_re=re.compile(t['junk_path_re'], re.I) if t.get('junk_path_re') else None)


def wants_hash(path, rule, size=None):
    """Считать ли хеш этого файла по выбранным типам (size=None - размер неизвестен, считается ненулевым)."""
    if not rule:
        return True
    if size == 0:
        return rule['mode'] == 'skip'            # пустой файл - «Другие»: выбраны ли они
    name = PureWindowsPath(str(path)).name.lower()
    if name in rule['names'] or (rule['prefixes'] and name.startswith(rule['prefixes'])) or             (rule['path_re'] and rule['path_re'].search(str(path).lower())):
        return False
    return (ext_of(name) in rule['ext']) == (rule['mode'] == 'only')


def utc_ns(text):
    """'2026-11-08T15:49:52.48+00:00' -> нс Unix (UTC). Пусто или неверно - None."""
    try:
        d = datetime.fromisoformat(str(text))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1e6) * 1000
    except (TypeError, ValueError):
        return None


def ns_utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat() if ns else ''


# ---------- сведения о файле через один дескриптор ----------

class _BHFI(ctypes.Structure):
    _fields_ = [('attrs', wintypes.DWORD), ('c', wintypes.FILETIME), ('a', wintypes.FILETIME), ('w', wintypes.FILETIME),
                ('vsn', wintypes.DWORD), ('size_hi', wintypes.DWORD), ('size_lo', wintypes.DWORD),
                ('links', wintypes.DWORD), ('idx_hi', wintypes.DWORD), ('idx_lo', wintypes.DWORD)]


class _FBI(ctypes.Structure):
    _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong), ('write', ctypes.c_longlong),
                ('change', ctypes.c_longlong), ('attrs', wintypes.DWORD)]


_K32 = None


def _k32():
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE]
        k.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        _K32 = k
    return _K32


class Busy(OSError):
    """Файл открыт другой программой на запись: подтвердить его неизменность сейчас нельзя."""


def file_info(path, exclusive=False):
    """Размер, mtime, время создания, ChangeTime, номер файла NTFS, атрибуты, ссылок - через ОДИН дескриптор.
    Содержимое не читается. exclusive=True - открыть так, чтобы никто не мог писать в файл, пока он открыт
    (если пишет уже сейчас - Busy)."""
    k = _k32()
    access = 0x80000000 if exclusive else 0x80          # GENERIC_READ (данные не читаются) / FILE_READ_ATTRIBUTES
    share = 0x1 if exclusive else 0x7                    # только чтение / чтение, запись, удаление
    h = k.CreateFileW('\\\\?\\' + os.path.abspath(path), access, share, None, 3, 0x02000000 | 0x00200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        code = ctypes.get_last_error()
        if code in (32, 33):
            raise Busy(code, 'файл занят другой программой', str(path))
        raise ctypes.WinError(code)
    try:
        b, f = _BHFI(), _FBI()
        if not k.GetFileInformationByHandle(h, ctypes.byref(b)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k.GetFileInformationByHandleEx(h, 0, ctypes.byref(f), ctypes.sizeof(f)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(h)

    def ns(ft):
        return (ft - EPOCH_DIFF) * 100 if ft else 0
    return dict(size=(b.size_hi << 32) | b.size_lo, mtime_ns=ns(f.write), ctime_ns=ns(f.creation), change_ns=ns(f.change),
                file_id=str((b.idx_hi << 32) | b.idx_lo), attrs=f.attrs, links=b.links)


# ---------- папки ----------

def normalize_folders(root, folders):
    """Папки от корня тома -> их настоящее написание на диске (регистр букв), покомпонентно.
    Отказ: пусто, корень тома, буква, '..', '/', reparse point в пути, не папка, повтор или вложенность."""
    if not folders:
        raise ValueError('Не заданы папки')
    res = []
    for raw in folders:
        rel = (raw or '').strip().strip('\\')
        p = PureWindowsPath(rel)
        if not rel or '/' in rel or ':' in rel or p.drive or p.root or any(x in ('.', '..') for x in p.parts):
            raise ValueError(f'Недопустимая папка «{raw}»: нужен путь от корня диска без буквы, например «Фото\\2014»')
        current, names = Path(root), []
        for part in p.parts:
            try:
                with os.scandir(current) as it:
                    match = [e.name for e in it if e.name.lower() == part.lower()]
            except OSError as exc:
                raise ValueError(f'Папка «{raw}» недоступна: {exc}')
            exact = [m for m in match if m == part]
            if not match:
                raise ValueError(f'Папки «{raw}» нет на диске')
            name = exact[0] if exact else match[0]
            current = current / name
            st = os.lstat(current)
            if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'В пути «{raw}» ссылка (reparse point) - такую папку сканировать нельзя')
            if not stat.S_ISDIR(st.st_mode):
                raise ValueError(f'«{raw}» - не папка')
            if part.lower() in EXCLUDED_DIRS:
                raise ValueError(f'«{raw}» - служебная папка, сканер её не описывает')
            names.append(name)
        norm = '\\'.join(names)
        for old in res:
            a, b = old.lower() + '\\', norm.lower() + '\\'
            if a.startswith(b) or b.startswith(a):
                raise ValueError(f'Папки повторяются или вложены друг в друга: «{old}» и «{norm}»')
        res.append(norm)
    return res


def inside(path, folders):
    """Папка из folders, в которой лежит path (покомпонентно: «Фото» не задевает «Фото2»), иначе None."""
    low = path.lower()
    for f in folders:
        fl = f.lower()
        if low == fl or low.startswith(fl + '\\'):
            return f
    return None


def walk(root, folders, info=True):
    """Обход папок по тем же правилам, что опись сканера (служебные папки, ключи .env, reparse points - мимо).
    Возвращает (файлы {путь: сведения}, ошибки [(путь, действие, текст)], пропущено reparse). Содержимое не читается."""
    files, errors, reparse = {}, [], 0
    stack = [os.path.join(root, f) for f in folders]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if excluded_file(e.name):
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                        if getattr(st, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(st.st_mode):
                            reparse += 1
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            if e.name.lower() not in EXCLUDED_DIRS:
                                stack.append(e.path)
                            continue
                        if not stat.S_ISREG(st.st_mode):
                            continue
                        rel = os.path.relpath(e.path, root)
                        files[rel] = file_info(e.path) if info else dict(size=st.st_size, mtime_ns=st.st_mtime_ns)
                    except OSError as exc:
                        errors.append((e.path, 'stat', str(exc)))
        except OSError as exc:
            errors.append((d, 'scandir', str(exc)))
    return files, errors, reparse


# ---------- прежние задания носителя ----------

def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def find_sources(roots, disk_id):
    """Прежние задания сканера этого носителя, от старого к новому: последняя завершённая полная опись (как у базы -
    самый свежий result.json) и более новые завершённые частичные сканы. [{dir, kind, folders, created_ns, time, record}]"""
    full, parts = None, []
    for root in roots:
        root = Path(root)
        for result in sorted(root.glob('*/*/result.json')) + sorted((root / PARTIAL_DIR).glob('*/*/result.json')):
            job = result.parent
            if '_Архив' in str(job):
                continue
            info, manifest = _json(result), _json(job / 'job.json')
            if not info or not manifest or (info.get('disk_id') or job.name.split('_')[0]) != disk_id:
                continue
            partial = str(info.get('scan_scope') or '').lower() == 'partial' or bool(info.get('folders'))
            item = dict(dir=job, kind='partial' if partial else 'full', status=str(info.get('status', '')),
                        folders=[str(f).strip('\\') for f in info.get('folders') or []],
                        created_ns=utc_ns(manifest.get('created_utc')), record=manifest.get('record') or {},
                        time=os.path.getmtime(job / 'inventory.sqlite') if (job / 'inventory.sqlite').exists() else 0,
                        mtime=os.path.getmtime(result))
            if partial:
                parts.append(item)
            elif full is None or item['mtime'] > full['mtime']:
                full = item
    if full is None:
        return []
    ok = [p for p in parts if p['status'].startswith('complete') and p['time'] > full['time']]
    return [full] + sorted(ok, key=lambda p: (p['time'], str(p['dir'])))


def _rows(db, folders):
    for f in folders:
        yield from db.execute('select * from files where path = ? or (path >= ? and path < ?)', (f, f + '\\', f + ']'))


def prior_map(sources, folders):
    """Путь -> прежняя запись для путей внутри folders: dict(size, mtime_ns, file_id, ctime_ns, sha, status, job,
    bound_ns - не позже этого момента хеш ещё не был посчитан). Для пути - самый свежий источник, чья область
    его покрывает."""
    res = {}
    for src in sources:
        if src['kind'] == 'full':
            scope = list(folders)
        else:                                   # пересечение областей: вложенная из двух папок
            scope = sorted({f for f in folders if inside(f, src['folders'])} |
                           {g for g in src['folders'] if inside(g, folders)})
        if not scope:
            continue
        for p in [p for p in res if inside(p, scope)]:
            del res[p]
        job, bound = src['dir'].name, src['created_ns']
        inv, hp = src['dir'] / 'inventory.sqlite', src['dir'] / 'hashes.sqlite'
        if not inv.exists():
            continue
        hashes, chain = {}, {}
        if hp.exists():
            with closing(sqlite3.connect(hp.as_uri() + '?mode=ro', uri=True)) as h:
                h.row_factory = sqlite3.Row
                for r in _rows_h(h, scope):
                    hashes[r['path']] = r
                if h.execute("select 1 from sqlite_master where name='hash_info'").fetchone():
                    for p, fj, b in h.execute('select path, from_job, bound_ns from hash_info'):
                        chain[p] = (fj, int(b) if b else None)
        with closing(sqlite3.connect(inv.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            for r in _rows(db, scope):
                p, h = r['path'], hashes.get(r['path'])
                rec = dict(size=r['size'], mtime_ns=str(r['mtime_ns']), file_id=str(r['file_id'] or '0'),
                           ctime_ns=str(r['ctime_ns'] or '0') if 'ctime_ns' in r.keys() else '0',
                           sha=None, status='none', job=job, bound_ns=bound)
                if h is not None:
                    rec['status'] = h['status']
                    same = (h['size'], str(h['mtime_ns'])) == (r['size'], str(r['mtime_ns'])) and \
                        str(h['file_id'] or '0') in ('0', '', rec['file_id'])
                    if h['status'] == 'verified' and h['sha256'] and same:
                        rec['sha'] = h['sha256'].lower()
                        if p in chain:
                            rec['job'], rec['bound_ns'] = chain[p][0] or job, chain[p][1]
                    elif h['status'] == 'verified':
                        rec['status'] = 'inconsistent'
                res[p] = rec
    return res


def _rows_h(h, folders):
    for f in folders:
        yield from h.execute('select * from hashes where path = ? or (path >= ? and path < ?)', (f, f + '\\', f + ']'))


def decide(cur, prior, rehash_all=False, ntfs=True, now_ns=None):
    """('reuse', None) или ('read', причина). cur - file_info текущего файла, prior - запись prior_map или None."""
    now_ns = now_ns or time.time_ns()
    if rehash_all:
        return 'read', 'rehash_all'
    if prior is None:
        return 'read', 'new'
    if not prior['sha']:
        return 'read', {'error': 'unread_before', 'damaged': 'unread_before', 'inconsistent': 'changed'}.get(prior['status'], 'nohash')
    if not ntfs:
        return 'read', 'not_ntfs'
    if cur['size'] != prior['size'] or str(cur['mtime_ns']) != prior['mtime_ns'] or \
            (prior['file_id'] not in ('', '0') and cur['file_id'] != prior['file_id']) or \
            (prior['ctime_ns'] not in ('', '0') and str(cur['ctime_ns']) != prior['ctime_ns']):
        return 'read', 'changed'
    bound = prior['bound_ns']
    if not bound or bound > now_ns or not cur['change_ns'] or cur['change_ns'] > now_ns + FUTURE_NS:
        return 'read', 'clock'
    if cur['change_ns'] >= bound:
        return 'read', 'change_time'
    return 'reuse', None


# ---------- предпросмотр ----------

def plan(root, disk_id, folders, roots, rehash_all=False, filesystem='NTFS', files=None):
    """Что сделает пересканирование, по оглавлению (пути, размеры, даты; содержимое не читается)."""
    sources = find_sources(roots, disk_id)
    if not sources:
        raise ValueError(f'Нет завершённой полной описи {disk_id} - сначала полное сканирование носителя')
    folders = normalize_folders(root, folders)
    prior = prior_map(sources, folders)
    if files is None:
        files, errors, reparse = walk(root, folders)
    else:
        errors, reparse = [], 0
    now = time.time_ns()
    by_id = {}
    for p, r in prior.items():
        if r['file_id'] not in ('', '0') and p not in files:
            by_id.setdefault((r['file_id'], r['size'], r['mtime_ns']), []).append(p)
    count = {'reuse': [0, 0]}
    nonmedia = [0, 0]                    # прочитать придётся и не фото/видео: хеш считается у всех файлов папки
    per_folder = {f: dict(files=0, bytes=0, reuse=0, reuse_bytes=0, read=0, read_bytes=0, gone=0) for f in folders}
    examples = {}
    items = []                           # (путь, байт, расширение, прежний хеш годится) - для выбора типов в окне
    for p, cur in files.items():
        how, why = decide(cur, prior.get(p), rehash_all, filesystem == 'NTFS', now)
        items.append((p, cur['size'], ext_of(p),
                      how == 'reuse' or (rehash_all and decide(cur, prior.get(p), False, filesystem == 'NTFS', now)[0] == 'reuse')))
        if how == 'read' and why == 'new' and len(by_id.get((cur['file_id'], cur['size'], str(cur['mtime_ns'])), [])) == 1:
            why = 'renamed'
        key = 'reuse' if how == 'reuse' else why
        c = count.setdefault(key, [0, 0])
        c[0] += 1; c[1] += cur['size']
        pf = per_folder[inside(p, folders)]
        pf['files'] += 1; pf['bytes'] += cur['size']
        pf['reuse' if how == 'reuse' else 'read'] += 1
        pf['reuse_bytes' if how == 'reuse' else 'read_bytes'] += cur['size']
        if how == 'read':
            examples.setdefault(key, []).append(p)
            if not select(p, cur['size'], THRESHOLDS_V2):
                nonmedia[0] += 1; nonmedia[1] += cur['size']
    gone = [p for p in prior if p not in files]
    for p in gone:
        per_folder[inside(p, folders)]['gone'] += 1
    read = [sum(v[0] for k, v in count.items() if k != 'reuse'), sum(v[1] for k, v in count.items() if k != 'reuse')]
    full = sources[0]
    return dict(disk=disk_id, folders=folders, files=len(files), bytes=sum(x['size'] for x in files.values()),
                reuse=count['reuse'], read=read, read_nonmedia=nonmedia, reasons={k: v for k, v in count.items() if k != 'reuse'},
                gone=len(gone), gone_examples=sorted(gone)[:5], errors=errors, reparse=reparse, per_folder=per_folder,
                examples={k: sorted(v)[:5] for k, v in examples.items()}, rehash_all=rehash_all, items=items,
                sources=[dict(job=s['dir'].name, kind=s['kind'], created=ns_utc(s['created_ns'])) for s in sources],
                full_record=full['record'], damaged_before=_damaged(full['dir']))


def by_types(p, rule):
    """Оценка по выбранным типам (по предпросмотру plan, файлы не читаются): read - прочитать [файлов, байт];
    reuse - взять прежний хеш; skip - останутся без хеша (тип не выбран, прежнего годного хеша нет), skip_paths - их пути.
    То же решение, что у сканера: выбранный тип читается, если прежний хеш не годится (или «перечитать всё»);
    невыбранный берёт прежний годный хеш даже при «перечитать всё», иначе остаётся без хеша."""
    res = dict(read=[0, 0], reuse=[0, 0], skip=[0, 0], skip_paths=[])
    for path, size, ext, ok in p.get('items') or []:
        if wants_hash(path, rule, size):
            key = 'read' if p.get('rehash_all') or not ok else 'reuse'
        else:
            key = 'reuse' if ok else 'skip'
            if key == 'skip':
                res['skip_paths'].append(path)
        res[key][0] += 1
        res[key][1] += size
    return res


def _damaged(job):
    try:
        with closing(sqlite3.connect((job / 'hashes.sqlite').as_uri() + '?mode=ro', uri=True)) as h:
            return h.execute("select count(*) from hashes where status='damaged'").fetchone()[0]
    except sqlite3.Error:
        return 0


def date_ru(text):
    """'2026-11-08T15:49:52+00:00' -> '08.11.2026' (местное время); пусто - ''."""
    ns = utc_ns(text)
    return time.strftime('%d.%m.%Y', time.localtime(ns / 1e9)) if ns else ''


CHANGED = ('changed', 'change_time')


def summary_text(r):
    """Итог пересканирования для владельца (result.json): непересекающиеся числа. Прочитано заново = новые +
    изменились + прочие причины; хеш взят из прежнего скана (правило доверия: размер, даты, номер файла и ChangeTime не
    менялись с прежнего чтения); не прочитано (ошибка чтения) - отдельно."""
    reasons = r.get('read_reasons') or {}
    n_new = (reasons.get('new') or [0])[0]
    n_chg = sum((reasons.get(k) or [0])[0] for k in CHANGED)
    other = [(k, v[0]) for k, v in reasons.items() if k not in CHANGED and k != 'new' and v and v[0]]
    read = r.get('hashed_files') or 0
    line = f'Прочитано заново: {num(read)} (новые {num(n_new)}, изменились {num(n_chg)}'
    line += ''.join(f', {REASONS.get(k, k)} {num(n)}' for k, n in other) + ').'
    reused = (r.get('reused_files') or 0) + (r.get('cached_files') or 0)
    dates = sorted({date_ru(x) for x in r.get('reused_measured_utc') or [] if x}, key=lambda d: d[6:] + d[3:5] + d[:2])
    if r.get('rehash_all'):
        line += ' Перечитано всё: прежние хеши не использовались.'
    else:
        since = (f'с {dates[0]}' if len(dates) == 1 else f'с {dates[0]}–{dates[-1]}' if dates else 'с прежнего чтения')
        line += (f' Хеш взят из прежнего скана (по правилу доверия файлы не менялись {since}): {num(reused)}.')
    if r.get('unread_files'):
        line += f' Не прочитано (ошибка чтения): {num(r["unread_files"])} - у них хеша нет.'
    return line


def gb(x):
    return f'{x / 1e9:,.2f}'.replace(',', ' ').replace('.', ',')


def num(n):
    return f'{n:,}'.replace(',', ' ')


def plan_text(p):
    """Короткий текст предпросмотра для окна и командной строки."""
    lines = [f'{p["disk"]}: папок {len(p["folders"])}, файлов {num(p["files"])} ({gb(p["bytes"])} ГБ).',
             f'Прочитать с диска: {num(p["read"][0])} файлов, {gb(p["read"][1])} ГБ.']
    for k, (n, b) in sorted(p['reasons'].items(), key=lambda x: -x[1][1]):
        ex = '; '.join(p['examples'].get(k, [])[:2])
        lines.append(f'  - {REASONS.get(k, k)}: {num(n)} ({gb(b)} ГБ)' + (f', например: {ex}' if ex else ''))
    nm = p.get('read_nonmedia') or [0, 0]
    lines.append(f'  из них не фото и не видео (документы, проекты, архивы, прочее): {num(nm[0])} ({gb(nm[1])} ГБ) - '
                 'это при хеше у всех типов файлов; хеш у всех файлов папки нужен для точного ответа «можно ли удалять».')
    lines.append(f'Взять хеш из прежней описи (без чтения): {num(p["reuse"][0])} файлов, {gb(p["reuse"][1])} ГБ.')
    lines.append(f'Исчезли с диска (были в прежней описи): {num(p["gone"])}'
                 + (f', например: {"; ".join(p["gone_examples"][:2])}' if p['gone'] else '') + '.')
    if len(p['folders']) > 1:
        for f, s in p['per_folder'].items():
            lines.append(f'  {f}: файлов {num(s["files"])}, прочитать {num(s["read"])} ({gb(s["read_bytes"])} ГБ), '
                         f'из описи {num(s["reuse"])}, исчезли {num(s["gone"])}')
    src = ', '.join(f'{s["job"][:14]}… от {s["created"][:10]}' for s in p['sources'])
    lines.append(f'Прежние описи: {src}.')
    if p['errors']:
        lines.append(f'ВНИМАНИЕ: недоступно {len(p["errors"])} мест ({p["errors"][0][0]}: {p["errors"][0][2]}) - '
                     'скан с такими ошибками база не примет.')
    if p['reparse']:
        lines.append(f'Ссылок (reparse points) пропущено: {p["reparse"]} - как и при полной описи.')
    if p['damaged_before']:
        lines.append(f'ВНИМАНИЕ: в прежней описи {p["damaged_before"]} файлов не читались из-за повреждений носителя. '
                     'Хеши из описи не подтверждают, что диск читается сейчас.')
    lines.append('Это оценка: при скане решение по каждому файлу принимается заново.')
    return lines
