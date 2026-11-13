"""Черновой общий каталог и пробная таблица Excel (только чтение описей).

Читает готовые результаты сканера (inventory.sqlite + hashes.sqlite) из нескольких
папок и старый индекс G (размер + путь, медиа от 1 МБ, без хешей). Ничего не
копирует, не перемещает и не удаляет; архивные диски не нужны.

Запуск:  py catalog\\build_pilot.py
Результат: Каталог дисков\\Пробная таблица <дата>.xlsx
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT = Path(__file__).resolve().parent.parent
# Все задания собираются сюда скриптом catalog\consolidate.py.
SCAN_ROOTS = [PROJECT / 'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные']
G_INDEX = PROJECT / 'index_G.txt'
OUT_DIR = PROJECT / 'Каталог дисков'

GIB = 1024 ** 3
TIB = 1024 ** 4
SEP = '\\'

TYPES = {
    'Фото JPEG': '.jpg .jpeg',
    'Фото HEIC (телефоны)': '.heic .heif',
    'Фото RAW': '.raw .cr2 .cr3 .nef .nrw .dng .arw .srf .sr2 .orf .rw2 .raf .pef',
    'Прочие изображения': '.png .tif .tiff .webp .bmp .gif .avif',
    'Видео': '.mov .mp4 .avi .mkv .m4v .mts .m2ts .mpg .mpeg .wmv .3gp .vob .mod .tod .mxf .ts .m2v .webm .flv',
}
EXT_TYPE = {e: t for t, exts in TYPES.items() for e in exts.split()}
T_CACHE = 'Кэш и прокси монтажа'
T_SMALL = 'Мелкие изображения < 50 КБ'
TYPE_ORDER = list(TYPES) + [T_SMALL, T_CACHE]

CACHE_RE = re.compile(r'cacheclip|proxymedia|proxy media|optimized media|render cache|'
                      r'lightroom.*previews|\.lrdata|gallery cache|\.dvcc', re.I)
# Технические подпапки внутри события: их не считаем отдельной папкой-событием.
TECH_DIR = re.compile(r'^(raw|jpe?g|jpg\+raw|raw\+jpe?g|cr2|cr3|nef|arw|dng|heic|video|videos|видео|'
                      r'фото|photo|photos|dcim|mov|mp4|avchd|bdmv|stream|private|clip|m4root|sub|'
                      r'camera|\d{3}[a-z_]{5}|\d{3}_?\d{4}|\d{3}gopro|\d{3}media)$', re.I)
PROJECT_RE = re.compile(r'сафари|safari|(?<![А-Яа-яЁёA-Za-z])АН(?![А-Яа-яЁёA-Za-z])')
PROJECT_EXCLUDE = re.compile(r'зоо ?парк|парк сафари', re.I)
YEAR_RE = re.compile(r'(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)')
SKIP_G = re.compile(r'^[A-Za-z]:\\(\$recycle\.bin|system volume information)\\', re.I)


def file_type(path, size):
    if CACHE_RE.search(path):
        return T_CACHE
    t = EXT_TYPE.get(os.path.splitext(path)[1].lower())
    if t and t != 'Видео' and size < 50_000:
        return T_SMALL
    return t


def event_of(path):
    parts = path.replace('/', SEP).split(SEP)[:-1]
    while parts and TECH_DIR.match(parts[-1].strip()):
        parts.pop()
    return SEP.join(parts) if parts else '(корень диска)'


def year_of(event, mtime_ns):
    found = YEAR_RE.findall(event)
    if found:
        return found[-1], 'из пути'
    try:
        return str(dt.datetime.fromtimestamp(int(mtime_ns) / 1e9).year), 'по дате файла'
    except (TypeError, ValueError, OSError):
        return '?', '—'


def norm_name(event):
    last = event.split(SEP)[-1].lower()
    return re.sub(r'[\W_]+', '', last)


def find_jobs():
    jobs = {}
    for root in SCAN_ROOTS:
        for result in glob.glob(str(root / '*' / '*' / 'result.json')):
            job = Path(result).parent
            if '_Архив' in str(job):
                continue
            try:
                info = json.loads(Path(result).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            disk = info.get('disk_id') or job.name.split('_')[0]
            mtime = os.path.getmtime(result)
            if disk not in jobs or mtime > jobs[disk]['mtime']:
                jobs[disk] = dict(dir=job, label=job.parent.name, status=info.get('status', '?'),
                                  mtime=mtime, bytes=(info.get('physical') or {}).get('bytes'))
    return dict(sorted(jobs.items()))


def ro(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def load_disk(disk, job):
    hashes = {}
    with ro(job['dir'] / 'hashes.sqlite') as c:
        for path, sha in c.execute("select path, sha256 from hashes where status='verified'"):
            hashes[path] = sha
    rows = []
    with ro(job['dir'] / 'inventory.sqlite') as c:
        q = "select path, size, mtime_ns from files where category in ('media_ge_1MiB','media_small')"
        for path, size, mtime in c.execute(q):
            size = size or 0
            t = file_type(path, size)
            if not t or size == 0:
                continue
            sha = hashes.get(path)
            name = path.replace('/', SEP).split(SEP)[-1].lower()
            key = ('h', sha) if sha else ('n', size, name)
            rows.append((disk, path, size, mtime, t, key, name))
    return rows


def load_g():
    files = []
    if not G_INDEX.exists():
        return files
    with open(G_INDEX, encoding='utf-8', errors='replace') as f:
        for line in f:
            size, _, path = line.rstrip('\n').partition('\t')
            if not path or SKIP_G.match(path):
                continue
            try:
                size = int(size)
            except ValueError:
                continue
            files.append((path[3:] if path[1:3] == ':\\' else path, size))
    return files


S_HAVE, S_PART, S_NONE = 'Есть на 18 ТБ', 'Частично: не хватает', 'На 18 ТБ нет'
S_PROJ, S_SMALL = 'Сафари / АН — позже', 'Только мелкие (< 1 МБ) — не сверить со старым индексом'
COMPARABLE = 1048576   # старый индекс G содержит только медиа от 1 МБ
YEAR_ONLY = re.compile(r'\s*(19|20)\d\d\s*(год|г\.?)?\s*', re.I)


def human(n):
    return f'{n / GIB:,.1f} ГБ' if n >= GIB else f'{n / 1024 ** 2:,.0f} МБ'


def is_project(path):
    return bool(PROJECT_RE.search(path)) and not PROJECT_EXCLUDE.search(path)


def status_rows(files, g_dirs):
    """Свёрнутые строки «папка → статус относительно G» для каждого носителя.

    Папка, у которой всё содержимое в одном статусе, — одна строка; смешанные
    папки разворачиваются до подпапок. Сверка с G — по имени и размеру.
    """
    out = []
    per_disk = collections.defaultdict(list)
    for f in files:
        if f[4] != T_CACHE:
            per_disk[f[0]].append(f)
    for disk, items in sorted(per_disk.items()):
        stats = collections.defaultdict(lambda: [0, 0, 0, 0, 0])   # bytes, onG, n, miss_n, small_n
        direct = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
        children = collections.defaultdict(set)
        for disk_, path, size, mtime, t, key, name in items:
            dirs = path.replace('/', SEP).split(SEP)[:-1]
            g = (size, name) in g_dirs
            for depth in range(len(dirs) + 1):
                folder = SEP.join(dirs[:depth])
                if depth:
                    children[SEP.join(dirs[:depth - 1])].add(folder)
                targets = [stats[folder]] + ([direct[folder]] if depth == len(dirs) else [])
                for s in targets:
                    if size < COMPARABLE:
                        s[4] += 1
                    else:
                        s[0] += size
                        s[2] += 1
                        if g:
                            s[1] += size
                        else:
                            s[3] += 1

        rows = []   # (folder, label, status, stats)

        def status_of(s):
            if not s[0]:
                return S_SMALL
            # Строго: «есть» — только если не хватает ни одного файла.
            return S_HAVE if not s[3] else S_NONE if not s[1] else S_PART

        def walk(folder):
            s = stats[folder]
            if folder and is_project(folder):
                rows.append((folder, folder, S_PROJ, s))
                return
            st = status_of(s)
            kids = sorted(children.get(folder, ()))
            last = folder.split(SEP)[-1] if folder else ''
            container = not folder or SEP not in folder or YEAR_ONLY.fullmatch(last)
            small_gap = (s[0] - s[1]) <= 0.02 * s[0] and s[3] <= 20
            if st != S_PART or not kids or (small_gap and not container):
                rows.append((folder, folder or '(весь носитель)', st, s))
                return
            for k in kids:
                walk(k)
            d = direct.get(folder)
            if d and (d[0] or d[4]):
                rows.append((folder, (folder + SEP if folder else '') + '(файлы в самой папке)', status_of(d), d))

        walk('')

        # Где эти файлы на G: путь G, обрезанный на папке с тем же названием, что и строка.
        row_keys = {r[0]: i for i, r in enumerate(rows)}
        where = collections.defaultdict(collections.Counter)
        missing = collections.defaultdict(collections.Counter)
        for disk_, path, size, mtime, t, key, name in items:
            if size < COMPARABLE:
                continue
            dirs = path.replace('/', SEP).split(SEP)[:-1]
            for depth in range(len(dirs), -1, -1):
                i = row_keys.get(SEP.join(dirs[:depth]))
                if i is not None:
                    break
            else:
                continue
            if (size, name) not in g_dirs:
                missing[i][SEP.join(dirs[depth:]) or '(в самой папке)'] += 1
                continue
            last = norm_name(rows[i][0]) if rows[i][0] else ''
            for gdir in list(g_dirs[(size, name)])[:3]:
                parts = gdir.split(SEP)
                cut = next((j for j in range(len(parts) - 1, -1, -1) if last and norm_name(parts[j]) == last), None)
                where[i][SEP.join(parts[:cut + 1]) if cut is not None else event_of(gdir + SEP + 'x')] += size

        for i, (folder, label, st, s) in enumerate(rows):
            top = where[i].most_common(3)
            g_name = ''
            if top and folder and st in (S_HAVE, S_PART) and not YEAR_ONLY.fullmatch(folder.split(SEP)[-1]):
                if not any(norm_name(p) == norm_name(folder.split(SEP)[-1]) for p in top[0][0].split(SEP)):
                    g_name = top[0][0].split(SEP)[-1]
            years = YEAR_RE.findall(folder)
            out.append((disk, label, years[-1] if years else '', st + (f' {s[3]} шт., {human(s[0] - s[1])}' if st == S_PART else ''),
                        s[0] / GIB, s[2], s[1] / GIB, (s[0] - s[1]) / GIB, s[3], s[4],
                        '; '.join(f'{p} ({b / GIB:,.1f} ГБ)' for p, b in top), g_name,
                        '; '.join(f'{p} ({n} шт.)' for p, n in missing[i].most_common(3)) if st.startswith(S_PART) else '',
                        ''))
    return out


def main():
    started = dt.datetime.now()
    jobs = find_jobs()
    files = []
    for disk, job in jobs.items():
        part = load_disk(disk, job)
        print(f'{disk}: {len(part)} медиафайлов ({job["status"]})', flush=True)
        files.extend(part)

    # --- содержимое и копии ---
    by_key = collections.defaultdict(list)
    for i, f in enumerate(files):
        by_key[f[5]].append(i)
    name_size_to_keys = collections.defaultdict(set)
    for f in files:
        name_size_to_keys[(f[2], f[6])].add(f[5])

    g_files = load_g()
    g_dirs = collections.defaultdict(set)
    for path, size in g_files:
        parts = path.split(SEP)
        g_dirs[(size, parts[-1].lower())].add(SEP.join(parts[:-1]))
    g_set = set(g_dirs)
    print(f'G (индекс): {len(g_files)} файлов', flush=True)
    decisions = status_rows(files, g_dirs)

    def on_g(f):
        return (f[2], f[6]) in g_set

    # --- события (папки) ---
    events = {}   # (disk, event) -> dict

    def ev(disk, event):
        k = (disk, event)
        if k not in events:
            events[k] = dict(types=collections.Counter(), tbytes=collections.Counter(), bytes=0, n=0,
                             only_here=0, on_g=0, years=collections.Counter(), ysrc='', exact=0)
        return events[k]

    for f in files:
        disk, path, size, mtime, t, key, name = f
        e = ev(disk, event_of(path))
        e['types'][t] += 1
        e['tbytes'][t] += size
        e['bytes'] += size
        e['n'] += 1
        y, src = year_of(event_of(path), mtime)
        e['years'][y] += size
        e['ysrc'] = src
        g = on_g(f)
        if g:
            e['on_g'] += size
        if len(by_key[key]) == 1 and not g:
            e['only_here'] += size

    # G как источник папок (приблизительно: имя + размер)
    g_event_bytes = collections.Counter()
    content_events = collections.defaultdict(set)
    for f in files:
        if f[5][0] == 'h':
            content_events[f[5]].add((f[0], event_of(f[1])))
    for path, size in g_files:
        name = path.split(SEP)[-1].lower()
        keys = name_size_to_keys.get((size, name))
        evn = event_of(path)
        g_event_bytes[evn] += size
        if keys and len(keys) == 1:
            k = next(iter(keys))
            if k[0] == 'h':
                content_events[k].add(('G≈', evn))
    content_size = {f[5]: f[2] for f in files}

    # --- пересечения папок ---
    pairs = collections.defaultdict(lambda: [0, 0])
    for k, evs in content_events.items():
        if 2 <= len(evs) <= 30:
            evs = sorted(evs)
            for a in range(len(evs)):
                for b in range(a + 1, len(evs)):
                    p = pairs[(evs[a], evs[b])]
                    p[0] += 1
                    p[1] += content_size[k]

    def ebytes(e):
        return g_event_bytes[e[1]] if e[0] == 'G≈' else events[e]['bytes']

    links = collections.defaultdict(list)
    pair_rows = []
    for (a, b), (n, shared) in pairs.items():
        ca, cb = shared / max(ebytes(a), 1), shared / max(ebytes(b), 1)
        same = norm_name(a[1]) == norm_name(b[1])
        if ca >= 0.98 and cb >= 0.98:
            kind = 'Полная копия, то же название' if same else 'Полная копия, ДРУГОЕ название — вручную'
        elif ca >= 0.98 or cb >= 0.98:
            kind = 'Одна папка входит в другую — вручную'
        else:
            kind = 'Частичное пересечение — вручную'
        pair_rows.append((a, b, n, shared, ca, cb, kind))
        links[a].append((shared, b, ca, kind))
        links[b].append((shared, a, cb, kind))
    pair_rows.sort(key=lambda r: -r[3])

    # --- сводки по типам ---
    uniq = {}   # key -> (type, size, year, project, on_g)
    for f in files:
        k = f[5]
        if k in uniq:
            if on_g(f) and not uniq[k][4]:
                uniq[k] = uniq[k][:4] + (True,)
            continue
        ev_name = event_of(f[1])
        y, _ = year_of(ev_name, f[3])
        proj = bool(PROJECT_RE.search(f[1])) and not PROJECT_EXCLUDE.search(f[1])
        uniq[k] = (f[4], f[2], y, proj, on_g(f))

    write_excel(jobs, files, by_key, uniq, events, links, pair_rows, g_files, on_g, started, decisions)


# ---------------- Excel ----------------
HEAD_FILL = PatternFill('solid', fgColor='DDE7F3')
NOTE_FONT = Font(italic=True, color='555555')


def sheet(wb, title, headers, rows, widths, notes=(), formats=None):
    ws = wb.create_sheet(title)
    r0 = 1
    for note in notes:
        ws.cell(row=r0, column=1, value=note).font = NOTE_FONT
        r0 += 1
    if notes:
        r0 += 1
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=r0, column=c, value=h)
        cell.font = Font(bold=True)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    for r, row in enumerate(rows, r0 + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if formats and formats.get(c):
                cell.number_format = formats[c]
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
    if rows:
        ws.auto_filter.ref = f'A{r0}:{get_column_letter(len(headers))}{r0 + len(rows)}'
    return ws


def write_excel(jobs, files, by_key, uniq, events, links, pair_rows, g_files, on_g, started, decisions):
    wb = Workbook()
    wb.remove(wb.active)
    detail = Workbook()
    detail.remove(detail.active)
    gb, tb, pct = '#,##0.0', '#,##0.00', '0%'
    common = ['Объёмы — в единицах Windows (ГБ = 1024³ байт), как в «Этом компьютере».',
              '«G≈» — старый индекс диска G (май 2026, медиа от 1 МБ, без хешей): совпадение по имени и размеру, приблизительно.',
              'Копии считаются по SHA-256; файлы без хеша (мелкие) — по имени и размеру.']

    # 0. Что требует решения — статус каждой папки относительно копилки G
    sheet(wb, 'Статус относительно 18 ТБ',
          ['Носитель', 'Папка', 'Год', 'Статус', 'Объём, ГБ', 'Файлов', 'Есть на 18 ТБ, ГБ', 'Не хватает, ГБ',
           'Не хватает, файлов', 'Мелких < 1 МБ (не сверены)', 'Где на 18 ТБ', 'Название на 18 ТБ (если другое — берём его)', 'Где не хватает (подпапки)',
           'Ваше решение'],
          decisions, [9, 70, 7, 30, 10, 9, 11, 11, 10, 11, 90, 30, 50, 20],
          notes=['Каждая папка сверена с диском G целиком. Если у всей папки один статус — она одна строка; '
                 'папки со смешанным статусом развёрнуты до подпапок.',
                 'Сверка по старому индексу G: имя + размер, только фото и видео от 1 МБ. Кэш и прокси монтажа не показаны.'],
          formats={5: gb, 7: gb, 8: gb})

    # 1. Итог по типам
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])
    for f in files:
        a = agg[f[4]]
        a[0] += 1
        a[1] += f[2]
    for k, (t, size, y, proj, g) in uniq.items():
        a = agg[t]
        a[2] += 1
        a[3] += size
        if len(by_key[k]) == 1:
            a[4] += size
        if g:
            a[5] += size
        if proj:
            a[6] += size
        if not g and not proj:
            a[7] += size
    rows = []
    for t in TYPE_ORDER:
        a = agg.get(t)
        if a:
            rows.append((t, a[0], a[1] / GIB, a[2], a[3] / GIB, a[4] / GIB, a[5] / GIB, a[6] / GIB, a[7] / GIB))
    tot = [sum(r[i] for r in rows) for i in range(1, 9)]
    rows.append(('ИТОГО', *tot))
    sheet(wb, 'Итог по типам',
          ['Тип', 'Файлов (все копии)', 'Объём всех копий, ГБ', 'Уникальных файлов', 'Уникальный объём, ГБ',
           'из него в одном экземпляре, ГБ', 'уже есть на G≈, ГБ', 'Сафари / АН, ГБ', 'Нет на G, не Сафари/АН — кандидат в копилку, ГБ'],
          rows, [30, 14, 14, 14, 14, 16, 14, 14, 22],
          notes=['Пробная таблица: учтены только уже отсканированные носители (список — на листе «Носители»).'] + common,
          formats={3: gb, 5: gb, 6: gb, 7: gb, 8: gb, 9: gb, 2: '#,##0', 4: '#,##0'})

    # 2. Типы по годам (уникальный объём, нет на G, без Сафари/АН)
    years = collections.defaultdict(collections.Counter)
    for k, (t, size, y, proj, g) in uniq.items():
        if not proj:
            years[y][t] += size
            years[y]['__notg_' + t] += 0 if g else size
    ordered = sorted(years, key=lambda y: (not y.isdigit(), y))
    main_types = [t for t in TYPE_ORDER if t != T_CACHE]
    rows = []
    for y in ordered:
        c = years[y]
        rows.append((y, *[c[t] / GIB for t in main_types], sum(c[t] for t in main_types) / GIB,
                     sum(c['__notg_' + t] for t in main_types) / GIB, c[T_CACHE] / GIB))
    sheet(wb, 'Типы по годам',
          ['Год', *[f'{t}, ГБ' for t in main_types], 'Всего, ГБ', 'из них нет на G≈, ГБ', 'Кэш монтажа, ГБ'],
          rows, [10] + [13] * (len(main_types) + 3),
          notes=['Уникальный объём (каждое содержимое один раз), без Сафари/АН.',
                 'Год — последний год в названии папки; если его нет — год изменения файла (ненадёжно, копирование его сбивает).'],
          formats={i: gb for i in range(2, len(main_types) + 5)})

    # 3. Носители
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0]))
    for f in files:
        p = per[f[0]][f[4]]
        p[0] += f[2]
        if len(by_key[f[5]]) == 1 and not on_g(f):
            p[1] += f[2]
        if on_g(f):
            p[2] += f[2]
    rows = []
    for disk, job in jobs.items():
        for t in TYPE_ORDER:
            if t in per[disk]:
                p = per[disk][t]
                rows.append((disk, job['label'], job['status'], t, p[0] / GIB, p[1] / GIB, p[2] / GIB,
                             p[1] / p[0] if p[0] else 0))
    sheet(detail, 'Носители',
          ['Носитель', 'Описание', 'Статус скана', 'Тип', 'Объём, ГБ', 'Только здесь (нет нигде больше и на G≈), ГБ',
           'Есть на G≈, ГБ', 'Доля «только здесь»'],
          rows, [10, 50, 26, 26, 12, 18, 14, 12], notes=common,
          formats={5: gb, 6: gb, 7: gb, 8: pct})

    # 4. Папки-события
    rows = []
    for (disk, evn), e in events.items():
        y = max(e['years'], key=e['years'].get)
        best = max(links.get((disk, evn), []), default=None, key=lambda x: x[0])
        proj = 'Сафари/АН?' if PROJECT_RE.search(evn) and not PROJECT_EXCLUDE.search(evn) else ''
        rows.append((disk, evn, y, e['ysrc'], proj,
                     e['types']['Фото JPEG'], e['tbytes']['Фото JPEG'] / GIB,
                     e['types']['Фото RAW'], e['tbytes']['Фото RAW'] / GIB,
                     e['types']['Видео'], e['tbytes']['Видео'] / GIB,
                     e['n'], e['bytes'] / GIB, e['only_here'] / GIB, e['on_g'] / max(e['bytes'], 1),
                     len(links.get((disk, evn), [])),
                     f'{best[1][0]}: {best[1][1]}' if best else '', best[2] if best else None,
                     best[3] if best else ''))
    rows.sort(key=lambda r: -r[12])
    sheet(detail, 'Папки-события',
          ['Носитель', 'Папка (событие)', 'Год', 'Откуда год', 'Проект', 'JPEG, шт', 'JPEG, ГБ', 'RAW, шт', 'RAW, ГБ',
           'Видео, шт', 'Видео, ГБ', 'Всего медиа, шт', 'Всего, ГБ', 'Только здесь, ГБ', 'Есть на G≈, доля',
           'Связанных папок', 'Самая похожая папка', 'Доля этой папки в ней', 'Вид связи'],
          rows, [9, 60, 7, 12, 11, 9, 9, 9, 9, 9, 9, 10, 10, 11, 10, 9, 60, 10, 36],
          notes=['Одна строка — папка с медиа на одном носителе. Технические подпапки (RAW, JPG, Видео, DCIM, 100CANON…) '
                 'слиты с родительской папкой-событием.',
                 '«Самая похожая папка» — где больше всего общих файлов (по SHA-256; с G — приблизительно).'],
          formats={7: gb, 9: gb, 11: gb, 13: gb, 14: gb, 15: pct, 18: pct})

    # 5. Пересечения папок
    rows = [(a[0], a[1], b[0], b[1], n, shared / GIB, ca, cb, kind)
            for a, b, n, shared, ca, cb, kind in pair_rows[:60000]]
    sheet(detail, 'Пересечения папок',
          ['Носитель A', 'Папка A', 'Носитель B', 'Папка B', 'Общих файлов', 'Общий объём, ГБ',
           'Доля A в B', 'Доля B в A', 'Вид'],
          rows, [9, 55, 9, 55, 10, 11, 9, 9, 38],
          notes=['Пары папок с одинаковыми файлами. «Вручную» — где нужно ваше решение: одинаковые снимки лежат '
                 'в папках с разными названиями или одна папка — часть другой.'],
          formats={6: gb, 7: pct, 8: pct})

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f'Сводка {started:%Y-%m-%d %H-%M}.xlsx'
    wb.save(out)
    detail.save(OUT_DIR / f'Подробности {started:%Y-%m-%d %H-%M}.xlsx')
    print(f'Готово: {out}  ({(dt.datetime.now() - started).seconds} с)')


if __name__ == '__main__':
    sys.exit(main())
