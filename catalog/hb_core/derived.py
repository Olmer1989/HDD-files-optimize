"""Готовые таблицы presence и folders: полный и дельта-пересчёт."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import os
import build_pilot as bp
from hb_core.consts import (C_ARCH, C_DOC, C_JUNK, C_MUSIC, C_PROJ, EV_RANK, EXT_CLASS, F_ARCH, F_JUNK, F_MUSIC, F_NEVER,
                            F_OTHER, F_PHOTO, F_PROJ, F_TEXT, F_VIDEO, MAIN, N_TYPES, NEVER_COPY_EXT, SEP)
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
    """Один из 5 прежних типов таблицы folders (фото, видео, тексты, прочие, мусор)."""
    k = copy_kind(path, name_lc, size)
    return F_OTHER if k > F_JUNK else k


OTHER_SUB = {C_ARCH: F_ARCH, C_PROJ: F_PROJ, C_MUSIC: F_MUSIC}


def sub_of_other(ext):
    """Подмножество «прочих» по расширению: архивы, проекты, музыка, программы (никогда) или F_OTHER («другие»)."""
    if ext in NEVER_COPY_EXT:
        return F_NEVER
    return OTHER_SUB.get(EXT_CLASS.get(ext), F_OTHER)


def copy_kind(path, name_lc, size):
    """Тип файла для «что копировать» (этап 5): 0..4 - прежние типы folders, 5..8 - подмножества «прочих» (архивы,
    проекты монтажа и графики, музыка, программы и системное). Расширение - последнее, без учёта регистра (имя в базе -
    в нижнем регистре): «file.jpg.exe» - программа; без расширения и неизвестное - «другие»; пустой файл - «другие»,
    но пустая программа (x.exe, 0 байт) - всё равно программа: «никогда» не зависит от размера. Прежний тип таблицы
    folders от этого не меняется (программа и пустой файл - оба «прочие»).
    Единственное место правила; fast_folder_type в razbor.py - та же логика быстрее (тест сверяет)."""
    if not size:
        return F_NEVER if os.path.splitext((name_lc or '').lower())[1] in NEVER_COPY_EXT else F_OTHER
    if class_of(path, name_lc or '', size) == C_JUNK:
        return F_JUNK
    ext = os.path.splitext((name_lc or '').lower())[1]
    t = bp.EXT_TYPE.get(ext)
    if t:
        return F_VIDEO if t == 'Видео' else F_PHOTO
    if EXT_CLASS.get(ext) == C_DOC:
        return F_TEXT
    return sub_of_other(ext)


W = 2 + 2 * N_TYPES             # файлов, байт, затем (число, байт) по каждому типу


def roll_up(agg):
    """Суммы по папкам (прямо в ней) -> суммы вместе со всеми подпапками, для всех папок-предков до корня ''."""
    total = {f: list(v) for f, v in agg.items()}
    for f in list(total):                                   # недостающие промежуточные папки
        while f:
            f = parent_of(f)
            if f in total:
                break
            total[f] = [0] * W
    for f in sorted(total, key=lambda x: -(x.count(SEP) + 1 if x else 0)):
        if f:
            p, v = total[parent_of(f)], total[f]
            for i in range(W):
                p[i] += v[i]
    return total


def add_file(agg, path, size, name_lc, sign=1):
    a = agg.get(parent_of(path))
    if a is None:
        a = agg[parent_of(path)] = [0] * W
    k = copy_kind(path, name_lc, size)
    size = (size or 0) * sign
    base = F_OTHER if k > F_JUNK else k
    a[0] += sign; a[1] += size; a[2 + 2 * base] += sign; a[3 + 2 * base] += size
    if k > F_JUNK:                                          # подмножество «прочих» - ещё и в свой столбец
        a[2 + 2 * k] += sign; a[3 + 2 * k] += size


def folder_row(d, f, v):
    return (d, f, f.count(SEP) + 1 if f else 0, f.lower(), *v)


def folders_full(c, disks=None):
    disks = disks or [r[0] for r in c.execute('select distinct disk from files')]
    for d in disks:
        c.execute('delete from folders where disk=?', (d,))
        agg = {}
        for path, size, nm in c.execute('select path, size, name_lc from files where disk=?', (d,)):
            add_file(agg, path, size, nm)
        c.executemany(f'insert into folders values ({",".join("?" * (4 + W))})',
                      (folder_row(d, f, v) for f, v in roll_up(agg).items()))


def folders_delta(c):
    """Изменения строк files (из триггеров) -> поправки сумм по папкам."""
    by_disk = collections.defaultdict(dict)
    for d, path, size, nm, sign in c.execute('select disk, path, size, name_lc, sign from temp.delta'):
        add_file(by_disk[d], path, size, nm, sign)
    c.execute('delete from temp.delta')
    upd = ', '.join(f'{x}={x}+excluded.{x}' for x in ['files', 'bytes'] + [f'{p}{i}' for i in range(N_TYPES) for p in 'nb'])
    for d, agg in by_disk.items():
        rows = [folder_row(d, f, v) for f, v in roll_up(agg).items() if any(v)]
        c.executemany(f'insert into folders values ({",".join("?" * (4 + W))}) on conflict(disk, folder) do update set {upd}', rows)
    c.execute('delete from folders where files <= 0')


def derived_start(c):
    """Включить учёт затронутых строк перед сборкой по шагам."""
    c.execute('pragma recursive_triggers = on')       # «insert or replace» удаляет старую строку - это тоже изменение
    for q in DERIVED_SCHEMA + TRIGGERS:
        c.execute(q)


def derived_finish(c):
    presence_touched(c)
    folders_delta(c)
