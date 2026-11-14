"""Пути проекта: база, таблицы владельца, ответы, шаблоны, задания. ЕДИНСТВЕННОЕ место, где они хранятся.
Читать только как атрибут модуля: paths.DB (после set_root() в тестах значение меняется)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import glob
from pathlib import Path
import build_pilot as bp


__all__ = ['set_root', 'journal_paths']   # пути не копируются через import *: читать paths.X


def set_root(out_dir):
    """Где лежат база и таблицы поправок (в тестах - временная папка)."""
    global BASE_DIR, DB, SNAP, MANUAL, DECISIONS, EXCLUSIONS, ANSWERS, TEMPLATE, MOVE_TEMPLATE, TASKS
    BASE_DIR = Path(out_dir) / '_БАЗА'
    DB = BASE_DIR / 'хеши.sqlite'          # рабочая база: снимок описей + поправки
    SNAP = BASE_DIR / 'описи.sqlite'       # снимок описей; пересобирается, только если изменились сами описи
    MANUAL = BASE_DIR / 'ручные операции.tsv'
    DECISIONS = BASE_DIR / 'решения.tsv'
    EXCLUSIONS = BASE_DIR / 'исключения.tsv'   # папки, которые база не учитывает (временные копии владельца)
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


set_root(bp.OUT_DIR)
