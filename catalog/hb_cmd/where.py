"""Команда where."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
from hb_core.util import gb, out
from hb_core.report import table
from hb_core.db import connect
from hb_core.query import check_disk, sha_sizes, where_unhashed


def cmd_where(a):
    c, _ = connect()
    check_disk(c, a.disk)
    mine = sha_sizes(c, a.disk, a.path)
    where_unhashed(c, a.disk, a.path, bool(mine))
    if not mine:
        return
    cnt, size, sample = collections.Counter(), collections.Counter(), {}
    c.execute('create temp table q(sha text primary key)')
    c.executemany('insert into q values (?)', ((k,) for k in mine))
    seen = set()
    for disk, path, sha in c.execute('select f.disk, f.path, f.sha from files f join q on q.sha=f.sha'):
        if disk == a.disk and mine[sha][0] == path:
            continue
        if (disk, sha) in seen:
            continue
        seen.add((disk, sha))
        cnt[disk] += 1; size[disk] += mine[sha][1]; sample.setdefault(disk, path)
    tot = sum(v[1] for v in mine.values())
    out(f'{a.disk}\\{a.path}: {len(mine)} разных файлов с SHA-256, {gb(tot)} ГБ. Где ещё лежит то же содержимое:')
    rows = [(d + (' (тот же диск, другое место)' if d == a.disk else ''), cnt[d], gb(size[d]), f'{100 * cnt[d] // len(mine)}%',
             sample[d][:70]) for d in sorted(cnt, key=lambda d: -size[d])]
    table(('диск', 'файлов', 'ГБ', 'доля', 'пример пути'), rows or [('нигде больше', 0, '0.00', '0%', '')])
    weak = collections.Counter()
    for disk, sha in c.execute('select f.disk, f.sha_exp from files f join q on q.sha=f.sha_exp'):
        weak[disk] += 1
    if weak:
        out('НЕПОДТВЕРЖДЁННЫЕ копии (сверен только размер, со слов пользователя или файл менялся) - копиями не считаются: '
            + ', '.join(f'{d} - {n}' for d, n in weak.most_common()))

NAMES = ('where',)
HELP = 'на каких ещё дисках лежит папка или файл'
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP, GUI_ORDER = 'Вопросы о диске', 3
GUI_TITLE = 'Где ещё лежит эта папка или файл?'
GUI_HINT = ('На каких носителях есть те же фото и видео (по SHA-256), а для остальных файлов — '
            'файлы с тем же именем и размером.')
GUI_ARGS = {'disk': 'Диск', 'path': 'Папка или файл'}


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('path')


def run(a):
    cmd_where(a)
