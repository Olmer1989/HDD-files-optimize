"""Общая база хешей: быстрые ответы на типовые вопросы без чтения дисков и без подсчётов в чате.

Одна база SQLite собирается из описей всех носителей (hashes.sqlite) и поправок:
  - журналы скриптов копирования, перемещения и корзины из «Каталог дисков\\<задача>\\Журнал*.tsv»;
  - «Каталог дисков\\_БАЗА\\ручные операции.tsv» - то, что пользователь сделал в Проводнике;
  - «Каталог дисков\\_БАЗА\\решения.tsv» - решения пользователя («не нужно», «раздел: …»).
Рабочая база пересобирается сама, если появился новый журнал или изменились эти таблицы; снимок описей
(все 11,3 млн файлов) собирается один раз и заново только при изменении самих описей.
Фото и видео сравниваются по SHA-256 - точно. Остальные файлы (без хеша) - по имени и размеру:
«копия не найдена» / «вероятная копия»; для ответа «можно удалять» вероятная копия не засчитывается.
Копией считается только ПОДТВЕРЖДЁННАЯ запись: хеш измерен сканером по самому файлу или посчитан скриптом
при копировании. Копия, у которой сверен только размер («уже есть»), и копия со слов пользователя
копией не считаются. Ответ «можно удалять» учитывает все файлы, полноту описи и не считает
сохраняемой копией то, что само удаляется.
Диски программа не читает вообще.

Команды (диск - номер HDDxx / Flashxx; папка - путь от корня диска, можно не указывать):
  py catalog\\hashbase.py missing HDD17 [папка] [--depth 2]   чего с диска нет на 45 и 77, по папкам
  py catalog\\hashbase.py only HDD17 [папка]                  что лежит только на этом диске
  py catalog\\hashbase.py cmp HDD17 "папка A" HDD61 "папка B" одинаковы ли две папки
  py catalog\\hashbase.py where HDD17 "папка или файл"        на каких ещё дисках это лежит
  py catalog\\hashbase.py candel HDD17 "папка"                можно ли удалять (есть ли всё на 45 и на 77)
  py catalog\\hashbase.py mklist HDD17 --to HDD45 HDD77 --name "K - остаток" [--folder "папка"] [--dry]
                                                             папка задачи для единого шаблона копирования
                                                             (--dry - только посчитать, ничего не создавать;
                                                             --whole - папки --folder целиком, все типы файлов)
  py catalog\\hashbase.py folders HDD45 [папка] [--depth 2]   сколько занимают папка и подпапки, по типам файлов
  py catalog\\hashbase.py find Сафари [--disk HDD45]          папки со словами в пути, на всех носителях
  py catalog\\hashbase.py build                               применить новые модули и показать сводку
  py catalog\\hashbase.py stats                               что в базе и какие модули учтены
  py catalog\\hashbase.py rebuild                             самопроверка: база с нуля против базы по шагам
Модули (ТЗ v3): описи, частичные сканы («Повторное сканирование»), журналы, строки ручных операций и
исключений («_БАЗА\\исключения.tsv»). Каждая команда применяет только новые модули (таблица applied).
На экран - не больше 20 строк; полный ответ - «_БАЗА\\ответы\\последний ответ.txt», списки - там же.
"""
# Разбор командной строки. Команды - файлы catalog\hb_cmd\*.py, находятся сами (pkgutil):
# новая команда = новый файл с NAMES, HELP, add_args(p, name), run(a); здесь ничего дописывать не надо.
import argparse
import importlib
import os
import pkgutil
import sys
import time

import hb_cmd
from hb_core import paths
from hb_core.short import ShortAnswer
from hb_core.util import out


def command_modules():
    """Все модули команд, по алфавиту."""
    return [importlib.import_module(f'hb_cmd.{m.name}')
            for m in sorted(pkgutil.iter_modules(hb_cmd.__path__), key=lambda m: m.name)]


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for mod in command_modules():
        for name in mod.NAMES:
            hlp = mod.HELP.get(name) if isinstance(mod.HELP, dict) else mod.HELP
            p = sub.add_parser(name, help=hlp)
            mod.add_args(p, name)
            p.set_defaults(_run=mod.run)
    return ap


def commands():
    """Для окна «Архив дисков»: [(имя, описание, показывать ли в окне, подпарсер)] - то же описание argparse,
    что у командной строки. Ничего не выполняет. GUI = False (или dict имя -> bool) в файле команды - не в окне."""
    ap = parser()
    sub = next(x for x in ap._actions if isinstance(x, argparse._SubParsersAction))
    res = []
    for mod in command_modules():
        gui = getattr(mod, 'GUI', True)
        for name in mod.NAMES:
            hlp = mod.HELP.get(name) if isinstance(mod.HELP, dict) else mod.HELP
            res.append((name, hlp, bool(gui.get(name, True) if isinstance(gui, dict) else gui), sub.choices[name]))
    return res


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    a = parser().parse_args(argv)
    t0 = time.time()
    if os.environ.get('HB_FULL_OUTPUT') == '1':     # окно: весь ответ без сокращения до 20 строк, окно покажет его само
        a._run(a)
        out(f'[{time.time() - t0:.1f} с]')
        return
    real, ans = sys.stdout, ShortAnswer(sys.stdout, paths.ANSWERS / 'последний ответ.txt')
    sys.stdout = ans
    try:
        a._run(a)
        out(f'[{time.time() - t0:.1f} с]')
    finally:
        sys.stdout = real
        ans.close_answer()
