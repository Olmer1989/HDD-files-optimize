"""Логика v3, ядро разбора носителя: основа - исходы, маршрут папок (Route, folder_routes), Plan; поштучные выборки
для planner (_collect_rest, _twins, _probe_all). Часть бывшего hb_core/razbor.py (разбит 17.11.2026, код дословно)."""
import collections
from collections import namedtuple
import build_pilot as bp
from hb_core.consts import (C_DOC, C_JUNK, COPIED_PREFIX, EXT_CLASS, F_JUNK, F_NEVER, F_OTHER, F_PHOTO, F_TEXT, F_VIDEO,
                            JUNK_NAMES, N_TYPES, NEVER_COPY_EXT, SEP)
from hb_core.derived import sub_of_other
from hb_core.util import is_moved_dir, parent_of
from hb_core.directions import R_DIR, R_NONE, R_UNSET
from hb_core.razbor_scope import top_folders

COPY_ROOT = 'ПЕРЕНОС с других дисков'  # куда шаблон копирования кладёт файлы на диске назначения
ROOT_GROUP = None                      # папка группы «(файлы в корне)» - отдельный идентификатор, не путь
ROOT_TITLE = '(файлы в корне)'

Route = namedtuple('Route', 'state num mark moved')
NONE_ROUTE = Route(R_NONE, None, None, False)

# исходы части А (каждый файл - ровно в одном)
O_COPY, O_HAVE, O_TYPE, O_NODISK = 'копировать', 'уже есть', 'не подходит по типу', 'диск не назначен'
O_SKIP, O_UNSET, O_NONE, O_MOVED, O_JUNK = 'не копировать', 'не задано', 'не отмечено', 'перенесено', 'мусор'
B_CONFLICT, B_CHECK = 'конфликт', 'нужна проверка'     # «длинный путь» снят 17.11.2026
B_TWIN = 'двойник пути'                # этап 14: у двух файлов носителя один путь назначения
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


def dest_rel(path, copied):
    """Путь файла (папки) в месте назначения копирования, от «ПЕРЕНОС с других дисков\\<носитель>» (этап 14): внутри
    служебной «Скопировано на …» ЭТОГО носителя (copied - только из журнала перемещения, moved_roots) - без неё, как
    до переноса (раскладка на втором диске та же, что на первом); иначе - сам путь. Сама служебная папка -> ''.
    «ПЕРЕНЕСЕНО → …» и папка владельца с таким же именем не очищаются."""
    head, _, tail = (path or '').partition(SEP)
    return tail if head in copied else path


def copied_sub(folder, copied):
    """Служебная «Скопировано на …», в которой лежит папка группы (подпапка источника задания), или ''."""
    head = (folder or '').split(SEP, 1)[0]
    return head if head in copied else ''


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
        self.docs_near = []                                          # (папка, документов, байт, основание)
        self.unhashed_copy = collections.defaultdict(lambda: [0, 0]) # диск -> файлов без хеша к копированию
        self.namesakes = collections.Counter()                       # диск -> тёзки без хеша (только с detail)
        self.dest_exists = {}                                        # диск -> папок назначения уже есть
        self.errors, self.notes = [], []
        self.rows = collections.defaultdict(list)                    # (группа, диск) -> строки задания (detail)
        self.deps = collections.defaultdict(list)                    # (группа, диск) -> (путь, sha, путь представителя)
        self.total = [0, 0]
        self.info = {}
        self.items = []                                              # collect: пофайловый список (окно, этап 16)
        self.junk_dir = collections.defaultdict(lambda: [0, 0])      # этап 18: мусор в папках направления -> [файлов, байт]

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


def wanted_item(want, o, num, r):
    """collect: подходит ли файл с исходом o (номер num) и маршрутом r. Этап 18: мусор (исход без направления) в папке,
    идущей в направление, входит в список «не подходит по типу» этого направления."""
    if num == want[0] and o in want[1]:
        return True
    return o == O_JUNK and O_TYPE in want[1] and r is not None and r.state == R_DIR and r.num == want[0]


def _collect_rest(c, P, disk, want, folders, dn, route, docs_ok, outcome, src_bit, special, blocked_pref, ftype):
    """collect (этап 16): файлы без хеша, которые planner считает суммами папок, - поштучно, только в папках, где по
    суммам есть нужный исход; тот же outcome. Число собранных = сумме по папкам, иначе - ошибка итога."""
    def wanted(f, k):
        o, num, _m = outcome(route[f], k, src_bit, docs_ok[f])
        return wanted_item(want, o, num, route[f])
    need = {f for f in folders if any(dn[f][k] and wanted(f, k) for k in range(N_TYPES))}
    if not need:
        return
    expected = sum(dn[f][k] for f in need for k in range(N_TYPES) if dn[f][k] and wanted(f, k))
    seen = 0
    for t in top_folders(need):
        cond, args = inside_cond('path', t)
        for path, size, nm in c.execute(f'select path, size, name_lc from files where disk=? and {cond} and sha is null',
                                        [disk] + args):
            f = parent_of(path)
            if f not in need or path in special:
                continue
            size = size or 0
            k = ftype(path, nm, size)
            o, num, miss = outcome(route[f], k, src_bit, docs_ok[f])
            if not wanted_item(want, o, num, route[f]):
                continue
            seen += 1
            st = {}
            for d in miss:
                if d == disk:
                    continue
                fl = f.lower()
                st[d] = (('blocked', B_CONFLICT, '') if any(fl == x or fl.startswith(x + SEP) for x in blocked_pref.get(d, ()))
                         else ('nohash', ''))
            P.items.append([path, size, None, k, o, tuple(miss), st])
    if seen != expected:
        P.errors.append(f'список файлов: без хеша прочитано {seen}, по суммам папок {expected}')


def _twins(c, disk, folders, children, copied):
    """Двойники пути (этап 14): файлы носителя, у которых путь назначения (dest_rel) совпадает с путём назначения
    другого файла или папки носителя: «Поход 2010\\x» и «Скопировано на A\\Поход 2010\\x», один остаток в двух служебных
    папках, файл против папки. Ищутся только среди прямых детей папок с одинаковым путём назначения (корень носителя
    и сами служебные папки - одна такая группа). Два файла с одним известным SHA-256 - не двойники (на цели будет «уже
    есть»); иначе - оба (файл против папки - файл) не копируются. -> {путь файла}."""
    by_dest = collections.defaultdict(list)
    for f in folders:
        by_dest[dest_rel(f, copied).lower()].append(f)
    res = set()
    for group in by_dest.values():
        if len(group) < 2:
            continue
        names = collections.defaultdict(list)                    # имя -> [(путь, sha, папка?)]
        for f in group:
            for ch in children.get(f, ()):
                if ch not in copied:
                    names[ch.rsplit(SEP, 1)[-1].lower()].append((ch, None, True))
            if f:
                cond, args = inside_cond('path', f)
                q, cut = f'select path, sha from files where disk=? and {cond} and instr(substr(path, ?), ?) = 0', len(f) + 2
                rows = c.execute(q, [disk] + args + [cut, SEP])
            else:
                rows = c.execute('select path, sha from files where disk=? and instr(path, ?) = 0', (disk, SEP))
            for p, sha in rows:
                names[p.rsplit(SEP, 1)[-1].lower()].append((p, sha, False))
        for lst in names.values():
            files_ = [x for x in lst if not x[2]]
            if len(lst) < 2 or not files_:
                continue
            shas = {x[1] for x in files_}
            if len(files_) == len(lst) and len(shas) == 1 and None not in shas:
                continue
            res |= {x[0] for x in files_}
    return res


def _probe_all(c, disk, paths_):
    """Файлы носителя по точным путям, без условия size>0: {путь: (name_lc, size, mtime, sha)}."""
    c.execute('create temp table if not exists rz_p(path text primary key)')
    c.execute('delete from rz_p')
    c.executemany('insert or ignore into rz_p values (?)', ((x,) for x in paths_))
    return {r[0]: r[1:] for r in c.execute('select f.path, f.name_lc, f.size, f.mtime, f.sha from rz_p q '
                                           'cross join files f on f.disk=? and f.path=q.path', (disk,))}
