"""Команды directions, direction-add, direction-edit, directions-default: направления разбора (логика v3, 15.11.2026).

Направление - номер (Н1…), имя, прежние имена, диски назначения, что копировать. Таблица «_БАЗА\\направления.tsv»;
пишет её только service.py (замок, копия в архив, предпросмотр). Без --yes - только предпросмотр.
"""
from hb_core import paths
from hb_core.util import out
from hb_core.report import table


def _write(preview, write, a):
    import service as sv
    try:
        pv = write() if a.yes else preview()
    except sv.Refused as e:
        out('НЕ ЗАПИСАНО: ' + str(e))
        raise SystemExit(1)
    for x in pv['lines']:
        out(x)
    if a.yes:
        out(f'Записано в «{paths.DIRECTIONS.name}» (строка {pv["line"]}). Копия таблицы до записи - в «_БАЗА\\архив таблиц».')
    else:
        out('Это предпросмотр, ничего не записано. Записать: та же команда с --yes')


def cmd_directions(a):
    import service as sv
    dirs = sv.directions()
    if not dirs:
        out(f'Направлений ещё нет ({paths.DIRECTIONS.name}). Завести по ответам владельца: directions-default --yes')
        return
    table(('номер', 'направление', 'диски', 'что копировать', 'папка на носителе', 'прежние имена'),
          [(d.num, d.name, ', '.join(d.disks) or 'не назначен', d.kind, d.folder() or '-', ', '.join(d.former))
           for d in dirs.values()], limit=15)


def cmd_direction_add(a):
    import service as sv
    kw = dict(name=a.name, disks=a.to or [], kind=a.what, former=a.former or ())
    _write(lambda: sv.direction_preview(note=a.note or '', **kw), lambda: sv.add_direction(note=a.note or '', **kw), a)


def cmd_direction_edit(a):
    import service as sv
    kw = dict(num=a.direction, name=a.name, disks=a.to if a.to else None, add_disks=a.add_disk or (), kind=a.what,
              former=a.former or ())
    _write(lambda: sv.direction_preview(note=a.note, **kw), lambda: sv.add_direction(note=a.note, **kw), a)


def cmd_directions_default(a):
    import service as sv
    _write(lambda: sv.directions_batch_preview(sv.DEFAULT_DIRECTIONS), lambda: sv.add_directions_batch(sv.DEFAULT_DIRECTIONS), a)


def cmd_family_split(a):
    """Этап 13: Н1 «Семейный архив» (45 и 77) -> Н1 «Семейный архив 45» (45) + Н7 «Семейный архив 77» (77)."""
    import service as sv
    _write(sv.family_split_preview, sv.family_split, a)


NAMES = ('directions', 'direction-add', 'direction-edit', 'directions-default', 'family-split')
HELP = {'directions': 'направления разбора: имя, диски, что копировать, папка на носителе',
        'direction-add': 'новое направление разбора (предпросмотр; запись - с --yes)',
        'direction-edit': 'переименовать направление, сменить или добавить диск, что копировать (предпросмотр; --yes)',
        'directions-default': 'завести направления по ответам владельца 15.11.2026 (предпросмотр; --yes)',
        'family-split': 'разделить «Семейный архив» на Н1 «Семейный архив 45» и Н7 «Семейный архив 77» (предпросмотр; --yes)'}
GUI = {'family-split': False}      # разовый переход данных (этап 13) - только из командной строки
# для окна «Архив дисков» (раздел «Команды»); свой экран «Направления» - этап 5а
GUI_GROUP = 'Разбор носителя (v3)'
GUI_ORDER = {'directions': 1, 'direction-add': 5, 'direction-edit': 6, 'directions-default': 7}
GUI_TITLE = {'directions': 'Направления', 'direction-add': 'Добавить направление',
             'direction-edit': 'Изменить направление', 'directions-default': 'Завести направления по умолчанию'}
GUI_HINT = {'directions': 'Куда разбираются носители: «Семейный архив» (45 и 77) и свои диски других направлений.',
            'direction-add': ('Новое направление и его диск. Один диск - одному направлению. Без диска можно: '
                              'папки отмечать можно, задания не создаются.'),
            'direction-edit': ('Переименование (номер и старые отметки сохраняются), смена или добавление диска - только '
                               'для новых заданий.'),
            'directions-default': ('Семейный архив (45 и 77), Работа и Сафари (78), Фильмы (55); без диска - '
                                   'Оцифрованные источники; Саша, Таня, Наташа; Разные.')}
GUI_ARGS = {'directions': {},
            'direction-add': {'name': 'Имя направления', 'to': 'Диски назначения', 'what': 'Что копировать',
                              'former': 'Прежние имена', 'note': 'Комментарий'},
            'direction-edit': {'direction': ('Направление', 'номер или имя, например Н2'), 'name': 'Новое имя',
                               'to': 'Заменить диски на', 'add_disk': 'Добавить диск', 'what': 'Что копировать',
                               'former': 'Добавить прежнее имя', 'note': 'Комментарий'},
            'directions-default': {}}


def add_args(p, name):
    if name == 'direction-add':
        p.add_argument('name', help='имя: до 30 знаков, без \\ / : * ? " < > | ;')
        p.add_argument('--to', nargs='+', default=[], help='диски назначения (можно не указывать - направление без диска)')
        p.add_argument('--what', choices=['фото', 'все'], default='все',
                       help='фото - фото, видео и документы рядом; все - все файлы')
        p.add_argument('--former', action='append', help='прежнее имя (например, старый «раздел: …»)')
        p.add_argument('--note')
        p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')
    elif name == 'direction-edit':
        p.add_argument('direction', help='номер (Н2) или имя направления')
        p.add_argument('--name', help='новое имя (старое станет прежним именем)')
        p.add_argument('--to', nargs='+', default=[], help='заменить диски на эти')
        p.add_argument('--add-disk', action='append', help='добавить диск')
        p.add_argument('--what', choices=['фото', 'все'])
        p.add_argument('--former', action='append', help='добавить прежнее имя')
        p.add_argument('--note')
        p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')
    elif name in ('directions-default', 'family-split'):
        p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')


def run(a):
    {'directions': cmd_directions, 'direction-add': cmd_direction_add, 'direction-edit': cmd_direction_edit,
     'directions-default': cmd_directions_default, 'family-split': cmd_family_split}[a.cmd](a)
