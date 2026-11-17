"""Тексты окна «Начать копирование» (18.11.2026, решение владельца; прежде окно «Подготовить задания»): таблица
отмеченных папок, куда, поместится ли, хеш, примерное время, что уже создано или идёт. Без Qt.

Числа - из того же пробного расчёта, что и прежде (flow_tasks.tasks_check): план по сохранённым отметкам, место по
каждому диску (service.capacity: только то, чего на диске ещё нет), сверка оглавления носителя, состояния уже
созданных заданий набора и средняя скорость прошлых копирований на эти диски (ui/tasks/model_load.tasks_info)."""
from hb_core import razbor as rz

import service as sv
from directions_look import show_num

from .texts_cell import GRAY, GREEN, ORANGE, RED, esc, gb, num, plural

NONE_ROW = '#fde7ea'                                  # строка «копировать нечего» (как фон такой папки в дереве)
WAIT = ('не запускалось', 'прервано')                 # задания набора, которые кнопка запустит вместе с новыми
FOOT = 'Файлы на носителе не трогаются. Окно программы можно закрыть — копирование продолжится.'


def task_sets(val):
    """Задания набора: -> (новые, созданные раньше и ждущие запуска, идущие сейчас)."""
    st = val.get('states') or {}
    old = [s for s in val['specs'] if s.get('exists')]
    return (list(val['new']), [s for s in old if st.get(s['name']) in WAIT],
            [s for s in old if st.get(s['name']) == 'идёт'])


def blocked(val):
    toc = val.get('toc')
    return toc is not None and (not toc['connected'] or bool(toc['problems']))


def start_mode(val):
    """'blocked' - сверка оглавления не прошла; 'running' - задания набора уже идут; 'none' - запускать нечего;
    'start' - кнопка «Подтвердить и начать копирование»."""
    new, wait, run = task_sets(val)
    if blocked(val):
        return 'blocked'
    if run:
        return 'running'
    return 'start' if new or wait else 'none'


def minutes_text(sec):
    m = max(1, round(sec / 60))
    return f'{m} мин' if m < 60 else f'{m // 60} ч {m % 60} мин'


def time_text(val, label):
    """«Примерно N мин (по скорости прошлых копирований на H:)» - байты к записи на каждый диск / средняя скорость
    прошлых завершённых копирований на него; истории нет хотя бы у одного диска - время будет видно после начала."""
    new, wait, _run = task_sets(val)
    per = {}
    for s in new + wait:
        for x in s['targets']:
            per[x] = per.get(x, 0) + s['bytes']
    speed = val.get('speed') or {}
    per = {x: b for x, b in per.items() if b > 0}
    if not per or any(not speed.get(x) for x in per):
        return f'<span style="color:{GRAY}">Время будет видно после начала копирования.</span>'
    sec = sum(b / speed[x] for x, b in per.items())
    return (f'Примерно {minutes_text(sec)} <span style="color:{GRAY}">(по скорости прошлых копирований на '
            f'{esc(" и ".join(label(x) for x in sorted(per)))})</span>')


def folders_table(val):
    """Отмеченные папки выбранных направлений: папка · копировать файлов · ГБ · уже есть; «копировать нечего» -
    розовая строка; «Итого»."""
    P = val['res']['plan']
    nums = [n for n in (val.get('nums') or P.dirs) if n not in val['short']]
    groups = sorted((g for g in P.groups.values() if g['num'] in nums and g['disks']),
                    key=lambda g: (g['num'] or '', str(g['folder'])))
    if not groups:
        return ''
    h = ['<table cellpadding="4" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
         '<tr><th align="left">Папка</th><th>Копировать файлов</th><th>ГБ</th><th>Уже есть</th></tr>']
    tot = [0, 0, 0]
    for g in groups:
        name = rz.ROOT_TITLE if g['folder'] is rz.ROOT_GROUP else g['folder']
        n, b, have = g['copy'][0], g['copy'][1], g['have'][0]
        tot[0], tot[1], tot[2] = tot[0] + n, tot[1] + b, tot[2] + have
        bg = '' if n else f' bgcolor="{NONE_ROW}"'
        mark = '' if n else f' <span style="color:{RED}">— копировать нечего</span>'
        h.append(f'<tr{bg}><td>{esc(name)}{mark}</td><td align="right">{num(n)}</td><td align="right">{gb(b)}</td>'
                 f'<td align="right">{num(have)}</td></tr>')
    h.append(f'<tr><td><b>Итого</b></td><td align="right"><b>{num(tot[0])}</b></td><td align="right"><b>{gb(tot[1])}'
             f'</b></td><td align="right"><b>{num(tot[2])}</b></td></tr></table>')
    return ''.join(h)


def place_lines(val, label):
    """«Куда» и «Поместится» по каждому диску назначения заданий набора."""
    P, cap = val['res']['plan'], val['cap']
    disks = sorted({x for n in (val.get('nums') or P.dirs) if n in P.dirs for x in P.dirs[n].disks if x != P.disk})
    h = []
    for x in disks:
        h.append(f'<p><b>Куда:</b> {esc(label(x))}\\{esc(rz.COPY_ROOT)}\\{esc(P.disk)}\\…</p>')
    for x in disks:
        c = cap.get(x)
        who = f'{esc(label(x))}: ' if len(disks) > 1 else ''
        if not c:
            continue
        if c['state'] == 'short':
            h.append(f'<p style="color:{RED}"><b>{who}Не помещается: нужно {gb(c["need"] + c["reserve"])} ГБ (с запасом '
                     f'{gb(c["reserve"])}), свободно {gb(c["free"])} ГБ.</b> Снимите галочки у части папок.</p>')
        elif c['state'] == 'unknown':
            h.append(f'<p style="color:{ORANGE}">{who}диск не подключён — место не проверено.</p>')
        elif c['free'] is not None:
            h.append(f'<p style="color:{GREEN}">{who}<b>Поместится:</b> нужно {gb(c["bytes"])} ГБ, свободно '
                     f'{gb(c["free"])} ГБ.</p>')
    return ''.join(h)


def toc_html(toc):
    if toc is None:
        return ''
    if not toc['connected'] or toc['problems']:
        h = [f'<p style="color:{RED}"><b>Копирование не начнётся: оглавление носителя не совпадает с описью'
             + (' (или его нельзя проверить)' if not toc['connected'] else '') + '.</b></p><ul>']
        h += [f'<li>{esc(x)}</li>' for x in sv.toc_lines(toc)]
        h.append('</ul>')
        if toc['connected']:
            h.append('<p>Что делать: пересканируйте эти папки (кнопка ниже - то же окно, что в «Диски и папки»), потом '
                     'нажмите «Начать копирование…» ещё раз. Файлы прямо в корне носителя папкой не пересканировать - '
                     'для них нужно полное сканирование носителя в «Сканере дисков».</p>')
        return ''.join(h)
    return (f'<p style="color:{GRAY}">Сверка оглавления носителя ({esc(toc["letter"])}) с описью: расхождений нет '
            f'(проверено файлов: {num(toc["checked"])}).</p>')


def start_html(val, label, note=''):
    """Окно «Начать копирование». label(диск) - «H:» (не подключён - «HDD45»). -> html."""
    P, states = val['res']['plan'], val['res']['states']
    new, wait, run = task_sets(val)
    mode = start_mode(val)
    h = [f'<p style="color:{RED}"><b>{esc(note)}</b></p>' if note else '', toc_html(val.get('toc'))]
    if P.info.get('is_target'):
        names = ', '.join(P.dirs[n].name for n in P.info['is_target'])
        h.append(f'<p style="color:{ORANGE}"><b>{esc(P.disk)} — сам диск направления «{esc(names)}»:</b> копировать с '
                 'него на остальные диски можно, перемещать на нём ничего нельзя.</p>')
    for n in val['short']:
        d = P.dirs[n]
        h.append(f'<p style="color:{RED}"><b>{esc(show_num(d.num))} {esc(d.name)} не помещается</b> — копировать его '
                 'не будем (ни на один его диск). Снимите галочки у части папок.</p>')
    h.append(folders_table(val))
    h.append(place_lines(val, label))
    if mode == 'running':
        h.append(f'<p style="color:#1565c0"><b>Уже копируется:</b> ' + esc(', '.join(f'«{s["name"]}»' for s in run))
                 + '. Ход — в «3. Копирование»' + ('; новые папки запустите, когда оно закончится.' if new else '.')
                 + '</p>')
    elif mode == 'start':
        files = len({r[1] for s in new + wait for r in s['rows']})     # файл на 45 и на 77 - один
        h.append(f'<p style="color:{GREEN}"><b>✔ У всех {num(files)} {plural(files, "файла", "файлов", "файлов")} есть '
                 'хеш — каждую копию сверим по SHA-256</b></p>')
        h.append(f'<p>{time_text(val, label)}</p>')
        if wait:
            h.append(f'<p style="color:{GRAY}">' + (f'Созданы раньше и ждут запуска: {len(wait)} — запустятся вместе с '
                                                     'новыми.' if new else 'Все задания уже созданы раньше — кнопка '
                                                     'запустит их.') + '</p>')
    elif mode == 'none' and not val['short']:
        h.append('<p>Копировать нечего: всё отмеченное уже есть на диске назначения (или нет файлов выбранного типа).'
                 '</p>')
    nod = sorted({g['direction'] for g in states if g['state'] == rz.G_NODISK})
    if nod:
        h.append(f'<p style="color:{GRAY}">Направление без диска — копирования не будет: {esc(", ".join(nod))}. '
                 'Назначьте диск в «Обзоре».</p>')
    h.append(f'<p style="color:{GRAY}; font-size:9pt">{FOOT}</p>')
    return ''.join(h)
