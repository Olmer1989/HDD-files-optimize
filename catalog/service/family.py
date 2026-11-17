"""Этап 13: 45 и 77 - два направления (переход данных; решение владельца 16.11.2026, вариант Б).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import append_rows, backup, db, Refused, TableLock
from .directions_v3 import _ensure_directions, _read_snapshot, direction_preview, directions
from .direction_edit import direction_usage


# ---------- этап 13: 45 и 77 - два направления (переход данных; решение владельца 16.11.2026, вариант Б) ----------
FAMILY_OLD = 'Семейный архив'
FAMILY_45, FAMILY_77 = 'Семейный архив 45', 'Семейный архив 77'


def family_split_preview(dirs=None, root=None, c=None):
    """Переход данных: Н1 «Семейный архив» (HDD45 + HDD77) -> Н1 «Семейный архив 45» (HDD45) и новое Н7 «Семейный архив
    77» (HDD77). Отметки Н1 остаются за Н1 (они хранят номер), прежнее имя «Семейный архив» записывается в прежние
    имена Н1 (старые «раздел: Семейный архив» - тоже Н1). Таблица только дописывается. Повтор после частичной записи
    продолжает (Н1 уже без 77, Н7 нет - дописывается только Н7). Ничего не пишет. -> dict(fields, lines)."""
    import dataclasses
    dirs = dict(directions() if dirs is None else dirs)
    n1 = dirs.get('Н1')
    if n1 is None:
        raise Refused('Нет направления Н1 - переходить не из чего.')
    lines, fields = [], []
    old = set(n1.disks) == {'HDD45', 'HDD77'} and n1.name == FAMILY_OLD
    half = n1.disks == ('HDD45',) and n1.name == FAMILY_45
    holder = hb.direction_of_disk(dirs, 'HDD77')
    if half and holder is not None:
        raise Refused(f'Переход уже сделан: Н1 «{n1.name}» (HDD45), {holder.num} «{holder.name}» (HDD77).')
    if not (old or half):
        raise Refused(f'Н1 сейчас «{n1.name}», диски {", ".join(n1.disks) or "не назначены"}: ожидалось «{FAMILY_OLD}» '
                      'на HDD45 и HDD77 (или уже «Семейный архив 45» на HDD45). Ничего не делаю - решите вручную.')
    c = c or db()
    if old:
        pv = direction_preview(num='Н1', name=FAMILY_45, disks=['HDD45'], kind=n1.kind, dirs=dirs, c=c,
                               note='копия 1 из 2: вторая - Н7 «Семейный архив 77»')
        nd = pv['direction']
        dirs['Н1'] = nd
        fields.append(pv['fields'])
        lines.append(f'Н1: «{n1.name}» (HDD45, HDD77) -> «{nd.name}» (HDD45); прежнее имя «{n1.name}» сохраняется '
                     f'(старые отметки «раздел: {n1.name}» - тоже Н1). Папка на носителе после переноса: «{nd.folder()}».')
    pv = direction_preview(name=FAMILY_77, disks=['HDD77'], kind=n1.kind, dirs=dirs, c=c,
                           note='копия 2 из 2: первая - Н1 «Семейный архив 45»')
    nd = pv['direction']
    if nd.num != 'Н7':
        raise Refused(f'Новое направление получило бы номер {nd.num}, а не Н7 (номера заняты иначе, чем ожидалось). '
                      'Ничего не делаю - решите вручную.')
    if n1.desc:
        nd = dataclasses.replace(nd, desc=n1.desc)
    fields.append(hb.direction_row(nd))
    lines.append(f'Н7 (новое): «{nd.name}» (HDD77), что копировать - как у Н1 ({nd.kind}). Папка на носителе после '
                 f'переноса: «{nd.folder()}»; после второй копии - «{hb.copied_join([hb.copied_tail(FAMILY_45, ["HDD45"]), hb.copied_tail(FAMILY_77, ["HDD77"])])}».')
    use = direction_usage('Н1', dirs, root)
    marks = use['marks']
    lines.append('Отметки папок Н1 остаются за Н1 (то есть пойдут только на 45): ' +
                 ('; '.join(f'{d}: {n}' for d, n in sorted(marks.items())) if marks else 'отметок Н1 нет') + '.')
    both = [t for t in use['tasks'] if set(t['disks']) >= {'HDD45', 'HDD77'}]
    if both:
        lines.append(f'Задания, созданные раньше на 45 и 77 ({len(both)}): остаются как есть - их перенос по-прежнему '
                     'ждёт копий на обоих дисках и идёт в «Скопировано на Семейный архив (45 и 77)»: '
                     + '; '.join(t['name'] for t in both[:5]) + ('…' if len(both) > 5 else '') + '.')
    else:
        lines.append('Заданий на 45 и 77 прежнего вида нет.')
    lines.append('Будет дописано в «направления.tsv» строк: ' + str(len(fields)) + ' (старые строки не меняются; копия '
                 'таблицы до записи - в «_БАЗА\\архив таблиц»).')
    return dict(fields=fields, lines=lines)


def family_split():
    """Запись перехода (family_split_preview) под замком таблиц: все проверки заново, копия таблицы, одна запись."""
    with TableLock():
        snap = _read_snapshot()
        pv = family_split_preview(hb.parse_directions(snap['directions']))
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_rows(hb.DIRECTIONS, pv['fields'])
    return pv
