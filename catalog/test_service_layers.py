"""Пакет service/ (шаг А разбивки service.py, 17.11.2026; docs/СТРУКТУРА_ПРОГРАММЫ.md, раздел «service: сделано»):
пакет вместо файла (одна копия в sys.modules), слои подмодулей, все прежние имена - те же объекты, каждое имя
определено один раз, запись таблиц - только под замком, подмены имён service в тестах - только через tests/sv_patch.py.
Диски и данные не нужны.

Запуск из корня проекта:  py -m unittest catalog.test_service_layers
"""
import ast
import builtins
import json
import os
import subprocess
import symtable
import sys
import tempfile
import unittest
from pathlib import Path

CAT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAT))
import service as sv                                 # noqa: E402
from tests.sv_patch import bindings, sv_patch, sv_patch_multiple   # noqa: E402

PKG = CAT / 'service'
# Ранги подмодулей снизу вверх: подмодуль импортирует из пакета только файлы СТРОГО ниже рангом (from .x import …);
# __init__ - выше всех (отдаёт все прежние имена). Новый файл без строки - ошибка test_service_layers.
SV_RANK = {'write': 0, 'directions_v3': 1, 'jobs': 1, 'jobs_cancel': 2, 'read_disks': 2, 'read_hash': 3, 'rescan_run': 3, 'marks': 3,
           'razbor_plan': 3, 'owner': 4, 'filelist': 4, 'razbor_screen': 4, 'direction_edit': 4, 'copy_retry': 4,
           'family': 5}
LOCK_ONLY = {'append_row', 'append_rows', 'backup'}         # запись таблиц владельца - только внутри «with TableLock()»
OWNER_TABLES = {'MANUAL', 'DECISIONS', 'EXCLUSIONS', 'DIRECTIONS', 'ANSWERS'}   # hb.X.write_text / write_bytes / open
WRITE_ONLY = {'TableLock', 'backup', 'append_rows', 'append_row', 'db', 'ro', 'Refused'}   # живут только в write.py
# Имена service.py до разбивки (без «__…», 156): пакет обязан отдавать их все.
OLD_NAMES = '''
    ACTIONS BACKUPS_KEEP CLUSTER DATE_RE DEFAULT_DIRECTIONS DESC_MAX EV_COLS EV_TEXT FAMILY_45 FAMILY_77
    FAMILY_OLD GOOD_COPY HASH_HINT KIND_WORDS LIST_KINDS LIST_MAX MOVE_MARK MTIME_SLACK NOHASH_SQL NO_HASH_TEXT
    Path RESERVE_MIN RESERVE_PART RETRY_WORD Refused SCANNER SEP TASK_ATTENTION TEMPLATE_VER_RE TYPE5 TYPE_WORD
    TableLock VERDICT_RE WHY_HEAD _copies _copy_group _day _disk_has_data _ensure_directions _log_day _meta _n
    _new_have_groups _norm_kind _plan _plan_list _read_snapshot _real_path _scanner _takes _task_meta _too_many
    _type_why _unique_from_list _usage_lines _write_json add_decision add_direction add_directions_batch
    add_exclusion add_manual add_manual_batch add_marks_batch append_row append_rows attention backup base_info
    bp capacity check_disk check_rel cluster_of collections contested contested_count copied_name copy_left
    copy_task_fingerprint copy_template_version db decision_preview direction_disks direction_preview
    direction_save direction_save_preview direction_usage directions directions_batch_preview disk_hash_info
    disk_letter disk_letters disk_space disks exclusion_preview family_split family_split_preview file_list
    files_under find_folders fix_manual folder_children folder_mark folder_missing folder_presence folders_files
    free_space full_path generation hash_dates hash_text hb io manual_preview mark_task_move mark_verdict
    marks_preview nohash_info os overview partial_outcome queued_copy razbor razbor_have razbor_tasks
    razbor_tree re read_progress rescan_argv rescan_confirmed rescan_files rescan_plan rescan_start rescans_text
    reserve_of retry_copy_task ro running_scripts same_task scanner_python short_directions shutil snapshot
    sources_signature sqlite3 stat_mod subprocess sys task_state tasks time toc_check toc_lines toc_targets
    type5 volumes
'''.split()


def files():
    return sorted(PKG.glob('*.py'))


def defined_names(tree):
    """Имена, которые файл определяет сам (def, class, присваивание верхнего уровня)."""
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, ast.Assign):
            out += [x.id for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name)]
    return out


def bound_names(tree):
    """Все имена верхнего уровня файла: свои и импортированные."""
    out = set(defined_names(tree))
    for n in tree.body:
        if isinstance(n, ast.Import):
            out |= {(a.asname or a.name).split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out |= {a.asname or a.name for a in n.names}
    return out


def global_reads(src, name):
    """Глобальные имена, которые читает код файла (symtable: функции, классы, лямбды, верхний уровень)."""
    acc = set()

    def walk(t):
        for s in t.get_symbols():
            if (t.get_type() == 'module' and s.is_referenced()) or (t.get_type() != 'module' and s.is_global()):
                acc.add(s.get_name())
        for ch in t.get_children():
            walk(ch)
    walk(symtable.symtable(src, name, 'exec'))
    return acc


def rel_imports(tree):
    """[(строка, уровень, модуль, [имена])] - все импорты из пакета (в том числе внутри функций)."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.level or (n.module or '').split('.')[0] == 'service'):
            out.append((n.lineno, n.level, n.module, [a.name for a in n.names]))
        elif isinstance(n, ast.Import):
            out += [(n.lineno, 0, a.name, None) for a in n.names if a.name.split('.')[0] == 'service']
    return out


# ---------- подмены имён service в тестах ----------

PATCH_FUNCS = ('object', 'multiple')


def sv_aliases(tree, seen=()):
    """Имена, под которыми в файле доступен пакет service: import service [as sv]; from base import * (по файлам
    проекта, в том числе tests/razbor/base.py); x = sv; self.sv = sv (текстом). Любое «<…>.sv» (app.sv, rp.sv) - тоже."""
    alias = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            alias |= {a.asname or a.name for a in n.names if a.name == 'service'}
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            alias |= {a.asname or a.name for a in n.names if a.name == 'service'}
            src = CAT / (n.module.replace('.', '/') + '.py')
            if src.exists() and src not in seen:
                inner = sv_aliases(ast.parse(src.read_text(encoding='utf-8')), (*seen, src))
                alias |= inner if any(a.name == '*' for a in n.names) else {a.asname or a.name for a in n.names
                                                                           if a.name in inner}
    for _ in range(3):
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id in alias:
                alias |= {ast.unparse(t) for t in n.targets if isinstance(t, (ast.Name, ast.Attribute))}
    return alias


def sv_patches(src):
    """Строки, где тест подменяет имя service мимо tests/sv_patch.py: patch.object(<sv>, …), patch.multiple(<sv>, …),
    patch('service.X'), <sv>.X = …, setattr(<sv>, …) / delattr (в том числе addCleanup(setattr, sv, …)). <sv> -
    псевдоним пакета или любое «….sv». Подмена атрибута ядра (sv.hb, 'X') разрешена: ядро - один объект."""
    tree = ast.parse(src)
    alias = sv_aliases(tree)
    is_sv = lambda e: isinstance(e, (ast.Name, ast.Attribute)) and (
        ast.unparse(e) in alias or (isinstance(e, ast.Attribute) and e.attr == 'sv'))
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            fname = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ''
            owner = f.value if isinstance(f, ast.Attribute) else None
            owner_name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else ''
            target = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == 'target'), None)
            if fname in PATCH_FUNCS and owner_name == 'patch' and target is not None and is_sv(target):
                bad.append(n.lineno)
            elif fname == 'patch' and isinstance(target, ast.Constant) and isinstance(target.value, str) \
                    and (target.value.split('.')[0] == 'service' or '.sv.' in target.value
                         or '.service.' in target.value):
                bad.append(n.lineno)
            args = [f] + list(n.args)
            for i, a in enumerate(args[:-1]):
                if isinstance(a, ast.Name) and a.id in ('setattr', 'delattr') and is_sv(args[i + 1]):
                    bad.append(n.lineno)
        elif isinstance(n, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and is_sv(t.value):
                    bad.append(n.lineno)
    return sorted(set(bad))


class ServiceLayersTest(unittest.TestCase):
    def test_package_replaces_module(self):
        """service - пакет: файла service.py нет, service.__file__ - service/__init__.py; после загрузки всей программы
        (app, hashbase, команды) в sys.modules ровно один service и его подмодули - каждый из своего файла."""
        self.assertFalse((CAT / 'service.py').exists(), 'service.py должен быть удалён: вместо него пакет service/')
        self.assertEqual(Path(sv.__file__).resolve(), (PKG / '__init__.py').resolve())
        code = ('import json, sys, app, hashbase, hb_cli\n'
                'for m in hb_cli.command_modules(): pass\n'
                'import service\n'
                'print(json.dumps({k: getattr(v, "__file__", None) for k, v in sys.modules.items() '
                'if "service" in k.split(".")}))')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        p = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], cwd=str(CAT), env=env, capture_output=True,
                           text=True, encoding='utf-8', timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        mods = json.loads(p.stdout.splitlines()[-1])
        want = {'service': PKG / '__init__.py'} | {f'service.{f.stem}': f for f in files() if f.stem != '__init__'}
        self.assertEqual(set(mods), set(want), 'вторая копия service или лишний модуль')
        for k, f in want.items():
            self.assertEqual(Path(mods[k]).resolve(), f.resolve(), k)

    def test_layers(self):
        """Ранги SV_RANK: подмодуль берёт из пакета только «from .x import имена» строго ниже рангом; ни «import
        service», ни «from . import x», ни «from service…» внутри пакета (в том числе внутри функций); __init__ берёт
        все подмодули и больше ничего из пакета не делает."""
        stems = {f.stem for f in files()} - {'__init__'}
        self.assertEqual(stems, set(SV_RANK), 'файл пакета service без ранга (или лишний ранг) - поправьте SV_RANK')
        for f in files():
            tree = ast.parse(f.read_text(encoding='utf-8'))
            self.assertNotIn('__all__', bound_names(tree), f.name)
            for line, level, mod, names in rel_imports(tree):
                where = f'service/{f.name}:{line}'
                self.assertEqual(level, 1, f'{where}: только «from .x import …» (не import service, не «..»)')
                self.assertTrue(mod, f'{where}: «from . import x» запрещён - берите имена: from .x import имя')
                self.assertNotIn('.', mod, where)
                self.assertIn(mod, SV_RANK, f'{where}: импорт неизвестного {mod}')
                if f.stem != '__init__':
                    self.assertLess(SV_RANK[mod], SV_RANK[f.stem], f'{where}: импорт вверх или вбок - {mod}')

    def test_submodule_loads_without_package_init(self):
        """Каждый подмодуль загружается сам, без service/__init__.py (пакет-пустышка с тем же __path__, новый процесс на
        каждый): подмодуль не зависит от того, что загрузил __init__ или соседний файл, и от порядка загрузки."""
        code = ('import importlib, sys, types\n'
                'pkg = types.ModuleType("service"); pkg.__path__ = [sys.argv[1]]; sys.modules["service"] = pkg\n'
                'm = importlib.import_module("service." + sys.argv[2])\n'
                'assert not hasattr(pkg, "add_manual")\n'
                'print(len(vars(m)))')
        for stem in SV_RANK:
            p = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(PKG), stem], cwd=str(CAT),
                               capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(p.returncode, 0, f'service/{stem}.py: {p.stderr}')

    def test_every_read_name_is_bound(self):
        """Каждое имя, которое читает код подмодуля (symtable), определено или импортировано в этом же файле, или
        встроенное: подмодуль не зависит от того, что загрузил __init__ или соседний файл (иначе - NameError)."""
        builtin = set(dir(builtins)) | {'__file__', '__name__'}
        for f in files():
            src = f.read_text(encoding='utf-8')
            tree = ast.parse(src)
            missing = global_reads(src, str(f)) - bound_names(tree) - builtin
            self.assertEqual(missing, set(), f'service/{f.name}: имена не определены и не импортированы')

    def test_names_defined_once(self):
        """Каждое имя определено (def, class, присваивание) ровно в одном подмодуле, __init__ только импортирует;
        замок, копия, дописывание, соединения и Refused - только в write.py; имя подмодуля не совпадает с прежним
        именем service (иначе атрибут пакета мог бы стать модулем)."""
        where = {}
        for f in files():
            for n in defined_names(ast.parse(f.read_text(encoding='utf-8'))):
                where.setdefault(n, []).append(f.stem)
        self.assertEqual({k: v for k, v in where.items() if len(v) > 1}, {}, 'имя определено в нескольких файлах')
        self.assertNotIn('__init__', {v[0] for v in where.values()}, '__init__ только отдаёт имена')
        for n in WRITE_ONLY:
            self.assertEqual(where.get(n), ['write'], n)
        self.assertEqual(set(SV_RANK) & set(OLD_NAMES), set())

    def test_old_names_are_the_same_objects(self):
        """Пакет отдаёт все 156 прежних имён; sv.X - тот же объект, что в файле, где X определено, и что во всех
        подмодулях, которые его импортировали (одна копия: постоянные, справочники, Refused, ядро hb)."""
        self.assertEqual(len(OLD_NAMES), 156)
        self.assertEqual(sorted(set(OLD_NAMES) - set(vars(sv))), [], 'пакет service потерял прежние имена')
        for f in files():
            if f.stem == '__init__':
                continue
            mod = sys.modules[f'service.{f.stem}']
            for n in bound_names(ast.parse(f.read_text(encoding='utf-8'))):
                if n in OLD_NAMES:
                    self.assertIs(vars(mod)[n], getattr(sv, n), f'service.{f.stem}.{n} - не тот объект, что sv.{n}')

    def test_scanner_path(self):
        """SCANNER - единственное изменённое при переносе выражение (файл на уровень глубже): значение прежнее."""
        self.assertEqual(sv.SCANNER, CAT.parent / 'scanner')
        self.assertTrue((sv.SCANNER / 'rescan.py').exists())

    def test_writes_only_under_lock(self):
        """Запись таблиц владельца не вышла из-под замка: каждый вызов append_row / append_rows / backup (кроме их
        определений в write.py) и каждая прямая запись таблицы (hb.MANUAL / DECISIONS / EXCLUSIONS / DIRECTIONS /
        ANSWERS: write_text, write_bytes, open) - внутри «with TableLock()» или в функции, которую весь пакет зовёт
        только изнутри «with TableLock()» (_ensure_directions)."""
        trees = {f.stem: ast.parse(f.read_text(encoding='utf-8')) for f in files()}

        def locked_ids(tree):
            out = set()
            for w in ast.walk(tree):
                if isinstance(w, ast.With) and any(isinstance(i.context_expr, ast.Call) and
                                                   ast.unparse(i.context_expr.func) == 'TableLock' for i in w.items):
                    out |= {id(x) for b in w.body for x in ast.walk(b)}
            return out
        locked = {k: locked_ids(t) for k, t in trees.items()}
        calls = {}                                                  # имя функции -> [под замком?] по всем вызовам
        for k, t in trees.items():
            for c in ast.walk(t):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name):
                    calls.setdefault(c.func.id, []).append(id(c) in locked[k])

        def table_write(c):
            f = c.func
            if isinstance(f, ast.Attribute) and f.attr in ('write_text', 'write_bytes', 'open'):
                recv = f.value
            elif isinstance(f, ast.Name) and f.id == 'open' and c.args:
                recv = c.args[0]
            else:
                return False
            return isinstance(recv, ast.Attribute) and recv.attr in OWNER_TABLES and ast.unparse(recv.value) == 'hb'
        bad, seen = [], 0
        for k, t in trees.items():
            for fn in [n for n in t.body if isinstance(n, ast.FunctionDef)]:
                for c in ast.walk(fn):
                    if not isinstance(c, ast.Call):
                        continue
                    lock_call = isinstance(c.func, ast.Name) and c.func.id in LOCK_ONLY and not (
                        k == 'write' and fn.name in LOCK_ONLY)
                    if not (lock_call or table_write(c)):
                        continue
                    seen += 1
                    if id(c) in locked[k]:
                        continue
                    if calls.get(fn.name) and all(calls[fn.name]):
                        continue
                    bad.append(f'{k}.py:{c.lineno} {fn.name}: {ast.unparse(c.func)}')
        self.assertGreater(seen, 15)
        self.assertEqual(bad, [], 'запись таблицы владельца вне замка')

    def test_sv_patch_reaches_internal_calls(self):
        """tests/sv_patch.py: подмена действует и на вызовы изнутри пакета (LIST_MAX в _too_many, rescan_files в
        read_progress), после выхода все места - снова прежний объект; обычный patch.object(sv, …) - нет."""
        from unittest import mock
        with mock.patch.object(sv, 'LIST_MAX', 1):
            sv._too_many(2)                                        # подмена только пакета на filelist не действует
        with sv_patch('LIST_MAX', 1):
            with self.assertRaises(sv.Refused):
                sv._too_many(2)
        tmp = Path(tempfile.mkdtemp(prefix='sv_patch_'))
        (tmp / 'ход.json').write_text('{"n": 7}', encoding='utf-8')
        real, real_max = sv.rescan_files, sv.LIST_MAX
        with sv_patch('rescan_files', return_value=(tmp / 'ход.json', tmp / 'стоп.txt', tmp / 'вывод.txt')) as m:
            self.assertEqual(sv.read_progress('X'), {'n': 7})
            m.assert_called_once_with('X')
        for mod in bindings('rescan_files'):
            self.assertIs(mod.rescan_files, real, mod.__name__)
        p = sv_patch('rescan_files')
        p.start()
        p.stop()
        self.assertIs(sys.modules['service.rescan_run'].rescan_files, real)
        with sv_patch('rescan_files', side_effect=sv.Refused('проба')):            # side_effect, вложенные
            with sv_patch('LIST_MAX', 0):
                with self.assertRaises(sv.Refused):
                    sv.read_progress('X')
                with self.assertRaises(sv.Refused):
                    sv._too_many(1)
            self.assertEqual(sys.modules['service.filelist'].LIST_MAX, real_max)
        self.assertIs(sys.modules['service.rescan_run'].rescan_files, real)
        try:                                                                        # исключение внутри - откат
            with sv_patch('rescan_files', return_value=None):
                raise KeyError('проба')
        except KeyError:
            pass
        self.assertIs(sys.modules['service.rescan_run'].rescan_files, real)
        with sv_patch('NO_SUCH_NAME', 1, create=True):
            self.assertEqual(sv.NO_SUCH_NAME, 1)
        self.assertFalse(hasattr(sv, 'NO_SUCH_NAME'))
        mp = sv_patch_multiple(LIST_MAX=0, rescan_files=lambda d: (tmp / 'ход.json',))
        mp.start()
        try:
            self.assertEqual(sys.modules['service.filelist'].LIST_MAX, 0)
            self.assertEqual(sv.read_progress('X'), {'n': 7})
        finally:
            mp.stop()
        self.assertEqual(sys.modules['service.filelist'].LIST_MAX, real_max)
        self.assertIs(sys.modules['service.rescan_run'].rescan_files, real)
        orig = sys.modules['service.jobs'].MOVE_MARK
        try:
            sys.modules['service.jobs'].MOVE_MARK = 'другое'
            with self.assertRaises(AssertionError):
                sv_patch('MOVE_MARK', 'x').start()
        finally:
            sys.modules['service.jobs'].MOVE_MARK = orig

    def test_sv_patch_like_mock(self):
        """sv_patch как mock: create=True создаёт имя в пакете и убирает его (без create - AttributeError); вложенная
        подмена того же имени - поверх внешней во всех местах, откат в обратном порядке; повторный start без stop -
        RuntimeError; sv_patch_multiple отдаёт словарь подмен для mock.DEFAULT (как mock.patch.multiple)."""
        from unittest import mock
        with self.assertRaises(AttributeError):
            sv_patch('NO_SUCH_NAME', 1).start()
        self.assertFalse(hasattr(sv, 'NO_SUCH_NAME'))
        with sv_patch('NO_SUCH_NAME', 2, create=True) as v:
            self.assertEqual((v, sv.NO_SUCH_NAME), (2, 2))
        self.assertFalse(hasattr(sv, 'NO_SUCH_NAME'))
        with sv_patch_multiple(create=True, NO_SUCH_NAME=3):
            self.assertEqual(sv.NO_SUCH_NAME, 3)
        self.assertFalse(hasattr(sv, 'NO_SUCH_NAME'))

        real = sv.LIST_MAX
        mods = bindings('LIST_MAX')
        self.assertGreater(len(mods), 1)                                    # пакет и filelist
        with sv_patch('LIST_MAX', 10):
            with sv_patch('LIST_MAX', 1):
                self.assertEqual({m.LIST_MAX for m in mods}, {1})
                with self.assertRaises(sv.Refused):
                    sv._too_many(2)
            self.assertEqual({m.LIST_MAX for m in mods}, {10})
            sv._too_many(2)
        self.assertEqual({m.LIST_MAX for m in mods}, {real})
        outer, inner = sv_patch('LIST_MAX', 10), sv_patch('LIST_MAX', 1)
        outer.start()
        inner.start()
        with self.assertRaises(RuntimeError):
            inner.start()
        inner.stop()
        outer.stop()
        self.assertEqual({m.LIST_MAX for m in mods}, {real})

        real_files = sv.rescan_files
        with sv_patch_multiple(rescan_files=mock.DEFAULT, LIST_MAX=5) as mocks:
            self.assertEqual(set(mocks), {'rescan_files'})
            self.assertIs(sys.modules['service.rescan_run'].rescan_files, mocks['rescan_files'])
            self.assertIsInstance(mocks['rescan_files'], mock.MagicMock)
        self.assertIs(sys.modules['service.rescan_run'].rescan_files, real_files)
        mp = sv_patch_multiple(rescan_files=mock.DEFAULT)
        self.assertEqual(set(mp.start()), {'rescan_files'})
        with self.assertRaises(RuntimeError):
            mp.start()
        mp.stop()
        self.assertIs(sv.rescan_files, real_files)

    def test_tests_patch_service_through_helper(self):
        """Тесты подменяют имена service только через tests/sv_patch.py: patch.object(sv, 'X') не действует на вызовы
        X изнутри пакета (тест проверял бы не то или сделал бы настоящую работу)."""
        bad = []
        for p in CAT.rglob('test*.py'):
            if '__pycache__' not in p.parts and p.name != 'test_service_layers.py':
                bad += [f'{p.relative_to(CAT)}:{n}' for n in sv_patches(p.read_text(encoding='utf-8'))]
        self.assertEqual(bad, [], 'подмена имени service мимо sv_patch')

    def test_checks_catch_broken_code(self):
        """Проверки подмен и имён на нарочно испорченном коде."""
        src = ('import service as sv\nimport app\nfrom unittest import mock\n'
               "mock.patch.object(sv, 'a')\n"
               "mock.patch.object(app.sv, 'b')\n"
               "mock.patch.multiple(app.sv, c=1)\n"
               "mock.patch('service.d')\n"
               'sv.e = 1\n'
               "self.addCleanup(setattr, sv, 'f', 1)\n"
               "mock.patch.object(sv.hb, 'g')\n"
               "x = sv\nmock.patch.object(x, 'h')\n"
               "mock.patch('app.sv.i')\n")
        self.assertEqual(sv_patches(src), [4, 5, 6, 7, 8, 9, 12, 13])
        self.assertEqual(global_reads('import os\ndef f():\n    return os.sep + q\n', 't') - {'os'}, {'q'})


if __name__ == '__main__':
    unittest.main()
