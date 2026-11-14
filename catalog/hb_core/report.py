"""Таблицы на экране и файлы ответов в «_БАЗА\ответы»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import csv
import io
import re
from hb_core import paths
from hb_core.util import gb, out


def save(name, head, rows):
    path = paths.ANSWERS / (re.sub(r'[\\/:*?"<>|]', '_', name) + '.tsv')
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_NONE, escapechar=None, quotechar=None)
        w.writerow(head)
        for r in rows:
            w.writerow(r)
    return path


def table(head, rows, limit=10, total=None):
    """Таблица на экран: не больше limit строк; total - итоговая строка, видна всегда."""
    rows = list(rows)
    shown = rows[:limit] + ([total] if total else [])
    widths = [max(len(str(h)), *(len(str(r[i])) for r in shown)) if shown else len(str(h)) for i, h in enumerate(head)]
    line = lambda r: '  '.join(str(x).ljust(w) if i == 0 else str(x).rjust(w) for i, (x, w) in enumerate(zip(r, widths)))
    out(line(head))
    for r in rows[:limit]:
        out(line(r))
    if len(rows) > limit:
        out(f'... ещё {len(rows) - limit} строк - см. файл')
    if total:
        out(line(total))


def type_cols(r, k=0):
    """ГБ по типам из строки folders, начиная с колонки n0 (k - её номер)."""
    return [gb(r[k + 1 + 2 * i]) for i in range(5)]
