"""Команда mark: отметки разбора носителя (логика v3, 15.11.2026) - пакетом, через service.add_marks_batch.

Отметка папки: направление (номер или имя), «не копировать» или «как у родителя» (снять свою отметку). Отметка
всего носителя (--disk-wide) - режим разбора: направление = «всё, кроме отмеченных», «не копировать» = «только
отмеченные». Действует отметка самой глубокой папки; у одной папки - последняя записанная. Без --yes - предпросмотр.
"""
from hb_core.util import out
from hb_core.sources import read_tsv


def cmd_mark(a):
    import service as sv
    rows = []
    if a.disk_wide:
        if not a.where:
            out('Укажите --where: направление для всего носителя или «не копировать».')
            raise SystemExit(1)
        rows.append(('', a.where))
    for f in a.folder or []:
        if not a.where:
            out('Укажите --where: куда отметить папки.')
            raise SystemExit(1)
        rows.append((f, a.where))
    if a.from_file:
        for f in read_tsv(a.from_file):
            if len(f) >= 2 and f[0].strip().lower() not in ('путь', 'папка'):
                rows.append((f[0], f[1].strip()))        # путь - как в файле (этап 16)
    if not rows:
        out('Нечего отмечать: укажите --folder и --where, --disk-wide или --from-file.')
        raise SystemExit(1)
    try:
        pv = sv.add_marks_batch(a.disk, rows, a.note or '') if a.yes else sv.marks_preview(a.disk, rows)
    except sv.Refused as e:
        out('НЕ ЗАПИСАНО: ' + str(e))
        raise SystemExit(1)
    for x in pv['lines'][:18]:
        out(x)
    if a.yes:
        out(f'Записано отметок: {len(pv["fields"])} (с строки {pv["line"]} «решения.tsv»). Копия таблицы - в «_БАЗА\\архив таблиц».')
    else:
        out('Это предпросмотр, ничего не записано. Записать: та же команда с --yes. Итог разбора: razbor ' + a.disk)


NAMES = ('mark',)
HELP = 'отметки разбора носителя: папка -> направление / не копировать / как у родителя (предпросмотр; --yes)'
GUI_GROUP, GUI_ORDER = 'Разбор носителя (v3)', 2
GUI_TITLE = 'Отметить папки'
GUI_HINT = ('Куда идут папки носителя: направление (номер или имя), «не копировать» или «как у родителя».\n'
            '«Весь носитель» - режим: направление = всё, кроме отмеченных; «не копировать» = только отмеченные.')
GUI_ARGS = {'disk': 'Носитель', 'folder': 'Папки', 'where': ('Куда', 'Семейный архив / Н2 / не копировать / как у родителя'),
            'disk_wide': 'Весь носитель (режим разбора)', 'from_file': ('Из файла', 'путь TAB куда, по строке на папку'),
            'note': 'Комментарий'}


def add_args(p, name):
    p.add_argument('disk')
    p.add_argument('--folder', action='append', help='папка (можно несколько раз)')
    p.add_argument('--where', help='направление (номер или имя), «не копировать» или «как у родителя»')
    p.add_argument('--disk-wide', action='store_true', help='отметить весь носитель (режим разбора)')
    p.add_argument('--from-file', help='TSV: путь TAB отметка (пустой путь - весь носитель)')
    p.add_argument('--note')
    p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')


def run(a):
    cmd_mark(a)
