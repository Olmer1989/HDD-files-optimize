"""Команда cmp."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from hb_core.consts import SEP
from hb_core.util import gb, name_key, out
from hb_core.report import save, table
from hb_core.db import connect
from hb_core.query import check_disk, name_sizes, sha_sizes


def cmd_cmp(a):
    c, _ = connect()
    check_disk(c, a.disk_a); check_disk(c, a.disk_b)
    A, B = sha_sizes(c, a.disk_a, a.folder_a), sha_sizes(c, a.disk_b, a.folder_b)
    both, oa, ob = A.keys() & B.keys(), A.keys() - B.keys(), B.keys() - A.keys()
    s = lambda keys, d: sum(d[k][1] for k in keys)
    NA, NB = name_sizes(c, a.disk_a, a.folder_a), name_sizes(c, a.disk_b, a.folder_b)
    nb, na_, nb_ = NA.keys() & NB.keys(), NA.keys() - NB.keys(), NB.keys() - NA.keys()
    # Файл с хешем с одной стороны и файл без хеша с другой: сравнение только по имени и размеру, один к одному
    # (у каждой пары (имя, размер) без хеша - одна строка, name_sizes). Такое совпадение «одинаковы» не даёт.
    mixed = []
    for H, U, side in ((A, nb_, 'A'), (B, na_, 'B')):
        only_h = oa if side == 'A' else ob
        for k in sorted(only_h, key=lambda k: H[k][0]):
            key = (name_key(H[k][0]), H[k][1])
            if key in U:
                U.discard(key); only_h.discard(k)
                mixed.append((side, H[k][0], H[k][1], k))
    out(f'A = {a.disk_a}\\{a.folder_a}    B = {a.disk_b}\\{a.folder_b}')
    out(f'Файлы с подтверждённым SHA-256 (разных): A {len(A)}, B {len(B)}')
    table(('', 'файлов', 'ГБ'), [('есть в обеих', len(both), gb(s(both, A))), ('только в A', len(oa), gb(s(oa, A))),
                                  ('только в B', len(ob), gb(s(ob, B)))])
    if NA or NB:
        out(f'Файлы без подтверждённого хеша (по имени и размеру, не доказательство): в обеих {len(nb)}, '
            f'только в A {len(na_)}, только в B {len(nb_)}')
    if mixed:
        out(f'С хешем с одной стороны и без хеша с другой (сравнение только по имени и размеру): совпали {len(mixed)}')
    # общий вывод - только после обеих частей
    if not A and not B and not NA and not NB:
        verdict = 'в базе нет файлов по этим путям - сравнивать нечего.'
    elif oa or ob:
        verdict = ('в B есть все файлы с хешем из A.' if not oa else 'в A есть все файлы с хешем из B.' if not ob
                   else 'папки различаются.')
        if na_ or nb_:
            verdict += ' Различаются и файлы без хеша.'
    elif na_ or nb_:
        verdict = ('файлы с хешем совпадают, но РАЗЛИЧАЮТСЯ файлы без хеша: '
                   f'только в A {len(na_)}, только в B {len(nb_)}. Папки не одинаковы.')
    elif NA or NB or mixed:
        verdict = ('файлы с хешем совпадают точно; остальные совпали по имени и размеру - это не доказательство. '
                   'Одинаковость папок НЕ подтверждена полностью.')
    else:
        verdict = 'наборы файлов одинаковы по содержимому (SHA-256).'
    out('Вывод: ' + verdict)
    out('Сравнивается набор файлов, а не расположение по подпапкам: структура папок не проверяется.')
    detail = [('только в A', *A[k], k) for k in oa] + [('только в B', *B[k], k) for k in ob]
    detail += [('только в A, без хеша', NA[k], k[1], '') for k in na_] + [('только в B, без хеша', NB[k], k[1], '') for k in nb_]
    detail += [(f'хеш только в {side}, совпали имя и размер', path, size, sha) for side, path, size, sha in mixed]
    p = save(f'сравнение - {a.disk_a} {a.folder_a} и {a.disk_b} {a.folder_b}'.replace(SEP, ' - '),
             ('где', 'путь', 'размер', 'SHA-256'), sorted(detail, key=lambda r: (r[0], r[1])))
    out(f'Различия по файлам ({len(detail)}): {p}')

NAMES = ('cmp',)
HELP = 'одинаковы ли две папки'
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP, GUI_ORDER = 'Вопросы о диске', 4
GUI_TITLE = 'Одинаковы ли две папки?'
GUI_HINT = ('Сравнивает две папки — на одном или на разных дисках: одинаковы ли фото и видео (по SHA-256) '
            'и остальные файлы (по имени и размеру).\nСравнивается набор файлов, раскладка по подпапкам не проверяется.')
GUI_ARGS = {'disk_a': 'Первая папка: диск', 'folder_a': 'Первая папка: путь',
            'disk_b': 'Вторая папка: диск', 'folder_b': 'Вторая папка: путь'}
GUI_PAIRS = {'folder_a': 'Первая папка', 'folder_b': 'Вторая папка'}     # диск и папка - одной строкой


def add_args(p, name):
    p.add_argument('disk_a'); p.add_argument('folder_a'); p.add_argument('disk_b'); p.add_argument('folder_b')


def run(a):
    cmd_cmp(a)
