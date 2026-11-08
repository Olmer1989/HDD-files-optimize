#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path
from openpyxl import Workbook

BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

G_ROOT = Path(r"G:\\")
S_ROOT = Path(r"S:\\")

G_OUT = BASE_DIR / "Список папок - диск Полный архив Фото и Видео.xlsx"
S_OUT = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"


def collect_folders(root: Path, out_file: Path, sheet_title: str):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    ws["A1"] = "Путь"

    row = 2
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            full_path = Path(dirpath) / d
            ws.cell(row=row, column=1, value=str(full_path))
            row += 1

    wb.save(out_file)
    print(f"Сохранён файл: {out_file} (папок: {row-2})")


def main():
    print("Собираю папки диска G...")
    collect_folders(G_ROOT, G_OUT, "Папки_G")

    print("Собираю папки диска S...")
    collect_folders(S_ROOT, S_OUT, "Папки_S")

    print("Готово.")


if __name__ == "__main__":
    main()
