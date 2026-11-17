"""«Я сделал в Проводнике»: что изменилось на подключённом диске по сравнению с базой. Без Qt.

Сравнивается то, что база считает лежащим на носителе (таблица files: опись + журналы + ручные операции),
с оглавлением диска сейчас: только пути, размеры, даты. Содержимое файлов НЕ читается.
Различия собираются в «единицы» (папка целиком или файл), владелец отмечает нужные галочками, а строки
ручных операций пишет только service.add_manual_batch (единый путь записи, ПРАВИЛА_ЗАПИСИ_И_СБОРКИ.md, раздел 2).

Правила (спор с GPT - «Проверка Архитектуры сортировки файлов\\Я_сделал_в_Проводнике_v1.md»):
- обход только выбранных папок и только по кнопке; при остановке результат отбрасывается целиком;
- папки, которые не удалось прочитать, служебные папки, точки повторной обработки и исключения - «не проверено»:
  исчезновения внутри них не выводятся;
- ключ пути - path.lower() (как сравнивает NTFS, без нормализации Unicode); два пути с одним ключом -
  «неоднозначно», такие места не записываются;
- пара «перемещено внутри диска» (сохраняет хеш и степень) - только при равных размере И дате изменения каждого
  файла и единственном кандидате с обеих сторон; это предложение, владелец подтверждает его сам;
- появившееся, у которого в базе на другом диске есть ровно такой же файл (имя, размер, дата, один и тот же хеш) -
  предложение «скопировано с HDDxx» (копия «со слов» = степень U); без источника записать нельзя -
  только пересканировать папку (отдельная функция окна, она читает файлы и считает хеши);
- перед записью повторно проверяются том (серийный номер), поколение базы и каждое место на диске.
"""
import collections
import ctypes
import os
import sqlite3
import stat
import sys
import tempfile
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb
import service as sv
from explorer_diff_base import (  # noqa: F401
    SEP, BIG_FOLDER, CHILDREN_MAX, UNITS_MAX, EXCLUDED_DIRS, excluded_file, Stopped, key, parent, ancestors, under,
    plural, gb_text, when_text, volume_serial, disk_root, top_folders)
from explorer_diff_scan import Diff, _walk, _put_file, scan  # noqa: F401
from explorer_diff_group import (  # noqa: F401
    _unit, group, _sig, _pair_moves, _find_sources, _same_file, rows_for, summary, selection_rows)
from explorer_diff_write import (  # noqa: F401
    check_date, verify_disk, disk_sig, expected, check_overlap, write, result_text, offline_rows, recorded,
    describe, fix_check, fix)
