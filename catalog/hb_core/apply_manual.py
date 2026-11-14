"""Применение модуля «строка ручных операций»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from hb_core.consts import EV_USER, SEP
from hb_core.util import prefix_cond
from hb_core.sources import manual_rows, manual_time
from hb_core.apply_common import put_row


def apply_manual_row(c, line_no, f, report, seen):
    """Одна ручная операция (то, что пользователь сделал в Проводнике). Копия «со слов» никогда не становится
    подтверждённой. Операция не действует на место, которое ПОЗЖЕ описал частичный скан: скан и есть итог."""
    f = [x.strip() for x in f] + [''] * 7
    date, act, disk, path, disk2, path2 = f[:6]
    act = act.lower()
    when = manual_time(date)
    origin = f'вручную {date}, строка {line_no}'
    cond, args = prefix_cond('path', path)
    label = f'{date} {act} {disk}:{path}' + (f' -> {disk2}:{path2}' if disk2 else '')
    late = 0
    if act.startswith('удал'):
        if when < seen.at(disk):
            report['old'].append(label + ' - не применено: опись диска новее')
            return False
        paths = [r[0] for r in c.execute(f'select path from files where disk=? and {cond}', [disk] + args)]
        keep = [p for p in paths if when < seen.at(disk, p)]
        late = len(keep)
        if late:
            keep = set(keep)
            paths = [p for p in paths if p not in keep]
        c.executemany('delete from files where disk=? and path=?', ((disk, p) for p in paths))
        k = len(paths)
    elif act.startswith(('скопир', 'перемещ')):
        move = act.startswith('перемещ')
        if when < seen.at(disk2) or (move and when < seen.at(disk)):
            report['old'].append(label + ' - не применено: опись диска новее')
            return False
        rows = c.execute(f'select path, size, sha, mtime, ev, sha_exp from files where disk=? and {cond}',
                         [disk] + args).fetchall()
        base = path.rstrip(SEP)
        todo = []
        for p, size, sha, mt, ev, exp in rows:
            tail = p[len(base):].lstrip(SEP)
            newp = (path2.rstrip(SEP) + (SEP + tail if tail else '')) if tail or path2 else p
            if when < seen.at(disk2, newp) or (move and when < seen.at(disk, p)):
                late += 1                         # это место позже описал частичный скан
                continue
            todo.append((p, newp, size, sha, mt, ev, exp))
        if move:                                  # сначала убрать ровно эти записи, потом создать новые
            c.executemany('delete from files where disk=? and path=?', ((disk, r[0]) for r in todo))
        for p, newp, size, sha, mt, ev, exp in todo:
            if move and disk2 == disk:            # тот же файл на том же диске: подтверждение не меняется
                put_row(c, disk2, newp, size, sha, mt, ev, exp, origin)
            else:                                 # содержимое копии никто не проверял
                put_row(c, disk2, newp, size, None, mt, EV_USER, sha or exp, origin)
        k = len(todo)
    else:
        report['warn'].add(f'ручные операции: непонятное действие «{act}»')
        return False
    report['manual'].append(label + f' - {k} файлов')
    if late:
        report['old'].append(label + f' - {late} файлов не применено: это место позже описал частичный скан')
    return True


def apply_manual(c, report, seen):
    return sum(apply_manual_row(c, n, f, report, seen) for n, f in manual_rows())
