"""Правила разбивки на модули (15.11.2026): контракт команд, направление импорта, пути только как paths.X,
загрузка в отдельном процессе. Диски и данные не нужны. Слои экранов ui/* и переходники - test_ui_layers.py.

Запуск из корня проекта:  py -m unittest catalog\\test_modules.py
"""
import argparse
import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

CAT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAT))
import hb_cli        # noqa: E402

# Уровни ядра снизу вверх: модуль может импортировать из ядра только модули СТРОГО ниже себя.
LEVELS = {'paths': 0, 'consts': 0, 'schema': 1, 'util': 1, 'report': 2, 'sources': 3, 'apply_common': 4,
          'apply_disk': 5, 'apply_log': 5, 'apply_manual': 5, 'apply_partial': 5, 'apply_excl': 5,
          'derived': 6, 'builder': 7, 'db': 8, 'query': 9, 'short': 10, 'api': 11,
          'directions': 4, 'razbor': 10}          # логика v3 (15.11.2026): направления и отметки; расчёт разбора
COMMANDS = {'missing', 'only', 'cmp', 'where', 'candel', 'mklist', 'mvlist', 'manual', 'fix-manual', 'decide',
            'exclude', 'tasks', 'stats', 'build', 'folders', 'find', 'rebuild', 'family-plan', 'family-check',
            'recovery-plan', 'recovery-staging', 'rescan-plan',
            'directions', 'direction-add', 'direction-edit', 'directions-default', 'family-split', 'mark', 'razbor', 'razbor-tasks',
            'contested'}
UPPER = {'service', 'app', 'hashbase', 'hb_cli', 'hb_cmd'}          # чего ядро не импортирует никогда

# Правило владельца 17.11.2026: файлы небольшие - каждая правка (особенно внешнего вида) затрагивает один небольшой
# файл. Новый файл .py в catalog - не больше FILE_MAX строк. Файлы, уже превысившие предел, - долг: расти им нельзя,
# только уменьшаться (разбиваются отдельными заданиями); после разбивки - убрать из списка.
FILE_MAX = 600
FILE_DEBT = {'service.py': 2438, 'commands_page.py': 1320,
             'tasks_page.py': 1263, 'test_move_v3.py': 1210, 'hb_core/razbor.py': 1053,
             'test_logic_v3.py': 944, 'hb_cmd/mvlist.py': 897, 'explorer_page.py': 841, 'directions_page.py': 820,
             'test_hashbase.py': 814, 'test_directions_page.py': 813, 'explorer_diff.py': 718, 'disks_page.py': 679,
             'build_pilot.py': 570, 'test_app.py': 519, 'test_copy_template_review.py': 515}
PATHVARS = {'BASE_DIR', 'DB', 'SNAP', 'MANUAL', 'DECISIONS', 'EXCLUSIONS', 'ANSWERS', 'TEMPLATE', 'MOVE_TEMPLATE', 'TASKS',
            'DIRECTIONS', 'RAZBORY'}


def imports(path):
    """Все импорты файла, в том числе внутри функций: [(модуль, [имена] или None)]."""
    res = []
    for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(n, ast.Import):
            res += [(a.name, None) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            res.append((n.module, [a.name for a in n.names]))
    return res


def top(mod):
    return mod.split('.')[0]


class ModulesTest(unittest.TestCase):
    def test_file_size(self):
        """Правило владельца 17.11.2026: файл .py не больше FILE_MAX строк; долг из FILE_DEBT только уменьшается."""
        bad = []
        for p in CAT.rglob('*.py'):
            rel = p.relative_to(CAT)
            if '__pycache__' in rel.parts or any(x.startswith('.') for x in rel.parts):
                continue
            key = rel.as_posix()
            n = len(p.read_text(encoding='utf-8').splitlines())
            limit = max(FILE_MAX, FILE_DEBT.get(key, 0))
            if n > limit:
                bad.append(f'{key}: {n} строк (предел {limit})')
        self.assertEqual(bad, [], 'Файл вырос сверх предела - вынесите часть в отдельный файл')

    def test_command_contract(self):
        seen = []
        for mod in hb_cli.command_modules():
            for attr in ('NAMES', 'HELP', 'add_args', 'run'):
                self.assertTrue(hasattr(mod, attr), f'{mod.__name__}: нет {attr}')
            if isinstance(mod.HELP, dict):
                self.assertEqual(set(mod.HELP), set(mod.NAMES), mod.__name__)
            seen += list(mod.NAMES)
        self.assertEqual(len(seen), len(set(seen)), 'имя команды повторяется')
        self.assertEqual(set(seen), COMMANDS)

    def test_core_imports_only_downwards(self):
        files = sorted((CAT / 'hb_core').glob('*.py'))
        self.assertEqual({f.stem for f in files} - {'__init__'}, set(LEVELS))
        for f in files:
            if f.stem == '__init__':
                continue
            for mod, names in imports(f):
                self.assertNotIn(top(mod), UPPER, f'{f.name} импортирует {mod}')
                targets = []
                if mod.startswith('hb_core.'):
                    targets = [mod.split('.')[1]]
                elif mod == 'hb_core':
                    targets = names or []
                for t in targets:
                    self.assertLess(LEVELS[t], LEVELS[f.stem], f'{f.name}: импорт вверх или вбок - {t}')

    def test_commands_do_not_import_each_other(self):
        for f in sorted((CAT / 'hb_cmd').glob('*.py')):
            for mod, names in imports(f):
                self.assertNotIn(top(mod), {'hb_cmd', 'hb_cli', 'hashbase', 'app'}, f'{f.name} импортирует {mod}')

    def test_upper_layers(self):
        for name in ('service', 'app', 'recovery_staging_audit', 'recovery_plan', 'copy_workflow', 'commands_page'):
            banned = {'hashbase', 'hb_cmd'} | ({'hb_cli'} if name != 'commands_page' else set())
            for mod, _ in imports(CAT / f'{name}.py'):
                self.assertNotIn(top(mod), banned, f'{name}.py импортирует {mod}')

    def test_window_never_runs_commands_in_its_process(self):
        # раздел «Команды» берёт у hb_cli только описание (commands()); выполняет команды отдельный процесс
        tree = ast.parse((CAT / 'commands_page.py').read_text(encoding='utf-8'))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name) and n.value.id == 'hb_cli'}
        self.assertEqual(used, {'commands'})
        self.assertNotIn('_run', {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})

    def test_gui_attribute(self):
        hidden = set()
        for mod in hb_cli.command_modules():
            gui = getattr(mod, 'GUI', True)
            self.assertIsInstance(gui, (bool, dict), mod.__name__)
            if isinstance(gui, dict):
                self.assertTrue(set(gui) <= set(mod.NAMES), mod.__name__)
        for name, hlp, show, p in hb_cli.commands():
            self.assertTrue(hlp, name)
            if not show:
                hidden.add(name)
        self.assertEqual(hidden, {'recovery-plan', 'recovery-staging', 'family-plan', 'family-check', 'mvlist',
                                  'manual', 'fix-manual', 'mklist', 'decide', 'exclude', 'rescan-plan', 'family-split'})

    def test_visible_commands_have_window_texts(self):
        # окно «Архив дисков»: у каждой видимой команды есть понятный заголовок и группа (GUI_TITLE, GUI_GROUP)
        for mod in hb_cli.command_modules():
            gui = getattr(mod, 'GUI', True)
            for name in mod.NAMES:
                if not (gui.get(name, True) if isinstance(gui, dict) else gui):
                    continue
                for attr in ('GUI_TITLE', 'GUI_GROUP'):
                    v = getattr(mod, attr, None)
                    if isinstance(v, dict):
                        v = v.get(name)
                    self.assertTrue(isinstance(v, str) and v.strip(), f'{name}: нет {attr}')
                args = getattr(mod, 'GUI_ARGS', {})
                if isinstance(args, dict) and args and set(args) <= set(mod.NAMES):
                    args = args.get(name, {})
                p = argparse.ArgumentParser()
                mod.add_args(p, name)
                dests = {a.dest for a in p._actions}
                self.assertTrue(set(args) <= dests, f'{name}: GUI_ARGS для несуществующих аргументов '
                                                    f'{set(args) - dests}')

    def test_hb_root_from_environment(self):
        # окно передаёт подпроцессу свои корни: подпроцесс не должен видеть настоящие таблицы владельца
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix='hb_root_'))
        try:
            env = dict(os.environ, HB_ROOT=str(tmp / 'Каталог'), HB_SCAN_ROOTS=str(tmp / 'scans'))
            code = ('import build_pilot as bp; from hb_core import paths as p; print(*[p.DB, p.MANUAL, p.DECISIONS, '
                    'p.EXCLUSIONS, p.ANSWERS, p.TEMPLATE, p.TASKS, bp.OUT_DIR, *bp.SCAN_ROOTS], sep="\\n"); '
                    'print(p.child_env()["HB_ROOT"])')
            r = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], cwd=str(CAT), env=env, capture_output=True,
                               text=True, encoding='utf-8', timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 10)
            for x in lines:
                self.assertTrue(Path(x).is_relative_to(tmp), x)
            self.assertEqual(Path(lines[-1]), tmp / 'Каталог')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_paths_are_read_as_attributes(self):
        # «from hb_core.paths import DB» сохранил бы старый путь после set_root(); соединение - только в db
        for f in list((CAT / 'hb_core').glob('*.py')) + list((CAT / 'hb_cmd').glob('*.py')) + [CAT / 'service.py']:
            for mod, names in imports(f):
                if mod == 'hb_core.paths':
                    self.assertFalse(PATHVARS & set(names or []), f'{f.name}: пути копируются из paths')
                if mod == 'hb_core.db':
                    self.assertNotIn('_last', names or [], f.name)

    def test_cli_loads_in_a_separate_process(self):
        # ловит ошибки загрузки, которых не видно изнутри тестов (двойная загрузка, круговой импорт)
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(CAT / 'hashbase.py'), *a],
                                        capture_output=True, text=True, encoding='utf-8', timeout=60)
        r = run('--help')
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in sorted(COMMANDS):
            r = run(name, '--help')
            self.assertEqual(r.returncode, 0, f'{name}: {r.stderr}')


if __name__ == '__main__':
    unittest.main()
