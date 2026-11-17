"""Логика v3, ядро разбора носителя: «Пересчитать хеши спорных файлов».
Часть бывшего hb_core/razbor.py (разбит 17.11.2026, код дословно)."""
import collections
from hb_core.consts import MAIN, SEP
from hb_core.util import parent_of, prefix_cond
from hb_core.query import _keys

# ---------- «Пересчитать хеши спорных файлов» (после ответа «НЕТ»/«НЕДОСТАТОЧНО» в candel) ----------

WHY_NOHASH = 'без хеша на этом носителе'
EV_WORD = {'Z': 'сверен только размер', 'U': 'со слов владельца', 'X': 'файл изменился после подсчёта хеша'}


def contested_rows(c, disk, folder, main=MAIN):
    """Спорные файлы поштучно (этап 16; правила - как у contested, contested - их свёртка по папкам): на проверяемом
    носителе - файлы без хеша (кроме пустых); на дисках-копиях (45, 77) - тёзки без хеша (то же имя и размер) файлов
    проверяемой папки и записи с ожидаемым хешем (Z/U/X) из хешей папки. Файл (диск, путь) - один раз, причины через
    «; ». Ничего не сканирует и не пишет. -> [(диск, путь, размер, дата, ev, причина)]."""
    folder = (folder or '').strip(SEP)
    cond, args = prefix_cond('path', folder)
    rows = {}

    def add(d, p, s, mt, ev, why):
        cur = rows.get((d, p))
        if cur is None:
            rows[(d, p)] = [s, mt, ev, [why]]
        elif why not in cur[3]:
            cur[3].append(why)
    keys, shas = set(), set()
    for p, s, nm, sha, mt, ev in c.execute(f'select path, size, name_lc, sha, mtime, ev from files where disk=? and {cond}',
                                           [disk] + args):
        if sha:
            shas.add(sha)
            keys.add((nm, s))
        elif s:
            add(disk, p, s, mt, ev, WHY_NOHASH)
            keys.add((nm, s))
    if keys:
        _keys(c, 'ct_k', ('name_lc', 'size'), keys)
        for d in main:
            excl, eargs = '', []
            if d == disk:
                ec, eargs = prefix_cond('g.path', folder)
                excl = f' and not ({ec})'
            q = f"""select g.path, g.size, g.mtime, g.ev from ct_k k cross join files g indexed by files_name
                    on g.name_lc=k.name_lc and g.size=k.size and g.disk=? where g.sha is null and g.size>0{excl}"""
            for p, s, mt, ev in c.execute(q, [d] + eargs):
                add(d, p, s, mt, ev, f'тёзка без хеша: то же имя и размер, что у файла {disk}')
    if shas:
        c.execute('create temp table if not exists ct_s(sha text primary key)')
        c.execute('delete from ct_s')
        c.executemany('insert or ignore into ct_s values (?)', ((x,) for x in shas))
        for d in main:
            # индекс files_exp - явно: без него (дата и степень не в индексе) SQLite выбирал проход по всему диску
            for p, s, mt, ev in c.execute('select g.path, g.size, g.mtime, g.ev from ct_s s cross join files g '
                                          'indexed by files_exp on g.sha_exp=s.sha and g.disk=? '
                                          "where g.sha_exp is not null and coalesce(g.ev, '') not in ('S', 'C')",
                                          (d,)):          # подтверждённая запись спорной не бывает (раздел 4)
                add(d, p, s, mt, ev, f'копия не проверена ({EV_WORD.get(ev, ev or "?")})')
    return [(d, p, v[0], v[1], v[2], '; '.join(v[3])) for (d, p), v in rows.items()]


def contested(c, disk, folder, main=MAIN):
    """Папки, где пересканирование с хешем всех файлов может снять сомнение - свёртка contested_rows по папкам (этап
    16: файл, попавший по двум причинам, считается один раз). Ничего не сканирует.
    -> {диск: [(папка, файлов)]}; вложенные папки, чей предок уже в списке, свёрнуты в предка."""
    res = collections.defaultdict(collections.Counter)
    for d, p, _s, _mt, _ev, _why in contested_rows(c, disk, folder, main):
        res[d][parent_of(p)] += 1
    out = {}
    for d, cnt in res.items():
        tops = []
        for f in sorted(cnt, key=lambda x: (x.count(SEP) + 1 if x else 0, x)):
            t = next((t for t in tops if t == '' or f == t or f.startswith(t + SEP)), None)
            if t is None:
                tops.append(f)
        agg = collections.Counter()
        for f, n in cnt.items():
            t = next(t for t in tops if t == '' or f == t or f.startswith(t + SEP))
            agg[t] += n
        out[d] = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
    return out
