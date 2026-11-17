"""Экран «Разбор носителя» (этапы 2 и 6): дерево, «Уже есть», место на дисках, сверка описи (toc).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections
import os
import shutil
import stat as stat_mod
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import check_disk, Refused, ro, SEP
from .directions_v3 import snapshot
from .read_disks import volumes
from .rescan_run import _scanner, disk_letter


# ---------- экран «Разбор носителя» (логика v3, этап 2, 15.11.2026; razbor_page.py) ----------

def razbor_tree(disk):
    """Всё для дерева экрана «Разбор носителя» одним вызовом, ничего не пишет: папки носителя из таблицы folders
    (суммы по поддереву: файлов, байт, число и байты по 5 типам; extra - n5..n8 / b5..b8), служебные папки переноса, направления и сохранённые
    отметки (снимок таблиц под замком - тот же, по которому считает итог), сведения об описи, поколение базы. -> dict."""
    snap = snapshot()
    c = ro()
    try:
        check_disk(c, disk)
        cols = 'folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(hb.N_TYPES))
        folders, extra = {}, {}
        for r in c.execute(f'select {cols} from folders where disk=?', (disk,)):
            folders[r[0]] = (r[1] or 0, r[2] or 0, tuple(r[3 + 2 * i] or 0 for i in range(5)),
                             tuple(r[4 + 2 * i] or 0 for i in range(5)))
            ex = (tuple(r[3 + 2 * i] or 0 for i in range(5, hb.N_TYPES)),
                  tuple(r[4 + 2 * i] or 0 for i in range(5, hb.N_TYPES)))
            if any(ex[0]):
                extra[r[0]] = ex                   # 18.11.2026: архивы, проекты, музыка, программы (n5..n8) - «нет на H:»
        roots = hb.moved_roots(c, disk)
        st = c.execute('select status, scanned, label from disks where disk=?', (disk,)).fetchone() or ('', None, '')
        issues = c.execute('select count(*) from issues where disk=?', (disk,)).fetchone()[0]
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.close()
    return dict(disk=disk, folders=folders, extra=extra, roots=roots, dirs=hb.parse_directions(snap['directions']),
                rows=hb.mark_rows(disk, snap['decisions']), sig=snap['sig'], built=gen, status=st[0] or '',
                scanned=st[1], label=st[2] or '', issues=issues)


def razbor_have(disk, disks_):
    """Колонка «Уже есть» экрана разбора: файлы носителя С ХЕШЕМ по папкам (непосредственно в папке, без подпапок), по
    типам и по тому, на каких из дисков disks_ уже есть подтверждённая запись (S/C) с тем же SHA-256: 45 и 77 - по
    таблице presence, у других дисков - множество их SHA-256 (как в итоге разбора; поиск по индексу на каждый файл был
    в 4 раза медленнее). Сам носитель среди disks_ считается имеющим файл (как в итоге разбора). Один проход по файлам
    с хешем носителя; ничего не пишет. Замер на настоящей базе: HDD45 (567 тыс. файлов с хешем) - около 5 с.
    -> {папка: {маска: [n0..n8, b0..b8]}} (9 типов derived.copy_kind), бит i маски - диск disks_[i]."""
    disks_ = list(disks_)
    main = [(i, d) for i, d in enumerate(disks_) if d in hb.MAIN and d != disk]
    base = sum(1 << i for i, d in enumerate(disks_) if d == disk)
    sel = ''.join(f", coalesce(p.e{d[3:]} in ('S','C'), 0)" for _, d in main)
    q = (f'select f.path, f.size, f.name_lc, f.sha{sel} from files f ' +
         ('left join presence p on p.sha=f.sha ' if main else '') + 'where f.disk=? and f.sha is not null')
    ft = hb.fast_folder_type(fine=True)
    res = collections.defaultdict(dict)
    c = ro()
    try:
        sets = [(1 << i, {x for (x,) in c.execute('select sha from files where disk=? and sha is not null', (d,))})
                for i, d in enumerate(disks_) if d not in hb.MAIN and d != disk]
        bits = [1 << i for i, _ in main]
        for r in c.execute(q, (disk,)):
            path, size, sha = r[0], r[1] or 0, r[3]
            mask = base
            for b, x in zip(bits, r[4:]):
                if x:
                    mask |= b
            for b, s_ in sets:
                if sha in s_:
                    mask |= b
            k = ft(path, r[2], size)
            cell = res[hb.parent_of(path)].get(mask)
            if cell is None:
                cell = res[hb.parent_of(path)][mask] = [0] * (2 * hb.N_TYPES)
            cell[k] += 1
            cell[hb.N_TYPES + k] += size
    finally:
        c.close()
    return dict(res)


# ---------- экран «Разбор носителя» по замечаниям владельца (логика v3, этап 6, 15.11.2026) ----------
# Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 6». Вместимость по каждому диску направления и быстрая
# сверка оглавления подключённого носителя с описью перед созданием заданий. Ничего не пишет.

CLUSTER = 4096                       # кластер, если узнать настоящий у тома не удалось
RESERVE_MIN = 2 * 1024 ** 3          # запас на диске: не меньше 2 ГиБ ...
RESERVE_PART = 0.01                  # ... и не меньше 1 % объёма диска
MTIME_SLACK = 0                      # даты в описи - целые секунды (floor); сверка точная (критик GPT, п. 6)


def disk_space(disks_):
    """Свободное место, объём и кластер подключённых дисков: {диск: (буква, свободно байт, объём байт, кластер байт)}.
    Диски не читаются (только сведения о томе, как free_space). Неподключённого диска в ответе нет: место неизвестно."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    res = {}
    for d in disks_:
        letter = vols.get(serial_of.get(d, '?'))
        if letter:
            try:
                u = shutil.disk_usage(letter + '\\')
                res[d] = (letter, u.free, u.total, cluster_of(letter))
            except OSError:
                pass
    return res


def cluster_of(letter):
    """Размер кластера тома (байт): GetDiskFreeSpaceW; не удалось - 4 КиБ."""
    try:
        import ctypes
        spc, bps, a, b = (ctypes.c_ulong() for _ in range(4))
        if ctypes.windll.kernel32.GetDiskFreeSpaceW(letter.rstrip('\\') + '\\', ctypes.byref(spc), ctypes.byref(bps),
                                                     ctypes.byref(a), ctypes.byref(b)):
            return spc.value * bps.value or CLUSTER
    except (OSError, AttributeError):
        pass
    return CLUSTER


def reserve_of(total):
    return max(RESERVE_MIN, int((total or 0) * RESERVE_PART))


def queued_copy(exclude_disk=None, root=None):
    """Незапущенные задания копирования ДРУГИХ носителей (журналов ещё нет): {диск назначения: [заданий, байт]}.
    Их файлы ещё не на диске, а место займут. Задания этого носителя не считаются: их недостающее уже в части Б
    (носитель задания - первая строка его тома.tsv). -> {диск: [заданий, байт, файлов]}."""
    root = Path(root or hb.TASKS)
    res = collections.defaultdict(lambda: [0, 0, 0])
    if not root.exists():
        return {}
    for t in root.iterdir():
        lst = t / 'список.tsv'
        if not t.is_dir() or not lst.exists() or list(t.glob('Журнал копирования *.tsv')):
            continue
        src = ''
        try:
            vol = hb.read_tsv(t / 'тома.tsv')
            src = vol[0][0] if vol and vol[0] else ''
        except OSError:
            pass
        if exclude_disk and src == exclude_disk:
            continue
        per, cnt = collections.Counter(), collections.Counter()
        for r in hb.read_tsv(lst):
            if len(r) >= 3:
                try:
                    per[r[0]] += int(r[2])
                    cnt[r[0]] += 1
                except ValueError:
                    pass
        for d, b in per.items():
            res[d][0] += 1
            res[d][1] += b
            res[d][2] += cnt[d]
    return dict(res)


def capacity(part_b, space, queued=None, disks=()):
    """Поместится ли на каждый диск части Б то, чего на нём ещё нет (часть Б: по SHA-256; файлы без хеша - всегда).
    нужно = байты + файлов × кластер тома (каждый файл теряет меньше кластера - верхняя граница) + незапущенные
    задания других носителей на этот диск; запас =
    max(2 ГиБ, 1 % объёма). -> {диск: dict(files, bytes, need, reserve, queued, free, total, letter,
    state 'ok' | 'short' | 'unknown' (не подключён) | 'none' (писать нечего))}. disks - ещё диски (диски направлений), на
    которые копировать нечего: у них запись 'none' (и место, если подключён)."""
    res = {}
    queued = queued or {}
    rows = dict(part_b)
    for d in disks:
        rows.setdefault(d, (0, 0))
    for d, (n, b) in rows.items():
        q = (list(queued.get(d, ())) + [0, 0, 0])[:3]
        cl = space[d][3] if d in space and len(space[d]) > 3 else CLUSTER
        need = b + n * cl + q[1] + q[2] * cl
        x = dict(files=n, bytes=b, need=need, queued=q, reserve=None, free=None, total=None, letter='', cluster=cl)
        if d in space:
            letter, free, total = space[d][:3]
            x.update(letter=letter, free=free, total=total, reserve=reserve_of(total))
        if not n:
            x['state'] = 'none'
        elif d in space:
            x['state'] = 'ok' if need + x['reserve'] <= free else 'short'
        else:
            x['state'] = 'unknown'
        res[d] = x
    return res


def short_directions(dirs, cap):
    """Направления, которым не хватает места хотя бы на одном их диске (тогда задания не создаются ни на один)."""
    return sorted(n for n, d in dirs.items() if any(cap.get(x, {}).get('state') == 'short' for x in d.disks))


def toc_targets(P, specs):
    """Что сверять перед созданием заданий specs: физические папки их групп (исходный путь и его копия внутри
    служебной папки переноса - те, что есть в описи), вложенные свёрнуты в верхние; файлы прямо в корне - флаг;
    зоны - отметки внутри сверяемых папок: (физический путь, сверять ли). Файл сверяется по САМОЙ ГЛУБОКОЙ зоне над
    ним: отметка другого направления или «не копировать» - не сверяется (его файлы в эти задания не входят), отметка
    направления сверяемых заданий или папка их группы глубже - снова сверяется (критик GPT, п. 7: переопределения на
    нескольких уровнях). -> (папки, корень, зоны)."""
    c = ro()
    try:
        have = {f.lower(): f for (f,) in c.execute('select folder from folders where disk=?', (P.disk,))}
    finally:
        c.close()
    roots = P.info.get('roots') or []
    want, root_files = set(), False
    nums = {s['num'] for s in specs}
    groups = {s['folder'].lower() for s in specs if s['folder'] is not None}

    def phys(f):
        return [have[x.lower()] for x in [f] + [r + SEP + f for r in roots] if x.lower() in have]
    for s in specs:
        f = s['folder']
        if f is None:                                   # группа «(файлы в корне)»
            root_files = True
            continue
        want.update(phys(f))
    zones = {}
    for m in P.marks.by_key.values():
        if m.path and any(m.path.lower().startswith(g + SEP) for g in groups):
            keep = m.path.lower() in groups or (m.kind == hb.R_DIR and m.num in nums)
            for x in phys(m.path):
                zones[x] = keep
    tops = []
    for f in sorted(want, key=lambda x: (x.count(SEP), x.lower())):
        if not any(f.lower() == t.lower() or f.lower().startswith(t.lower() + SEP) for t in tops):
            tops.append(f)
    return tops, root_files, sorted(zones.items())


def toc_check(disk, folders, root_files=False, zones=(), limit=3):
    """Быстрая сверка оглавления подключённого носителя с описью: пути, размеры, даты (os.scandir/stat - содержимое
    файлов не читается, хешей нет), по тем же правилам пропуска служебных папок и файлов, что опись сканера.
    -> dict(connected, reason, letter, checked, problems=[dict(folder, gone, new, size, date, unread, examples)]).
    Носитель не подключён -> connected=False и причина (сверка невозможна - задания не создаются)."""
    try:
        letter = disk_letter(disk)
    except Refused as e:
        return dict(connected=False, reason=str(e), letter='', checked=0, problems=[])
    rescan, inventory = _scanner()
    root = letter.rstrip('\\') + '\\'
    c = ro()
    try:
        excl = {p.lower() for (p,) in c.execute('select path from excluded where disk=?', (disk,))}
        excl_dirs = [f.lower() + SEP for f in hb.read_exclusions().get(disk, ())]

        def skipped(rel):
            """Одно правило для описи и оглавления: исключённое владельцем (таблица excluded и папки исключений),
            файлы и папки, которые опись сканера не описывает (inventory.excluded_file, EXCLUDED_DIRS)."""
            k = rel.lower()
            if k in excl or any(k.startswith(x) for x in excl_dirs):
                return True
            parts = k.split(SEP)
            return inventory.excluded_file(parts[-1]) or any(x in inventory.EXCLUDED_DIRS for x in parts[:-1])

        def base_rows(folder):
            if folder is None:
                return c.execute('select path, size, mtime from files where disk=? and instr(path, ?) = 0', (disk, SEP))
            cond, args = hb.inside_cond('path', folder)
            return c.execute(f'select path, size, mtime from files where disk=? and {cond}', [disk] + args)
        zl = sorted(((z.lower() + SEP, keep) for z, keep in zones), key=lambda x: -len(x[0]))

        def wanted(k):
            """Самая глубокая зона над файлом решает, сверять ли его; вне зон - сверять."""
            return next((keep for z, keep in zl if k.startswith(z)), True)
        problems, checked = [], 0
        for folder in ([None] if root_files else []) + list(folders):
            exp = {}
            for p, s, mt in base_rows(folder):
                if not skipped(p):
                    exp.setdefault(p.lower(), []).append((p, s or 0, mt))
            unread = []
            if folder is None:
                cur = {}
                try:
                    with os.scandir(root) as it:
                        for e in it:
                            if inventory.excluded_file(e.name):
                                continue
                            try:
                                st = e.stat(follow_symlinks=False)
                                if (stat_mod.S_ISREG(st.st_mode)
                                        and not getattr(st, 'st_file_attributes', 0) & 0x400):
                                    cur[e.name] = dict(size=st.st_size, mtime_ns=st.st_mtime_ns)
                            except OSError as exc:
                                unread.append(f'{e.name}: {exc}')
                except OSError as exc:
                    unread.append(f'корень: {exc}')
            elif not os.path.isdir(os.path.join(root, folder)):
                cur = {}
                unread.append('папки нет на носителе')
            else:
                cur, errors, _rep = rescan.walk(root, [folder], info=False)
                unread += [f'{os.path.relpath(p, root)}: {msg}' for p, _op, msg in errors]
            if zl:
                cur = {r: v for r, v in cur.items() if wanted(r.lower())}
                exp = {k: v for k, v in exp.items() if wanted(k)}
            new, size, date, seen = [], [], [], set()
            for rel, v in cur.items():
                k = rel.lower()
                if skipped(rel):
                    continue
                checked += 1
                cand = exp.get(k)
                if not cand:
                    new.append(rel)
                    continue
                seen.add(k)
                e = next((x for x in cand if x[0] == rel), cand[0])      # точное написание - первым
                if v['size'] != e[1]:
                    size.append(rel)
                elif e[2] is not None and abs(v['mtime_ns'] // 1_000_000_000 - e[2]) > MTIME_SLACK:
                    date.append(rel)
            gone = [x[0] for k, v in exp.items() if k not in seen for x in v]
            if gone or new or size or date or unread:
                problems.append(dict(folder=folder, gone=len(gone), new=len(new), size=len(size), date=len(date),
                                     unread=len(unread),
                                     examples=dict(gone=sorted(gone)[:limit], new=sorted(new)[:limit],
                                                   size=sorted(size)[:limit], date=sorted(date)[:limit],
                                                   unread=unread[:limit])))
    finally:
        c.close()
    return dict(connected=True, reason='', letter=letter, checked=checked, problems=problems)


def toc_lines(toc):
    """Текст сверки для окна: «папка — что не так»."""
    if not toc['connected']:
        return ['Носитель не подключён — сверка оглавления с описью невозможна, поэтому задания не создаются. '
                'Подключите носитель и нажмите ещё раз. (' + toc['reason'] + ')']
    L = []
    for p in toc['problems']:
        where = '(файлы прямо в корне носителя)' if p['folder'] is None else p['folder']
        bits = [f'{w} {p[k]}' for k, w in (('gone', 'исчезли'), ('new', 'новые'), ('size', 'другой размер'),
                                           ('date', 'другая дата'), ('unread', 'не прочитано')) if p[k]]
        ex = '; '.join(x for k in ('gone', 'new', 'size', 'date', 'unread') for x in p['examples'][k][:2])
        L.append(f'{where} — ' + ', '.join(bits) + (f' (например: {ex})' if ex else ''))
    return L
