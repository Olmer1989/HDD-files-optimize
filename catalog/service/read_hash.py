"""Чтение для окна: пять типов, «без хеша», даты хешей папки, поиск папок, подпись источников.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections
import re
import sqlite3
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import ro, SEP
from .directions_v3 import snapshot
from .read_disks import folder_mark, rescans_text


TYPE5 = ('фото', 'видео', 'документы', 'архивы', 'другие')       # 5 типов окна «Список файлов» и «Без хеша»


def type5(k):
    """Тип файла (derived.copy_kind, 9 видов) -> один из 5 типов окна: прочие, проекты, музыка, программы и мусор -
    «другие»."""
    return {hb.F_PHOTO: 0, hb.F_VIDEO: 1, hb.F_TEXT: 2, hb.F_ARCH: 3}.get(k, 4)


NOHASH_SQL = "(sha is null or sha = '') and size > 0"            # «без хеша» - одно определение (этап 16)


def nohash_info(disk, c=None):
    """«Без хеша» носителя (этап 16): ОДИН проход по его записям без хеша (sha пуст, size > 0; Z/U/X тоже - у них хеш не
    измерен) - всего, фото и видео, по 5 типам, Z/U/X и число в каждой папке вместе с подпапками (для столбца «Без хеша»
    дерева «Дисков и папок»; агрегат в базе не хранится - считается по требованию).
    -> dict(total, media, by_type=[5], zux, folders={папка: файлов}, media_folders=[папки фото и видео без хеша для
    «Досчитать хеш»: родители файлов, вложенная в уже взятую не повторяется], media_root=файлов в корне)."""
    own = c is None
    c = c or ro()
    try:
        ft = hb.fast_folder_type(fine=True)
        direct = collections.Counter()
        by, total, zux, media_paths = [0] * 5, 0, 0, []
        for path, size, nm, ev in c.execute(f'select path, size, name_lc, ev from files where disk=? and {NOHASH_SQL}',
                                            (disk,)):
            k = ft(path, nm, size)
            by[type5(k)] += 1
            total += 1
            if k in (hb.F_PHOTO, hb.F_VIDEO):
                media_paths.append(path)
            zux += ev in (hb.EV_SIZE, hb.EV_USER, hb.EV_STALE)
            direct[hb.parent_of(path)] += 1
    finally:
        if own:
            c.close()
    media = len(media_paths)
    media_folders, media_root = hb.scan_folders(media_paths)
    sub = collections.Counter()
    for f, n in direct.items():
        while True:
            sub[f] += n
            if not f:
                break
            f = hb.parent_of(f)
    return dict(total=total, media=media, by_type=by, zux=zux, folders=dict(sub), media_folders=media_folders,
                media_root=media_root)


def disk_hash_info(disk):
    """Строки над деревом «Диски и папки» (этап 16): text - откуда даты («опись от …» и «после полной описи N раз
    пересканированы выбранные папки»); hash - «Хеш есть у всех фото и видео» или тревога; nohash - nohash_info (тот же
    проход даёт столбец «Без хеша»). -> dict(text, tip, hash, alarm, nohash)."""
    c = ro()
    try:
        total = c.execute('select count(*) from files where disk=?', (disk,)).fetchone()[0]
        scanned = (c.execute('select scanned from disks where disk=?', (disk,)).fetchone() or [None])[0]
        parts, pf = c.execute('select count(distinct time), count(*) from scan_folders where disk=?', (disk,)).fetchone()
        media_all = (c.execute("select coalesce(n0, 0) + coalesce(n1, 0) from folders where disk=? and folder=''",
                               (disk,)).fetchone() or [0])[0]
        info = nohash_info(disk, c)
    finally:
        c.close()
    when = f'опись от {_day(scanned)}' if scanned else 'дата описи неизвестна'
    if parts:
        when += ' · ' + rescans_text(parts, pf)
    if not total:
        return dict(text='файлов в описи нет', tip='', hash='', alarm=False, nohash=info)
    if info['media']:
        hash_ = (f'⚠ Без хеша {info["media"]:,} фото и видео'.replace(',', ' ') +
                 ' — копию нельзя проверить: пересканируйте их папки с типами «Фото» и «Видео»')
    elif not media_all:
        hash_ = 'Фото и видео на носителе нет'              # «есть у всех» при нуле фото и видео сбивало бы с толку
    else:
        hash_ = 'Хеш есть у всех фото и видео'
    return dict(text=when, tip='Точно, когда измерены хеши выбранной папки, — строка в панели ниже (выделите одну '
                               'папку).', hash=hash_, alarm=bool(info['media']), nohash=info)


def folder_presence(disk, folder):
    """Чего из папки нет на 45 и 77 (файлы с SHA-256 любого типа, по таблице presence; решения не учитываются)."""
    cond, args = hb.prefix_cond('f.path', (folder or '').strip(SEP))
    c = ro()
    try:
        q = f"""select count(*), coalesce(sum(f.size),0),
                       coalesce(sum(case when not coalesce(p.e45 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when not coalesce(p.e77 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when p.ndisks=1 then f.size end),0)
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        n, b, no45, no77, only = c.execute(q, [disk] + args).fetchone()
        nohash = c.execute(f"select count(*) from files f where f.disk=? and f.sha is null and {cond}", [disk] + args).fetchone()[0]
        return dict(files=n, gib=b / hb.GIB, no45=no45 / hb.GIB, no77=no77 / hb.GIB, only=only / hb.GIB, nohash=nohash)
    finally:
        c.close()


def _day(t):
    return time.strftime('%d.%m.%Y', time.localtime(t)) if t else 'дата неизвестна'


def _log_day(name):
    m = re.search(r'(\d{4})-(\d\d)-(\d\d)', name or '')
    return f'{m.group(3)}.{m.group(2)}.{m.group(1)}' if m else 'дата неизвестна'


_n = lambda n: f'{n:,}'.replace(',', ' ')

HASH_HINT = 'Сомневаетесь? «Пересканировать папку…» с галочкой «Перечитать всё».'


def hash_dates(disk, folder):
    """Когда измерены хеши файлов папки - по происхождению строк базы (origin) и, для частичных сканов, по таблице
    hash_info их hashes.sqlite. Считается при ответе, база не меняется. Дата частичного скана - время его описи;
    «взято из прежнего скана» - хеш не перечитывался (правило доверия), «измерены не раньше» - начало задания,
    которое действительно прочитало файл (bound_ns). Нет сведений - «дата неизвестна».
    -> dict(text=одна строка, hint=подсказка, parts=[...], nohash=число)."""
    folder = (folder or '').strip(SEP)
    cond, args = hb.prefix_cond('path', folder)
    c = ro()
    try:
        groups = c.execute(f'select origin, count(*), count(sha) from files where disk=? and {cond} group by origin',
                           [disk] + args).fetchall()
        scanned = (c.execute('select scanned from disks where disk=?', (disk,)).fetchone() or [None])[0]
    finally:
        c.close()
    nohash = sum(n - h for _, n, h in groups)
    partials = {pj['name']: pj for pj in hb.find_partials()} if any((o or '').startswith('частичный скан') for o, _, _ in groups) else {}
    parts, logs, manual = [], [0, set()], 0
    for origin, n, h in sorted(groups, key=lambda g: g[0] or ''):
        origin = origin or ''
        if not h:
            continue
        if origin == 'опись':
            parts.append((scanned or 0, f'{_day(scanned)} - полная опись ({_n(h)} файлов)'))
        elif origin.startswith('частичный скан: '):
            name = origin.split(': ', 1)[1]
            pj = partials.get(name)
            reused, bounds = None, []
            if pj and (pj['dir'] / 'hashes.sqlite').exists():
                try:
                    hc = sqlite3.connect(f'file:{(pj["dir"] / "hashes.sqlite").as_posix()}?mode=ro', uri=True)
                    try:
                        if hc.execute("select 1 from sqlite_master where name='hash_info'").fetchone():
                            hcond, hargs = hb.prefix_cond('path', folder)
                            reused, b0, b1 = hc.execute(
                                f"select count(*), min(bound_ns), max(bound_ns) from hash_info where how='reused' and {hcond}",
                                hargs).fetchone()
                            bounds = [x for x in (b0, b1) if x]
                    finally:
                        hc.close()
                except sqlite3.Error:
                    reused = None
            extra = ''
            if reused is None:
                extra = ', сколько взято из прежнего скана - неизвестно'
            elif reused:
                days = sorted({_day(b / 1e9) for b in bounds}, key=lambda d: d[6:] + d[3:5] + d[:2])
                extra = (f', из них взято из прежнего скана {_n(reused)}'
                         + (f' (измерены не раньше {"–".join(days)})' if days else ''))
            parts.append((pj['time'] if pj else 0,
                          f'{_day(pj["time"]) if pj else "дата неизвестна"} - пересканирование ({_n(h)} файлов'
                          + extra + ')'))
        elif origin.startswith('журнал: '):
            logs[0] += h
            logs[1].add(_log_day(origin))
        else:
            manual += h
    if logs[0]:
        days = sorted(logs[1], key=lambda d: d[6:] + d[3:5] + d[:2])
        parts.append((1e12, f'{", ".join(days[:3])}{"…" if len(days) > 3 else ""} - копирование шаблоном '
                      f'(хеш прочитанных байтов, {_n(logs[0])} файлов)'))
    if manual:
        parts.append((2e12, f'другие записи ({manual} файлов)'))
    parts.sort(key=lambda x: x[0])
    text = ('Хеши измерены: ' + '; '.join(p for _, p in parts) + '.') if parts else 'Хешей у файлов этой папки нет.'
    if nohash:
        text += f' Без хеша: {_n(nohash)} файлов.'
    return dict(text=text, hint=HASH_HINT, parts=[p for _, p in parts], nohash=nohash)


def find_folders(words, disk=None, limit=300):
    """Папки, в пути которых есть все слова (только верхние совпадения), по таблице folders; у каждой - ГБ по типам и
    решение владельца (как в дереве «Дисков и папок»), тем же запросом."""
    words = [w.lower() for w in words if w.strip()]
    if not words:
        return []
    q = ('select disk, folder, files, bytes, ' + ', '.join(f'b{i}' for i in range(5)) + ' from folders where '
         + ' and '.join(['instr(folder_lc, ?) > 0'] * len(words)))
    args = list(words)
    if disk:
        q += ' and disk=?'
        args.append(disk)
    c = ro()
    try:
        rows = c.execute(q, args).fetchall()
        hits = {(r[0], r[1]) for r in rows}
        top = [r for r in rows if r[1] and (r[0], hb.parent_of(r[1])) not in hits]
        top.sort(key=lambda r: -r[3])
        top = top[:limit]
        # состав и решение владельца - как в дереве (folder_children): отметки и служебные папки - по разу на носитель
        snap = snapshot()
        dirs = hb.parse_directions(snap['directions'])
        per = {}
        for d in {r[0] for r in top}:
            per[d] = (hb.MarkSet.build(hb.mark_rows(d, snap['decisions']), dirs), hb.moved_roots(c, d))
    finally:
        c.close()
    return [dict(disk=r[0], path=r[1], files=r[2], gib=r[3] / hb.GIB, types=[(x or 0) / hb.GIB for x in r[4:9]],
                 mark=folder_mark(r[1], per[r[0]][0], dirs, per[r[0]][1])) for r in top]


def sources_signature():
    """Быстрая подпись первоисточников (размеры и время таблиц, журналов, описей) - чтобы окно знало,
    что пора применить новые модули. Диски не читаются."""
    sig = []
    for p in [hb.MANUAL, hb.DECISIONS, hb.EXCLUSIONS] + [Path(x) for x in hb.journal_paths()]:
        try:
            st = Path(p).stat()
            sig.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for j in bp.find_jobs().values():
        try:
            st = (j['dir'] / 'inventory.sqlite').stat()
            sig.append((str(j['dir']), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for pj in hb.find_partials():
        sig.append((str(pj['dir']), pj['time']))
    return hash(tuple(sorted(sig)))
