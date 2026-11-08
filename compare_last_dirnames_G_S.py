#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from openpyxl import load_workbook, Workbook

BASE_DIR = Path(r"E:\Диски с фото и видео - оптимизация каталог")

# Новый список папок диска G (полный архив)
G_FILE = BASE_DIR / "Список папок - диск Полный архив Фото и Видео.xlsx"
# Новый список папок диска S (бэкап)
S_FILE = BASE_DIR / "Список папок - диск Бэкап фото и видео.xlsx"

OUT_G_NOT_S = BASE_DIR / "Конечные_папки_G_нет_на_S.xlsx"
OUT_S_NOT_G = BASE_DIR / "Конечные_папки_S_нет_на_G.xlsx"


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
    print("Читаю список папок диска G...")
    g_names, g_name_to_full = load_names_from_excel(G_FILE)

    print("Читаю список папок диска S...")
    s_names, s_name_to_full = load_names_from_excel(S_FILE)

    print(f"Уникальных имён конечных папок G: {len(g_names)}")
    print(f"Уникальных имён конечных папок S: {len(s_names)}")

    # 1) Имя папки есть на G, но нет на S
    write_diff(
        OUT_G_NOT_S,
        title="G_not_S",
        base_names=g_names,
        base_name_to_full=g_name_to_full,
        other_names=s_names,
        note="Имя папки есть на диске G, нет на диске S",
    )

    # 2) Имя папки есть на S, но нет на G
    write_diff(
        OUT_S_NOT_G,
        title="S_not_G",
        base_names=s_names,
        base_name_to_full=s_name_to_full,
        other_names=g_names,
        note="Имя папки есть на диске S, нет на диске G",
    )


if __name__ == "__main__":
    main()
