"""Правила разбивки на модули (15.11.2026): контракт команд, направление импорта, пути только как paths.X,
загрузка в отдельном процессе. Диски и данные не нужны.

Запуск из корня проекта:  py -m unittest catalog\\test_modules.py
"""
import ast
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
          'derived': 6, 'builder': 7, 'db': 8, 'query': 9, 'short': 10, 'api': 11}
COMMANDS = {'missing', 'only', 'cmp', 'where', 'candel', 'mklist', 'mvlist', 'manual', 'fix-manual', 'decide',
            'exclude', 'tasks', 'stats', 'build', 'folders', 'find', 'rebuild', 'family-plan', 'family-check',
            'recovery-plan', 'recovery-staging'}
UPPER = {'service', 'app', 'hashbase', 'hb_cli', 'hb_cmd'}          # чего ядро не импортирует никогда
PATHVARS = {'BASE_DIR', 'DB', 'SNAP', 'MANUAL', 'DECISIONS', 'EXCLUSIONS', 'ANSWERS', 'TEMPLATE', 'MOVE_TEMPLATE', 'TASKS'}


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
        for name in ('service', 'app', 'recovery_staging_audit', 'recovery_plan', 'copy_workflow'):
            for mod, _ in imports(CAT / f'{name}.py'):
                self.assertNotIn(top(mod), {'hashbase', 'hb_cmd', 'hb_cli'}, f'{name}.py импортирует {mod}')

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
