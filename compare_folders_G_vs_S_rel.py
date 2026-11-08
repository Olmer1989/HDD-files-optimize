#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook

# Пути к Excel с папками
G_FILE = Path(r"G:\folders.xlsx")  # список папок с диска G
S_FILE = Path(r"S:\folders.xlsx")  # список папок с диска S

# Куда сохранить результат
OUTPUT_FILE = Path(r"G:\folders_missing_on_S_rel.xlsx")


def normalize_path(p: str) -> str:
    """
    Превращает 'G:\\Алтай 2023' или 'S:\\Алтай 2023'
    в 'Алтай 2023' (то есть убираем букву диска и обратный слеш).
    """
    p = p.strip()
    if len(p) >= 3 and p[1:3] == r":\\":
        return p[3:]  # всё после 'X:\'
    return p


def load_paths_from_excel(xlsx_path):
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    paths_abs = set()
    paths_rel = set()

    for row in ws.iter_rows(min_row=2, values_only=True):
        path = row[0]
        if not path:
            continue
        path_str = str(path).strip()
        paths_abs.add(path_str)
        paths_rel.add(normalize_path(path_str))

    wb.close()
    return paths_abs, paths_rel


def main():
    print("Читаю папки с диска G...")
    g_abs, g_rel = load_paths_from_excel(G_FILE)
    print(f"  Папок на G (уникальных относительных): {len(g_rel)}")

    print("Читаю папки с диска S...")
    s_abs, s_rel = load_paths_from_excel(S_FILE)
    print(f"  Папок на S (уникальных относительных): {len(s_rel)}")

    # Какие относительные папки есть на G, но нет на S
    missing_rel = sorted(g_rel - s_rel)
    print(f"Папок (по относительным путям), которых нет на S: {len(missing_rel)}")

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Нет_на_S"

    ws_out["A1"] = "Относительный путь (G есть, S нет)"
    ws_out["B1"] = "Полный путь на G (если найден)"

    row = 2
    for rel in missing_rel:
        ws_out.cell(row=row, column=1, value=rel)

        # Попробуем восстановить один пример полного пути на G
        # (берём любой из тех, что начинаются с этого относительного пути)
        full_match = None
        for p in g_abs:
            if normalize_path(p) == rel:
                full_match = p
                break

        if full_match:
            ws_out.cell(row=row, column=2, value=full_match)

        row += 1

    wb_out.save(OUTPUT_FILE)
    print(f"Готово. Результат: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
