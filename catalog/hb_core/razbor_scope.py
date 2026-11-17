"""«Без хеша» в «Разборе носителя» (17.11.2026, решение владельца): только то, что пойдёт в копирование.

Ничего не сканирует и не пишет. Список файлов «к копированию» даёт planner(collect=…) - тот же расчёт, что суммы
итога (наследование отметок, типы направления, «документы рядом»); здесь - только свёртка этого списка:
- N - файлы без хеша, которые реально пишутся хотя бы на один диск направления (вид 'nohash'; заблокированные - нет);
- папки для пересканирования - родители этих файлов (не свёрнутые до отмеченной папки: сканер идёт вглубь, лишнее
  поддерево - лишнее чтение); вложенная папка, чей предок уже в списке, не повторяется;
- непрочитанные - файлы, которые при ПЕРЕсканировании снова не прочитались (issues с kind UNREAD_KIND, пишет
  apply_partial): planner их не копирует (причина B_UNREAD), здесь - отдельный список;
- K - возможные копии на дисках направления: тот же (имя, размер), у архивного файла нет хеша (как тёзки в
  contested_rows), только для файлов, которые пойдут на этот диск.
"""
import collections

from hb_core.consts import CAT_OF_TYPE, SEP, UNREAD_KIND
from hb_core.util import name_key, parent_of

B_UNREAD = 'не прочитан'                                     # причина блокировки в planner (файл не копируется)
SHOW_MAX = 2000                                              # путей для «Показать» (число - всегда полное)


def top_folders(need):
    """Самые верхние папки набора: папка, чей предок уже в наборе, не берётся ('' - корень - покрывает всё)."""
    tops = set()
    for f in sorted(need, key=lambda x: (x.count(SEP), x)):
        if '' in tops:
            break
        p, inside = f, False
        while p:
            if p in tops:
                inside = True
                break
            p = parent_of(p)
        if not inside:
            tops.add(f)
    return tops


def unread_files(c, disk):
    """Файлы носителя, которые при пересканировании снова не прочитались: {путь: причина}."""
    return dict(c.execute('select path, note from issues where disk=? and kind=?', (disk, UNREAD_KIND)))


def scan_folders(paths):
    """Папки для окна пересканирования: родители файлов без вложенных повторов, корень носителя - отдельно.
    -> (папки по алфавиту, файлов в корне)."""
    parents = collections.Counter(parent_of(p) for p in paths)
    root = parents.pop('', 0)
    return sorted(top_folders(parents)), root


def _cats(ks):
    return sorted({CAT_OF_TYPE[k] for k in ks if CAT_OF_TYPE.get(k)})


def nohash_scope(items, disks, carrier, blocked=(), unread=None):
    """Свёртка списка collect направления (исход «копировать»). disks - диски направления; blocked - P.blocked;
    unread - {путь: причина}. -> dict(n, bytes, folders, root, cats, sample, unread=[(путь, причина, размер)])."""
    targets = [d for d in disks if d != carrier]
    nh = [it for it in items if it[2] is None and any(it[6].get(d, ('nohash',))[0] == 'nohash' for d in targets
                                                      if d in it[5])]
    folders, root = scan_folders([it[0] for it in nh])
    unread = unread or {}
    seen, bad = set(), []
    for path, d, why, size in blocked:
        if why == B_UNREAD and d in targets and path not in seen:
            seen.add(path)
            bad.append((path, unread.get(path, ''), size))
    return dict(n=len(nh), bytes=sum(it[1] for it in nh), folders=folders, root=root, cats=_cats(it[3] for it in nh),
                sample=sorted(it[0] for it in nh)[:SHOW_MAX], unread=sorted(bad))


def namesakes_nohash(c, items, disks, carrier):
    """K по каждому диску направления: файлы диска без хеша (размер > 0, как в contested_rows) с тем же (имя, размер),
    что у файла, который пойдёт на этот диск (с хешем или без; заблокированные - нет).
    -> {диск: dict(k, folders, root, cats, sample)}."""
    out = {}
    c.execute('create temp table if not exists rs_k(name_lc text, size integer, primary key(name_lc, size))')
    for d in disks:
        if d == carrier:
            continue
        keys = {}
        for it in items:
            if it[1] and d in it[5] and it[6].get(d, ('nohash',))[0] != 'blocked':
                keys.setdefault((name_key(it[0]), it[1]), set()).add(it[3])
        c.execute('delete from rs_k')
        c.executemany('insert or ignore into rs_k values (?, ?)', keys)
        hits = c.execute('select g.path, g.name_lc, g.size from rs_k k cross join files g indexed by files_name '
                         'on g.name_lc=k.name_lc and g.size=k.size and g.disk=? where g.sha is null and g.size>0',
                         (d,)).fetchall()
        folders, root = scan_folders([p for p, _n, _s in hits])
        out[d] = dict(k=len(hits), folders=folders, root=root,
                      cats=_cats(k for _p, nm, s in hits for k in keys.get((nm, s), ())),
                      sample=sorted(p for p, _n, _s in hits)[:SHOW_MAX])
    return out
