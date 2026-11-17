"""Окно «Список файлов»: строки модели без виджетов - подготовка, пути, запись Excel/CSV, курсор ожидания.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import csv

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

import service as sv

from .texts_list import norm
from .common import R_DISK, R_FOLDER, R_NAME, SEP, XLSX_MAX


class Busy:
    """Курсор ожидания на время сортировки и фильтра всего набора (510 тыс. строк: 0,2–1,2 с, замер критиков по коду)."""

    def __enter__(self):
        if QApplication.instance() is not None:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

    def __exit__(self, *exc):
        if QApplication.instance() is not None:
            QApplication.restoreOverrideCursor()


def place_of(r, letters):
    """«Где лежит» (этап 18): полный путь папки файла - с буквой подключённого носителя («F:\\Алёнкин клип»), иначе
    «HDD09\\Алёнкин клип». Пробелы в именах не трогаются."""
    return sv.full_path(r[R_DISK], r[R_FOLDER], letters)


def file_path(r, letters):
    """Полный путь файла строки (с буквой или номером носителя)."""
    return place_of(r, letters).rstrip(SEP) + SEP + r[R_NAME]


def prepare(data):
    """Строки service.file_list -> строки модели (в фоновом потоке): папка и имя - из пути без обрезки, нижний регистр
    для поиска (папки - общим кэшем)."""
    folders, flc = {}, {}
    rows = []
    for disk, path, size, mt, ev, k, why, where in data['rows']:
        i = path.rfind(SEP)
        folder, name = (path[:i], path[i + 1:]) if i >= 0 else ('', path)
        folder = folders.setdefault(folder, folder)
        lc = flc.get(folder)
        if lc is None:
            lc = flc[folder] = norm(folder)
        rows.append((disk, folder, name, k, sv.type5(k), size, mt, ev, why or '', where or '', lc, norm(name)))
    data['model_rows'] = rows
    return data


def save_table(path, heads, rows):
    """Запись видимых строк: .csv - UTF-8 с BOM, разделитель «;» (кавычки по правилам CSV - имена с «;» и кавычками
    не ломают столбцы); иначе .xlsx (openpyxl, потоковая запись). -> путь."""
    if str(path).lower().endswith('.csv'):
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            w.writerow(heads)
            w.writerows(rows)
        return path
    if len(rows) > XLSX_MAX:
        raise sv.Refused(f'Строк {len(rows)} - больше, чем помещается на лист Excel ({XLSX_MAX}).')
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('Список файлов')
    ws.append(heads)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def collapse(folders):
    """Папки для пересканирования: вложенные в другую выбранную - убираются (её пересканирует верхняя)."""
    res = []
    for f in sorted(set(folders), key=lambda x: (x.count(SEP), x.lower())):
        fl = f.lower()
        if not any(fl == t.lower() or fl.startswith(t.lower() + SEP) for t in res):
            res.append(f)
    return res
