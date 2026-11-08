#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
index_drive.py — сканирование одного диска и сохранение индекса в текстовый файл.

Что делает скрипт:
  - Рекурсивно обходит указанный диск (или папку).
  - Берёт только файлы с расширениями .jpg .jpeg .raw .cr2 .nef .dng .mov .mp4 .avi
    (любого регистра — JPG, Jpg, jpg и т. п. учитываются).
  - Игнорирует файлы меньше 1 МБ (1 048 576 байт).
  - Для каждого подходящего файла записывает строку вида:
        <размер_в_байтах>\\t<полный_путь>
    Разделитель — табуляция, чтобы пути с пробелами и кириллицей читались надёжно.

Для чего:
  Один раз создать индексы по дискам G и S (основные), потом многократно
  индексировать другие диски (F, V и т. д.) и сравнивать через find_missing.py.

Запуск:
  Открыть командную строку (cmd) в папке E:\\Диски с фото и видео - оптимизация каталог:
      cd /d "E:\\Диски с фото и видео - оптимизация каталог"

  И выполнить (по одному на каждый диск):
      py index_drive.py G:\\ index_G.txt
      py index_drive.py S:\\ index_S.txt
      py index_drive.py F:\\ index_F.txt

  Прогресс пишется в консоль каждые 5 секунд: «обработано N файлов, M ГБ».
  Скрипт пропускает недоступные файлы (отказ доступа, битые имена) и в конце
  выводит сколько таких пропущено.
"""

import os
import sys
import time
from pathlib import Path

# Расширения, которые нас интересуют. Регистр игнорируется при сравнении —
# для проверки берём суффикс файла в нижнем регистре.
EXTENSIONS = {'.jpg', '.jpeg', '.raw', '.cr2', '.nef', '.dng',
              '.mov', '.mp4', '.avi'}

# Минимальный размер файла, которые включаем в индекс.
MIN_SIZE_BYTES = 1 * 1024 * 1024   # 1 МБ

# Как часто печатать прогресс в консоль (секунды).
PROGRESS_INTERVAL_SEC = 5.0


def format_bytes(n):
    """Преобразует число байт в читаемый вид (ГБ или МБ)."""
    gb = n / (1024 ** 3)
    if gb >= 1.0:
        return f'{gb:.2f} ГБ'
    mb = n / (1024 ** 2)
    return f'{mb:.1f} МБ'


def index_drive(root_path: Path, output_path: Path):
    """Обход root_path и запись индекса в output_path.

    Возвращает кортеж: (количество_включённых_файлов, общий_размер_байт,
    количество_пропусков).
    """
    if not root_path.exists():
        print(f'❌ Путь не найден: {root_path}')
        sys.exit(1)

    print(f'Сканирую: {root_path}')
    print(f'Пишу индекс в: {output_path}')
    print(f'Расширения: {sorted(EXTENSIONS)}')
    print(f'Минимальный размер: {format_bytes(MIN_SIZE_BYTES)}')
    print()

    counted = 0
    total_bytes = 0
    skipped = 0
    last_print = time.monotonic()
    start = last_print

    # Открываем выходной файл в UTF-8 — чтобы кириллические пути писались
    # без проблем. newline='' — чтобы Python не подставлял \r\n под Windows
    # (мы всё равно пишем \n сами и хотим чистый формат).
    with output_path.open('w', encoding='utf-8', newline='') as out:
        # os.walk даёт обход всего дерева. errors='ignore' было бы хорошо,
        # но Python 3.10 поддерживает onerror — функция, которая вызывается
        # при ошибке доступа. Игнорируем тихо.
        def on_error(_e):
            nonlocal skipped
            skipped += 1

        for dirpath, dirnames, filenames in os.walk(
            str(root_path), onerror=on_error
        ):
            for fname in filenames:
                # Быстрый отсев по расширению — не дёргаем диск зря.
                # Path(fname).suffix даёт '.JPG' и т. п., приводим к нижнему.
                ext = os.path.splitext(fname)[1].lower()
                if ext not in EXTENSIONS:
                    continue

                full_path = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(full_path)
                except (OSError, PermissionError):
                    skipped += 1
                    continue

                if size < MIN_SIZE_BYTES:
                    continue

                # Пишем строку: размер<TAB>путь<NL>.
                # Путь сохраняем как есть (с буквой диска), чтобы потом
                # знать, на каком диске лежит файл.
                out.write(f'{size}\t{full_path}\n')
                counted += 1
                total_bytes += size

                # Прогресс — каждые 5 секунд.
                now = time.monotonic()
                if now - last_print >= PROGRESS_INTERVAL_SEC:
                    elapsed = now - start
                    speed = counted / elapsed if elapsed > 0 else 0
                    print(f'  ... обработано {counted:>9,d} файлов, '
                          f'{format_bytes(total_bytes)} '
                          f'(скорость {speed:.0f} файлов/с)')
                    last_print = now

    elapsed = time.monotonic() - start
    print()
    print(f'Готово за {elapsed:.0f} секунд ({elapsed/60:.1f} мин).')
    print(f'Включено в индекс: {counted:,d} файлов '
          f'({format_bytes(total_bytes)}).')
    if skipped:
        print(f'Пропущено из-за ошибок доступа: {skipped}.')
    print(f'Индекс сохранён: {output_path}')
    return counted, total_bytes, skipped


def main():
    if len(sys.argv) != 3:
        print('Использование:')
        print(r'  py index_drive.py <путь_к_корню_диска> <выходной_файл>')
        print()
        print('Примеры:')
        print(r'  py index_drive.py G:\ index_G.txt')
        print(r'  py index_drive.py S:\ index_S.txt')
        print(r'  py index_drive.py F:\ index_F.txt')
        sys.exit(1)

    root = Path(sys.argv[1])
    output = Path(sys.argv[2])

    index_drive(root, output)


if __name__ == '__main__':
    main()
