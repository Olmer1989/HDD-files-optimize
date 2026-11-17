"""«Я сделал в Проводнике»: единицы различий, пары перемещений, источники копий, что будет записано."""
import collections

from hb_core import api as hb
from explorer_diff_base import SEP, CHILDREN_MAX, key, parent, ancestors, plural, gb_text


# ---------- единицы ----------

def _unit(kind, path, files, size, when, children=None, **kw):
    u = dict(kind=kind, path=path, is_dir=children is not None or kw.pop('is_dir', False), files=files, bytes=size,
             when=when, children=children)
    u.update(kw)
    return u


def group(disk, gone, new, base_counts, dirs, c, bad_k=()):
    """Исчезнувшие и появившиеся файлы -> единицы: самая верхняя папка, где исчезли ВСЕ файлы базы (или где
    появились только новые файлы), иначе - отдельный файл. Затем пары перемещений и источники на других дисках.
    c - временная база сравнения (таблицы d, b, dirs; подключена base)."""
    def dir_time(path):                                  # подсказка: дата изменения ближайшей папки на диске
        for p in [path] + ancestors(path):
            if key(p) in dirs:
                return dirs[key(p)][1]
        return None

    # исчезли
    cnt = collections.Counter()
    for p, size, mt in gone:
        for a in ancestors(p):
            cnt[a] += 1
    full = {a for a, n in cnt.items() if n == base_counts.get(a, -1)}
    tops = {a for a in full if not any(x in full for x in ancestors(a))}
    units = []
    by_top = collections.defaultdict(list)
    for p, size, mt in gone:
        top = next((a for a in reversed(ancestors(p)) if a in tops), None)
        if top:
            by_top[top].append((p, size, mt))
        else:
            units.append(_unit('gone', p, 1, size, dir_time(parent(p)), mtime=mt))
    for top, rows in by_top.items():
        units.append(_unit('gone', top, len(rows), sum(r[1] or 0 for r in rows), dir_time(parent(top)),
                           children=[dict(path=p, bytes=s, mtime=m) for p, s, m in rows] if len(rows) <= CHILDREN_MAX else [],
                           sig=_sig(top, rows)))
    # появились
    disk_cnt = collections.Counter()
    for (p,) in c.execute('select path from d'):
        for a in ancestors(p):
            disk_cnt[a] += 1
    ncnt = collections.Counter()
    for p, *_ in new:
        for a in ancestors(p):
            ncnt[a] += 1
    base_k = {k.lower() for k, n in base_counts.items() if n}
    full = {a for a, n in ncnt.items() if n == disk_cnt[a] and a.lower() not in base_k}
    tops = {a for a in full if not any(x in full for x in ancestors(a))}
    by_top = collections.defaultdict(list)
    for p, size, mt, born in new:
        top = next((a for a in reversed(ancestors(p)) if a in tops), None)
        if top:
            by_top[top].append((p, size, mt, born))
        else:
            units.append(_unit('new', p, 1, size, max(mt or 0, born or 0), mtime=mt))
    for top, rows in by_top.items():
        units.append(_unit('new', top, len(rows), sum(r[1] or 0 for r in rows),
                           max([max(r[2] or 0, r[3] or 0) for r in rows] + [dirs.get(key(top), (0, 0))[1] or 0]),
                           children=[dict(path=p, bytes=s, mtime=m) for p, s, m, _ in rows] if len(rows) <= CHILDREN_MAX else [],
                           sig=_sig(top, [r[:3] for r in rows])))
    for u in units:                  # в папке есть непроверенное место: её нельзя переносить или копировать целиком
        u['tainted'] = u['is_dir'] and any(b.startswith(key(u['path']) + SEP) for b in bad_k)
    _pair_moves(units)
    _find_sources(disk, units, c)
    units.sort(key=lambda u: (u.get('src') or u['path']).lower())
    return units


def _sig(top, rows):
    """Подпись папки: (путь внутри папки в нижнем регистре, размер, дата изменения) всех файлов."""
    n = len(top) + 1
    return tuple(sorted((p[n:].lower(), s, m) for p, s, m in rows))


def _pair_moves(units):
    """Исчезнувшее + появившееся на том же диске = перемещено/переименовано, если совпадение единственное."""
    gone = [u for u in units if u['kind'] == 'gone']
    new = [u for u in units if u['kind'] == 'new']

    def match(g, n):
        if g['tainted'] or n['tainted'] or g['is_dir'] != n['is_dir'] or g['files'] != n['files'] or g['bytes'] != n['bytes']:
            return False
        if g['is_dir']:
            return g['sig'] == n['sig'] and all(x[2] is not None for x in g['sig'])
        if g['mtime'] is None or g['mtime'] != n['mtime']:
            return False
        gname, nname = g['path'].rsplit(SEP, 1)[-1].lower(), n['path'].rsplit(SEP, 1)[-1].lower()
        return gname == nname or parent(g['path']).lower() == parent(n['path']).lower()

    cand_g = collections.defaultdict(list)
    cand_n = collections.defaultdict(list)
    by_size = collections.defaultdict(list)
    for n in new:
        by_size[(n['is_dir'], n['bytes'])].append(n)
    for g in gone:
        for n in by_size.get((g['is_dir'], g['bytes']), []):
            if match(g, n):
                cand_g[id(g)].append(n)
                cand_n[id(n)].append(g)
    drop = set()
    for g in gone:
        ns = cand_g.get(id(g), [])
        if len(ns) == 1 and len(cand_n[id(ns[0])]) == 1:
            n = ns[0]
            g.update(kind='move', src=g['path'], path=n['path'], when=max(g['when'] or 0, n['when'] or 0))
            if g['is_dir']:
                pairs = {x['path'][len(g['src']) + 1:].lower(): x['path'] for x in g['children'] or []}
                g['children'] = [dict(path=pairs[x['path'][len(n['path']) + 1:].lower()], dst=x['path'],
                                      bytes=x['bytes'], mtime=x['mtime']) for x in n['children'] or []] if g['children'] else []
            drop.add(id(n))
    units[:] = [u for u in units if id(u) not in drop]


def _find_sources(disk, units, c):
    """Появившееся, у которого в базе на ДРУГОМ диске есть ровно такие же файлы (имя, размер, дата, один хеш) ->
    предложение «скопировано с того диска»."""
    for u in units:
        if u['kind'] != 'new' or u['files'] == 0 or u['tainted']:
            continue
        if not u['is_dir']:
            src = _same_file(c, disk, u['path'], u['bytes'], u['mtime'])
            if src:
                u.update(kind='copy', src_disk=src[0], src=src[1], others=src[2])
            continue
        if not u['sig']:
            continue
        tail, size, mt = max(u['sig'], key=lambda x: x[1])
        found = None
        name = hb.name_key(tail)
        for d2, p2 in c.execute('select disk, path from base.files where name_lc=? and size=? and disk<>? limit 40',
                                (name, size, disk)):
            if not p2.lower().endswith(SEP + tail):
                continue
            folder = p2[:len(p2) - len(tail) - 1]
            cond, a = hb.prefix_cond('path', folder)
            rows = c.execute(f'select path, size, mtime from base.files where disk=? and {cond}', [d2] + a).fetchall()
            if _sig(folder, rows) == u['sig']:
                found = (d2, folder) if not found or d2 in hb.MAIN else found
        if found:
            u.update(kind='copy', src_disk=found[0], src=found[1], others=0)


def _same_file(c, disk, path, size, mt):
    """Единственный по содержимому источник файла на другом диске: (диск, путь, сколько ещё копий) или None."""
    if mt is None:
        return None
    rows = c.execute('select disk, path, coalesce(sha, sha_exp), ev from base.files where name_lc=? and size=? and mtime=? '
                     'and disk<>? limit 50', (hb.name_key(path), size, mt, disk)).fetchall()
    hashes = {r[2] for r in rows}
    if not rows or None in hashes or len(hashes) != 1:
        return None
    best = sorted(rows, key=lambda r: (r[3] not in ('S', 'C'), r[0] not in hb.MAIN, r[0], r[1]))[0]
    return best[0], best[1], len(rows) - 1


# ---------- что будет записано ----------

def rows_for(disk, unit, chosen=None):
    """Строки ручных операций для единицы: chosen=None - целиком (одна строка), иначе - индексы отмеченных
    файлов внутри папки (строка на файл). Строка: (действие, диск, путь, диск2, путь2, файлов, байт)."""
    k = unit['kind']
    if chosen is None:
        items = [dict(path=unit.get('src') or unit['path'], dst=unit['path'], bytes=unit['bytes'], files=unit['files'])]
    else:
        items = []
        for i in chosen:
            ch = unit['children'][i]
            if k == 'move':
                items.append(dict(path=ch['path'], dst=ch['dst'], bytes=ch['bytes'], files=1))
            elif k == 'copy':
                items.append(dict(path=unit['src'] + ch['path'][len(unit['path']):], dst=ch['path'], bytes=ch['bytes'], files=1))
            else:
                items.append(dict(path=ch['path'], dst=ch['path'], bytes=ch['bytes'], files=1))
    res = []
    for it in items:
        if k == 'gone':
            res.append(('удалено', disk, it['path'], '', '', it['files'], it['bytes']))
        elif k == 'move':
            res.append(('перемещено', disk, it['path'], disk, it['dst'], it['files'], it['bytes']))
        elif k == 'copy':
            res.append(('скопировано', unit['src_disk'], it['path'], disk, it['dst'], it['files'], it['bytes']))
    return res


def summary(rows):
    """«Будет записано: удалено - 3 папки и 5 файлов (1 240 файлов, 12,00 ГБ); …»"""
    if not rows:
        return 'Ничего не отмечено.'
    names = {'удалено': 'удалено', 'перемещено': 'перемещено внутри диска', 'скопировано': 'скопировано с других дисков'}
    parts = []
    for act in ('удалено', 'перемещено', 'скопировано'):
        rs = [r for r in rows if r[0] == act]
        if not rs:
            continue
        nf = sum(1 for r in rs if len(r) > 7 and r[7])          # r[7] - строка на папку целиком
        nfile = len(rs) - nf
        what = ' и '.join(x for x in (plural(nf, 'папка', 'папки', 'папок') if nf else '',
                                       plural(nfile, 'файл', 'файла', 'файлов') if nfile else '') if x)
        files = f'{plural(sum(r[5] for r in rs), "файл", "файла", "файлов")}, ' if nf else ''
        parts.append(f'{names[act]} — {what} ({files}{gb_text(sum(r[6] or 0 for r in rs))})')
    return 'Будет записано: ' + '; '.join(parts) + '.'


def selection_rows(diff, choice):
    """choice: {номер единицы: None (целиком) или [индексы файлов]}. Строки с признаком «папка» в конце."""
    rows = []
    for i, chosen in sorted(choice.items()):
        u = diff.units[i]
        for r in rows_for(diff.disk, u, chosen):
            rows.append(r + (u['is_dir'] and chosen is None,))
    return rows
