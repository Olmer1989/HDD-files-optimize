"""Подозрение на повреждение: одинаковые имя, размер и дата изменения, но разный SHA-256.

Такие копии не считаются ни дублем, ни уникальным файлом, и ни одну из них нельзя
удалять, пока пользователь не решит, какая правильная (третья копия или просмотр).
Только чтение описей. Результат: Каталог дисков\\Проверка - подозрение на повреждение <дата>.xlsx

Запуск:  py catalog\\find_suspects.py
"""
import collections
import datetime as dt
import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import build_pilot as bp

SEP = '\\'


def main():
    groups = collections.defaultdict(list)
    for disk, job in bp.find_jobs().items():
        with sqlite3.connect(f"file:{job['dir'] / 'hashes.sqlite'}?mode=ro", uri=True) as c:
            for path, size, mtime, sha in c.execute(
                    "select path, size, mtime_ns, sha256 from hashes where status='verified'"):
                name = path.replace('/', SEP).split(SEP)[-1].lower()
                groups[(name, size, str(mtime))].append((disk, path, sha))

    wb = Workbook()
    ws = wb.active
    ws.title = 'Подозрение на повреждение'
    head = ['Группа', 'Носитель', 'Путь', 'Размер, ГБ', 'SHA-256 (начало)', 'Сколько копий с этим хешем',
            'Вариантов хеша в группе', 'Какая правильная (решение)']
    for c, h in enumerate(head, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='F8D7DA')
    row = 2
    total = 0
    keyed = sorted(((k, g) for k, g in groups.items() if len({s for _, _, s in g}) > 1), key=lambda kg: -kg[0][1])
    for n, (key, g) in enumerate(keyed, 1):
        counts = collections.Counter(sha for _, _, sha in g)
        total += key[1]
        for disk, path, sha in sorted(g):
            for c, v in enumerate([n, disk, path, key[1] / 1024 ** 3, sha[:16], counts[sha], len(counts), ''], 1):
                ws.cell(row=row, column=c, value=v)
            ws.cell(row=row, column=4).number_format = '#,##0.00'
            row += 1
    for c, w in enumerate([8, 10, 110, 11, 20, 12, 12, 24], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:H{row - 1}'
    bp.OUT_DIR.mkdir(exist_ok=True)
    out = bp.OUT_DIR / f'Проверка - подозрение на повреждение {dt.datetime.now():%Y-%m-%d %H-%M}.xlsx'
    wb.save(out)
    print(f'Групп: {len(keyed)}, файлов: {row - 2}, объём одной копии на группу: {total / 1024 ** 3:,.1f} ГБ')
    print('Готово:', out)
    return keyed


if __name__ == '__main__':
    main()
