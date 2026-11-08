#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook


BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

# Путешествия 2018-2025 (диск S)
TRIPS_FILE = BASE_DIR / "Список папок диска Путешествия 2018-2025.xlsx"

# Бэкап фото и видео (диск S/G – неважно, главное другой список)
BACKUP_FILE = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"

OUT_TRIPS_NOT_BACKUP = BASE_DIR / "Папки_Путешествия_нет_в_Бэкапе.xlsx"
OUT_BACKUP_NOT_TRIPS = BASE_DIR / "Папки_Бэкап_нет_в_Путешествиях.xlsx"


def normalize_path(p: str) -> str:
    p = p.strip()
    if len(p) >= 3 and p[1:3] == r":\\":
        return p[3:]
    return p


def load_paths_from_excel(xlsx_path: Path):
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    abs_paths = set()
    rel_paths = set()

    for row in ws.iter_rows(min_row=2, values_only=True):
        path = row[0]
        if not path:
            continue
        path_str = str(path).strip()
        abs_paths.add(path_str)
        rel_paths.add(normalize_path(path_str))

    wb.close()
    return abs_paths, rel_paths


def write_result(output_path: Path, title: str, rel_set, abs_set, other_rel_set, note: str):
    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = title[:31]  # на всякий случай режем до 31 символа [web:59][web:85]

    ws_out["A1"] = "Относительный путь"
    ws_out["B1"] = "Пример полного пути"
    ws_out["C1"] = note

    diff = sorted(rel_set - other_rel_set)

    row = 2
    for rel in diff:
        ws_out.cell(row=row, column=1, value=rel)

        full_path = None
        for p in abs_set:
            if normalize_path(p) == rel:
                full_path = p
                break

        if full_path:
            ws_out.cell(row=row, column=2, value=full_path)

        row += 1

    wb_out.save(output_path)
    print(f"Сохранён файл: {output_path} (кол-во строк: {len(diff)})")


def main():
    print("Читаю списки папок из файлов...")
    trips_abs, trips_rel = load_paths_from_excel(TRIPS_FILE)
    backup_abs, backup_rel = load_paths_from_excel(BACKUP_FILE)

    print(f"Уникальных относительных путей в Путешествиях: {len(trips_rel)}")
    print(f"Уникальных относительных путей в Бэкапе:       {len(backup_rel)}")

    # 1) Есть в Путешествиях, нет в Бэкапе
    write_result(
        OUT_TRIPS_NOT_BACKUP,
        title="Trips_not_Backup",
        rel_set=trips_rel,
        abs_set=trips_abs,
        other_rel_set=backup_rel,
        note="Есть в Путешествиях, нет в Бэкапе",
    )

    # 2) Есть в Бэкапе, нет в Путешествиях
    write_result(
        OUT_BACKUP_NOT_TRIPS,
        title="Backup_not_Trips",
        rel_set=backup_rel,
        abs_set=backup_abs,
        other_rel_set=trips_rel,
        note="Есть в Бэкапе, нет в Путешествиях",
    )


if __name__ == "__main__":
    main()
