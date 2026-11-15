"""Команда manual, fix-manual, decide, exclude."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from hb_core import paths
from hb_core.util import out
from hb_core.sources import manual_rows


def owner_write(preview, write, a):
    """Предпросмотр по умолчанию; запись - только с --yes. Всё - через service (единый путь записи)."""
    import service as sv
    try:
        pv = write() if a.yes else preview()
    except sv.Refused as e:
        out('НЕ ЗАПИСАНО: ' + str(e))
        raise SystemExit(1)
    for x in pv['lines']:
        out(x)
    if a.yes:
        out(f'Записано: строка {pv["line"]}. Копия таблицы до записи - в «_БАЗА\\архив таблиц».')
    else:
        out('Это предпросмотр, ничего не записано. Записать: та же команда с --yes')


def cmd_manual(a):
    import service as sv
    args = (a.date, a.action, a.disk, a.path, a.disk2 or '', a.path2 or '')
    owner_write(lambda: sv.manual_preview(*args), lambda: sv.add_manual(*args, note=a.note or ''), a)


def cmd_decide(a):
    import service as sv
    owner_write(lambda: sv.decision_preview(a.disk, a.path, a.verdict),
                lambda: sv.add_decision(a.disk, a.path, a.verdict, a.note or ''), a)


def cmd_exclude(a):
    import service as sv
    owner_write(lambda: sv.exclusion_preview(a.disk, a.path), lambda: sv.add_exclusion(a.disk, a.path, a.note or ''), a)


def cmd_fix_manual(a):
    import service as sv
    rows = dict(manual_rows())
    if a.line not in rows:
        out(f'Строки {a.line} в «{paths.MANUAL.name}» нет.')
        raise SystemExit(1)
    old = rows[a.line]
    out('Было: ' + ' | '.join(x for x in old[:6] if x))
    new = [a.date, a.action, a.disk, a.path, a.disk2 or '', a.path2 or '', old[6]]
    out('Станет: ' + ' | '.join(x for x in new[:6] if x))
    if not a.yes:
        out('Это предпросмотр. Исправить: та же команда с --yes (база соберётся заново, несколько минут).')
        return
    try:
        sv.fix_manual(a.line, new, a.reason)
    except sv.Refused as e:
        out('НЕ ИСПРАВЛЕНО: ' + str(e))
        raise SystemExit(1)
    out('Исправлено, причина записана в комментарий строки; база собрана заново.')

NAMES = ('manual', 'fix-manual', 'decide', 'exclude')
HELP = {'manual': 'записать, что владелец сделал в Проводнике', 'fix-manual': 'исправить ошибочную строку ручных операций', 'decide': 'записать решение владельца по папке', 'exclude': 'папка, которую база не учитывает (временная копия)'}
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP = 'Записать (сначала предпросмотр)'
GUI_ORDER = {'manual': 1, 'decide': 2, 'exclude': 3, 'fix-manual': 4}
GUI_TITLE = {'manual': 'Я сделал в Проводнике', 'decide': 'Решение по папке', 'exclude': 'Не учитывать папку',
             'fix-manual': 'Исправить запись о действии в Проводнике'}
GUI_HINT = {'manual': 'Записать, что вы скопировали, переместили или удалили вручную, чтобы база это знала.',
            'decide': ('«не нужно» — можно не сохранять; «раздел: …» — хранить на диске раздела, не на 45/77; '
                       '«пока не трогаем» — отложить.'),
            'exclude': 'Временная копия, которую база не должна считать.',
            'fix-manual': ('Заменить ошибочную строку (номер строки — из таблицы ручных операций); причина обязательна; '
                           'база пересоберётся (минуты).')}
_MANUAL_ARGS = {'date': ('Дата', 'ДД.ММ.ГГГГ'), 'action': 'Действие', 'disk': 'Диск', 'path': 'Папка или файл',
                'disk2': 'Куда: диск', 'path2': 'Куда: папка', 'note': 'Комментарий'}
GUI_ARGS = {'manual': _MANUAL_ARGS,
            'fix-manual': dict(_MANUAL_ARGS, line='Номер строки', reason='Причина исправления'),
            'decide': {'disk': 'Диск', 'path': 'Папка', 'verdict': 'Решение', 'note': 'Комментарий'},
            'exclude': {'disk': 'Диск', 'path': 'Папка', 'note': 'Комментарий'}}
_MANUAL_PAIRS = {'path': 'Что', 'path2': ('Куда', 'для «скопировано» и «перемещено»')}
GUI_PAIRS = {'manual': _MANUAL_PAIRS, 'fix-manual': _MANUAL_PAIRS, 'decide': {}, 'exclude': {}}


def add_args(p, name):
    if name in ('manual', 'fix-manual'):
        if name == 'fix-manual':
            p.add_argument('line', type=int); p.add_argument('--reason', required=True)
        p.add_argument('date'); p.add_argument('action', choices=['удалено', 'скопировано', 'перемещено'])
        p.add_argument('disk'); p.add_argument('path'); p.add_argument('disk2', nargs='?'); p.add_argument('path2', nargs='?')
        p.add_argument('--note'); p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')
    elif name == 'decide':
        p.add_argument('disk'); p.add_argument('path'); p.add_argument('verdict'); p.add_argument('--note')
        p.add_argument('--yes', action='store_true')
    else:
        p.add_argument('disk'); p.add_argument('path'); p.add_argument('--note'); p.add_argument('--yes', action='store_true')


def run(a):
    {'manual': cmd_manual, 'fix-manual': cmd_fix_manual, 'decide': cmd_decide, 'exclude': cmd_exclude}[a.cmd](a)
