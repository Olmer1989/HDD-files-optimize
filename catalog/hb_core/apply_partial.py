"""Применение модуля «частичный скан папок»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import sqlite3
import build_pilot as bp
from hb_core.consts import EV_COPY, EV_NONE, EV_SCAN, EV_SIZE, EV_STALE, EV_USER, SEP
from hb_core.util import gb, inside, prefix_cond, rel_of
from hb_core.apply_common import scan_row


def apply_partial(c, pj, seen, excl, report):
    """Частичный скан папок: строки носителя ВНУТРИ его папок заменяются строками скана (степень S),
    строки вне этих папок не трогаются. Папки из исключений пропускаются. Итог - в report['partial']."""
    disk, label = pj['disk'], f'частичный скан {pj["disk"]} ({pj["name"]})'
    info = pj['info']
    if not str(pj['status']).startswith('complete'):
        report['warn'].add(f'{label}: состояние «{pj["status"]}» - скан не принят')
        return False
    if disk not in seen.full:
        report['warn'].add(f'{label}: полной описи этого носителя нет в базе - скан не принят')
        return False
    if pj['time'] <= seen.full[disk]:
        report['old'].append(f'{label}: не применён - полная опись носителя новее')
        return False
    folders = sorted({f.strip().strip(SEP) for f in pj['folders'] if f.strip().strip(SEP)}, key=lambda f: -len(f))
    if not folders:
        report['warn'].add(f'{label}: в result.json нет списка папок - скан не принят')
        return False
    hp, ip = pj['dir'] / 'hashes.sqlite', pj['dir'] / 'inventory.sqlite'
    hashes, unread = {}, 0
    if hp.exists():
        with bp.ro(hp) as h:
            for p, s, m, x, st in h.execute('select path, size, mtime_ns, lower(sha256), status from hashes'):
                if st == 'verified' and x:
                    hashes[p] = (s, '' if m is None else str(m), x)
                else:
                    unread += 1
    with bp.ro(ip) as inv:
        scan = inv.execute('select path, size, mtime_ns from files').fetchall()
        try:
            errors = inv.execute('select path, operation, message from errors').fetchall()
        except sqlite3.Error:
            errors = []
    ex = excl.get(disk, [])
    origin = f'частичный скан: {pj["name"]}'
    st = {f: collections.Counter() for f in folders}
    prev = {}
    for f in folders:
        cond, args = prefix_cond('path', f)
        for p, sha, exp, ev, size in c.execute(f'select path, sha, sha_exp, ev, size from files where disk=? and {cond}',
                                               [disk] + args):
            prev[p] = (sha or exp, ev, size or 0)
        c.execute(f'delete from files where disk=? and {cond}', [disk] + args)
        c.execute(f'delete from issues where disk=? and {cond}', [disk] + args)
        seen.add(disk, f, pj['time'])
        c.execute('insert or replace into scan_folders values (?,?,?)', (disk, f, pj['time']))
    rows, outside = [], 0
    for p, size, mt in scan:
        f = inside(p, folders)
        if f is None:
            outside += 1
            continue
        k = st[f]
        k['файлов'] += 1; k['байт'] += size or 0
        r = scan_row(disk, p, size, mt, hashes.get(p), origin)
        h = r[3] or r[8]
        if inside(p, ex):
            k['исключено'] += 1; k['исключено байт'] += size or 0
            c.execute('insert or replace into excluded values (?,?,?,?,?,?)', (disk, p, size or 0, h, r[5], origin))
            continue
        rows.append(r)
        old = prev.pop(p, None)
        if old is None:
            k['новые'] += 1; k['новые байт'] += size or 0
        elif old[0] and h and old[0] != h:
            k['хеш не совпал'] += 1
        elif r[7] == EV_SCAN:
            k['было ' + (old[1] or EV_NONE)] += 1
    c.executemany('insert or replace into files values (?,?,?,?,?,?,?,?,?)', rows)
    for p, (h, ev, size) in prev.items():                        # было в базе, в скане нет
        k = st[inside(p, folders)]
        if inside(p, ex):
            k['убрано по исключениям'] += 1
        else:
            k['исчезли'] += 1; k['исчезли байт'] += size
    for p, op, msg in errors:
        c.execute('insert into issues values (?,?,?,?)', (disk, rel_of(p or '')[1].rstrip(SEP),
                                                          'не прочитано при частичном скане', f'{op}: {msg}'[:300]))
    lines = []
    for f in sorted(folders):
        k = st[f]
        conf = ', '.join(f'{e} {k["было " + e]}' for e in (EV_SIZE, EV_COPY, EV_USER, EV_STALE, EV_NONE) if k['было ' + e])
        lines.append(f'{disk}\\{f}: в скане {k["файлов"]} файлов ({gb(k["байт"])} ГБ); стало S: {conf or "0"}'
                     + (f', уже было S {k["было S"]}' if k['было S'] else '')
                     + f'; новые {k["новые"]} ({gb(k["новые байт"])} ГБ); исчезли из базы {k["исчезли"]}'
                     + f'; хеш не совпал {k["хеш не совпал"]}'
                     + (f'; пропущено по исключениям {k["исключено"]} ({gb(k["исключено байт"])} ГБ)' if k['исключено'] else '')
                     + (f'; старых записей убрано по исключениям {k["убрано по исключениям"]}'
                        if k['убрано по исключениям'] else ''))
    report.setdefault('partial', []).extend(lines)
    report.setdefault('partial_stats', {})[pj['name']] = {f: dict(st[f]) for f in folders}
    if outside:
        report['warn'].add(f'{label}: {outside} файлов вне перечисленных папок - не приняты')
    if unread or info.get('damaged_files') or info.get('unread_files') or errors:
        report['warn'].add(f'{label}: не прочитано файлов {unread or info.get("unread_files") or 0}, '
                           f'повреждено {info.get("damaged_files") or 0}, ошибок описи {len(errors)}')
    return True
