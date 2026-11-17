"""Тексты окна «Подготовить задания»: таблица заданий, место по дискам, внимание (без Qt).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import razbor as rz

import service as sv

from directions_look import show_num                 # «Н2» на экране - «А2» (18.11.2026)

from .texts_cell import GREEN, ORANGE, RED, esc, gb, num


def place_html(x, at=''):
    """Строка места на диске по service.capacity."""
    if x['state'] == 'short':
        return (f'<b style="color:{RED}">не помещается: нужно {gb(x["need"] + x["reserve"])} ГБ (с запасом '
                f'{gb(x["reserve"])}), свободно {gb(x["free"])} ГБ ({esc(x["letter"])})</b>')
    if x['state'] == 'unknown':
        return f'<span style="color:{ORANGE}">диск не подключён — место не проверено</span>'
    if x['state'] == 'none':
        return '' if x['free'] is None else f'свободно {gb(x["free"])} ГБ'
    return f'<span style="color:{GREEN}">помещается: свободно {gb(x["free"])} ГБ ({esc(x["letter"])})' + \
        (f' на {at}' if at else '') + '</span>'


def tasks_html(val, disk_name, note=''):
    """Окно «Подготовить задания»: сверка оглавления, таблица заданий, место по дискам, не помещающиеся направления,
    папки без диска, «копировать нечего», внимание. -> (html, новые задания)."""
    res, cap, at, toc = val['res'], val['cap'], val['at'], val.get('toc')
    P, states = res['plan'], res['states']
    specs, new, short = val['specs'], val['new'], val['short']
    h = []
    if note:
        h.append(f'<p style="color:{RED}"><b>{esc(note)}</b></p>')
    if toc is not None:
        if not toc['connected'] or toc['problems']:
            h.append(f'<p style="color:{RED}"><b>Задания не создаются: оглавление носителя не совпадает с описью'
                     + (' (или его нельзя проверить)' if not toc['connected'] else '') + '.</b></p><ul>')
            h += [f'<li>{esc(x)}</li>' for x in sv.toc_lines(toc)]
            h.append('</ul>')
            if toc['connected']:
                h.append('<p>Что делать: пересканируйте эти папки (кнопка ниже - то же окно, что в «Диски и папки»), '
                         'потом нажмите «Подготовить задания» ещё раз. Файлы прямо в корне носителя папкой не '
                         'пересканировать - для них нужно полное сканирование носителя в «Сканере дисков».</p>')
        else:
            h.append(f'<p style="color:{GREEN}">Сверка оглавления носителя ({esc(toc["letter"])}) с описью: '
                     f'расхождений нет (проверено файлов: {num(toc["checked"])}; только пути, размеры и даты).</p>')
    if P.info.get('is_target'):
        names = ', '.join(P.dirs[n].name for n in P.info['is_target'])
        h.append(f'<p style="color:{ORANGE}"><b>{esc(P.disk)} — сам диск направления «{esc(names)}»:</b> копировать с '
                 'него на остальные диски можно, перемещать на нём ничего нельзя (после копирования «Переместить» '
                 'предложено не будет).</p>')
    for n in short:
        d = P.dirs[n]
        bad = '; '.join(f'на {rz.disk_word(x)}: нужно {gb(cap[x]["need"] + cap[x]["reserve"])} ГБ с запасом, свободно '
                        f'{gb(cap[x]["free"])} ГБ' for x in d.disks if cap.get(x, {}).get('state') == 'short')
        h.append(f'<p style="color:{RED}"><b>{esc(show_num(d.num))} {esc(d.name)} не помещается</b> ({esc(bad)}) — заданий для '
                 'него не будет (ни на один его диск). Снимите галочки у части папок.</p>')
    if specs:
        h.append('<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                 '<tr><th align="left">Задание</th><th>Файлов</th><th>ГБ</th><th align="left">На диски</th></tr>')
        for s in specs:
            old = ' <span style="color:gray">(уже подготовлено раньше)</span>' if s.get('exists') else ''
            h.append(f'<tr><td>{esc(s["name"])}{old}</td><td align="right">{num(s["files"])}</td>'
                     f'<td align="right">{gb(s["bytes"])}</td><td>{esc(", ".join(disk_name(d) for d in s["targets"]))}'
                     '</td></tr>')
        h.append('</table>')
        per = sorted({d for s in specs for d in s['targets']})
        if per:
            h.append('<p><b>Место на дисках</b> (всё, чего на диске ещё нет с этого носителя, плюс незапущенные задания '
                     'других носителей):</p><ul>')
            for d in per:
                x = cap.get(d)
                if x:
                    q = (f'; в очереди с других носителей {num(x["queued"][0])} заданий, {gb(x["queued"][1])} ГБ'
                         if x['queued'][0] else '')
                    h.append(f'<li>{esc(disk_name(d))}: копировать {gb(x["bytes"])} ГБ{q}; {place_html(x, at)}</li>')
            h.append('</ul>')
    elif not short:
        h.append('<p>Заданий копирования нет: копировать нечего (или у направлений нет дисков).</p>')
    nod = [g for g in states if g['state'] == rz.G_NODISK]
    if nod:
        h.append(f'<p>Без задания — направление без диска: {len(nod)} папок ('
                 f'{esc(", ".join(sorted({g["direction"] for g in nod})))}). Назначьте диск направлению.</p>')
    have = [g for g in states if g['state'] == rz.G_HAVE]
    if have:
        h.append(f'<p>Копировать нечего (всё уже есть на дисках направления): {len(have)} папок. Это ещё не разрешение '
                 'перемещать — его проверит перемещение по базе.</p>')
    chosen = set(val.get('nums') or P.dirs)                  # только диски выбранных направлений (план - полный)
    other = {x for n, d in P.dirs.items() if n not in chosen for x in d.disks} - \
        {x for n in chosen if n in P.dirs for x in P.dirs[n].disks}
    att = [x for x in rz.attention_lines(P) if not x.startswith(f'{P.disk} - диск направления')
           and not any(o in x for o in other)]
    if att:
        h.append('<p><b>Нужно внимание</b></p><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in att) + '</ul>')
    blocked = toc is not None and (not toc['connected'] or toc['problems'])
    if new and not blocked:
        h.append(f'<p style="color:gray">Будет создано заданий: {len(new)} в «Запускаемые скрипты». Ничего не копируется '
                 'и не запускается; запуск - на вкладке «Копирование».</p>')
    elif specs and not new:
        h.append('<p>Все задания уже подготовлены раньше - новых нет.</p>')
    return ''.join(h), new
