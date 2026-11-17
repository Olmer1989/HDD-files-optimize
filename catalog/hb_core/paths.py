"""Пути проекта: база, таблицы владельца, ответы, шаблоны, задания. ЕДИНСТВЕННОЕ место, где они хранятся.
Читать только как атрибут модуля: paths.DB (после set_root() в тестах значение меняется)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import glob
import hashlib
import os
import re
import shutil
from pathlib import Path
import build_pilot as bp


__all__ = ['set_root', 'journal_paths', 'child_env', 'template_parts', 'template_problems', 'copy_template',
           'part_sha']   # пути не копируются через import *: читать paths.X


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


# Шаблон из частей (шаблон копирования 2.8, 17.11.2026): главный .ps1 + части .psm1 рядом («Запустить.cmd»
# запускает только *.ps1). Главный перечисляет части с SHA-256 их текста (таблица $PartSha, строка на часть) и не
# начнёт работу, если части нет или она изменена. Здесь - единственное место в Python, которое знает состав шаблона.
_PART_RE = re.compile(r"^\s*'([^'\r\n\\/:]+\.psm1)'\s*=\s*'([0-9A-Fa-f]{64})'\s*$", re.M)


def part_sha(path):
    """SHA-256 текста части так же, как считает главный: UTF-8 без BOM, концы строк LF, заглавными."""
    text = Path(path).read_bytes().decode('utf-8').lstrip('﻿').replace('\r\n', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()


def template_parts(main):
    """Части шаблона по таблице $PartSha главного: [(имя, SHA-256)]; однофайловый шаблон (2.7 и старше) - []."""
    return [(n, h.upper()) for n, h in _PART_RE.findall(Path(main).read_text(encoding='utf-8-sig'))]


def template_problems(folder, main):
    """Что не так с частями шаблона в папке: [] - всё на месте; иначе строки «нет части …» / «часть … изменена»."""
    res = []
    for name, sha in template_parts(Path(folder) / main):
        p = Path(folder) / name
        try:
            if part_sha(p) != sha:
                res.append(f'часть «{name}» изменена (SHA-256 не тот, что записан в {main})')
        except FileNotFoundError:
            res.append(f'нет части «{name}»')
        except (OSError, UnicodeDecodeError) as e:
            res.append(f'часть «{name}» не читается: {e}')
    return res


def copy_template(src, dst, main, extra=('Запустить.cmd',)):
    """Кладёт шаблон в папку задания: главный, `extra` и все его части; байты сверяются. Эталон без части или с
    изменённой частью - исключение (задание не готовится). Возвращает имена скопированных файлов."""
    src, dst = Path(src), Path(dst)
    bad = template_problems(src, main)
    if bad:
        raise RuntimeError(f'Шаблон {src} испорчен: ' + '; '.join(bad))
    names = [main, *extra, *(n for n, _ in template_parts(src / main))]
    for n in names:
        shutil.copy2(src / n, dst / n)
        if (src / n).read_bytes() != (dst / n).read_bytes():
            raise RuntimeError(f'{dst / n}: копия шаблона не совпала с эталоном')
    return names


def _from_env():
    """HB_ROOT - папка «Каталог дисков» (база, таблицы, задачи), HB_SCAN_ROOTS - папки описей через «;».
    Добавлено 15.11.2026 для окна и тестов; без переменных всё как раньше."""
    if os.environ.get('HB_ROOT'):
        bp.OUT_DIR = Path(os.environ['HB_ROOT'])
    if os.environ.get('HB_SCAN_ROOTS'):
        bp.SCAN_ROOTS = [Path(x) for x in os.environ['HB_SCAN_ROOTS'].split(os.pathsep) if x]


_from_env()
set_root(bp.OUT_DIR)
