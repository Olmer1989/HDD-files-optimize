"""«Задания на копирование»: тексты строк - плашки-сводка, «Что и куда», «Состояние», подсказка «Ошибки», «Копии
проверены по хешу …», состояние задания группы 45/77. Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from .common import BAD_STATES, GREY, RED, STATE_COLOR
from .texts_words import fmt_ago, gb, n, _num, _on_disks, _where


def summary(rows, queue=()):
    """Плашки над таблицей: [(текст, цвет или None)]. «Неизвестно» - отдельно и только если есть (не ошибка)."""
    st = [r['state'] for r in rows]
    wait = st.count('не запускалось')
    queued = sum(1 for r in rows if r['state'] == 'не запускалось' and r['task'] in queue)
    bad = sum(1 for s in st if s in BAD_STATES)
    res = [(f'Идёт: {st.count("идёт")}', '#1565c0' if 'идёт' in st else None),
           (f'Ждут запуска: {wait}' + (f' (в очереди {queued})' if queued else ''), None),
           (f'Прервано, с ошибками: {bad}', RED if bad else None),
           (f'Готово: {st.count("готово")}', '#2e7d32' if 'готово' in st else None)]
    unknown = st.count('состояние неизвестно')
    if unknown:
        res.append((f'Неизвестно: {unknown}', GREY))
    return res


def _target_words(meta, targets):
    """«Работа и Сафари — HDD78»; у направления на двух дисках задание на один - «Семейный архив — на 45 (HDD45)»."""
    name = meta.get('имя направления') or ''
    tg = list(meta.get('цели') or targets or [])
    req = meta.get('обязательные диски') or []
    if len(req) > 1 and len(tg) == 1:
        return f'{name} — на {_num(tg[0])} ({tg[0]})'
    return f'{name} — {", ".join(tg)}' if name else ', '.join(tg)


def what_where(r):
    """«Что и куда» в две строки: («HDD09 · F:\\Котуй 2026», «→ Работа и Сафари — HDD78»)."""
    m, mm = r.get('meta'), r.get('move_meta')
    src = r.get('src') or (m or {}).get('носитель') or ''
    letter = r.get('src_letter') or ''
    if m:
        where = _where(letter, m.get('папка'))
        tail = ' (повтор не скопированного)' if m.get('повтор') else ''
        return f'{src} · {where}', f'→ {_target_words(m, r.get("targets"))}{tail}'
    if mm:
        where = _where(letter, mm.get('папка'))
        return f'{src} · {where}', f'→ перемещение внутри носителя в «{mm.get("куда", "Скопировано на …")}»'
    return r['task'], '→ ' + (r.get('disks') or 'диски не указаны')


def state_text(r, queue=()):
    """Столбец «Состояние»: (текст, цвет). У идущего - скорость и остаток; у прерванного - последняя запись журнала."""
    s = r['state']
    if s == 'идёт':
        parts = ['Идёт']
        sp = r.get('speed')
        if sp:
            parts.append((f'{sp / 1024 ** 2:,.0f} МБ/с' if sp >= 10 * 1024 ** 2 else
                          f'{sp / 1024 ** 2:.1f} МБ/с').replace(',', ' ').replace('.', ','))
        eta = r.get('eta_text') or ''
        if eta:
            parts.append(('осталось ' + eta.lstrip('~')) if r.get('eta') is not None else eta)
        text = ' · '.join(parts)
        if r.get('ago') is not None and r['ago'] > 120:
            text += f' · последняя запись {fmt_ago(r["ago"])}: идёт большой файл или диск завис'
        return text, STATE_COLOR['идёт']
    if s == 'не запускалось':
        return ('В очереди', STATE_COLOR['в очереди']) if r['task'] in queue else ('Ждёт запуска', STATE_COLOR[s])
    if s == 'прервано':
        last = r.get('last_res') or ''
        ok = last.startswith(('скопирован', 'уже есть', 'перемещён', 'уже перемещён'))
        return ('Прервано' + (f' · последняя запись: {last[:80]}' if last and not ok else
                              ' · повторный запуск продолжит'), STATE_COLOR[s])
    if s == 'состояние неизвестно':
        return 'Неизвестно, идёт ли (не удалось узнать) — нажмите «Обновить»', STATE_COLOR[s]
    if s == 'готово с ошибками':
        return f'Готово с ошибками: не сделано {n(r["errors"] + r["skipped"])}', STATE_COLOR[s]
    return s.capitalize(), STATE_COLOR.get(s)


def errors_tip(r):
    lines = [f'ошибок (ОШИБКА, КОНФЛИКТ): {n(r["errors"])}', f'не сделано по другим причинам: {n(r["skipped"])}']
    return '\n'.join(lines + (r.get('examples') or []))


def _targets_of(x):
    return list((x.get('meta') or {}).get('цели') or x.get('targets') or [])


def hash_words(members, extra=()):
    """«Копии проверены по хешу на диске 78», если у каждой строки списка последний результат журнала - с SHA-256;
    иначе честно «по хешу проверено K из N». Окончательно разрешает перенос пофайловая проверка базы (mvlist)."""
    disks = sorted({t for x in members for t in _targets_of(x)})
    total = sum(x.get('total', 0) for x in members)
    group = list(members) + list(extra)
    if all('hashed_keys' in x for x in group):              # повтор тех же файлов не засчитывается дважды
        hashed = min(total, len(frozenset().union(*(x['hashed_keys'] for x in group))))
    else:                                                    # строки без ключей (тесты окна): по каждому заданию
        hashed = min(total, sum(x.get('hashed', 0) for x in members))
    if total and hashed >= total:
        return f'Копии проверены по хешу на {_on_disks(disks)}'
    return (f'Скопировано на {_on_disks(disks)}; по журналу копирования SHA-256 сверен у {n(hashed)} из {n(total)} — '
            'остальное перемещение проверит по базе')


def _size_words(r):
    return f'{n(r.get("total", 0))} файлов, {gb(r.get("total_b", 0))} ГБ'


def member_word(x):
    """Состояние одного задания группы 45/77: «на 45 скопировано и проверено», «на 77 ждёт запуска»."""
    s = x['state']
    if s == 'готово':
        w = ('скопировано и проверено' if x.get('hashed', 0) >= x.get('total', 0) else
             f'скопировано (по хешу проверено {n(x.get("hashed", 0))} из {n(x.get("total", 0))})')
    else:
        w = {'идёт': 'идёт копирование', 'готово с ошибками': 'скопировано с ошибками', 'не запускалось': 'ждёт запуска',
             'прервано': 'прервано, ждёт продолжения', 'состояние неизвестно': 'неизвестно, идёт ли'}.get(s, s)
    return f'на {", ".join(_num(t) for t in _targets_of(x)) or "?"} {w}'
