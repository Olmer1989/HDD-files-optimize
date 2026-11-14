"""Команда find."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
from hb_core.consts import FOLDER_TYPES
from hb_core.util import gb, out, parent_of
from hb_core.report import save, table, type_cols
from hb_core.db import connect
from hb_core.query import check_disk


def cmd_find(a):
    """Папки, в пути которых есть все слова: по таблице folders, а не по 11 млн файлов."""
    c, _ = connect()
    words = [w.lower() for w in a.words if w.strip()]
    q = ('select disk, folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5)) + ' from folders where '
         + ' and '.join(['instr(folder_lc, ?) > 0'] * len(words)))
    args = list(words)
    if a.disk:
        check_disk(c, a.disk)
        q += ' and disk=?'
        args.append(a.disk)
    rows = c.execute(q, args).fetchall()
    hits = {(r[0], r[1]) for r in rows}
    top = [r for r in rows if (r[0], parent_of(r[1])) not in hits or not r[1]]   # только верхние совпадения
    top.sort(key=lambda r: -r[3])
    by_disk = collections.defaultdict(lambda: [0, 0, 0])
    for r in top:
        k = by_disk[r[0]]
        k[0] += 1; k[1] += r[2]; k[2] += r[3]
    what = ' '.join(f'«{w}»' for w in a.words)
    if not top:
        out(f'Папок со словами {what} нет' + (f' на {a.disk}.' if a.disk else '.'))
        return
    out(f'Папки со словами {what}: {len(top)} (вложенные совпадения не считаются), файлов {sum(r[2] for r in top)}, '
        f'{gb(sum(r[3] for r in top))} ГБ')
    if not a.disk:
        out('По носителям: ' + '; '.join(f'{d} - {k[0]} папок, {gb(k[2])} ГБ'
                                         for d, k in sorted(by_disk.items(), key=lambda kv: -kv[1][2])[:8])
            + ('; …' if len(by_disk) > 8 else ''))
    head = ('диск', 'папка', 'файлов', 'ГБ') + FOLDER_TYPES
    body = [(r[0], r[1][-70:], r[2], gb(r[3]), *type_cols(r, 4)) for r in top]
    table(head[:4], [b[:4] for b in body], limit=10)
    path = save(f'поиск папок - {" ".join(a.words)}', head, [(r[0], r[1], r[2], gb(r[3]), *type_cols(r, 4)) for r in top])
    out(f'Все найденные папки с разбивкой по типам: {path}')

NAMES = ('find',)
HELP = 'папки, в пути которых есть слова (например «Сафари»)'


def add_args(p, name):
    p.add_argument('words', nargs='+'); p.add_argument('--disk')


def run(a):
    cmd_find(a)
