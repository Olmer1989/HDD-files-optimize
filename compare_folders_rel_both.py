#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook

# Папка, где лежат файлы и скрипт
BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

# Excel-файл для "полного архива" (диск G)  ← имя проверь по факту
G_FILE = BASE_DIR / "Список папок - диск Полный архив Фото и Видео.xlsx"

# Excel-файл для "бэкапа" (диск S)        ← имя проверь по факту
S_FILE = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"

# Файлы-результаты
OUT_G_NOT_S = BASE_DIR / "Папки_есть_в_Полном_архиве_нет_в_Бэкапе.xlsx"
OUT_S_NOT_G = BASE_DIR / "Папки_есть_в_Бэкапе_нет_в_Полном_архиве.xlsx"


def normalize_path(p: str) -> str:
    """
    'G:\\Алтай 2023' или 'S:\\Алтай 2023' -> 'Алтай 2023'
    (убираем букву диска и начальный слеш).
    """
    p = p.strip()
    if len(p) >= 3 and p[1:3] == r":\\":
        return p[3:]
    return p


def load_paths_from_excel(xlsx_path: Path):
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    abs_paths = set()
    rel_paths = set()

    # Заголовок в строке 1, пути в колонке A начиная со строки 2
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
    ws_out.title = title

    ws_out["A1"] = "Относительный путь"
    ws_out["B1"] = "Пример полного пути"
    ws_out["C1"] = note

    # Что есть в rel_set, но нет в other_rel_set
    diff = sorted(rel_set - other_rel_set)

    row = 2
    for rel in diff:
        ws_out.cell(row=row, column=1, value=rel)

        # Найдём пример полного пути
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
    g_abs, g_rel = load_paths_from_excel(G_FILE)
    s_abs, s_rel = load_paths_from_excel(S_FILE)

    print(f"Уникальных относительных путей в Полном архиве: {len(g_rel)}")
    print(f"Уникальных относительных путей в Бэкапе:       {len(s_rel)}")

    # 1) Есть в Полном архиве, нет в Бэкапе
    write_result(
        OUT_G_NOT_S,
        title="Есть_в_Полном_архиве_нет_в_Бэкапе",
        rel_set=g_rel,
        abs_set=g_abs,
        other_rel_set=s_rel,
        note="Есть в Полном архиве, нет в Бэкапе",
    )

    # 2) Есть в Бэкапе, нет в Полном архиве
    write_result(
        OUT_S_NOT_G,
        title="Есть_в_Бэкапе_нет_в_Полном_архиве",
        rel_set=s_rel,
        abs_set=s_abs,
        other_rel_set=g_rel,
        note="Есть в Бэкапе, нет в Полном архиве",
    )


if __name__ == "__main__":
    main()
