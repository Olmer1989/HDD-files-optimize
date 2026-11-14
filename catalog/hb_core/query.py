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
    cond, args = prefix_cond('f.path', prefix)
    q = f'''select f.path, f.size, f.name_lc,
                   (select count(distinct g.disk) from files g
                     where g.name_lc=f.name_lc and g.size=f.size and g.disk<>f.disk),
                   exists(select 1 from files g
                     where g.name_lc=f.name_lc and g.size=f.size and g.disk=f.disk and g.path<>f.path)
            from files f where f.disk=? and f.sha is null and {cond}'''
    return [(p, s or 0, nm or '', class_of(p, nm or '', s or 0), others, dup)
            for p, s, nm, others, dup in c.execute(q, [disk] + args)]


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
    q = f'''select f.path, g.disk, g.path, g.mtime from files f join files g on g.name_lc=f.name_lc and g.size=f.size
            where f.disk=? and f.sha is null and f.size>0 and {cond} and not (g.disk=f.disk and g.path=f.path)'''
    for p, gd, gp, gmt in c.execute(q, [disk] + args):
        if p not in mine or p in found[gd]:
            continue
        found[gd].add(p); hit.add(p)
        same_date[gd] += bool(gmt and gmt == mine[p][2])
        sample.setdefault(gd, gp)
    out(f'{disk}\\{path}: файлов без SHA-256 (кроме служебных и пустых) {len(mine)}, '
        f'{gb(sum(v[0] for v in mine.values()))} ГБ. Где есть файлы с тем же именем и размером:')
    rows = [(d + (' (тот же диск, другое место)' if d == disk else ''), len(found[d]), f'{100 * len(found[d]) // len(mine)}%',
             same_date[d], sample[d][-70:]) for d in sorted(found, key=lambda d: -len(found[d]))]
    table(('диск', 'файлов', 'доля', 'из них с той же датой', 'пример пути'), rows or [('нигде больше', 0, '0%', 0, '')])
    out(f'Копия не найдена нигде: {len(mine) - len(hit)} файлов. Совпадение имени и размера - вероятная копия, не доказательство.')
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
