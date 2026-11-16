"""Логика v3, ядро разбора носителя: маршрут файлов, итог (части А и Б), задания по отметкам, «спорные» файлы.

Документ - «Проверка Архитектуры сортировки файлов\\Логика_v3_разбор_носителя.md» (разделы 1.2-1.6 и «Ядро: устройство»).
Ничего не пишет: итог и план заданий - данные; записывает их service.py (единый путь записи), печатает команда.

Как считается быстро (секунды на носителе с 4 млн файлов):
- маршрут - по ПАПКАМ таблицы folders (у самого большого носителя 16 тыс. папок), а не по файлам;
- файлы без хеша по одному не читаются: «прямо в папке» = суммы folders папки минус суммы её детей по 5 типам, минус
  файлы, прочитанные поштучно. Поштучно читаются: все файлы с хешем (нужен SHA-256 для «уже есть»), файлы с
  собственной отметкой, файлы с длинным путём назначения, файлы, чей путь назначения на диске D уже занят;
- «уже есть на 45/77» - по готовой таблице presence; на других дисках - множество SHA-256 диска (один запрос).
Сверки (спор с GPT, п. 20): сумма части А = строке корня folders = независимому счёту по files (число и байты);
отрицательный остаток в папке - ошибка. Ошибка сверки - итог «НЕВЕРЕН», задания не создаются.
"""
import collections
import time
from collections import namedtuple
import build_pilot as bp
from hb_core.consts import (C_DOC, C_JUNK, CAT_DOC, CAT_OF_TYPE, EV_COPY, EV_SCAN, EXT_CLASS, F_ARCH, F_JUNK, F_MUSIC,
                            F_NEVER, F_OTHER, F_PHOTO, F_PROJ, F_TEXT, F_VIDEO, JUNK_NAMES, MAIN, N_TYPES,
                            NEVER_COPY_EXT, SEP)
from hb_core.derived import sub_of_other
from hb_core.consts import COPIED_PREFIX
from hb_core.util import is_moved_dir, parent_of, prefix_cond
from hb_core.directions import R_DIR, R_NONE, R_SKIP, R_UNSET
from hb_core.query import _keys

MAX_PATH = 259                         # политика совместимости с Проводником (как в mvlist)
COPY_ROOT = 'ПЕРЕНОС с других дисков'  # куда шаблон копирования кладёт файлы на диске назначения
ROOT_GROUP = None                      # папка группы «(файлы в корне)» - отдельный идентификатор, не путь
ROOT_TITLE = '(файлы в корне)'

Route = namedtuple('Route', 'state num mark moved')
NONE_ROUTE = Route(R_NONE, None, None, False)

# исходы части А (каждый файл - ровно в одном)
O_COPY, O_HAVE, O_TYPE, O_NODISK = 'копировать', 'уже есть', 'не подходит по типу', 'диск не назначен'
O_SKIP, O_UNSET, O_NONE, O_MOVED, O_JUNK = 'не копировать', 'не задано', 'не отмечено', 'перенесено', 'мусор'
B_LONG, B_CONFLICT, B_CHECK = 'длинный путь', 'конфликт', 'нужна проверка'
G_COPY, G_HAVE, G_TYPE, G_NODISK, G_BLOCKED = ('есть что копировать', 'все подходящие уже есть на всех дисках',
                                               'нет подходящих файлов', 'у направления нет диска',
                                               'есть заблокированные')


def inside_cond(col, folder):
    """SQL «всё внутри папки» одним диапазоном по первичному ключу (disk, path). Условие prefix_cond с OR («сам путь
    или внутри») SQLite здесь выполнял полным проходом по носителю: 1,2 с на каждую папку у HDD09."""
    f = (folder or '').strip(SEP)
    if not f:
        return '1=1', []
    return f'({col} >= ? and {col} < ?)', [f + SEP, f + ']']


def fast_folder_type(fine=False):
    """То же, что derived.folder_type (тип файла для таблицы folders; fine=True - derived.copy_kind, 9 типов с
    подмножествами «прочих»), но регулярное выражение кэша монтажа
    проверяется по ПАПКЕ один раз, а у файла - только по имени. Совпадение, которое переходит границу папка/имя,
    возможно только у «lightroom.*previews»: в папках со словом lightroom путь проверяется целиком. Тест сверяет с
    folder_type. -> функция (путь, name_lc, размер) -> тип."""
    cache = {}
    cre = bp.CACHE_RE

    def ft(path, nm, size):
        nm = nm or ''
        if not size:
            if fine:
                j = nm.rfind('.')
                if j > 0 and nm[:j].strip('.') and nm[j:] in NEVER_COPY_EXT:
                    return F_NEVER
            return F_OTHER
        i = path.rfind(SEP)
        folder = path[:i] if i >= 0 else ''
        fc = cache.get(folder)
        if fc is None:
            fl = folder.lower()
            fc = cache[folder] = 2 if cre.search(fl) else (1 if 'lightroom' in fl else 0)
        if fc == 2 or nm in JUNK_NAMES or nm.startswith('~$'):
            return F_JUNK
        if (cre.search(path.lower()) if fc == 1 else cre.search(nm)):
            return F_JUNK
        j = nm.rfind('.')
        ext = nm[j:] if j > 0 and nm[:j].strip('.') else ''
        cls = EXT_CLASS.get(ext)
        if cls == C_JUNK:
            return F_JUNK
        t = bp.EXT_TYPE.get(ext)
        if t:
            return F_VIDEO if t == 'Видео' else F_PHOTO
        if cls == C_DOC:
            return F_TEXT
        return sub_of_other(ext) if fine else F_OTHER
    return ft


def _mark_route(m, dirs, moved=False):
    if m.kind == R_DIR and m.num not in dirs:
        return Route(R_UNSET, None, m, moved)
    return Route(m.kind, m.num, m, moved)


def moved_roots(c, disk):
    """Служебные папки верхнего уровня: старые «ПЕРЕНЕСЕНО → …»/«МУСОР» по имени, «Скопировано на …» - только из
    журнала перемещения (таблица moved_roots, BUILD_VERSION 8)."""
    roots = {f for (f,) in c.execute("select folder from folders where disk=? and depth=1", (disk,)) if is_moved_dir(f)}
    try:
        roots |= {f for (f,) in c.execute('select folder from moved_roots where disk=?', (disk,))}
    except Exception:                    # база старой версии (до 8) - таблицы ещё нет
        pass
    return roots


def original_of(path, roots):
    """Исходный путь (без служебной первой папки) и признак «внутри служебной папки»."""
    head, _, tail = path.partition(SEP)
    if head in roots:
        return tail, True
    return path, False


def copied_roots(roots):
    """Служебные папки логики v3 («Скопировано на …» из журнала перемещения) - в отличие от старых «ПЕРЕНЕСЕНО → …»."""
    return {r for r in roots if r.startswith(COPIED_PREFIX)}


def mark_path(path, roots):
    """Путь, по которому хранится отметка папки (этап 13): внутри «Скопировано на …» (и сама эта папка) - НЫНЕШНИЙ путь,
    отметка действует только там; внутри старой «ПЕРЕНЕСЕНО → …» - исходный путь (как раньше; сама папка - '')."""
    head = (path or '').split(SEP, 1)[0]
    if head in roots and head.startswith(COPIED_PREFIX):
        return path
    return original_of(path, roots)[0] if path else ''


def is_second(r, roots):
    """Маршрут от отметки, поставленной внутри «Скопировано на …» (второй проход, этап 13): такая папка ведёт себя
    как обычная (копировать / уже есть / не подходит), а не как «уже перенесено»."""
    m = r.mark
    return bool(r.moved and m is not None and m.path and m.path.split(SEP, 1)[0] in roots
                and m.path.startswith(COPIED_PREFIX))


def folder_routes(order, marks, dirs, roots):
    """Действующая отметка каждой папки (order - папки от корня вглубь). Одна функция для расчёта (planner) и окна:
    - корень - отметка всего носителя;
    - старая «ПЕРЕНЕСЕНО → …»: сама - «уже перенесено» (отметка носителя туда не наследуется), внутри - только явные
      отметки ИСХОДНОГО пути;
    - «Скопировано на …» (этап 13): действуют только отметки, поставленные внутри неё (по нынешнему пути, самая
      глубокая решает; саму папку тоже можно отметить); исходные отметки и отметка носителя внутрь не проникают -
      без своей отметки там «уже перенесено»;
    - остальные - своя отметка или маршрут родителя."""
    route = {}
    for f in order:
        if not f:
            m = marks.get('')
            route[f] = _mark_route(m, dirs) if m else NONE_ROUTE
            continue
        top = f.split(SEP, 1)[0]
        if top in roots:
            if top.startswith(COPIED_PREFIX):
                m = marks.get(f)
                if m:
                    route[f] = _mark_route(m, dirs, True)
                elif f == top:
                    route[f] = Route(R_NONE, None, None, True)
                else:
                    route[f] = route.get(parent_of(f), Route(R_NONE, None, None, True))
                continue
            if f == top:
                route[f] = Route(R_NONE, None, None, True)       # отметка всего носителя сюда не наследуется
                continue
            m = marks.get(f[len(top) + 1:])
            route[f] = _mark_route(m, dirs, True) if m else route.get(parent_of(f), Route(R_NONE, None, None, True))
            continue
        m = marks.get(f)
        route[f] = _mark_route(m, dirs) if m else route.get(parent_of(f), NONE_ROUTE)
    return route


def _group(route, physical_folder, roots):
    """Ключ задания: (номер строки решающей отметки, папка группы). Отметка всего носителя делится по папкам верхнего
    уровня; файлы прямо в корне - ROOT_GROUP."""
    m = route.mark
    if m.path:
        return (m.row, m.path)
    top = physical_folder.split(SEP, 1)[0] if physical_folder else ROOT_GROUP
    return (m.row, top)


class Plan:
    """Результат planner(): части А и Б, группы заданий, пометки, сверки. Поля - простые словари и списки."""

    def __init__(self, disk, dirs, marks):
        self.disk, self.dirs, self.marks = disk, dirs, marks
        self.part_a = collections.defaultdict(lambda: [0, 0])        # (исход, номер направления|None) -> [файлов, байт]
        self.moved_copy = [0, 0]                                     # из «копировать» - лежат в служебных папках
        self.part_b = collections.defaultdict(lambda: [0, 0])        # диск -> [файлов, байт] исполнимых строк
        self.groups = {}                                             # ключ группы -> dict
        self.blocked = []                                            # (путь, диск, причина, размер)
        self.blocked_agg = collections.Counter()                     # (диск, причина) -> файлов без пути (по папкам)
        self.move_long = [0, 0]                                      # путь на носителе после переноса > 259
        self.docs_near = []                                          # (папка, документов, байт, основание)
        self.unhashed_copy = collections.defaultdict(lambda: [0, 0]) # диск -> файлов без хеша к копированию
        self.namesakes = collections.Counter()                       # диск -> тёзки без хеша (только с detail)
        self.dest_exists = {}                                        # диск -> папок назначения уже есть
        self.errors, self.notes = [], []
        self.rows = collections.defaultdict(list)                    # (группа, диск) -> строки задания (detail)
        self.deps = collections.defaultdict(list)                    # (группа, диск) -> (путь, sha, путь представителя)
        self.total = [0, 0]
        self.info = {}

    def group(self, g, route):
        if g not in self.groups:
            d = self.dirs.get(route.num)
            self.groups[g] = dict(key=g, row=g[0], folder=g[1], num=route.num, direction=d.name if d else '',
                                  disks=tuple(d.disks) if d else (), kind=d.kind if d else '', mark=route.mark.verdict,
                                  mark_path=route.mark.path, eligible=[0, 0], copy=[0, 0], have=[0, 0], type=[0, 0],
                                  blocked=0, per_disk=collections.defaultdict(lambda: [0, 0]), moved=0)
        return self.groups[g]

    def group_state(self, g):
        x = self.groups[g]
        if not x['disks']:
            return G_NODISK
        if x['blocked']:
            return G_BLOCKED
        if x['copy'][0]:
            return G_COPY
        if x['eligible'][0]:
            return G_HAVE
        return G_TYPE


def planner(c, disk, dirs, marks, detail=False):
    """Расчёт разбора носителя disk по направлениям dirs и отметкам marks (MarkSet, может включать черновик).
    detail=True - ещё и строки заданий поштучно (подготовка заданий) и тёзки без хеша на дисках направлений."""
    P = Plan(disk, dirs, marks)
    roots = moved_roots(c, disk)
    cols = 'folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(N_TYPES))
    own = {}
    for r in c.execute(f'select {cols} from folders where disk=?', (disk,)):
        n_ = [r[3 + 2 * i] or 0 for i in range(N_TYPES)]
        b_ = [r[4 + 2 * i] or 0 for i in range(N_TYPES)]
        n_[F_OTHER] -= sum(n_[F_ARCH:])                          # «прочие» в folders - все прочие; здесь - только «другие»
        b_[F_OTHER] -= sum(b_[F_ARCH:])
        own[r[0]] = (r[1], r[2], n_, b_)
    if not own:
        P.errors.append(f'в базе нет файлов носителя {disk}')
        return P
    folders = sorted(own, key=lambda f: (f.count(SEP) + 1 if f else 0, f))
    children = collections.defaultdict(list)
    for f in folders:
        if f:
            children[parent_of(f)].append(f)
    # «прямо в папке» = своя сумма минус суммы детей
    dn = {f: list(own[f][2]) for f in folders}
    db = {f: list(own[f][3]) for f in folders}
    for f in folders:
        if f:
            p = parent_of(f)
            if p in dn:
                for i in range(N_TYPES):
                    dn[p][i] -= own[f][2][i]
                    db[p][i] -= own[f][3][i]

    # ---------- маршрут по папкам ----------
    route = folder_routes(folders, marks, dirs, roots)
    copied = copied_roots(roots)

    # ---------- файлы с собственной отметкой ----------
    folder_lc = {f.lower() for f in folders}
    file_marks = {}                                              # физический путь -> Route
    cand = []
    for m in marks.by_key.values():
        if m.path and m.path.lower() not in folder_lc:
            cand.append((m.path, m, m.path.split(SEP, 1)[0] in copied))
            cand += [(r + SEP + m.path, m, True) for r in roots if r not in copied]   # исходный путь - только в старых
    if cand:
        got = _probe_all(c, disk, [p for p, _, _ in cand])
        for p, m, moved in cand:
            if p in got:
                file_marks[p] = _mark_route(m, dirs, moved)

    # ---------- какие диски направлений участвуют ----------
    nums = {r.num for r in route.values() if r.state == R_DIR} | {r.num for r in file_marks.values() if r.state == R_DIR}
    used = sorted({d for n in nums for d in dirs[n].disks})
    bit = {d: 1 << i for i, d in enumerate(used)}
    src_bit = bit.get(disk, 0)
    sets = {}
    for d in used:
        if d != disk:                                            # сам носитель - бит src_bit
            sets[d] = {s for (s,) in c.execute('select sha from files where disk=? and sha is not null', (d,))}
    ftype = fast_folder_type(fine=True)

    # ---------- поштучные файлы без хеша: длинный путь назначения и занятый путь назначения ----------
    copy_prefix_len = len(f'X:{SEP}{COPY_ROOT}{SEP}{disk}{SEP}')
    special = set(file_marks)
    copy_thr = MAX_PATH - copy_prefix_len
    move_names = [dirs[n].folder() for n in nums if dirs[n].disks]
    move_thr = None
    if move_names and not any(disk in dirs[n].disks for n in dirs):
        move_thr = MAX_PATH - len(f'X:{SEP}') - max(len(x) for x in move_names) - 1
    # ОДИН проход по носителю: независимый счёт числа и байтов (сверка) и длинные пути (порог - меньший из двух)
    thr = min(copy_thr, move_thr) if move_thr is not None else copy_thr
    real_n, real_b, longs = c.execute("select count(*), coalesce(sum(size), 0), group_concat(case when length(path) > ? "
                                      "then path end, char(1)) from files where disk=?", (thr, disk)).fetchone()
    longs = longs.split('\x01') if longs else []
    long_copy = {p for p in longs if len(p) > copy_thr}
    long_move = {p for p in longs if move_thr is not None and len(p) > move_thr}
    special |= long_copy | long_move
    occ = collections.defaultdict(dict)                          # путь носителя -> {диск D: (sha, ev) на D}
    blocked_pref = collections.defaultdict(list)                 # диск D -> папки носителя, где на D файл вместо папки
    for d in used:
        if d == disk:
            continue
        base = f'{COPY_ROOT}{SEP}{disk}'
        cond, args = inside_cond('path', base)
        on_d = {}
        for p, sha, ev in c.execute(f'select path, sha, ev from files where disk=? and {cond}', [d] + args):
            if p != base:
                on_d[p[len(base) + 1:]] = (sha, ev)
        P.dest_exists[d] = len(on_d)
        if not on_d:
            continue
        hit = _probe_all(c, disk, list(on_d))
        for rel, v in on_d.items():
            if rel in hit:
                occ[rel][d] = v
                special.add(rel)
            elif rel.lower() in folder_lc:
                blocked_pref[d].append(rel.lower())

    # ---------- файлы с хешем (поштучно) ----------
    hashed = []                                                  # (путь, размер, sha, тип, маска)
    # «есть S/C с тем же SHA-256 на D» - по множествам хешей дисков (sha заполнен только у S и C): это быстрее, чем
    # поиск в presence по каждой строке (570 тыс. случайных поисков у HDD45 - 5 с против 0,8 с)
    others = [(bit[d], s) for d, s in sets.items()]
    for path, size, sha, nm in c.execute('select path, size, sha, name_lc from files where disk=? and sha is not null',
                                         (disk,)):
        k = ftype(path, nm, size)
        mask = src_bit
        for b_, s in others:
            if sha in s:
                mask |= b_
        hashed.append((path, size or 0, sha, k, mask))
    hashed_paths = {h[0] for h in hashed}
    unh_special = {}
    rest = [p for p in special if p not in hashed_paths]
    if rest:
        for p, (nm, size, mt, sha) in _probe_all(c, disk, rest).items():
            unh_special[p] = (size or 0, ftype(p, nm, size or 0), nm)
    # вычитание поштучных из сумм папок; сначала файлы с собственной отметкой (они не основание «документов рядом»)
    fm_hashed = {h[0]: h for h in hashed if h[0] in file_marks}

    def sub(path, size, k):
        f = parent_of(path)
        dn[f][k] -= 1
        db[f][k] -= size

    for p in file_marks:
        if p in fm_hashed:
            h = fm_hashed[p]
            sub(p, h[1], h[3])
        elif p in unh_special:
            sub(p, unh_special[p][0], unh_special[p][1])
    media_direct = {f: dn[f][F_PHOTO] + dn[f][F_VIDEO] for f in folders}
    docs_direct = {f: (dn[f][F_TEXT], db[f][F_TEXT]) for f in folders}
    for h in hashed:
        if h[0] not in file_marks:
            sub(h[0], h[1], h[3])
    for p, (size, k, _nm) in unh_special.items():
        if p not in file_marks:
            sub(p, size, k)
    for f in folders:
        if any(x < 0 for x in dn[f]) or any(x < 0 for x in db[f]):
            P.errors.append(f'отрицательный остаток в папке «{f or "корень"}» (таблица folders не сходится с files)')
            break

    # ---------- «документы рядом»: снизу вверх по детям с той же решающей отметкой ----------
    ident = lambda r: (r.mark.row if r.mark else None, r.moved, r.state, r.num)
    ms, basis = {}, {}
    for f in reversed(folders):
        n = media_direct[f]
        bs = f if n > 0 else None
        for ch in children.get(f, ()):
            if ident(route[ch]) == ident(route[f]) and ms[ch] > 0:
                n += ms[ch]
                bs = bs or basis[ch]
        ms[f], basis[f] = n, bs
    docs_ok = {}
    for f in folders:
        top = f.split(SEP, 1)[0] if f else ''
        docs_ok[f] = bool(f) and not (top in roots and f == top) and ms[f] > 0
        r = route[f]
        if (docs_ok[f] and r.state == R_DIR and dirs[r.num].docs_near and docs_direct[f][0] > 0
                and not (r.moved and not dirs[r.num].disks)):
            P.docs_near.append((f, docs_direct[f][0], docs_direct[f][1], basis[f]))

    # ---------- исход файла ----------
    def eligible(d, k, dok):
        """Подходит ли тип направлению: набор категорий «что копировать»; программы и мусор - никогда."""
        cat = CAT_OF_TYPE.get(k)
        if cat is None or cat not in d.cats:
            return False
        return not (cat == CAT_DOC and d.docs_near) or dok

    def outcome(r, k, mask, dok):
        """-> (исход, номер, недостающие диски)."""
        if r.state == R_DIR:
            d = dirs[r.num]
            if r.moved and not is_second(r, copied):
                if d.disks and eligible(d, k, dok):
                    miss = [x for x in d.disks if not mask & bit[x]]
                    if miss:
                        return O_COPY, r.num, miss
                return O_MOVED, None, ()
            if not d.disks:
                return O_NODISK, r.num, ()
            if k == F_JUNK:
                return O_JUNK, None, ()
            if not eligible(d, k, dok):
                return O_TYPE, r.num, ()
            miss = [x for x in d.disks if not mask & bit[x]]
            return (O_COPY, r.num, miss) if miss else (O_HAVE, r.num, ())
        if r.moved:
            return O_MOVED, None, ()
        return {R_SKIP: O_SKIP, R_UNSET: O_UNSET}.get(r.state, O_NONE), None, ()

    reps = collections.defaultdict(dict)                         # (группа, диск) -> {sha: (путь, размер)}
    dep_cand = collections.defaultdict(list)                     # (группа, диск, sha) -> [пути]
    blocked_sha = collections.defaultdict(list)                  # (группа, диск, sha) -> [(путь, причина, размер)]

    def block_reason(path, d, sha):
        if path in long_copy:
            return B_LONG
        o = occ.get(path, {}).get(d)
        if o:
            dsha, dev = o
            return B_CONFLICT if (dsha and sha and dev in (EV_SCAN, EV_COPY) and dsha != sha) else B_CHECK
        pl = path.lower()
        for bp_ in blocked_pref.get(d, ()):
            if pl.startswith(bp_ + SEP):
                return B_CONFLICT
        return None

    def account(path, size, sha, k, mask, r, folder, dok, nm=None):
        o, num, miss = outcome(r, k, mask, dok)
        P.part_a[(o, num)][0] += 1
        P.part_a[(o, num)][1] += size
        if r.state != R_DIR or r.mark is None:
            return
        g = P.group(_group(r, folder if not r.moved else original_of(folder, roots)[0], roots), r)
        if o in (O_COPY, O_HAVE):
            g['eligible'][0] += 1; g['eligible'][1] += size
        if o == O_HAVE:
            g['have'][0] += 1; g['have'][1] += size
        elif o == O_TYPE:
            g['type'][0] += 1; g['type'][1] += size
        if o != O_COPY:
            return
        g['copy'][0] += 1; g['copy'][1] += size
        if r.moved and not is_second(r, copied):
            P.moved_copy[0] += 1; P.moved_copy[1] += size
            g['moved'] += 1
        for d in miss:
            if d == disk:
                continue
            why = block_reason(path, d, sha)
            if sha:
                if why:
                    blocked_sha[(g['key'], d, sha)].append((path, why, size))
                else:
                    cur = reps[(g['key'], d)].get(sha)
                    if cur is None or path < cur[0]:
                        if cur:
                            dep_cand[(g['key'], d, sha)].append(cur[0])
                        reps[(g['key'], d)][sha] = (path, size)
                    else:
                        dep_cand[(g['key'], d, sha)].append(path)
            elif why:
                P.blocked.append((path, d, why, size))
                g['blocked'] += 1
            else:
                P.part_b[d][0] += 1; P.part_b[d][1] += size
                g['per_disk'][d][0] += 1; g['per_disk'][d][1] += size
                P.unhashed_copy[d][0] += 1; P.unhashed_copy[d][1] += size
                if detail:
                    P.rows[(g['key'], d)].append((d, path, size, 'без хеша', ''))
                    if nm is not None:
                        P.info.setdefault('nh_keys', collections.defaultdict(set))[d].add((nm, size))
        if path in long_move and not r.moved:
            dd = dirs[r.num]
            orig = path
            if len(f'X:{SEP}{dd.folder()}{SEP}{orig}') > MAX_PATH:
                P.move_long[0] += 1; P.move_long[1] += size

    for path, size, sha, k, mask in hashed:
        f = parent_of(path)
        if path in file_marks:
            r = file_marks[path]
            pr = route[f]
            dok = pr.state == R_DIR and pr.num == r.num and docs_ok[f]
        else:
            r, dok = route[f], docs_ok[f]
        account(path, size, sha, k, mask, r, f, dok)
    for path, (size, k, nm) in unh_special.items():
        f = parent_of(path)
        if path in file_marks:
            r = file_marks[path]
            pr = route[f]
            dok = pr.state == R_DIR and pr.num == r.num and docs_ok[f]
        else:
            r, dok = route[f], docs_ok[f]
        account(path, size, None, k, src_bit, r, f, dok, nm)

    # остаток папок (файлы без хеша, не поштучные)
    need_files = []                                              # папки, где файлы без хеша пойдут в задания
    for f in folders:
        r = route[f]
        for k in range(N_TYPES):
            n, b = dn[f][k], db[f][k]
            if not n:
                continue
            o, num, miss = outcome(r, k, src_bit, docs_ok[f])
            P.part_a[(o, num)][0] += n
            P.part_a[(o, num)][1] += b
            if r.state != R_DIR or r.mark is None:
                continue
            g = P.group(_group(r, original_of(f, roots)[0] if r.moved else f, roots), r)
            if o in (O_COPY, O_HAVE):
                g['eligible'][0] += n; g['eligible'][1] += b
            if o == O_HAVE:
                g['have'][0] += n; g['have'][1] += b
            elif o == O_TYPE:
                g['type'][0] += n; g['type'][1] += b
            if o != O_COPY:
                continue
            g['copy'][0] += n; g['copy'][1] += b
            if r.moved and not is_second(r, copied):
                P.moved_copy[0] += n; P.moved_copy[1] += b
                g['moved'] += n
            if detail:
                need_files.append(f)
            for d in miss:
                if d == disk:
                    continue
                fl = f.lower()
                if any(fl == x or fl.startswith(x + SEP) for x in blocked_pref.get(d, ())):
                    P.blocked_agg[(d, B_CONFLICT)] += n
                    g['blocked'] += n
                    continue
                P.part_b[d][0] += n; P.part_b[d][1] += b
                g['per_disk'][d][0] += n; g['per_disk'][d][1] += b
                P.unhashed_copy[d][0] += n; P.unhashed_copy[d][1] += b

    # представители одинакового содержимого внутри задания; заблокированные - только если исполнимого экземпляра нет
    for (gk, d), by_sha in reps.items():
        g = P.groups[gk]
        for sha, (path, size) in by_sha.items():
            P.part_b[d][0] += 1; P.part_b[d][1] += size
            g['per_disk'][d][0] += 1; g['per_disk'][d][1] += size
            if detail:
                P.rows[(gk, d)].append((d, path, size, 'с хешем', sha.upper()))
                for dep in dep_cand.get((gk, d, sha), ()):
                    P.deps[(gk, d)].append((dep, sha.upper(), path))
                for bp_, _why, _s in blocked_sha.get((gk, d, sha), ()):
                    P.deps[(gk, d)].append((bp_, sha.upper(), path))
    for (gk, d, sha), lst in blocked_sha.items():
        if sha in reps.get((gk, d), {}):
            continue
        for path, why, size in sorted(lst):
            P.blocked.append((path, d, why, size))
            P.groups[gk]['blocked'] += 1

    # ---------- detail: файлы без хеша поштучно (строки заданий) и тёзки ----------
    if detail and need_files:
        need = set(need_files)
        tops = set()                                             # самые верхние папки (предок уже взят - не надо)
        for f in sorted(need, key=lambda x: (x.count(SEP), x)):
            if '' in tops:
                break
            p, inside = f, False
            while p:
                if p in tops:
                    inside = True
                    break
                p = parent_of(p)
            if not inside:
                tops.add(f)
        seen_rows = 0
        for t in tops:
            cond, args = inside_cond('path', t)
            for path, size, nm in c.execute(f'select path, size, name_lc from files where disk=? and {cond} and sha is null',
                                            [disk] + args):
                f = parent_of(path)
                if f not in need or path in special:
                    continue
                k = ftype(path, nm, size or 0)
                r = route[f]
                o, num, miss = outcome(r, k, src_bit, docs_ok[f])
                if o != O_COPY:
                    continue
                seen_rows += 1
                g = P.groups[_group(r, original_of(f, roots)[0] if r.moved else f, roots)]
                for d in miss:
                    if d == disk:
                        continue
                    fl = f.lower()
                    if any(fl == x or fl.startswith(x + SEP) for x in blocked_pref.get(d, ())):
                        P.blocked.append((path, d, B_CONFLICT, size or 0))
                        continue
                    P.rows[(g['key'], d)].append((d, path, size or 0, 'без хеша', ''))
                    P.info.setdefault('nh_keys', collections.defaultdict(set))[d].add((nm, size or 0))
        expected = sum(dn[f][k] for f in need for k in range(N_TYPES)
                       if outcome(route[f], k, src_bit, docs_ok[f])[0] == O_COPY)
        if seen_rows != expected:
            P.errors.append(f'файлов без хеша к копированию прочитано {seen_rows}, по суммам папок {expected}')
    if detail and P.info.get('nh_keys'):
        # все ключи (имя, размер) - одной временной таблицей без индекса (она - внешний цикл), один проход по files_name
        per = P.info.pop('nh_keys')
        allk = set().union(*per.values())
        c.execute('create temp table if not exists rz_nh(name_lc text, size integer)')
        c.execute('delete from rz_nh')
        c.executemany('insert into rz_nh values (?, ?)', allk)
        ds = sorted(per)
        hit = collections.defaultdict(set)
        for nm, s, gd in c.execute(f"""select k.name_lc, k.size, g.disk from rz_nh k cross join files g indexed by files_name
                                       on g.name_lc=k.name_lc and g.size=k.size and g.disk in ({",".join("?" * len(ds))})
                                       group by 1, 2, 3""", ds):
            hit[gd].add((nm, s))
        for d in ds:
            P.namesakes[d] = len(hit[d] & per[d])

    # ---------- сверки ----------
    tot = own.get('', (0, 0))
    P.total = [tot[0], tot[1]]
    a_n, a_b = sum(v[0] for v in P.part_a.values()), sum(v[1] for v in P.part_a.values())
    real = (real_n, real_b)                                      # независимый счёт по files (тот же проход, что пути)
    if (a_n, a_b) != (tot[0], tot[1]) or tuple(real) != (tot[0], tot[1]):
        P.errors.append(f'сумма итога ({a_n} файлов, {a_b} байт) / folders ({tot[0]}, {tot[1]}) / files '
                        f'({real[0]}, {real[1]}) не сходятся')
    st = c.execute('select status, scanned, label from disks where disk=?', (disk,)).fetchone() or ('?', None, '')
    P.info.update(status=st[0], scanned=st[1], label=st[2], roots=sorted(roots),
                  issues=c.execute('select count(*) from issues where disk=?', (disk,)).fetchone()[0],
                  is_target=[n for n, d in dirs.items() if disk in d.disks])
    return P


def _probe_all(c, disk, paths_):
    """Файлы носителя по точным путям, без условия size>0: {путь: (name_lc, size, mtime, sha)}."""
    c.execute('create temp table if not exists rz_p(path text primary key)')
    c.execute('delete from rz_p')
    c.executemany('insert or ignore into rz_p values (?)', ((x,) for x in paths_))
    return {r[0]: r[1:] for r in c.execute('select f.path, f.name_lc, f.size, f.mtime, f.sha from rz_p q '
                                           'cross join files f on f.disk=? and f.path=q.path', (disk,))}


# ---------- текст итога ----------

def _n(x):
    return f'{x:,}'.replace(',', ' ')


def _gb(b):
    return f'{(b or 0) / 1024 ** 3:.2f}'.replace('.', ',')


def part_a_rows(P):
    """Строки части А в порядке показа: (подпись, файлов, байт)."""
    rows = []
    for num, d in P.dirs.items():
        for o, text in ((O_COPY, 'будет скопирован хотя бы на один его диск'), (O_HAVE, 'уже есть на всех его дисках'),
                        (O_TYPE, 'не подходит по типу, останется на месте'), (O_NODISK, 'диск не назначен, ждёт')):
            v = P.part_a.get((o, num))
            if v and v[0]:
                rows.append((f'{d.name}: {text}', v[0], v[1]))
    for o, text in ((O_SKIP, 'Не копировать'), (O_UNSET, 'Направление не задано (старый «раздел: …» без направления)'),
                    (O_NONE, 'Не отмечено (режим разбора не выбран)'),
                    (O_MOVED, 'Уже перенесено раньше («ПЕРЕНЕСЕНО → …», «Скопировано на …»)'),
                    (O_JUNK, 'Мусор (не копируется, едет вместе с папкой)')):
        v = P.part_a.get((o, None))
        if v and v[0]:
            rows.append((text, v[0], v[1]))
    return rows


def group_title(g):
    return ROOT_TITLE if g['folder'] is ROOT_GROUP else g['folder'].rsplit(SEP, 1)[-1]


WIN_BAD = set('\\/:*?"<>|') | {chr(i) for i in range(32)}


def safe_name(text):
    """Имя папки задания для Windows: запрещённые знаки -> «_», без точек и пробелов в конце (имя папки носителя
    могло прийти с другой файловой системы)."""
    t = ''.join('_' if ch in WIN_BAD else ch for ch in text).rstrip(' .')
    return t or '_'


def summary_lines(P):
    """Короткий итог для экрана (≤ 20 строк) и полный - для файла."""
    L = []
    lab = (P.info.get('label') or '').split(' - ', 1)[-1]
    L.append(f'Разбор {P.disk} {lab}: {_n(P.total[0])} файлов, {_gb(P.total[1])} ГБ; отметок {len(P.marks)}.')
    if P.errors:
        L.append('ИТОГ НЕВЕРЕН: ' + '; '.join(P.errors) + '. Задания не создаются.')
    L.append('А. Что будет с каждым файлом (файлов · ГБ):')
    for text, n, b in part_a_rows(P):
        L.append(f'  {text}: {_n(n)} · {_gb(b)}')
    if P.moved_copy[0]:
        L.append(f'  (из «будет скопирован» {_n(P.moved_copy[0])} лежат в уже перенесённых папках - копируются '
                 'дополнительно, второй раз не перемещаются)')
    L.append(f'  Итого = опись носителя: {_n(P.total[0])} · {_gb(P.total[1])}')
    if P.part_b:
        L.append('Б. Сколько писать: ' + '; '.join(f'на {d[3:] if d.startswith("HDD") else d}: {_n(v[0])} файлов, '
                                                  f'{_gb(v[1])} ГБ' for d, v in sorted(P.part_b.items())))
    else:
        L.append('Б. Писать на диски нечего.')
    return L


def attention_lines(P):
    L = []
    if P.info.get('is_target'):
        L.append(f'{P.disk} - диск направления «' + ', '.join(P.dirs[n].name for n in P.info['is_target']) +
                 '»: копировать с него можно, перемещать на нём ничего нельзя.')
    for d, (n, b) in sorted(P.unhashed_copy.items()):
        if n:
            extra = f'; на {d} есть тёзки (то же имя и размер) у {_n(P.namesakes[d])}' if d in P.namesakes else ''
            L.append(f'Без хеша к копированию на {d}: {_n(n)} файлов (сравнение только по имени и размеру{extra}).')
    why = collections.Counter((d, w) for _p, d, w, _s in P.blocked) + P.blocked_agg
    for (d, w), n in sorted(why.items()):
        hint = {B_LONG: f'путь назначения длиннее {MAX_PATH} символов - не копируются',
                B_CONFLICT: 'на месте назначения другое подтверждённое содержимое (или файл вместо папки) - не '
                            'копируются; решите вручную на диске',
                B_CHECK: 'путь назначения занят неподтверждённой записью - пересканируйте эту папку на диске'}[w]
        L.append(f'{d}: {_n(n)} файлов - {hint}.')
    if P.move_long[0]:
        L.append(f'После переноса на носителе путь станет длиннее {MAX_PATH} у {_n(P.move_long[0])} файлов: '
                 'скопировать можно, переносить их не будут.')
    st = P.info.get('status') or '?'
    if st != 'complete' or P.info.get('issues'):
        L.append(f'Опись: состояние «{st}», непрочитанных мест {_n(P.info.get("issues", 0))} - итог по тому, что описано.')
    sc = P.info.get('scanned')
    if sc:
        L.append('Дата описи: ' + time.strftime('%d.%m.%Y', time.localtime(sc)) + '.')
    return L


def group_rows(P):
    """Группы заданий для показа: (направление, папка, состояние, копировать файлов, ГБ, по дискам)."""
    res = []
    for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder']))):
        per = ', '.join(f'{d}: {_n(v[0])}' for d, v in sorted(g['per_disk'].items()))
        res.append((g['direction'], group_title(g) if g['folder'] is ROOT_GROUP else g['folder'], P.group_state(gk),
                    g['copy'][0], _gb(g['copy'][1]), per))
    return res


# ---------- задания (план без записи; записывает service.publish_tasks) ----------

def disk_word(d):
    return d[3:] if d.startswith('HDD') and d[3:].isdigit() else d


def task_specs(P, serials):
    """Задания по группам: одна группа (решающая отметка + папка) и её направление, и ОДИН диск назначения (этап 5:
    у «Семейного архива» - отдельное задание на 45 и на 77; что недостающее - своё для каждого диска). Имя у
    направления с несколькими дисками - «… — на 45». Обязательные диски задания - все диски направления (перемещение
    требует копий на всех). -> [dict], по группе, затем по диску."""
    specs, used = [], set()
    for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder']))):
        targets = [d for d in g['disks'] if d != P.disk and P.rows.get((gk, d))]
        if not targets:
            continue
        group = safe_name(f'{P.disk} — {group_title(g)[:60]} — {g["direction"]}')
        for d in targets:
            base = group + (f' — на {disk_word(d)}' if len(g['disks']) > 1 else '')
            name, i = base, 2
            while name.lower() in used:
                name, i = f'{base} ({i})', i + 1
            used.add(name.lower())
            rows = sorted(set(P.rows[(gk, d)]), key=lambda r: (r[0], r[1]))
            specs.append(dict(name=name, group=group, key=[g['row'], g['folder']], folder=g['folder'], num=g['num'],
                              direction=g['direction'], disks=list(g['disks']), targets=[d], kind=g['kind'],
                              mark=g['mark'], mark_row=g['row'], rows=rows, deps={d: P.deps.get((gk, d), [])},
                              files=len(rows), bytes=sum(r[2] for r in rows),
                              serials={x: serials.get(x, 'НЕТ_СЕРИЙНОГО_НОМЕРА') for x in (P.disk, d)}))
    return specs


def group_states(P):
    """Группы для манифеста: состояние каждой (в том числе «копировать нечего» - но это НЕ разрешение перемещать)."""
    return [dict(folder=g['folder'], title=group_title(g), num=g['num'], direction=g['direction'], disks=list(g['disks']),
                 kind=g['kind'], mark=g['mark'], mark_row=g['row'], state=P.group_state(gk), files_copy=g['copy'][0],
                 files_have=g['have'][0], files_type=g['type'][0], blocked=g['blocked'])
            for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder'])))]


# ---------- «Пересчитать хеши спорных файлов» (после ответа «НЕТ»/«НЕДОСТАТОЧНО» в candel) ----------

def contested(c, disk, folder, main=MAIN):
    """Папки, где пересканирование с хешем всех файлов может снять сомнение: на проверяемом носителе - файлы без хеша
    (кроме пустых; корень - тоже папка ''); на дисках-копиях (45, 77) - тёзки без хеша (имя и размер) файлов
    проверяемой папки и неподтверждённые записи Z/U/X с ожидаемым хешем. Ничего не сканирует.
    -> {диск: [(папка, файлов)]}; вложенные папки, чей предок уже в списке, свёрнуты в предка."""
    folder = (folder or '').strip(SEP)
    cond, args = prefix_cond('path', folder)
    res = collections.defaultdict(collections.Counter)
    keys, shas = set(), set()
    for p, s, nm, sha in c.execute(f'select path, size, name_lc, sha from files where disk=? and {cond}', [disk] + args):
        if sha:
            shas.add(sha)
            keys.add((nm, s))
        elif s:
            res[disk][parent_of(p)] += 1
            keys.add((nm, s))
    if keys:
        _keys(c, 'ct_k', ('name_lc', 'size'), keys)
        for d in main:
            excl, eargs = '', []
            if d == disk:
                ec, eargs = prefix_cond('g.path', folder)
                excl = f' and not ({ec})'
            q = f"""select g.path from ct_k k cross join files g indexed by files_name
                    on g.name_lc=k.name_lc and g.size=k.size and g.disk=? where g.sha is null and g.size>0{excl}"""
            for (p,) in c.execute(q, [d] + eargs):
                res[d][parent_of(p)] += 1
    if shas:
        c.execute('create temp table if not exists ct_s(sha text primary key)')
        c.execute('delete from ct_s')
        c.executemany('insert or ignore into ct_s values (?)', ((x,) for x in shas))
        for d in main:
            for (p,) in c.execute('select g.path from ct_s s cross join files g on g.sha_exp=s.sha and g.disk=?', (d,)):
                res[d][parent_of(p)] += 1
    out = {}
    for d, cnt in res.items():
        tops = []
        for f in sorted(cnt, key=lambda x: (x.count(SEP) + 1 if x else 0, x)):
            t = next((t for t in tops if t == '' or f == t or f.startswith(t + SEP)), None)
            if t is None:
                tops.append(f)
        agg = collections.Counter()
        for f, n in cnt.items():
            t = next(t for t in tops if t == '' or f == t or f.startswith(t + SEP))
            agg[t] += n
        out[d] = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
    return out
