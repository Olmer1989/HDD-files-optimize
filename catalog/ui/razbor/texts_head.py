"""Тексты верхней плашки и строк носителя / диска назначения (без Qt): «Диск назначения: …», места, режимы.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import api as hb

import disk_ui
from directions_look import show_num                 # «Н2» на экране - «А2» (18.11.2026)
from disk_ui import tb_text   # перенесена в disk_ui (17.11.2026); имя здесь - для прежних импортов

from .common import EXC_BG, EXC_FG, JOURNAL, NONE_BG, PALE, SEL_BG
from .texts_cell import BLUE, EVERY, EXCEPT, GRAY, GREEN, LINK, ONLY, ORANGE, RED, esc, files_word, gb, num, vol


def place(row, disk=''):
    """«F: Монтаж - SN850»; неподключённый - «Монтаж - SN850 (не подключён)»; метки тома нет - номер носителя.
    Модель и объём (устройство подключения) не показываются нигде (решение владельца 16.11.2026, disk_ui.disk_name)."""
    r = disk_ui.as_row(row) if row else {'disk': disk, 'label': '', 'letter': ''}
    name = disk_ui.disk_name(r) or r.get('disk') or disk
    return f'{r["letter"]} {name}' if r.get('letter') else f'{name} (не подключён)'


def carrier_text(row):
    """Строка списка «Выберите носитель»: «F: Монтаж - SN850 — HDD09 (по журналу сканирования дисков)»."""
    r = disk_ui.as_row(row)
    if not disk_ui.disk_name(r):                          # метки нет - номер один раз
        return f'{r["letter"] + " " if r.get("letter") else ""}{r["disk"]}' +             ('' if r.get('letter') else ' (не подключён)') + f' ({JOURNAL})'
    return f'{place(r)} — {r["disk"]} ({JOURNAL})'


def hdds(d):
    return ' и '.join(d.disks)


def dest_places(d, rows):
    by = {r['disk']: r for r in rows}
    return ' и '.join(place(by.get(x), x) for x in d.disks)


COPIES_WORDS = {2: 'две копии', 3: 'три копии', 4: 'четыре копии'}


def copies_word(n):
    return COPIES_WORDS.get(n, f'{n} копий')


def letters(d, rows):
    """«H: и S:» - буквы дисков направления; неподключённый - номером («H: и HDD77»)."""
    by = {r['disk']: r for r in rows}
    return ' и '.join((by.get(x) or {}).get('letter') or x for x in d.disks)


def dest_text(d, rows):
    """Строка списка «Диск назначения»: «I: My Book — Н3 Фильмы — HDD55 (по журналу сканирования дисков)»; у
    направления с несколькими дисками - коротко «Н1 Семейный архив — H: и S: (две копии)» (этап 12)."""
    if len(d.disks) > 1:
        return f'{show_num(d.num)} {d.name} — {letters(d, rows)} ({copies_word(len(d.disks))})'
    return f'{dest_places(d, rows)} — {show_num(d.num)} {d.name} — {hdds(d)} ({JOURNAL})'


def dest_html(d, rows):
    """То же с именем направления оранжевым (как отмеченные в «Обзоре»)."""
    name = f'<span style="color:{ORANGE}"><b>{esc(show_num(d.num))} {esc(d.name)}</b></span>'
    if len(d.disks) > 1:
        return f'{name} — {esc(letters(d, rows))} <span style="color:{GRAY}">({copies_word(len(d.disks))})</span>'
    return (f'{esc(dest_places(d, rows))} — {name} — '
            f'{esc(hdds(d))} <span style="color:{GRAY}">({JOURNAL})</span>')


OFF_PILL = (f'<span style="background:#ffe0b2; color:{ORANGE}; font-size:11pt">&nbsp;не подключён&nbsp;</span>')


def free_of(x, rows, space=None):
    """Свободно на диске назначения, байт: по последнему расчёту места (space) или по service.disks (free_gib)."""
    if space and x in space:
        return space[x][1]
    r = next((r for r in rows if r['disk'] == x), None)
    return r['free_gib'] * hb.GIB if r and 'free_gib' in r else None


def total_of(x, rows, space=None):
    """Объём тома диска назначения, байт: по расчёту места (space: буква, свободно, объём, кластер) или по service.disks
    (total_bytes подключённого). Не подключён - None."""
    if space and x in space and len(space[x]) > 2:
        return space[x][2]
    r = next((r for r in rows if r['disk'] == x), None)
    return r.get('total_bytes') if r else None


def disk_head(x, rows, space=None):
    """«H: Бэкап фото и видео — HDD45, 16 ТБ · свободно 3 210,5 ГБ» (+ плашка «не подключён»)."""
    r = next((r for r in rows if r['disk'] == x), None) or {'disk': x, 'label': '', 'letter': ''}
    name = disk_ui.disk_place(r) or x
    line = esc(name) + (f' — {esc(x)}' if name != x else '')
    size = tb_text(total_of(x, rows, space))
    if size:
        line += f', {esc(size)}'
    b = free_of(x, rows, space)
    if b is not None:
        line += f' <span style="color:#33691e">· свободно {gb(b)} ГБ</span>'
    if not r.get('letter'):
        line += ' ' + OFF_PILL
    return line


def head_html(d, rows, space=None, others=()):
    """Зелёная плашка (этап 16, решение владельца): «Диск назначения: H: Бэкап фото и видео — HDD45, 16 ТБ · свободно
    …» - название диска (метка тома), номер, объём, свободно - вместо имени направления (оно - в ячейке справа).
    Направление на нескольких дисках - строка на каждый диск. others - другие направления, отмеченные в «Обзоре»."""
    if d is None:
        return (f'<span style="color:{ORANGE}">Диска назначения нет: ни у одного направления не назначен диск.</span> '
                '<span style="font-size:10pt; font-weight:normal">Назначьте диск на вкладке «Назначить Архивный диск» → «Направления».</span>')
    if len(d.disks) > 1:
        h = (f'Диск назначения — {copies_word(len(d.disks))}:<br>'
             '<span style="font-size:12pt">' + '<br>'.join(disk_head(x, rows, space) for x in d.disks) + '</span>')
    else:
        h = 'Диск назначения: ' + disk_head(d.disks[0], rows, space)
    if others:
        h += ('<br><span style="font-size:9pt; font-weight:normal; color:#37474f">На вкладке «Назначить Архивный диск» отмечено ещё: '
              + esc(', '.join(f'{show_num(o.num)} {o.name}' for o in others)) +
              ' — здесь используется первое по номеру; сменить диск — на вкладке «Назначить Архивный диск».</span>')
    return h


MODE_NOTE = {ONLY: 'Копируются только папки с галочкой — остальные остаются на носителе.',
             EVERY: 'Весь носитель копируется на этот диск. Папки, отмеченные для другого диска (метка «А2»), остаются '
                    'за ним.',
             EXCEPT: 'Весь носитель копируется на этот диск, кроме папок с галочкой — они подсвечены красным и не '
                     'копируются.'}


NO_SPACE = 'Подключите диск, чтобы проверить свободное место. Отмечать папки можно и без него.'


def dest_info_html(d, rows, space=None):
    """Строка под «Диском назначения»: «Свободно 421 ГБ» или «Подключите диск, чтобы проверить свободное место…»."""
    if d is None:
        return ''
    if len(d.disks) > 1:                                  # этап 12: по строке на каждый диск
        by = {r['disk']: r for r in rows}
        out = []
        for i, x in enumerate(d.disks, 1):
            b = free_of(x, rows, space)
            head = f'Копия {i} — {esc(disk_ui.disk_place(by.get(x) or x))} ({esc(x)}): '
            if b is None:
                out.append(f'<span style="color:{ORANGE}">{head}подключите диск, чтобы проверить свободное место.</span>')
            else:
                out.append(f'<span style="color:{GREEN}">{head}свободно {gb(b)} ГБ</span>')
        if any(free_of(x, rows, space) is None for x in d.disks):
            out.append('Отмечать папки можно и без них.')
        return '<br>'.join(out)
    free, off = [], []
    for x in d.disks:
        b = free_of(x, rows, space)
        if b is None:
            off.append(x)
        else:
            free.append(f'{x} — {gb(b)} ГБ' if len(d.disks) > 1 else f'{gb(b)} ГБ')
    out = []
    if free:
        out.append(f'<span style="color:{GREEN}">Свободно {esc(", ".join(free))}</span>')
    if off:
        out.append(f'<span style="color:{ORANGE}">' + (f'{esc(", ".join(off))}: ' if len(d.disks) > 1 else '')
                   + NO_SPACE + '</span>')
    return ' · '.join(out)


def legend_html(mode):
    """Подпись цветов под деревом - по режиму: в «Все, кроме выбранных» зелёного нет, выбранные - красным."""
    if mode == EXCEPT:
        first = (f'<span style="background:{EXC_BG}; color:{EXC_FG}">&nbsp;красный фон&nbsp;</span> — папка с '
                 'галочкой НЕ копируется; ')
    else:
        first = f'<span style="background:{SEL_BG}">&nbsp;зелёный фон&nbsp;</span> — папка выбрана; '
    return (first + f'<span style="color:{PALE}">бледный текст и серая галочка</span> — вместе с родительской папкой; '
            f'<span style="color:{GRAY}">А2</span> — папка отмечена для другого диска; '
            f'<i style="color:{BLUE}">• курсив</i> — сохраняется (отметки сохраняются сразу).'
            + (' Галочка у строки носителя — выбрать все папки.' if mode == ONLY else ''))


def short_place(row, disk):
    """«I: My Book» для заголовка ячейки: буква и метка тома без марки; неподключённый - «My Book (не подключён)»."""
    if not row:
        return f'{disk} (не подключён)'
    title = disk_ui.disk_title(row) or disk
    title = title.rsplit(' (', 1)[0] if title.endswith(')') else title
    return f'{row["letter"]} {title}' if row.get('letter') else f'{title} (не подключён)'


def kinds_words(d):
    """Что копирует направление словами (18.11.2026, решение владельца): каждый тип в кавычках через запятую -
    «фото», «видео», «документы рядом с ними»; «Все файлы» - «все, кроме программ и временных»."""
    if d.cats == hb.ALL_CATS and not d.docs_near:
        return 'все, кроме программ и временных'
    w = [('документы рядом с ними' if c == hb.CAT_DOC and d.docs_near else c) for c in hb.COPY_CATS if c in d.cats]
    if not w:
        return 'ничего (набор «что копировать» не распознан)'
    return ', '.join(f'«{x}»' for x in w)


def kinds_line(d):
    """«Типы файлов: «фото», «видео» — согласно настройкам А1» (строка «нет на H:» и строка «без хеша» ячейки)."""
    return f'Типы файлов: {kinds_words(d)} — согласно настройкам {show_num(d.num)}'


def archive_where(d, rows, carrier=None, space=None):
    """«Архивном диске А1 (H: «Бэкап фото и видео», 16 ТБ)» для строки «без хеша» ячейки (18.11.2026): буква (не
    подключён - код диска), метка тома в кавычках (меток нет - без неё), объём (нет данных - без него); дисков
    направления несколько - «Архивных дисках А1 (H: …, 16 ТБ и HDD77 …)». Сам носитель не считается."""
    by = {r['disk']: r for r in rows}
    parts = []
    for x in [x for x in d.disks if x != carrier] or d.disks:
        r = disk_ui.as_row(by.get(x) or {'disk': x, 'label': '', 'letter': ''})
        name = disk_ui.disk_name(r)
        s = (r.get('letter') or x) + (f' «{name}»' if name and name != disk_ui.kind_word(x) else '')
        size = tb_text(total_of(x, rows, space))
        parts.append(s + (f', {size}' if size else ''))
    word = 'Архивном диске' if len(parts) == 1 else 'Архивных дисках'
    return f'{word} {show_num(d.num)} ({" и ".join(parts)})'


def tree_legend(label):
    """Пояснение цветов над деревом (18.11.2026, решение владельца): [(цвет фона, текст)] - друг под другом."""
    return [(SEL_BG, f'зелёный — папка отмечена, из неё есть что копировать на {label}'),
            (NONE_BG, f'розовый — папка отмечена, но копировать из неё нечего: всё уже есть на {label} или нет файлов '
                      'выбранных типов')]


def not_on_target_html(carrier, label, d, v, x):
    """Строка над «Что копировать с носителя» (18.11.2026, решение владельца): «Из содержимого HDD09 нет на H:
    1 234 файла (15,9 ГБ)», мелко - какие типы; зелёным - в отмеченных (= «Копировать на H:» ячейки), красным - в неотмеченных и
    «Показать по папкам» (ссылка nt:<диск>), серым - без хеша в неотмеченных (отдельно: проверить нельзя).
    v - Model.not_on_disk(...)[x]; None - «Уже есть» ещё считается."""
    head = f'Из содержимого {esc(carrier)} нет на {esc(label)}'
    kinds = f'<br><span style="color:{GRAY}; font-size:8pt">{esc(kinds_line(d))}</span>'
    if v is None:
        return f'<b>{head}:</b> <span style="color:{GRAY}">считаю…</span>{kinds}'
    mk, mn, un, nh = v['marked'], v['marked_nohash'], v['unmarked'], v['nohash']
    if not (mk[0] or un[0] or nh[0]):
        return f'<span style="color:{GREEN}"><b>Всё нужное с {esc(carrier)} уже есть на {esc(label)}</b></span>{kinds}'
    h = [f'<b>{head} {files_word(mk[0] + un[0])} ({vol(mk[1] + un[1])})</b>', kinds,
         f'<br><span style="color:{GREEN}">в отмеченных папках {files_word(mk[0])}, {vol(mk[1])} — будут скопированы на '
         f'{esc(label)}' + (f' (из них без хеша {num(mn[0])} — сначала «Посчитать хеш»)' if mn[0] else '') + '</span>',
         f'<br><span style="color:{RED}">в неотмеченных папках {files_word(un[0])}, {vol(un[1])} — не попадут на '
         f'{esc(label)}</span> <a href="nt:{esc(x)}" style="{LINK}">Показать по папкам</a>']
    if nh[0]:
        h.append(f'<br><span style="color:{GRAY}">ещё без хеша {files_word(nh[0])}, {vol(nh[1])} в неотмеченных папках — '
                 f'есть ли они на {esc(label)}, проверить нельзя</span>')
    return ''.join(h)
