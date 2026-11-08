#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_missing.py — сравнение индекса одного диска с индексами G и S.

Что делает скрипт:
  - Читает индекс «проверяемого» диска (например, F).
  - Читает индексы дисков G и S (основные).
  - Для каждого файла с проверяемого диска проверяет: есть ли где-нибудь
    на G или S файл с таким же именем (без учёта регистра) и таким же
    размером в байтах.
  - Файлы, которые НЕ нашлись ни на G, ни на S, пишет в Excel-таблицу.
  - Дополнительно: файлы, которые нашлись, выгружает в отдельный
    Excel-файл — там видно, в какой папке на G/S лежит совпадающий
    файл (а если есть несколько совпадений — все они в одной строке
    через перенос строки).

Колонки выходного Excel (отсутствующие):
  A — Имя файла
  B — Размер (байт)
  C — Размер (читаемо: МБ или ГБ)
  D — Конечная папка (та, в которой лежит файл)
  E — Последние 3 папки в пути (компактный ориентир)
  F — Полный путь на проверяемом диске

Колонки выходного Excel (найденные совпадения):
  A — Имя файла
  B — Размер (байт)
  C — Размер (читаемо: МБ или ГБ)
  D — Конечная папка
  E — Последние 3 папки в пути
  F — Полный путь на проверяемом диске
  G — Где лежит на G/S (один или несколько путей через перенос строки)

Запуск (из папки E:\\Диски с фото и видео - оптимизация каталог):
  py find_missing.py index_F.txt index_G.txt index_S.txt missing_F.xlsx

Ещё будет создан файл found_F.xlsx (рядом с missing_F.xlsx) — со
списком найденных совпадений.

Сравнение по правилу:
  ИМЯ ФАЙЛА (без учёта регистра) + РАЗМЕР В БАЙТАХ.
  Это надёжно для камерных файлов (IMG_NNNN.JPG, MVI_NNNN.MOV) и
  не требует чтения содержимого файлов.
"""

import os
import sys
import time
from pathlib import Path
from collections import defaultdict

from openpyxl import Workbook


def format_bytes(n):
    """Читаемый размер."""
    gb = n / (1024 ** 3)
    if gb >= 1.0:
        return f'{gb:.2f} ГБ'
    mb = n / (1024 ** 2)
    return f'{mb:.1f} МБ'


def get_filename(full_path: str) -> str:
    """Извлечь имя файла из пути.

    Работает с обоими разделителями (\\ и /), независимо от того,
    на какой ОС запущен скрипт. os.path.basename() на Linux не считает
    обратный слеш разделителем, поэтому для надёжности делаем сами.
    """
    s = full_path.replace('/', '\\').rstrip('\\')
    return s.split('\\')[-1]


def split_path_components(full_path: str):
    """Разбить полный путь на компоненты-папки.

    Корректно работает и с путями Windows ('E:\\Папка\\Под\\file.mp4'),
    и с unix-стилем. Возвращает список компонентов БЕЗ имени файла и
    БЕЗ корня (буква диска отбрасывается).

    Пример:
      'E:\\САФАРИ\\Проверенные исходники\\Hunting.mp4'
      → ['САФАРИ', 'Проверенные исходники']
    """
    # Унифицируем разделители.
    s = full_path.replace('/', '\\').rstrip('\\')
    parts = s.split('\\')
    # parts[0] — это либо буква диска ('E:'), либо первый компонент пути.
    # parts[-1] — имя файла. Отбрасываем имя файла и корень.
    if len(parts) <= 1:
        return []
    # Первый элемент: 'E:' для Windows-абсолютного пути — отбросить.
    # Если первый элемент пуст (был ведущий слеш в unix-стиле) — тоже отбросить.
    middle = parts[1:-1]
    if parts[0].endswith(':') or parts[0] == '':
        # буква диска или пустой корень — уже учтено через [1:-1]
        pass
    else:
        # если первый элемент — реальная папка (относительный путь),
        # его не отбрасываем
        middle = parts[:-1]
    return middle


def last_three_dirs(full_path: str) -> str:
    """Вернуть последние 3 папки вложения в виде 'A\\B\\C'.

    Если папок меньше трёх — вернуть сколько есть.
    """
    parts = split_path_components(full_path)
    return '\\'.join(parts[-3:]) if parts else ''


def final_dir(full_path: str) -> str:
    """Вернуть имя конечной папки (та, в которой лежит файл)."""
    parts = split_path_components(full_path)
    return parts[-1] if parts else ''


def load_index(index_path: Path):
    """Прочитать файл-индекс.

    Каждая строка — '<размер>\\t<полный_путь>'.
    Возвращает список кортежей (size:int, full_path:str, name_lower:str).
    """
    if not index_path.exists():
        print(f'❌ Файл индекса не найден: {index_path}')
        sys.exit(1)

    items = []
    with index_path.open('r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.rstrip('\n').rstrip('\r')
            if not line:
                continue
            try:
                size_str, path = line.split('\t', 1)
                size = int(size_str)
            except ValueError:
                print(f'  ⚠ Не могу разобрать строку {line_num} в '
                      f'{index_path}: {line[:80]!r}')
                continue
            name = get_filename(path).lower()
            items.append((size, path, name))
    return items


def build_lookup(items):
    """Построить таблицу для быстрого поиска.

    Ключ — (имя_в_нижнем_регистре, размер). Значение — список путей
    (на G или S может быть несколько копий одного файла в разных папках).
    """
    lookup = defaultdict(list)
    for size, path, name in items:
        lookup[(name, size)].append(path)
    return lookup


def main():
    if len(sys.argv) != 5:
        print('Использование:')
        print(r'  py find_missing.py <индекс_проверяемого> <индекс_G> '
              r'<индекс_S> <выходной_xlsx>')
        print()
        print('Пример:')
        print(r'  py find_missing.py index_F.txt index_G.txt index_S.txt '
              r'missing_F.xlsx')
        sys.exit(1)

    src_index_path = Path(sys.argv[1])    # проверяемый (например F)
    g_index_path = Path(sys.argv[2])      # основной G
    s_index_path = Path(sys.argv[3])      # основной S
    output_path = Path(sys.argv[4])       # куда сохранить «отсутствующие»

    # Имя файла «найденные совпадения» делаем рядом, заменяя приставку.
    # missing_F.xlsx -> found_F.xlsx
    out_stem = output_path.stem
    if out_stem.lower().startswith('missing'):
        found_stem = 'found' + out_stem[len('missing'):]
    else:
        found_stem = out_stem + '_found'
    found_path = output_path.with_name(found_stem + output_path.suffix)

    print(f'Проверяемый индекс:  {src_index_path}')
    print(f'Индекс G:            {g_index_path}')
    print(f'Индекс S:            {s_index_path}')
    print(f'Отсутствующие → :    {output_path}')
    print(f'Найденные →     :    {found_path}')
    print()

    print('Читаю индексы...')
    t0 = time.monotonic()
    src_items = load_index(src_index_path)
    g_items = load_index(g_index_path)
    s_items = load_index(s_index_path)
    print(f'  {src_index_path.name}: {len(src_items):>9,d} файлов')
    print(f'  {g_index_path.name}:   {len(g_items):>9,d} файлов')
    print(f'  {s_index_path.name}:   {len(s_items):>9,d} файлов')

    print('Строю таблицы поиска...')
    g_lookup = build_lookup(g_items)
    s_lookup = build_lookup(s_items)
    print(f'  Уникальных (имя+размер) на G: {len(g_lookup):,d}')
    print(f'  Уникальных (имя+размер) на S: {len(s_lookup):,d}')

    print('Сравниваю...')
    missing = []   # список (size, src_path, name)
    found = []     # список (size, src_path, name, [пути_на_GS])

    for size, src_path, name in src_items:
        key = (name, size)
        matches = g_lookup.get(key, []) + s_lookup.get(key, [])
        if matches:
            found.append((size, src_path, name, matches))
        else:
            missing.append((size, src_path, name))

    elapsed = time.monotonic() - t0
    print(f'Готово за {elapsed:.1f} с.')
    print()

    src_count = len(src_items)
    miss_count = len(missing)
    found_count = len(found)
    miss_size = sum(s for s, _, _ in missing)
    found_size = sum(s for s, _, _, _ in found)

    print(f'Итого по {src_index_path.name}:')
    print(f'  Всего файлов в индексе:   {src_count:>9,d} '
          f'({format_bytes(sum(s for s, _, _ in src_items))})')
    print(f'  Отсутствуют на G и на S:  {miss_count:>9,d} '
          f'({format_bytes(miss_size)})')
    print(f'  Есть на G или на S:       {found_count:>9,d} '
          f'({format_bytes(found_size)})')
    print()

    # ----- Запись «отсутствующих» -----
    print('Пишу Excel с отсутствующими файлами...')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Отсутствующие'
    ws['A1'] = 'Имя файла'
    ws['B1'] = 'Размер (байт)'
    ws['C1'] = 'Размер'
    ws['D1'] = 'Конечная папка'
    ws['E1'] = 'Последние 3 папки'
    ws['F1'] = 'Путь на проверяемом диске'

    # Сортировка: по убыванию размера, потом по пути. Так в начале списка
    # будут самые «жирные» потери.
    missing.sort(key=lambda x: (-x[0], x[1]))
    for i, (size, path, name) in enumerate(missing, start=2):
        ws.cell(row=i, column=1, value=get_filename(path))
        ws.cell(row=i, column=2, value=size)
        ws.cell(row=i, column=3, value=format_bytes(size))
        ws.cell(row=i, column=4, value=final_dir(path))
        ws.cell(row=i, column=5, value=last_three_dirs(path))
        ws.cell(row=i, column=6, value=path)

    # Чуть-чуть оформления — ширины колонок.
    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 30
    ws.column_dimensions['E'].width = 50
    ws.column_dimensions['F'].width = 80

    wb.save(output_path)
    print(f'  Сохранено: {output_path} ({miss_count:,d} строк)')

    # ----- Запись «найденных» -----
    print('Пишу Excel с найденными совпадениями...')
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.title = 'Найденные'
    ws2['A1'] = 'Имя файла'
    ws2['B1'] = 'Размер (байт)'
    ws2['C1'] = 'Размер'
    ws2['D1'] = 'Конечная папка'
    ws2['E1'] = 'Последние 3 папки'
    ws2['F1'] = 'Путь на проверяемом диске'
    ws2['G1'] = 'Совпадения на G и S'

    found.sort(key=lambda x: (-x[0], x[1]))
    for i, (size, path, name, matches) in enumerate(found, start=2):
        ws2.cell(row=i, column=1, value=get_filename(path))
        ws2.cell(row=i, column=2, value=size)
        ws2.cell(row=i, column=3, value=format_bytes(size))
        ws2.cell(row=i, column=4, value=final_dir(path))
        ws2.cell(row=i, column=5, value=last_three_dirs(path))
        ws2.cell(row=i, column=6, value=path)
        # Все совпадения — в одной ячейке, через перенос строки.
        ws2.cell(row=i, column=7, value='\n'.join(matches))

    ws2.column_dimensions['A'].width = 28
    ws2.column_dimensions['B'].width = 16
    ws2.column_dimensions['C'].width = 12
    ws2.column_dimensions['D'].width = 30
    ws2.column_dimensions['E'].width = 50
    ws2.column_dimensions['F'].width = 80
    ws2.column_dimensions['G'].width = 100

    wb2.save(found_path)
    print(f'  Сохранено: {found_path} ({found_count:,d} строк)')

    print()
    print('Всё готово.')


if __name__ == '__main__':
    main()
