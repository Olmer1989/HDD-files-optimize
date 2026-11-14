"""Готовые таблицы presence и folders: полный и дельта-пересчёт."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import os
import build_pilot as bp
from hb_core.consts import C_DOC, C_JUNK, EV_RANK, EXT_CLASS, F_JUNK, F_OTHER, F_PHOTO, F_TEXT, F_VIDEO, MAIN, SEP
from hb_core.schema import DERIVED_SCHEMA, TRIGGERS
from hb_core.util import class_of, parent_of


def presence_sql(where_sha, where_exp):
    return f'''insert into presence
        select h, substr(min(case when disk='{MAIN[0]}' then r end), 2), substr(min(case when disk='{MAIN[1]}' then r end), 2),
               count(distinct case when conf=1 then disk end), sum(conf)
        from (select sha h, disk, {EV_RANK} r, 1 conf from files where sha is not null {where_sha}
              union all
              select sha_exp, disk, {EV_RANK}, 0 from files where sha_exp is not null {where_exp})
        group by h'''


def presence_full(c):
    c.execute('delete from presence')
    c.execute(presence_sql('', ''))


def presence_touched(c):
    c.execute('delete from presence where sha in (select sha from temp.touched)')
    c.execute(presence_sql('and sha in (select sha from temp.touched)', 'and sha_exp in (select sha from temp.touched)'))
    c.execute('delete from temp.touched')


def folder_type(path, name_lc, size):
    if not size:
        return F_OTHER
    if class_of(path, name_lc or '', size) == C_JUNK:
        return F_JUNK
    t = bp.EXT_TYPE.get(os.path.splitext(name_lc or '')[1])
    if t:
        return F_VIDEO if t == 'Видео' else F_PHOTO
    return F_TEXT if EXT_CLASS.get(os.path.splitext(name_lc or '')[1]) == C_DOC else F_OTHER


def roll_up(agg):
    """Суммы по папкам (прямо в ней) -> суммы вместе со всеми подпапками, для всех папок-предков до корня ''."""
    total = {f: list(v) for f, v in agg.items()}
    for f in list(total):                                   # недостающие промежуточные папки
        while f:
            f = parent_of(f)
            if f in total:
                break
            total[f] = [0] * 12
    for f in sorted(total, key=lambda x: -(x.count(SEP) + 1 if x else 0)):
        if f:
            p, v = total[parent_of(f)], total[f]
            for i in range(12):
                p[i] += v[i]
    return total


def add_file(agg, path, size, name_lc, sign=1):
    a = agg.get(parent_of(path))
    if a is None:
        a = agg[parent_of(path)] = [0] * 12
    k = folder_type(path, name_lc, size)
    size = (size or 0) * sign
    a[0] += sign; a[1] += size; a[2 + 2 * k] += sign; a[3 + 2 * k] += size


def folder_row(d, f, v):
    return (d, f, f.count(SEP) + 1 if f else 0, f.lower(), *v)


def folders_full(c, disks=None):
    disks = disks or [r[0] for r in c.execute('select distinct disk from files')]
    for d in disks:
        c.execute('delete from folders where disk=?', (d,))
        agg = {}
        for path, size, nm in c.execute('select path, size, name_lc from files where disk=?', (d,)):
            add_file(agg, path, size, nm)
        c.executemany(f'insert into folders values ({",".join("?" * 16)})',
                      (folder_row(d, f, v) for f, v in roll_up(agg).items()))


def folders_delta(c):
    """Изменения строк files (из триггеров) -> поправки сумм по папкам."""
    by_disk = collections.defaultdict(dict)
    for d, path, size, nm, sign in c.execute('select disk, path, size, name_lc, sign from temp.delta'):
        add_file(by_disk[d], path, size, nm, sign)
    c.execute('delete from temp.delta')
    upd = ', '.join(f'{x}={x}+excluded.{x}' for x in ['files', 'bytes'] + [f'{p}{i}' for i in range(5) for p in 'nb'])
    for d, agg in by_disk.items():
        rows = [folder_row(d, f, v) for f, v in roll_up(agg).items() if any(v)]
        c.executemany(f'insert into folders values ({",".join("?" * 16)}) on conflict(disk, folder) do update set {upd}', rows)
    c.execute('delete from folders where files <= 0')


def derived_start(c):
    """Включить учёт затронутых строк перед сборкой по шагам."""
    c.execute('pragma recursive_triggers = on')       # «insert or replace» удаляет старую строку - это тоже изменение
    for q in DERIVED_SCHEMA + TRIGGERS:
        c.execute(q)


def derived_finish(c):
    presence_touched(c)
    folders_delta(c)
