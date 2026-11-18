"""Сервис над hashbase: единственный путь записи в таблицы владельца и данные для окна программы.

Записи владельца (ручные операции, решения, исключения) делают ТОЛЬКО эти функции - из окна, из командной
строки и из чата (через команды hashbase.py manual / decide / exclude). Каждая запись:
  1. проверяет формат и смысл (диск есть в базе, путь есть в базе, такой же строки ещё нет);
  2. показывает предпросмотр: сколько файлов базы затронет и примеры путей;
  3. под замком таблиц кладёт копию таблицы в «_БАЗА\архив таблиц» и дописывает ОДНУ целую строку;
  4. сразу применяет её к базе (сборщик берёт только новые строки; если программа упадёт между шагами 3 и 4,
     следующая команда применит строку сама - строка уже является модулем).
Строку, записанную по ошибке, исправляет fix_manual: старая строка заменяется, причина пишется в комментарий,
база собирается заново целиком (изменённый модуль) - так ошибка не остаётся в учёте навсегда.

Пакет (шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md, раздел «service: сделано»): бывший service.py
по темам, тела функций не менялись. Здесь - все прежние имена: import service as sv; sv.X. Подменять имя
в тестах - только tests/sv_patch.py (подмена во всех подмодулях, где имя связано).
"""
import collections
import io
import os
import re
import shutil
import sqlite3
import stat as stat_mod
import subprocess
import sys
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import (SEP, ACTIONS, VERDICT_RE, DATE_RE, BACKUPS_KEEP, Refused, TableLock, backup, append_rows,
    append_row, check_rel, db, check_disk, files_under, ro)
from .directions_v3 import (KIND_WORDS, DEFAULT_DIRECTIONS, _read_snapshot, snapshot, directions, _ensure_directions,
    _norm_kind, direction_preview, add_direction, directions_batch_preview, add_directions_batch)
from .jobs import running_scripts, task_state, tasks, MOVE_MARK, mark_task_move
from .jobs_cancel import CANCEL_DIR, CANCEL_LOG, CANCEL_STATES, can_cancel, cancel_tasks
from .read_disks import (generation, base_info, volumes, disks, EV_COLS, TASK_ATTENTION, direction_disks,
    _unique_from_list, overview, attention, folder_mark, folder_children, folder_missing, rescans_text)
from .read_hash import (TYPE5, type5, NOHASH_SQL, nohash_info, disk_hash_info, folder_presence, _day, _log_day, _n,
    HASH_HINT, hash_dates, find_folders, sources_signature)
from .rescan_run import (SCANNER, _scanner, disk_letter, rescan_plan, rescan_confirmed, rescan_files, scanner_python,
    rescan_argv, rescan_start, read_progress, partial_outcome)
from .marks import mark_verdict, _real_path, marks_preview, add_marks_batch
from .razbor_plan import (_plan, razbor, free_space, _task_meta, _write_json, same_task, _new_have_groups,
    razbor_tasks, contested, contested_count, nohash_check)
from .owner import (manual_preview, add_manual, add_manual_batch, fix_manual, decision_preview, add_decision,
    exclusion_preview, add_exclusion)
from .filelist import (LIST_KINDS, LIST_MAX, EV_TEXT, NO_HASH_TEXT, TYPE_WORD, WHY_HEAD, hash_text, _too_many, _meta,
    disk_letters, full_path, _copies, _takes, _type_why, _plan_list, file_list, folders_files)
from .razbor_screen import (razbor_tree, razbor_have, CLUSTER, RESERVE_MIN, RESERVE_PART, MTIME_SLACK, disk_space,
    cluster_of, reserve_of, queued_copy, capacity, short_directions, toc_targets, toc_check, toc_lines)
from .direction_edit import (DESC_MAX, GOOD_COPY, direction_usage, copied_name, _disk_has_data, _usage_lines,
    direction_save_preview, direction_save, TEMPLATE_VER_RE, copy_template_version, copy_task_fingerprint)
from .copy_retry import RETRY_WORD, _copy_group, copy_left, retry_copy_task
from .family import FAMILY_OLD, FAMILY_45, FAMILY_77, family_split_preview, family_split
