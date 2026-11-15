"""Запросы к базе для ответов команд: решения владельца, присутствие на 45/77, файлы без хеша."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import json
import sys
import time
from pathlib import Path
from hb_core import paths
from hb_core.paths import journal_paths
from hb_core.consts import CLASS_ORDER, C_EMPTY, C_JUNK, MAIN, NOHASH_NOTE, SEP, SIGNIFICANT
from hb_core.util import class_of, gb, original_path, out, prefix_cond, rel_of
from hb_core.report import save, table
from hb_core.sources import log_time, read_table, read_tsv, serial_map


def decisions_for(disk):
    """Решения по путям для диска (строки с диском «*» действуют на все диски)."""
    res = []
    for f in read_table(paths.DECISIONS)[1:]:
        f = [x.strip() for x in f] + [''] * 4
        if f[0] in (disk, '*') and f[2] and not f[1].lower().startswith('класс:'):
            res.append((f[1].rstrip(SEP), f[2]))
    return res


def class_rules(disk):
    """Решения владельца по целому классу файлов: путь вида «класс: служебные и временные»."""
    res = {}
    for f in read_table(paths.DECISIONS)[1:]:
        f = [x.strip() for x in f] + [''] * 4
        if f[0] in (disk, '*') and f[2] and f[1].lower().startswith('класс:'):
            res[f[1].split(':', 1)[1].strip().lower()] = f[2]
    return res


def decision_of(path, decs):
    path = original_path(path)                # решения привязаны к исходному пути и действуют после перемещения
    for p, verdict in decs:
        if not p or path == p or path.startswith(p + SEP):
            return verdict
    return None


def check_disk(c, disk):
    if not c.execute('select 1 from disks where disk=?', (disk,)).fetchone():
        known = ', '.join(r[0] for r in c.execute('select disk from disks order by disk'))
        sys.exit(f'Диска {disk} нет в базе. Есть: {known}')


def presence(c, disk, prefix, exclude=None, weak=False):
    """Каждый файл диска с подтверждённым хешем: (path, size, sha, на45, на77, сколько дисков всего[, слабая45, слабая77]).
    Копией считается только запись с подтверждённым хешем (измерен сканером или сверен скриптом при копировании).
    exclude=(диск, папка) - не считать копиями то, что само собираются удалить.
    weak=True - добавить признаки «на диске лежит неподтверждённая копия» (только размер или со слов)."""
    cond, args = prefix_cond('f.path', prefix)
    if not exclude:                       # обычный вопрос - по готовой таблице presence (быстро)
        conf, weak_ev = "('S','C')", "('Z','U','X')"
        extra = f', coalesce(p.e45 in {weak_ev}, 0), coalesce(p.e77 in {weak_ev}, 0)' if weak else ''
        q = f"""select f.path, f.size, f.sha, coalesce(p.e45 in {conf}, 0), coalesce(p.e77 in {conf}, 0), p.ndisks{extra}
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        return c.execute(q, [disk] + args).fetchall()
    ex_sql, ex_args = '', []
    if exclude:
        ec, ea = prefix_cond('g.path', exclude[1])
        ex_sql, ex_args = f' and not (g.disk=? and {ec})', [exclude[0]] + ea
    cols = [f'exists(select 1 from files g where g.sha=f.sha and g.disk=?{ex_sql})'] * 2
    params = [MAIN[0]] + ex_args + [MAIN[1]] + ex_args
    extra = ''
    if weak:
        extra = (', exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)'
                 ', exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)')
    q = f"""select f.path, f.size, f.sha, {cols[0]}, {cols[1]},
                   (select count(distinct g.disk) from files g where g.sha=f.sha){extra}
            from files f where f.disk=? and f.sha is not null and {cond}"""
    return c.execute(q, params + ([MAIN[0], MAIN[1]] if weak else []) + [disk] + args).fetchall()


def _probe(c, disk, paths_):
    """Файлы диска по списку путей: {путь: (name_lc, size, mtime, sha)}. Порядок соединения задан явно (CROSS JOIN):
    список снаружи, files - по первичному ключу (disk, path). Без этого SQLite (без ANALYZE) выбирает внешним циклом
    files диска - миллионы строк - и ответ идёт десятки минут."""
    c.execute('create temp table if not exists probe_p(path text primary key)')
    c.execute('delete from probe_p')
    c.executemany('insert or ignore into probe_p values (?)', ((x,) for x in paths_))
    return {r[0]: r[1:] for r in c.execute('select f.path, f.name_lc, f.size, f.mtime, f.sha from probe_p q '
                                           'cross join files f on f.disk=? and f.path=q.path where f.size>0', (disk,))}


def _scope_sql(disk, targets, exclude, col='g', others=False):
    sql, args = '', []
    if others:                                   # только ДРУГИЕ диски (only: «больше нигде»)
        sql += f' and {col}.disk<>?'
        args.append(disk)
    if targets:
        sql += f' and {col}.disk in ({",".join("?" * len(targets))})'
        args += list(targets)
    if exclude:
        ec, ea = prefix_cond(f'{col}.path', exclude[1])
        sql += f' and not ({col}.disk=? and {ec})'
        args += [exclude[0]] + ea
    return sql, args


def _keys(c, name, cols, values):
    c.execute(f'create temp table if not exists {name}({", ".join(cols)}, primary key({", ".join(cols)}))')
    c.execute(f'delete from {name}')
    c.executemany(f'insert or ignore into {name} values ({",".join("?" * len(cols))})', values)


def candidates(c, disk, paths_, targets=None, exclude=None, others=False):
    """Совпадение по имени и размеру для файлов С хешем там, где подтверждённой копии нет: файл с тем же именем
    (без регистра, NFC) и размером, у которого хеш НЕ СЧИТАЛСЯ (ev='N'). Строки Z/U/X (ожидаемый хеш) сюда не входят:
    о них говорит sha_exp; строка S/C с другим sha - другое содержимое. «По хешу или по имени» решает наличие хеша у
    ОБЕИХ сторон, а не класс файла (раздел 11 правил сборки). Копией совпадение не считается.
    paths_ - пути файлов диска disk; targets - только эти диски (иначе любые); exclude=(диск, папка) - не считать то,
    что само собираются удалить. Счёт по ключам (имя, размер): каждый ключ перебирается по индексу один раз.
    -> {путь: {диск: путь кандидата}}."""
    files = _probe(c, disk, list(paths_))
    if not files:
        return {}
    _keys(c, 'cand_k', ('name_lc', 'size'), {(v[0], v[1]) for v in files.values()})
    sql, args = _scope_sql(disk, targets, exclude, others=others)
    per_key = {}
    q = f"""select k.name_lc, k.size, g.disk, min(g.path) from cand_k k cross join files g indexed by files_name
                on g.name_lc=k.name_lc and g.size=k.size
            where g.ev='N' and g.sha is null and g.sha_exp is null{sql} group by 1, 2, 3"""
    for nm, s, gd, gp in c.execute(q, args):
        per_key.setdefault((nm, s), {})[gd] = gp
    return {p: per_key[(v[0], v[1])] for p, v in files.items() if (v[0], v[1]) in per_key}


RENAMED_MIN = 1048576       # подсказка «возможно, переименована» - только для файлов от 1 МБ


def renamed(c, disk, paths_, targets=None, exclude=None, others=False):
    """Подсказка «возможно, переименована»: файл того же размера и той же даты изменения (mtime, секунды) с ДРУГИМ
    именем; только от 1 МБ. Не копия и не довод: итоги и вердикты не меняет, последнее слово - за хешем. Пара, где у
    обоих файлов есть подтверждённый хеш и он разный, подсказкой не бывает. Индекс files_sizetime (size, mtime)
    where size >= 1 МБ; счёт по ключам (размер, дата). -> {путь: {диск: путь кандидата}}."""
    files = {p: v for p, v in _probe(c, disk, list(paths_)).items() if v[1] >= RENAMED_MIN and v[2] is not None}
    if not files:
        return {}
    _keys(c, 'ren_k', ('size', 'mtime'), {(v[1], v[2]) for v in files.values()})
    sql, args = _scope_sql(disk, targets, exclude, others=others)
    per_key = {}
    q = f"""select k.size, k.mtime, g.disk, g.name_lc, g.sha, min(g.path) from ren_k k
                cross join files g indexed by files_sizetime on g.size=k.size and g.mtime=k.mtime
            where g.size >= {RENAMED_MIN}{sql} group by 1, 2, 3, 4, 5"""
    for s, mt, gd, nm, sha, gp in c.execute(q, args):
        per_key.setdefault((s, mt), []).append((gd, nm, sha, gp))
    res = {}
    for p, (nm, s, mt, sha) in files.items():
        for gd, gnm, gsha, gp in per_key.get((s, mt), ()):
            if gnm == nm or (sha and gsha and sha != gsha):
                continue
            res.setdefault(p, {}).setdefault(gd, gp)
    return res


NAME_ONLY = 'сравнение только по имени и размеру'
CAND_NOTE = (NAME_ONLY + ': у копии хеш не считался, копией не считается; подтвердить - пересканировать папку с копией '
             '(хеш считается у всех файлов)')
RENAMED_NOTE = ('возможно, переименована: на другом диске есть файл того же размера и той же даты изменения с другим '
                'именем; совпадают только размер и дата - копией не считается, проверит только хеш')


def issues_for(c, disk, folder):
    """Места, которые сканер не смог прочитать и которые задевают папку (внутри неё или выше неё)."""
    base = (folder or '').rstrip(SEP)
    res = []
    for p, kind, note in c.execute('select path, kind, note from issues where disk=?', (disk,)):
        p = p or ''
        if not base or not p or p == base or p.startswith(base + SEP) or base.startswith(p + SEP):
            res.append((p, kind, note))
    return res


def evidence_notes(c):
    """Предупреждения сборки, которые обязаны попадать в ответ об удалении."""
    rep = json.loads(c.execute("select value from meta where key='report'").fetchone()[0])
    notes = [f'журнал не прочитан программой: {x}' for x in rep.get('skipped', [])]
    notes += list(rep.get('warn', []))
    return notes


def folder_key(path, prefix, depth):
    tail = path[len(prefix.rstrip(SEP)) + 1:] if prefix else path
    parts = tail.split(SEP)
    if len(parts) == 1:
        return '[файлы прямо в папке]'
    return SEP.join(parts[:min(depth, len(parts) - 1)])


def unhashed(c, disk, prefix):
    """Файлы без хеша: (path, size, name_lc, класс, на скольких ДРУГИХ дисках есть файл с тем же именем и размером,
    есть ли второй такой же на этом диске)."""
    # Счёт по КЛЮЧАМ (имя, размер), а не по файлам: раньше подзапрос на каждый файл перебирал всех его тёзок, и у
    # диска с миллионами одинаковых служебных файлов (кэш монтажа) ответ шёл минутами (only HDD09 - 7 минут).
    # Теперь каждый ключ считается один раз: строки файлов-тёзок перебираются по индексу files_name один раз.
    cond, args = prefix_cond('path', prefix)
    c.execute('create temp table if not exists uh_keys(name_lc text, size integer, others integer, here integer, '
              'primary key(name_lc, size))')
    c.execute('delete from uh_keys')
    c.execute(f'insert or ignore into uh_keys(name_lc, size) select name_lc, size from files '
              f'where disk=? and sha is null and {cond}', [disk] + args)
    c.execute('''update uh_keys set
                   others = (select count(distinct g.disk) from files g indexed by files_name
                             where g.name_lc=uh_keys.name_lc and g.size=uh_keys.size and g.disk<>?),
                   here = (select count(*) from files g indexed by files_name
                           where g.name_lc=uh_keys.name_lc and g.size=uh_keys.size and g.disk=?)''', (disk, disk))
    keys = {(nm, s): (o, h) for nm, s, o, h in c.execute('select name_lc, size, others, here from uh_keys')}
    res = []
    for p, s, nm in c.execute(f'select path, size, name_lc from files where disk=? and sha is null and {cond}', [disk] + args):
        others, here = keys.get((nm, s), (0, 1))
        res.append((p, s or 0, nm or '', class_of(p, nm or '', s or 0), others, here > 1))
    return res


def namesakes(c, disk, names):
    """Какие из имён встречаются на других дисках (с любым размером) - возможно, другая версия файла."""
    c.execute('create temp table if not exists nm(name text primary key)')
    c.execute('delete from nm')
    c.executemany('insert or ignore into nm values (?)', ((n,) for n in names))
    return {r[0] for r in c.execute(
        'select name from nm where exists(select 1 from files g where g.name_lc=nm.name and g.disk<>?)', (disk,))}


def unhashed_note(c, disk, prefix):
    cond, args = prefix_cond('path', prefix)
    n = c.execute(f'select count(*) from files where disk=? and sha is null and {cond}', [disk] + args).fetchone()[0]
    if n:
        out(f'Файлов без SHA-256 (документы, проекты, архивы, мелочь): {n} - здесь не сравниваются; '
            f'их уникальность показывает команда only.')


def unhashed_report(c, disk, prefix, decs, save_name):
    """Вторая таблица: файлы без хеша по классам и папки, которые есть только на этом диске."""
    rows = unhashed(c, disk, prefix)
    if not rows:
        return
    cls = collections.defaultdict(lambda: [0, 0, 0, 0])            # файлов, байт, не найдено: файлов, байт
    tot, unf, unf_bytes = collections.Counter(), collections.Counter(), collections.Counter()
    detail, decided, root_unf = [], 0, 0
    base = prefix.rstrip(SEP)
    for p, s, nm, k, others, dup in rows:
        if decision_of(p, decs):
            decided += 1
            continue
        a = cls[k]
        a[0] += 1; a[1] += s
        lost = others == 0 and k != C_EMPTY
        if lost:
            a[2] += 1; a[3] += s
        if k not in SIGNIFICANT:
            continue
        parts = p.split(SEP)[:-1]
        for i in range(1, len(parts) + 1):
            d = SEP.join(parts[:i])
            if base and not (d == base or d.startswith(base + SEP)):
                continue
            tot[d] += 1
            if lost:
                unf[d] += 1; unf_bytes[d] += s
        if lost:
            root_unf += not parts
            detail.append([p, s, k, nm, 'есть второй такой же файл на этом диске' if dup else ''])
    other_version = namesakes(c, disk, {d[3] for d in detail}) if detail else set()
    hint = renamed(c, disk, [d[0] for d in detail], others=True)
    for d in detail:
        if d[0] in hint:
            d[4] = (d[4] + '; ' if d[4] else '') + 'возможно, переименована: ' + ', '.join(
                f'{k}: {v}' for k, v in sorted(hint[d[0]].items()))
    for d in detail:
        if d[3] in other_version:
            d[4] = (d[4] + '; ' if d[4] else '') + 'на других дисках есть файл с тем же именем, но другого размера'
    out('')
    out(f'ОСТАЛЬНЫЕ ФАЙЛЫ (без SHA-256): {sum(v[0] for v in cls.values())}')
    out(NOHASH_NOTE)
    table(('класс', 'файлов', 'ГБ', 'копия не найдена: файлов', 'ГБ'),
          [(k, cls[k][0], gb(cls[k][1]), cls[k][2] if k != C_EMPTY else '-', gb(cls[k][3]) if k != C_EMPTY else '-')
           for k in CLASS_ORDER if k in cls])
    whole = sorted((d for d in tot if unf[d] == tot[d]), key=lambda d: d.count(SEP))
    top = []
    for d in whole:                                   # только самые верхние из целиком уникальных
        if not any(d.startswith(t + SEP) for t in top):
            top.append(d)
    top.sort(key=lambda d: -unf_bytes[d])
    if top:
        out('')
        out('Папки, у которых НИ У ОДНОГО значимого файла копия не найдена (вероятно, есть только на этом диске):')
        table(('папка', 'файлов', 'ГБ'), [(d[-90:], unf[d], gb(unf_bytes[d])) for d in top], limit=20)
    depth = (base.count(SEP) + 1 if base else 0)
    partial = sorted((d for d in tot if d.count(SEP) == depth and unf[d] and unf[d] != tot[d]), key=lambda d: -unf_bytes[d])
    if partial:
        out('')
        out('Папки, где копия не найдена у части значимых файлов:')
        table(('папка', 'значимых файлов', 'не найдено', 'ГБ не найдено'),
              [(d[-70:], tot[d], unf[d], gb(unf_bytes[d])) for d in partial], limit=12)
    if root_unf:
        out(f'Прямо в корне: {root_unf} значимых файлов без найденной копии.')
    n_ver = sum(1 for d in detail if d[3] in other_version)
    if n_ver:
        out(f'Из ненайденных у {n_ver} файлов на других дисках есть тёзка другого размера - возможно, другая версия.')
    if hint:
        out(f'Подсказка: у {len(hint)} ненайденных файлов от 1 МБ на других дисках есть файл того же размера и даты с другим '
            f'именем ({RENAMED_NOTE}).')
    if decided:
        out(f'Не показано по решениям пользователя: {decided} файлов.')
    path = save(save_name, ('путь', 'размер', 'класс', 'пометка'), sorted((d[0], d[1], d[2], d[4]) for d in detail))
    out(f'Значимые файлы без найденной копии ({len(detail)}): {path}')


def sha_sizes(c, disk, prefix):
    cond, args = prefix_cond('path', prefix)
    d = {}
    for path, size, sha in c.execute(f'select path, size, sha from files where disk=? and sha is not null and {cond}',
                                     [disk] + args):
        d.setdefault(sha, (path, size))
    return d


def name_sizes(c, disk, prefix):
    """Файлы без хеша в папке: (имя, размер) -> путь; без служебных и пустых."""
    cond, args = prefix_cond('path', prefix)
    d = {}
    for path, size, nm in c.execute(f'select path, size, name_lc from files where disk=? and sha is null and {cond}',
                                    [disk] + args):
        if class_of(path, nm or '', size or 0) not in (C_JUNK, C_EMPTY):
            d.setdefault((nm, size), path)
    return d


def where_unhashed(c, disk, path, has_hashed):
    cond, args = prefix_cond('f.path', path)
    mine = {}
    for p, s, nm, mt in c.execute(f'select f.path, f.size, f.name_lc, f.mtime from files f '
                                  f'where f.disk=? and f.sha is null and {cond}', [disk] + args):
        if class_of(p, nm or '', s or 0) not in (C_JUNK, C_EMPTY):
            mine[p] = (s, nm, mt)
    if not mine:
        if not has_hashed:
            out('В базе нет файлов по этому пути (проверьте написание пути и номер диска).')
        return
    found, same_date, sample, hit = collections.defaultdict(set), collections.Counter(), {}, set()
    # По ключам (имя, размер, диск), а не по парам файлов: у папки с тысячами одинаковых файлов (кэш монтажа) пары
    # файл x тёзка - квадрат. Каждый ключ перебирается по индексу files_name один раз.
    c.execute('create temp table if not exists wu_keys(name_lc text, size integer, primary key(name_lc, size))')
    c.execute('delete from wu_keys')
    c.executemany('insert or ignore into wu_keys values (?, ?)', ((v[1], v[0]) for v in mine.values() if v[0]))
    per_disk, dates = {}, collections.Counter()
    for nm, s, gd, n, gp in c.execute('''select k.name_lc, k.size, g.disk, count(*), min(g.path)
                                          from wu_keys k cross join files g indexed by files_name
                                            on g.name_lc=k.name_lc and g.size=k.size group by 1, 2, 3'''):
        per_disk.setdefault((nm, s), []).append((gd, n, gp))
    for nm, s, gd, mt, n in c.execute('''select k.name_lc, k.size, g.disk, g.mtime, count(*)
                                          from wu_keys k cross join files g indexed by files_name
                                            on g.name_lc=k.name_lc and g.size=k.size
                                          where g.mtime is not null group by 1, 2, 3, 4'''):
        dates[(nm, s, gd, mt)] = n
    for p in sorted(mine):
        s, nm, mt = mine[p]
        for gd, n, gp in per_disk.get((nm, s), ()):
            if gd == disk and n < 2:                   # на этом же диске - только он сам
                continue
            found[gd].add(p); hit.add(p)
            same_date[gd] += bool(mt) and dates.get((nm, s, gd, mt), 0) > (1 if gd == disk else 0)
            sample.setdefault(gd, gp if not (gd == disk and gp == p) else p)
    out(f'{disk}\\{path}: файлов без SHA-256 (кроме служебных и пустых) {len(mine)}, '
        f'{gb(sum(v[0] for v in mine.values()))} ГБ. Где есть файлы с тем же именем и размером:')
    rows = [(d + (' (тот же диск, другое место)' if d == disk else ''), len(found[d]), f'{100 * len(found[d]) // len(mine)}%',
             same_date[d], sample[d][-70:]) for d in sorted(found, key=lambda d: -len(found[d]))]
    table(('диск', 'файлов', 'доля', 'из них с той же датой', 'пример пути'), rows or [('нигде больше', 0, '0%', 0, '')])
    out(f'Копия не найдена нигде: {len(mine) - len(hit)} файлов. Сравнение только по имени и размеру: совпадение - не '
        f'доказательство копии.')
    hint = renamed(c, disk, [p for p in mine if p not in hit])
    if hint:
        by = collections.Counter(d for v in hint.values() for d in v)
        out(f'Подсказка: у {len(hint)} из них есть файл того же размера и даты с другим именем: '
            + ', '.join(f'{d} - {n}' for d, n in by.most_common()) + f' ({RENAMED_NOTE}).')
    if has_hashed:
        out('')


def report_lines(c, rep):
    """Полный отчёт сборки - для файла подробностей."""
    L = []
    L.append('Учтённые журналы скриптов (добавлено, перемещено, убрано, из добавленных без подтверждения содержимого):')
    L += [f'  {k}: {v[0]}, {v[1]}, {v[2]}, {v[3]}' for k, v in sorted(rep['logs'].items())]
    if rep['skipped']:
        L.append('Журналы, которые программа не умеет читать (не учтены):')
        L += ['  ' + x for x in rep['skipped']]
    if rep['old_logs'] or rep['old']:
        L.append('Не применено, потому что опись диска (или частичный скан папки) новее операции:')
        L += [f'  {k}: {n} строк' for k, n in sorted(rep['old_logs'].items())] + ['  ' + x for x in rep['old']]
    if rep['partial']:
        L.append('Частичные сканы папок:')
        L += ['  ' + x for x in rep['partial']]
    L += [f'Исключения ({paths.EXCLUSIONS.name}): {x}' for x in rep['excluded']]
    L.append(f'Ручные операции ({paths.MANUAL.name}): {len(rep["manual"])}')
    L += ['  ' + x for x in rep['manual']]
    L += ['ВНИМАНИЕ: ' + x for x in sorted(rep['warn'])]
    L += ['ВНИМАНИЕ: ' + x for _, x in sorted(rep['unique'].items())]
    L.append('Модули (вид, ключ, время, когда применён, строк изменено):')
    L += [f'  {k}\t{m}\t{time.strftime("%d.%m.%Y %H:%M", time.localtime(t)) if t else "-"}\t{at}\t{n}'
          for m, k, t, at, n in c.execute('select module, kind, time, applied_at, changed from applied order by kind, time, module')]
    return L


def copied_from(disk, jobs):
    """Что журналы единого шаблона скопировали С этого диска: путь источника -> {диск-цель: путь назначения}.
    Учитываются строки «скопирован…» и «уже есть»; подтверждена ли копия, решает база (степень S или C)."""
    serials = serial_map(jobs)
    res = collections.defaultdict(dict)
    for log in sorted(journal_paths(), key=log_time):
        task = Path(log).parent
        if not (task / 'тома.tsv').exists():
            continue
        vols = [f for f in read_tsv(task / 'тома.tsv') if len(f) >= 2]
        names = {f[0].strip(): serials.get(f[1].strip().upper()) for f in vols}
        if not vols or names.get(vols[0][0].strip()) != disk:
            continue
        rows = read_tsv(log)
        head = [h.strip().lower() for h in rows[0]] if rows else []
        if not ('цель' in head and 'куда' in head):
            continue
        i_t, i_r, i_src, i_dst = (head.index(x) for x in ('цель', 'результат', 'источник', 'куда'))
        for f in rows[1:]:
            if len(f) <= i_dst or not (f[i_r].startswith('скопирован') or f[i_r] == 'уже есть'):
                continue
            t = names.get(f[i_t]) or (f[i_t] if f[i_t] in jobs else None)
            if t:
                res[rel_of(f[i_src])[1]][t] = rel_of(f[i_dst])[1]
    return res
