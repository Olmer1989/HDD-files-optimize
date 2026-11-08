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
OUTPUT_FILE = BASE_DIR / "Папки_есть_в_Бэкапе_нет_в_Путешествиях.xlsx"


def load_paths_from_excel(xlsx_path):
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    paths = set()
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

    missing_in_trips = sorted(backup_paths - trips_paths)
    print(f"Папок, которые есть в Бэкапе и отсутствуют в Путешествиях: {len(missing_in_trips)}")

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Нет_в_Путешествиях"
    ws_out["A1"] = "Путь (есть в Бэкапе, нет в Путешествиях)"

    row = 2
    for p in missing_in_trips:
        ws_out.cell(row=row, column=1, value=p)
        row += 1

    wb_out.save(OUTPUT_FILE)
    print(f"Готово. Результат: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
