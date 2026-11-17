"""Логика v3, ядро разбора носителя: planner - расчёт разбора (итог, части А и Б, задания).
Часть бывшего hb_core/razbor.py (разбит 17.11.2026, код дословно)."""
import collections
from hb_core.consts import (CAT_DOC, CAT_OF_TYPE, EV_COPY, EV_SCAN, F_ARCH, F_JUNK, F_OTHER, F_PHOTO, F_TEXT, F_VIDEO,
                            N_TYPES, SEP)
from hb_core.util import parent_of
from hb_core.directions import R_DIR, R_SKIP, R_UNSET
from hb_core.razbor_scope import B_UNREAD, top_folders, unread_files
from hb_core.razbor_base import (B_CHECK, B_CONFLICT, B_TWIN, COPY_ROOT, NONE_ROUTE, O_COPY, O_HAVE, O_JUNK, O_MOVED,
                                 O_NODISK, O_NONE, O_SKIP, O_TYPE, O_UNSET, Plan, _collect_rest, _group, _mark_route,
                                 _probe_all, _twins, copied_roots, fast_folder_type, folder_routes, inside_cond,
                                 is_second, moved_roots, original_of, wanted_item)

def planner(c, disk, dirs, marks, detail=False, collect=None):
    """Расчёт разбора носителя disk по направлениям dirs и отметкам marks (MarkSet, может включать черновик).
    detail=True - ещё и строки заданий поштучно (подготовка заданий) и тёзки без хеша на дисках направлений.
    collect=(номер направления, {исходы}) - окно «Список файлов» (этап 16): каждый файл с таким исходом этого
    направления - в P.items поштучно, тем же расчётом (функция outcome), что и суммы части А: файлы с хешем и «особые» -
    в account(), остаток папок без хеша - отдельным проходом только по нужным папкам (сверка числа с суммами папок).
    Элемент: [путь, размер, sha, тип, исход, недостающие диски, {диск: (вид, подробность)}]; вид для «копировать» по
    каждому недостающему диску: 'rep' (пишется), 'dup' (то же содержимое пишется из другого пути), 'nohash' (без хеша,
    пишется), 'blocked' (не пишется: причина)."""
    P = Plan(disk, dirs, marks)
    want = None if collect is None else (collect[0], frozenset(collect[1]))
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

    # ---------- поштучные файлы без хеша: занятый путь назначения ----------
    # длина пути не ограничена (17.11.2026, решение владельца): шаблоны копирования 2.7 и перемещения 1.3 - через \\?\
    special = set(file_marks)
    # независимый счёт числа и байтов носителя (сверка)
    real_n, real_b = c.execute('select count(*), coalesce(sum(size), 0) from files where disk=?', (disk,)).fetchone()
    twins = _twins(c, disk, folders, children, copied) if copied else set()
    unread = {p: w for p, w in unread_files(c, disk).items()   # только где что-то копируется (не весь носитель)
              if p in file_marks or route.get(parent_of(p), NONE_ROUTE).state == R_DIR}
    special |= twins | set(unread)                               # снова не прочитан при пересканировании - поштучно
    occ = collections.defaultdict(dict)                          # путь носителя -> {диск D: (sha, ev) на D}
    blocked_pref = collections.defaultdict(list)                 # диск D -> папки носителя, где на D файл вместо папки

    def sources_of(rel):
        """Пути носителя, чей путь назначения - rel (этап 14): сам rel (если он не в служебной папке) и rel внутри
        каждой служебной «Скопировано на …» (только где есть такая папка верхнего уровня - для скорости)."""
        top = rel.split(SEP, 1)[0]
        res = [] if top in copied else [rel]
        for r in copied:
            # файл прямо в корне R (rel без папок) - если R есть; иначе - если есть R\<первая папка rel>
            if (SEP not in rel and r.lower() in folder_lc) or (r + SEP + top).lower() in folder_lc:
                res.append(r + SEP + rel)
        return res

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
        srcs = {rel: sources_of(rel) for rel in on_d} if copied else {rel: [rel] for rel in on_d}
        hit = _probe_all(c, disk, [s_ for v in srcs.values() for s_ in v])
        for rel, v in on_d.items():
            files_ = [s_ for s_ in srcs[rel] if s_ in hit]
            for s_ in files_:
                occ[s_][d] = v
                special.add(s_)
            if not files_:
                blocked_pref[d] += [s_.lower() for s_ in srcs[rel] if s_.lower() in folder_lc]

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
        if not sha and path in unread:                           # не копируется (решение владельца 17.11.2026)
            return B_UNREAD
        if path in twins:
            return B_TWIN
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
        if o == O_JUNK and r.state == R_DIR:
            P.junk_dir[r.num][0] += 1; P.junk_dir[r.num][1] += size
        item = None
        if want is not None and wanted_item(want, o, num, r):
            item = [path, size, sha, k, o, tuple(miss), {}]
            P.items.append(item)
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
            if item is not None:
                item[6][d] = (('blocked', why, g['key'] if sha else None) if why else
                              (('hash', g['key']) if sha else ('nohash', '')))
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
                g['blocked'] += why != B_UNREAD                  # непрочитанный не держит задание остальных
            else:
                P.part_b[d][0] += 1; P.part_b[d][1] += size
                g['per_disk'][d][0] += 1; g['per_disk'][d][1] += size
                P.unhashed_copy[d][0] += 1; P.unhashed_copy[d][1] += size
                if detail:
                    P.rows[(g['key'], d)].append((d, path, size, 'без хеша', ''))
                    if nm is not None:
                        P.info.setdefault('nh_keys', collections.defaultdict(set))[d].add((nm, size))

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
            if o == O_JUNK and r.state == R_DIR:
                P.junk_dir[r.num][0] += n; P.junk_dir[r.num][1] += b
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

    if want is not None:
        _collect_rest(c, P, disk, want, folders, dn, route, docs_ok, outcome, src_bit, special, blocked_pref, ftype)

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

    if want is not None:                                         # «копировать»: пишется ли этот экземпляр
        for it in P.items:
            for d, st in list(it[6].items()):
                if st[0] == 'hash':
                    rep = reps.get((st[1], d), {}).get(it[2])
                    it[6][d] = ('rep', '') if rep and rep[0] == it[0] else ('dup', rep[0] if rep else '')
                elif st[0] == 'blocked':
                    rep = reps.get((st[2], d), {}).get(it[2]) if len(st) > 2 and st[2] is not None else None
                    it[6][d] = ('blocked', st[1], rep[0] if rep else '')   # rep - то же содержимое пишется из другого пути

    # ---------- detail: файлы без хеша поштучно (строки заданий) и тёзки ----------
    if detail and need_files:
        need = set(need_files)
        tops = top_folders(need)                                 # самые верхние папки (предок уже взят - не надо)
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
    P.info.update(status=st[0], scanned=st[1], label=st[2], roots=sorted(roots), copied=sorted(copied),
                  issues=c.execute('select count(*) from issues where disk=?', (disk,)).fetchone()[0],
                  is_target=[n for n, d in dirs.items() if disk in d.disks])
    return P
