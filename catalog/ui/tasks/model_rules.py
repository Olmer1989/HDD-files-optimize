"""«Задания на копирование»: решения без экрана - галочка, «Запустить все по очереди», «Готово (N)», общие диски,
перемещение и копирование с одного носителя. Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from .texts_words import _date, gb


def checkable(r):
    """Галочку можно ставить всем, кроме идущего, неизвестного (может уже идти) и «готово с ошибками» задания разбора,
    которое можно перемещать на носителе (для него в блоке ниже - «Повторить копирование»: старое задание после переноса
    дало бы «нет источника»). Если источник - диск направления, блока нет: повтор - самим заданием (галочка)."""
    if r['state'] in ('идёт', 'состояние неизвестно'):
        return False
    m = r.get('meta')
    if r['state'] == 'готово с ошибками' and m and m.get('перемещать на носителе', True):
        return False
    return True                      # на диске направления ничего не перемещается - задание можно просто запустить снова


def run_all_set(rows):
    """«Запустить все по очереди»: ждущие и прерванные (не идущие, не готовые, не неизвестные)."""
    return [r for r in rows if r['state'] in ('не запускалось', 'прервано')]


def done_rows(rows, done_items=()):
    """«Готово (N)»: [dict(task, files, gb, errors, date, left, tip, item)] по заданиям «готово»."""
    info = {it['task']: it for it in done_items}
    res = []
    for r in rows:
        if r['state'] != 'готово':
            continue
        it = info.get(r['task'])
        left = (it or {}).get('left', 0) if r['kind'] == 'перемещение' else 0
        res.append(dict(task=r['task'], files=r['total'], gb=gb(r.get('total_b', 0)) if r['kind'] == 'копирование' else '',
                        errors=r['errors'] + r['skipped'], date=_date(r.get('log_ts')), left=left,
                        tip=(it or {}).get('text', ''), item=it))
    return res


def _overlap(a, b):
    """Папки групп пересекаются? None - «файлы в корне» (пересекается только с такой же группой)."""
    if a is None or b is None:
        return a is None and b is None
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b + '\\') or b.startswith(a + '\\')


def conflicts(rows):
    """Пары заданий, которые одновременно работают с одним физическим диском (в любой роли)."""
    res = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            common = a.get('serials', set()) & b.get('serials', set())
            if common:
                res.append(f'«{a["task"]}» и «{b["task"]}» — общий диск')
    return res


def move_blocks(sel, rows):
    """Перемещение нельзя запускать, пока идёт или запускается копирование с того же носителя, и наоборот."""
    act = [r for r in rows if r['state'] == 'идёт'] + list(sel)
    res = []
    for m in (r for r in act if r['kind'] == 'перемещение'):
        for c in (r for r in act if r['kind'] == 'копирование'):
            if m.get('src_serial') and m['src_serial'] == c.get('src_serial'):
                mm, cm = m.get('move_meta'), c.get('meta')
                if mm and cm and not _overlap(mm.get('папка'), cm.get('папка')):
                    continue                  # логика v3: другая папка того же носителя - пути не пересекаются
                res.append(f'«{m["task"]}» (перемещение) и «{c["task"]}» (копирование) — один и тот же источник')
    return res
