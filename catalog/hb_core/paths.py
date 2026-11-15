"""Пути проекта: база, таблицы владельца, ответы, шаблоны, задания. ЕДИНСТВЕННОЕ место, где они хранятся.
Читать только как атрибут модуля: paths.DB (после set_root() в тестах значение меняется)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import glob
import os
from pathlib import Path
import build_pilot as bp


__all__ = ['set_root', 'journal_paths', 'child_env']   # пути не копируются через import *: читать paths.X


def set_root(out_dir):
    """Где лежат база и таблицы поправок (в тестах - временная папка)."""
    global BASE_DIR, DB, SNAP, MANUAL, DECISIONS, EXCLUSIONS, ANSWERS, TEMPLATE, MOVE_TEMPLATE, TASKS, DIRECTIONS, RAZBORY
    BASE_DIR = Path(out_dir) / '_БАЗА'
    DB = BASE_DIR / 'хеши.sqlite'          # рабочая база: снимок описей + поправки
    SNAP = BASE_DIR / 'описи.sqlite'       # снимок описей; пересобирается, только если изменились сами описи
    MANUAL = BASE_DIR / 'ручные операции.tsv'
    DECISIONS = BASE_DIR / 'решения.tsv'
    EXCLUSIONS = BASE_DIR / 'исключения.tsv'   # папки, которые база не учитывает (временные копии владельца)
    DIRECTIONS = BASE_DIR / 'направления.tsv'  # направления разбора (логика v3): номер, имя, диски, что копировать
    RAZBORY = BASE_DIR / 'разборы'             # манифесты разборов носителей (логика v3)
    ANSWERS = BASE_DIR / 'ответы'
    TEMPLATE = Path(out_dir) / '_ШАБЛОН копирования'
    MOVE_TEMPLATE = Path(out_dir) / '_ШАБЛОН перемещения'
    TASKS = Path(out_dir).parent / 'Запускаемые скрипты'   # готовые задания владельца (правило 13.11.2026)


def journal_paths():
    """Журналы скриптов: в папках задач «Каталог дисков\\<задача>» и «Запускаемые скрипты\\<задание>»."""
    res = []
    for root in (bp.OUT_DIR, TASKS):
        res += glob.glob(str(Path(root) / '*' / 'Журнал*.tsv'))
    return res


def child_env():
    """Корни для подпроцесса (окно запускает команды отдельным процессом): он видит те же данные, что и окно.
    В работе это значения по умолчанию, в тестах - временные папки."""
    return {'HB_ROOT': str(BASE_DIR.parent), 'HB_SCAN_ROOTS': os.pathsep.join(str(x) for x in bp.SCAN_ROOTS)}


def _from_env():
    """HB_ROOT - папка «Каталог дисков» (база, таблицы, задачи), HB_SCAN_ROOTS - папки описей через «;».
    Добавлено 15.11.2026 для окна и тестов; без переменных всё как раньше."""
    if os.environ.get('HB_ROOT'):
        bp.OUT_DIR = Path(os.environ['HB_ROOT'])
    if os.environ.get('HB_SCAN_ROOTS'):
        bp.SCAN_ROOTS = [Path(x) for x in os.environ['HB_SCAN_ROOTS'].split(os.pathsep) if x]


_from_env()
set_root(bp.OUT_DIR)
