#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook

# Папка, где лежат файлы и скрипт
BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

# Файлы 1 и 3
BACKUP_FILE = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"
TRIPS_FILE = BASE_DIR / "Список папок диска Путешествия 2018-2025.xlsx"

# Куда сохранить результат
OUTPUT_FILE = BASE_DIR / "Папки_есть_в_Путешествиях_нет_в_Бэкапе.xlsx"


def load_paths_from_excel(xlsx_path):
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    paths = set()

    # Заголовок в строке 1, пути в колонке A начиная со строки 2
    for row in ws.iter_rows(min_row=2, values_only=True):
        path = row[0]
        if path:
            paths.add(str(path).strip())
    wb.close()
    return paths


def main():
    print("Читаю папки из файла Бэкапа...")
    backup_paths = load_paths_from_excel(BACKUP_FILE)
    print(f"  Папок в Бэкапе: {len(backup_paths)}")

    print("Читаю папки из файла Путешествия...")
    trips_paths = load_paths_from_excel(TRIPS_FILE)
    print(f"  Папок в Путешествиях: {len(trips_paths)}")

    # Какие папки есть в Путешествиях, но отсутствуют в Бэкапе
    missing_in_backup = sorted(trips_paths - backup_paths)
    print(f"Папок, которые есть в Путешествиях и отсутствуют в Бэкапе: {len(missing_in_backup)}")

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Нет_в_Бэкапе"
    ws_out["A1"] = "Путь (есть в Путешествиях, нет в Бэкапе)"

    row = 2
    for p in missing_in_backup:
        ws_out.cell(row=row, column=1, value=p)
        row += 1

    wb_out.save(OUTPUT_FILE)
    print(f"Готово. Результат: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
