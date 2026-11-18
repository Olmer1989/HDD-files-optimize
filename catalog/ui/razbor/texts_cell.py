"""Тексты ячейки «Копировать на диск …» страницы «Разбор носителя» (этап 18; вынесено из razbor_page.py по правилу
владельца «файл .py - не больше 500 строк»): числа ячейки по плану ядра, строки таблицы, плашка итога, блок диска
направления на нескольких дисках; мелкие помощники текста (числа, ГБ, склонения). Окно (Qt) не нужно; razbor_page
импортирует отсюда, не наоборот."""
import html

from hb_core import api as hb
from hb_core import razbor as rz

ONLY, EVERY, EXCEPT = 'only', 'all', 'except'             # режимы для диска назначения
GRAY, BLUE, BLUE2, ORANGE, RED, GREEN = '#757575', '#1565c0', '#5c6bc0', '#e65100', '#c62828', '#2e7d32'
LINK = 'color:#1565c0'
SKIP_TEXT = 'Не копируются (другой тип)'                  # макет владельца 18.11.2026 (прежде длинная строка)
PLATE = {'red': ('#ffebee', RED), 'green': ('#e8f5e9', GREEN), 'orange': ('#fff3e0', ORANGE)}


def num(n):
    return f'{n or 0:,}'.replace(',', ' ')


def gb(b):
    return f'{(b or 0) / hb.GIB:,.1f}'.replace(',', ' ').replace('.', ',')


def esc(x):
    return html.escape(str(x))


def plural(n, one, few, many):
    n = abs(n or 0)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def folders_word(n):
    return f'{num(n)} {plural(n, "папка", "папки", "папок")}'


def files_word(n):
    return f'{num(n)} {plural(n, "файл", "файла", "файлов")}'


def list_link(kind, x=''):
    """Ссылка «Показать» (этапы 16, 18) - окно «Список файлов»: copy:<диск> / have / type."""
    return f' <a href="{kind}:{esc(x)}" style="{LINK}">Показать</a>'


def vol(b):
    """Объём для ячейки (этап 18): от 0,1 ГБ - в ГБ, меньше - в МБ, совсем малое - в КБ (ГБ, МБ - как везде в окне,
    по 1024)."""
    b = b or 0
    if not b:
        return '0 ГБ'
    if b >= 0.1 * hb.GIB:
        return f'{gb(b)} ГБ'
    if b >= 0.1 * 1024 ** 2:
        return f'{b / 1024 ** 2:,.1f} МБ'.replace(',', ' ').replace('.', ',')
    return f'{max(1, round(b / 1024))} КБ'


def cell_numbers(d, P):
    """Числа ячейки (этап 18) по плану ядра: копировать, уже есть, не копируются по типу (с мусором отмеченных папок) -
    каждый файл ровно в одной; отмечено = их сумма. -> dict(copy, have, skip, total) - (файлов, байт)."""
    cp = tuple(P.part_a.get((rz.O_COPY, d.num), (0, 0)))
    hv = tuple(P.part_a.get((rz.O_HAVE, d.num), (0, 0)))
    tp = P.part_a.get((rz.O_TYPE, d.num), (0, 0))
    jk = P.junk_dir.get(d.num, (0, 0)) if hasattr(P, 'junk_dir') else (0, 0)
    skip = (tp[0] + jk[0], tp[1] + jk[1])
    return dict(copy=cp, have=hv, skip=skip, total=(cp[0] + hv[0] + skip[0], cp[1] + hv[1] + skip[1]))


def row_html(text, v, link='', color=None, bold=False):
    """Строка таблицы ячейки: подпись · файлов · объём · «Показать» (только у ненулевой)."""
    style = f' style="color:{color}"' if color else ''
    t = f'<b>{esc(text)}</b>' if bold else esc(text)
    return (f'<tr><td{style}>{t}</td><td align="right"{style}>{files_word(v[0])}</td>'
            f'<td align="right"{style}><b>{vol(v[1])}</b></td><td>{link if v[0] else ""}</td></tr>')


def plate_html(label, c, n_copy, n_have, n_skip):
    """Плашка итога по диску (этап 18, правки владельца): «Копировать нечего: все файлы выбранного в настройках типа уже
    есть на H:» - красная (цвет нуля в строке «Копировать»); «Поместится: нужно X, свободно Y» - зелёная; «Не
    помещается…» - красная; «Место не проверено: H: не подключён» - оранжевая. -> (html, состояние)."""
    if not n_copy:
        if n_have:
            text, kind = f'Копировать нечего: все файлы выбранного в настройках типа уже есть на {label}', 'red'
        elif n_skip:
            text, kind = 'Копировать нечего: в отмеченных папках нет файлов выбранного в настройках типа', 'red'
        else:
            return '', 'none'
        state = 'none'
    elif c['state'] == 'short':
        text, kind, state = (f'Не помещается: нужно {vol(c["need"] + c["reserve"])} (с запасом {vol(c["reserve"])}), '
                             f'свободно {vol(c["free"])}'), 'red', 'short'
    elif c['state'] == 'unknown':
        text, kind, state = f'Место не проверено: {label} не подключён', 'orange', 'unknown'
    elif c['state'] == 'none':
        return '', 'none'
    else:
        text, kind, state = (f'Поместится: нужно {vol(c["need"] + c["reserve"])}, свободно {vol(c["free"])}', 'green',
                             'ok')
    bg, fg = PLATE[kind]
    q = (f'<br><span style="color:{GRAY}; font-size:8pt">в очереди на этот диск ещё {num(c["queued"][0])} незапущенных '
         f'заданий других носителей, {vol(c["queued"][1])} (учтено)</span>' if n_copy and c.get('queued', [0])[0] else '')
    return (f'<table width="100%" cellpadding="5" cellspacing="0"><tr><td bgcolor="{bg}"><span style="color:{fg}">'
            f'<b>{esc(text)}</b></span>{q}</td></tr></table>'), state


def copy_color(n):
    return GREEN if n else RED                           # правка владельца: 0 - красным, больше 0 - зелёным


def dest_cell_html(d, P, cap, mode, sel, exc, place_fn, split=False):
    """Ячейка «Копировать на диск …» (этап 18, макет владельца): «Отмечено: N папок · M файлов · X» - ВСЕ файлы
    отмеченных папок (копировать + уже есть + не копируются по типу, из плана ядра: каждый файл в одной строке);
    таблица из трёх строк (сумма = «Отмечено»); плашка итога. split=True (направление на нескольких дисках) - общее
    «Отмечено» и общая серая строка; «Копировать»/«Уже есть» и плашка - в блоках дисков (disk_block_html). place_fn(x) -
    короткое имя диска («H:» или «HDD45»). -> (html, состояние 'short' / 'unknown' / 'ok' / 'none')."""
    if P is None:
        return '', 'normal'                              # до первого итога - только плашка «Идёт пересчёт…»
    v = cell_numbers(d, P)
    total = v['total']
    if mode == EVERY:
        what = 'Отмечено: весь носитель'
    elif mode == EXCEPT:
        what = 'Отмечено: весь носитель' + (f', кроме {num(exc)} {plural(exc, "папки", "папок", "папок")}' if exc else '')
    else:
        what = f'Отмечено {folders_word(sel)}'
    if mode == ONLY and not sel and not total[0]:
        return (f'<span style="font-size:12pt"><b>Ничего не отмечено — поставьте галочки у папок</b></span><br>'
                f'<span style="color:{GRAY}">или перетащите папки сюда.</span>'), 'none'
    h = [f'<span style="font-size:12pt"><b>{what} · {files_word(total[0])} · {vol(total[1])}</b></span>',
         '<table cellpadding="3" cellspacing="0" width="100%">']
    state = 'none'
    if not split:
        x = d.disks[0]
        label = place_fn(x)
        h.append(row_html(f'Копировать на {label}', v['copy'], list_link('copy', x), copy_color(v['copy'][0]), True))
        h.append(row_html(f'Уже есть на {label}', v['have'], list_link('have')))
    h.append(row_html(SKIP_TEXT, v['skip'], list_link('type'), GRAY))
    h.append('</table>')
    if not split:
        c = cap.get(x) or dict(state='none', files=0, bytes=0, free=None, queued=[0, 0, 0])
        if P is not None and x == P.disk:
            h.append(f'<span style="color:{GRAY}">Это сам носитель — на него не копируется.</span>')
        else:
            plate, state = plate_html(label, c, v['copy'][0], v['have'][0], v['skip'][0])
            h.append(plate)
    else:
        for x in d.disks:
            c = cap.get(x) or dict(state='none')
            if c['state'] == 'short':
                state = 'short'
            elif c['state'] == 'unknown' and state != 'short':
                state = 'unknown'
            elif c['state'] == 'ok' and state == 'none':
                state = 'ok'
    return ''.join(h), state


def disk_block_html(i, x, c, P, total, have, name, label=None, have_all=None, n_skip=0):
    """Блок одного диска направления на нескольких дисках (этапы 12, 18): «Копия 1 — H: Бэкап фото и видео (HDD45)»;
    «Уже есть на H:» - Model.have_on_disk (тот же SHA-256 подтверждён на этом диске); «Копировать на H:» = (копировать +
    уже есть направления) - уже есть на H: (total - их сумма); своя плашка. have=None - ещё считается. have_all -
    «уже есть» на всех дисках направления: «Показать» у «Уже есть» - только когда список совпадает с числом. n_skip -
    файлов другого типа направления (общая серая строка): для плашки «Копировать нечего…», когда больше ничего нет.
    -> (html, состояние блока 'short' / 'unknown' / 'ok' / 'none')."""
    label = label or x
    h = [f'<span style="font-size:11pt"><b>Копия {i} — {esc(name)} ({esc(x)})</b></span>']
    if P is not None and x == P.disk:
        h.append(f'<br><span style="color:{GRAY}">Это сам носитель — на него не копируется.</span>')
        return ''.join(h), 'none'
    if have is None:
        h.append(f'<br><span style="color:{GRAY}">Уже есть на {esc(label)}: считаю…</span>')
        return ''.join(h), c.get('state', 'none') if c.get('state') != 'ok' else 'ok'
    cp = (total[0] - have[0], total[1] - have[1])
    h.append('<table cellpadding="3" cellspacing="0" width="100%">')
    h.append(row_html(f'Копировать на {label}', cp, list_link('copy', x), copy_color(cp[0]), True))
    h.append(row_html(f'Уже есть на {label}', have, list_link('have') if have_all == have[0] else ''))
    h.append('</table>')
    plate, state = plate_html(label, c, cp[0], have[0], n_skip)
    h.append(plate)
    return ''.join(h), state


STAY_NONE = (rz.O_SKIP, rz.O_UNSET, rz.O_NONE, rz.O_JUNK)     # не копируется никуда (общие категории плана)


STAY_DIR = (rz.O_TYPE, rz.O_NODISK)                            # ... и по направлениям: не по типу, диск не назначен


def stay_numbers(P):
    """Сколько остаётся на носителе (не копируется никуда) по плану ядра: (файлов, байт). Уже перенесённое и идущее в
    другие направления (копировать / уже есть) сюда не входит; каждый файл в плане ровно в одной категории."""
    n = b = 0
    for (o, _num), v in P.part_a.items():
        if o in STAY_NONE or o in STAY_DIR:
            n += v[0]
            b += v[1]
    return n, b


# «Перед копированием» ячейки (макет владельца 18.11.2026): шаг 1 - хеш на носителе (обязательно), шаг 2 - хеш у
# файлов на диске назначения с тем же именем и размером (по желанию); «Что копировать» - плашки типов и «Изменить…».
PREP_TITLE = 'Перед копированием'
WAIT_STEP1 = 'станет доступно после шага 1'
EDIT_TEXT = 'Изменить…'
SMALL = f'color:{GRAY}; font-size:8pt'


def kinds_note(a):
    """Мелкая строка под плашками типов: «Настройка А1 — общая для всех носителей; …»."""
    return f'Настройка {a} — общая для всех носителей; уже созданные задания не меняются.'


def step1_html(res, fast, carrier, copy_n):
    """Шаг 1 (обязательный): хеш у файлов для копирования на носителе. res - service.nohash_check (None - ещё
    считается; {'error': текст} - не посчитано); fast - быстрый признак итога (0 - без хеша точно нет); carrier - носитель
    («HDD09»); copy_n - файлов «копировать». -> html."""
    if res is not None and 'error' in res:
        return f'<span style="color:{ORANGE}"><b>1. Хеш: не посчитано ({esc(res["error"])}).</b> Нажмите «Обновить».</span>'
    if res is None and fast:
        return f'<span style="color:{GRAY}">○ 1. Хеш: идёт проверка — у всех ли файлов для копирования он есть…</span>'
    if res is None or not res['n']:
        return f'<span style="color:{GREEN}"><b>✓ 1. Хеш есть у всех файлов для копирования</b></span>'
    n, k = res['n'], max(res['n'], copy_n)
    h = (f'<span style="color:{RED}"><b>✖</b></span> <b>1. Посчитать хеш на {esc(carrier)} — '
         f'<span style="color:{RED}">обязательно</span></b><br>'
         f'У {num(n)} из {num(k)} {plural(k, "файла", "файлов", "файлов")} для копирования нет хеша. Без него копию '
         f'нельзя проверить. <a href="nh-list:" style="{LINK}">Какие файлы</a>')
    if res.get('root'):
        h += (f'<br><span style="{SMALL}">Из них {files_word(res["root"])} прямо в корне носителя — пересканирование '
              'папок корень не берёт: хеш им даст только полное сканирование носителя.</span>')
    return h


def step2_html(no, x, label, k):
    """Шаг no (по желанию) для диска назначения x («H:» - label): k - nohash_check()['copies'][x]. -> html."""
    n = k['k']
    h = (f'<span style="color:{GRAY}">○</span> <b>{no}. Посчитать хеш у файлов на {esc(label)} с тем же именем и '
         f'размером — <span style="color:{GRAY}">по желанию</span></b><br>'
         f'На {esc(label)} {plural(n, "лежит", "лежат", "лежат")} {files_word(n)} с теми же именами и размерами, что у '
         'файлов для копирования, но без хеша. Если посчитать их хеш, часть файлов может оказаться «уже есть» и не '
         'скопируется второй раз.')
    if k.get('sample'):
        h += f' <a href="nh-clist:{esc(x)}" style="{LINK}">Какие файлы</a>'
    if k.get('root'):
        h += f'<br><span style="{SMALL}">В корне диска {files_word(k["root"])} — только полным сканированием.</span>'
    return h


def unread_html(res):
    """Строка «Не прочитаны при пересканировании» (под шагами) или ''."""
    if not (res and res.get('unread')):
        return ''
    return (f'<span style="color:{ORANGE}">Не прочитаны при пересканировании: {files_word(len(res["unread"]))} — не '
            f'копируются (остальные копируются)</span>{list_link("nh-unread")}')
