"""Команда folders."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from hb_core.consts import FOLDER_TYPES, SEP
from hb_core.util import gb, out, prefix_cond
from hb_core.report import save, table, type_cols
from hb_core.db import connect
from hb_core.query import check_disk


def cmd_folders(a):
    """Сколько занимает папка и её подпапки, по типам файлов: по готовой таблице folders, диски не читаются."""
    c, _ = connect()
    check_disk(c, a.disk)
    base = (a.folder or '').strip(SEP)
    level = base.count(SEP) + 1 if base else 0
    depth = level + a.depth                     # a.depth == 0 - все уровни: все подпапки глубже выбранной
    cols = 'folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5))
    me = c.execute(f'select {cols} from folders where disk=? and folder=?', (a.disk, base)).fetchone()
    if not me:
        out(f'В базе нет файлов в {a.disk}\\{base} (проверьте написание пути).')
        return
    out(f'{a.disk}\\{base}: файлов {me[1]}, {gb(me[2])} ГБ; по типам, ГБ: '
        + ', '.join(f'{t} {v}' for t, v in zip(FOLDER_TYPES, type_cols(me, 3))))
    cond, args = prefix_cond('folder', base)
    rows = c.execute(f'select {cols} from folders where disk=? and depth{"=" if a.depth else ">"}? and {cond} '
                     'order by bytes desc', [a.disk, depth] + args).fetchall()
    head = ('папка', 'файлов', 'ГБ') + FOLDER_TYPES
    body = [(r[0][len(base):].lstrip(SEP)[-60:], r[1], gb(r[2]), *type_cols(r, 3)) for r in rows]
    if body:
        table(head, body, limit=12)
    path = save(f'папки - {a.disk} {base}'.replace(SEP, ' - ').strip(), head, body)
    out(f'Все подпапки ({len(body)}): {path}')

NAMES = ('folders',)
HELP = 'сколько занимают папка и её подпапки, по типам файлов'
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP, GUI_ORDER = 'Вопросы о диске', 6
GUI_TITLE = 'Сколько занимает папка?'
GUI_HINT = 'Размер папки и подпапок: фото, видео, тексты, прочее, мусор.'
GUI_ARGS = {'disk': 'Диск', 'folder': 'Папка', 'depth': 'Сколько уровней папок показать'}


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('folder', nargs='?', default='')
    p.add_argument('--depth', type=int, default=1, help='уровней подпапок (0 - все уровни)')


def run(a):
    cmd_folders(a)
