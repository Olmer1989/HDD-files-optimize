#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook

BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

# Путешествия 2018-2025
TRIPS_FILE  = BASE_DIR / "Список папок диска Путешествия 2018-2025.xlsx"
# Бэкап фото и видео
BACKUP_FILE = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"

OUT_TRIPS_NOT_BACKUP  = BASE_DIR / "Конечные_папки_Путешествия_нет_в_Бэкапе.xlsx"
OUT_BACKUP_NOT_TRIPS  = BASE_DIR / "Конечные_папки_Бэкап_нет_в_Путешествиях.xlsx"


def get_last_component(path_str: str) -> str:
    """Возвращает имя конечной папки из пути."""
    p = path_str.replace("/", "\\").rstrip("\\").strip()
    return p.split("\\")[-1]


def load_names_from_excel(xlsx_path: Path):
    """
    Возвращает:
      - множество имён конечных папок,
      - словарь {имя_конечной_папки: один_из_полных_путей}.
    """
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    names_set = set()
    name_to_full = {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        path = row[0]
        if not path:
            continue
        full = str(path).strip()
        last = get_last_component(full)
        names_set.add(last)
        if last not in name_to_full:
            name_to_full[last] = full

    wb.close()
    return names_set, name_to_full


def write_diff(output_path: Path,
               title: str,
               base_names, base_name_to_full,
               other_names,
               note: str):
    """Пишет Excel с именами папок, которых нет во втором списке."""
    diff_names = sorted(base_names - other_names)

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = title[:31]

    ws_out["A1"] = "Имя конечной папки"
    ws_out["B1"] = "Пример полного пути"
    ws_out["C1"] = note

    row = 2
    for name in diff_names:
        ws_out.cell(row=row, column=1, value=name)
        ws_out.cell(row=row, column=2, value=base_name_to_full.get(name, ""))
        row += 1

    wb_out.save(output_path)
    print(f"Сохранён файл: {output_path} (строк: {len(diff_names)})")


def main():
    print("Читаю Путешествия...")
    trips_names, trips_name_to_full = load_names_from_excel(TRIPS_FILE)
    print("Читаю Бэкап...")
    backup_names, backup_name_to_full = load_names_from_excel(BACKUP_FILE)

    print(f"Уникальных имён конечных папок Путешествия: {len(trips_names)}")
    print(f"Уникальных имён конечных папок Бэкап:       {len(backup_names)}")

    # 1) Имя папки есть в Путешествиях, но нет в Бэкапе
    write_diff(
        OUT_TRIPS_NOT_BACKUP,
        title="Trips_not_Backup",
        base_names=trips_names,
        base_name_to_full=trips_name_to_full,
        other_names=backup_names,
        note="Имя папки есть в Путешествиях, нет в Бэкапе",
    )

    # 2) Имя папки есть в Бэкапе, но нет в Путешествиях
    write_diff(
        OUT_BACKUP_NOT_TRIPS,
        title="Backup_not_Trips",
        base_names=backup_names,
        base_name_to_full=backup_name_to_full,
        other_names=trips_names,
        note="Имя папки есть в Бэкапе, нет в Путешествиях",
    )


if __name__ == "__main__":
    main()
