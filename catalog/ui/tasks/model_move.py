"""«Задания на копирование»: логика v3 - блоки «Скопировано — можно переместить папку на носителе» и «Готово» по файлам
заданий и манифестам разбора. Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from pathlib import Path

from hb_core import api as hb

from .common import DONE, _meta
from .texts_words import disks_words, _folder_word, move_line, n, _on_disks
from .texts_rows import hash_words, member_word, _size_words


def latest_manifest_groups(root=None):
    """Группы манифестов разбора, где копировать нечего («все подходящие уже есть»): их тоже можно переместить.
    По носителю и папке - из самого нового готового манифеста. -> [dict(manifest, disk, group, move_allowed)]."""
    root = Path(root or hb.RAZBORY)
    best = {}
    for p in sorted(root.glob('*.json')) if root.exists() else []:
        m = _meta(p)
        if not m or m.get('статус') != 'готово':
            continue
        for g in m.get('группы', []):
            best[(m.get('носитель'), g.get('folder'))] = dict(manifest=p.name, disk=m.get('носитель'), group=g,
                                                              allowed=m.get('перемещать на носителе', True))
    return [v for v in best.values() if v['group'].get('state') == hb.G_HAVE]


def r1_of(folder):
    return hb.copied_inside(folder or '')[0]


def move_items(rows, groups=()):
    """Блоки под таблицей: (можно переместить [dict], готово [dict]). Считается заново по файлам заданий."""
    offers, done, waiting = [], [], []
    retries = {}
    moves = {}
    for r in rows:
        m = r.get('meta')
        if m and m.get('повтор'):
            retries.setdefault(m['повтор'], []).append(r)
        mm = r.get('move_meta')
        if mm:
            key = mm.get('задание копирования') or ('манифест', mm.get('манифест'), mm.get('папка'))
            moves.setdefault(key, []).append(r)
    for v in moves.values():
        v.sort(key=lambda x: x['move_meta'].get('создано_ts', 0))
    parts_of = {}                                        # этап 13: части имени «Скопировано на …» по записям переносов
    for r in rows:
        mm = r.get('move_meta') or {}
        if mm.get('куда') and mm.get('части'):
            parts_of.setdefault(mm['куда'], [])
            parts_of[mm['куда']] += [t for t in mm['части'] if t not in parts_of[mm['куда']]]

    def done_items(key, disks, labels, folder, src_disk):
        keys = key if isinstance(key, list) else [key]
        for mv in [m for k in keys for m in moves.get(k, [])]:
            mm = mv['move_meta']
            if mv['state'] not in DONE:
                continue
            text = (f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)} и перенесена в '
                    f'«{mm["куда"]}» на {src_disk}. Содержимое источника перед перемещением не проверялось.')
            total = (mm.get('всего в папке') or [0])[0]
            left = max(0, total - mv.get('good', 0))
            if left:
                text += f' На старом месте осталось {n(left)} файлов.'
            if mv['state'] == 'готово с ошибками':
                text += f' Не перенесено по ошибке или конфликту: {n(mv["errors"] + mv["skipped"])}.'
            done.append(dict(text=text, task=mv['task'], left=left, reasons=mm.get('остаток') or {}, ok=not left))

    # этап 5: у направления с несколькими дисками (45 и 77) - отдельное задание на каждый диск одной группы («группа» в
    # разбор.json). Перемещение группы предлагается, только когда закончены ВСЕ её задания; пока нет - строка «на 45
    # скопировано, на 77 - ждёт». Окончательно решает пофайловая проверка SHA-256 на всех дисках (mvlist).
    sibs = {}
    for r in rows:
        m = r.get('meta')
        if r['kind'] != 'копирование' or not m or m.get('повтор'):
            continue
        key = (m.get('носитель', ''), m.get('группа')) if m.get('группа') else ('', r['task'])
        sibs.setdefault(key, []).append(r)

    for members in sibs.values():
        members.sort(key=lambda x: x['task'])
        r = members[0]                                       # «ведущее» задание группы: им вызывается mvlist
        m = r['meta']
        labels = r.get('labels') or {}
        folder, disks, src = m.get('папка'), m.get('обязательные диски') or [], m.get('носитель', '')
        letter = r.get('src_letter') or ''
        group = [g for x in members for g in [x] + retries.get(x['task'], [])]
        if any(g['state'] == 'идёт' for g in group) and len(members) == 1:
            continue
        if any(x['state'] not in DONE for x in members) or any(g['state'] == 'идёт' for g in group):
            if len(members) > 1:                             # не все диски группы скопированы - перемещать рано
                parts = [member_word(x) for x in members]
                dest = hb.move_dest(folder, m.get('имя направления', ''), disks, parts_of.get(r1_of(folder))) if disks else '…'
                small = ' · '.join(parts)
                waiting.append(dict(text=f'Папка «{_folder_word(folder)}»: ' + '; '.join(parts) + '. Переместить на '
                                         f'носителе можно, когда копии будут на {disks_words(disks, labels)}.',
                                    task=r['task'], left=0, reasons={}, ok=False, copy_task=r['task'], folder=folder,
                                    line=move_line(letter, src, folder, dest), small=small[:1].upper() + small[1:]))
            continue
        if not m.get('перемещать на носителе', True):
            done.append(dict(text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}; '
                                  f'источник {src} — диск направления, на нём ничего не перемещается.',
                             task=r['task'], left=0, reasons={}, ok=True))
            continue
        dest = hb.move_dest(folder, m.get('имя направления', ''), disks, parts_of.get(r1_of(folder))) if disks else '…'
        # задание переноса могло быть создано по ЛЮБОМУ заданию группы (mvlist --razbor «… — на 77» из командной строки)
        mv = sorted((x for t in members for x in moves.get(t['task'], [])),
                    key=lambda x: x['move_meta'].get('создано_ts', 0))
        last = mv[-1] if mv else None
        left = sum(x.get('left', 0) for x in members)
        with_left = [x['task'] for x in members if x.get('left', 0)]
        retry_busy = any(g['state'] not in DONE for x in members for g in retries.get(x['task'], []))
        hw = hash_words(members, [g for x in members for g in retries.get(x['task'], [])])
        base = dict(copy_task=r['task'], folder=folder, dest=dest, disk=src, retry_tasks=with_left or [r['task']],
                    line=move_line(letter, src, folder, dest), small=f'{hw} · {_size_words(r)}')
        if last and last['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            word = 'Запустить перемещение' if last['state'] == 'не запускалось' else 'Продолжить перемещение'
            offers.append(dict(base, kind='run', move_task=last['task'], buttons=[word],
                               small=('Задание перемещения создано, но не запускалось' if last['state'] == 'не запускалось'
                                      else 'Перемещение прервано — повторный запуск продолжит с места остановки'),
                               text=f'Папка «{_folder_word(folder)}»: задание переноса в «{dest}» '
                                    + ('создано, но не запускалось.' if last['state'] == 'не запускалось' else
                                       'прервано — повторный запуск продолжит с места остановки.')))
        elif last and last['state'] == 'идёт':
            pass
        else:
            newer = any(g['state'] in DONE and g.get('log_ts', 0) > last['move_meta'].get('создано_ts', 0)
                        for x in members for g in retries.get(x['task'], [])) if last else False
            if (not last or newer) and not retry_busy:
                if left:
                    offers.append(dict(base, kind='move', buttons=['Переместить скопированное', 'Повторить копирование'],
                                       small=f'Не скопировано {n(left)} файлов: можно переместить скопированное '
                                             f'(остальное останется на месте), затем повторить копирование · {hw}',
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)} '
                                            f'не полностью: не скопировано {n(left)} файлов. Сначала можно переместить '
                                            f'скопированное в «{dest}» (остальное останется на месте), затем повторить '
                                            'копирование остального.'))
                else:
                    offers.append(dict(base, kind='move', buttons=['Переместить'],
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}. '
                                            f'Переместить её на носителе {src} в «{dest}»? Проверка по хешу — по журналу '
                                            'копирования (SHA-256 прочитанного и записанного); перед перемещением '
                                            'каждый файл ещё раз сверяется с базой.'))
            elif left and not retry_busy:
                offers.append(dict(base, kind='retry', buttons=['Повторить копирование'],
                                   small=f'Скопированное уже перенесено; не скопировано {n(left)} файлов',
                                   text=f'Папка «{_folder_word(folder)}»: скопированное перенесено, не скопировано '
                                        f'{n(left)} файлов. Повторить копирование остального?'))
        done_items([x['task'] for x in members], disks, labels, folder, src)
    labels = next((r.get('labels') for r in rows if r.get('labels')), {}) or {}
    for g in groups:
        gr = g['group']
        if not g.get('allowed', True):
            continue
        key = ('манифест', g['manifest'], gr.get('folder'))
        mv = moves.get(key, [])
        dest = (hb.move_dest(gr.get('folder'), gr.get('direction', ''), gr.get('disks') or [],
                                parts_of.get(hb.copied_inside(gr.get('folder') or '')[0])) if gr.get('disks') else '…')
        gdisks = gr.get('disks') or []
        base = dict(manifest=g['manifest'], group=_folder_word(gr.get('folder')), folder=gr.get('folder'), dest=dest,
                    disk=g['disk'], line=move_line(g.get('letter') or '', g['disk'], gr.get('folder'), dest),
                    small=f'Все подходящие файлы уже есть на {_on_disks(gdisks)}' if gdisks else 'Копировать нечего')
        if not mv:
            offers.append(dict(base, kind='move', buttons=['Переместить'],
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: все подходящие файлы уже есть на '
                                    f'{disks_words(gr.get("disks") or [], labels)}. Переместить её на носителе '
                                    f'{g["disk"]} в «{dest}»?'))
        elif mv[-1]['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            offers.append(dict(base, kind='run', move_task=mv[-1]['task'], buttons=['Продолжить перемещение'],
                               small='Перемещение не закончено — повторный запуск продолжит с места остановки',
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: задание переноса в «{dest}» не закончено.'))
        done_items(key, gr.get('disks') or [], labels, gr.get('folder'), g['disk'])
    return offers + [dict(w, kind='wait', buttons=['Переместить'], disabled=True) for w in waiting], done
