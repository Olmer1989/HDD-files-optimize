"""Экраны по блокам ui/* (шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md): слои пакетов, круговые импорты,
переходники (длина, прежние имена, запрет подмен их имён в тестах). Вынесено из test_modules.py. Диски и данные не нужны.

Запуск из корня проекта:  py -m unittest catalog.test_ui_layers
"""
import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

CAT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAT))
from test_modules import imports, top        # noqa: E402

# Экраны по блокам (шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md): ранги слоёв каждого пакета ui/<экран>
# (view_*, flow_* - 6). Файл пакета импортирует из пакета только файлы СТРОГО ниже рангом: view_* и flow_* друг друга не
# импортируют. Новый пакет ui/* без строки здесь - ошибка test_ui_layers.
UI_RANK = {'razbor': {'texts_cell': 0, 'common': 1, 'texts_tasks': 1, 'texts_head': 2, 'model_marks': 3, 'model_checks': 3,
                      'model_show': 3, 'model': 4, 'dialogs': 5, 'page': 7},
           'filelist': {'texts_list': 0, 'common': 1, 'model_rows': 2, 'model_table': 3, 'page': 7}}
SHIMS = {'razbor_page': 60, 'razbor_cell': 60, 'test_razbor_page': 60,          # переходники шага А: прежние имена,
         'filelist_window': 60}                                                 # до 60 строк


def ui_packages(root=CAT):
    """Пакеты экранов: каталоги <root>/ui/* с __init__.py."""
    return sorted(p.name for p in (root / 'ui').iterdir() if (p / '__init__.py').exists())


def ui_rank(pkg, stem):
    """Ранг файла пакета; __init__ - ниже всех (-1): не импортирует ничего из своего пакета."""
    if stem == '__init__':
        return -1
    return UI_RANK[pkg].get(stem, 6 if stem.startswith(('view_', 'flow_')) else None)


def resolve(here, level, module):
    """Относительный импорт -> полное имя: here - пакет файла (у __init__ - сам пакет); «from ..x» - к родителю.
    None - выше корня."""
    parts = here.split('.') if here else []
    if level - 1 >= len(parts):
        return None
    base = parts[:len(parts) - (level - 1)]
    return '.'.join(base + ([module] if module else []))


def ui_targets(path, pkg):
    """Какие файлы своего пакета ui/<pkg> импортирует файл пакета (и его __init__): [(строка, имя файла)]. Учитывает
    «from .x import», «from . import x, y» (каждое имя), «from ..» (родитель - не свой пакет), «from ui.<pkg> import x»,
    «import ui.<pkg>.x», «from ui.<pkg>.x import». Выше корня - неизвестный импорт «..»."""
    me = f'ui.{pkg}'
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(n, ast.ImportFrom):
            mod = resolve(me, n.level, n.module) if n.level else n.module
            if mod is None:
                out.append((n.lineno, '..' + (n.module or '')))             # выше корня - неизвестный импорт
            elif mod == me:
                out += [(n.lineno, a.name) for a in n.names]
            elif mod.startswith(me + '.'):
                out.append((n.lineno, mod.split('.')[2]))
        elif isinstance(n, ast.Import):
            out += [(n.lineno, a.name.split('.')[2]) for a in n.names if a.name.startswith(me + '.')]
    return out


def load_time_imports(tree):
    """Импорты, выполняемые при загрузке модуля: верхний уровень и вложенные в if / try / with верхнего уровня."""
    todo, out = list(tree.body), []
    while todo:
        n = todo.pop()
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            out.append(n)
        elif isinstance(n, (ast.If, ast.Try, ast.With)):
            for f in ('body', 'orelse', 'finalbody', 'handlers'):
                todo += getattr(n, f, [])
        elif isinstance(n, ast.ExceptHandler):
            todo += n.body
    return out


def module_graph(root=CAT):
    """{модуль: {модули}} по импортам при загрузке, один граф на всё: файлы <root>/*.py (имя без .py), ui/__init__.py
    (ui), ui/<экран>/__init__.py (ui.<экран>) и ui/<экран>/*.py (ui.<экран>.x) - круговой импорт ловится и между
    пакетами, и через __init__, и через модули catalog. Импорт ui.a.x загружает и ui, ui.a - ребро к ним тоже."""
    files = {p.stem: p for p in root.glob('*.py')}
    if (root / 'ui' / '__init__.py').exists():
        files['ui'] = root / 'ui' / '__init__.py'
    for k in ui_packages(root):
        files.update({f'ui.{k}' + ('' if p.stem == '__init__' else f'.{p.stem}'): p
                      for p in (root / 'ui' / k).glob('*.py')})
    g = {}
    for name, p in files.items():
        here = name if p.name == '__init__.py' else name.rsplit('.', 1)[0] if '.' in name else ''
        edges = set()
        for n in load_time_imports(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            else:
                mod = resolve(here, n.level, n.module) if n.level else n.module
                mods = [mod] + [f'{mod}.{a.name}' for a in n.names] if mod else []
            for m in mods:
                if m != 'ui' and not m.startswith('ui.'):
                    m = top(m)
                parts = m.split('.')
                for i in range(1, len(parts) + 1):                     # ui.a.x -> ui, ui.a, ui.a.x
                    x = '.'.join(parts[:i])
                    if x in files and x != name:
                        edges.add(x)
        g[name] = edges
    return g


def find_cycle(g):
    """Первый найденный цикл [a, b, …, a] или None."""
    state, stack = {}, []

    def dfs(v):
        state[v] = 1
        stack.append(v)
        for w in sorted(g.get(v, ())):
            if state.get(w) == 1:
                return stack[stack.index(w):] + [w]
            if not state.get(w):
                c = dfs(w)
                if c:
                    return c
        state[v] = 2
        stack.pop()
        return None
    for v in sorted(g):
        if not state.get(v):
            c = dfs(v)
            if c:
                return c
    return None


SHIM_MODS = {'razbor_page', 'razbor_cell', 'filelist_window'}
# Имена модулей до разбивки (без «__…»): переходник обязан отдавать их все (test_shims_keep_old_names).
SHIM_NAMES = {
    'filelist_window': '''
        Busy C_DATE C_DISK C_FOLDER C_HASH C_NAME C_SIZE C_TYPE C_WHERE C_WHY EV_ORDER FILTER_MS F_MORE F_PART
        F_ROLE FileListWindow FileModel HEAD KIND_TITLE MARK_KINDS QAbstractItemView QAbstractTableModel
        QApplication QCheckBox QColor QCursor QFileDialog QHBoxLayout QHeaderView QLabel QLineEdit QMessageBox
        QModelIndex QPushButton QSpinBox QSplitter QTableView QTimer QTreeWidget QTreeWidgetItem QVBoxLayout
        QWidget Qt RELOAD_MS R_DISK R_EV R_FLC R_FOLDER R_K R_MTIME R_NAME R_NLC R_SIZE R_T5 R_WHERE R_WHY SEP
        SMALL_KB TITLE TREE_CHUNK WIDTH XLSX_MAX _esc _last_line _safe collapse columns csv date_ok date_text
        disk_ui export_values file_path files_word gb_text head log_error n_text norm open_in_explorer open_list
        os place_of prepare save_table size_text subprocess sv time totals_line unicodedata
    ''',
    'razbor_page': '''
        AUTOSAVE_MS BLOCK_LOOK BLUE BLUE2 BUSY_CSS CAT_OF_TYPE CHUNK CONTESTED_MS CONTESTED_NOTE COPIED_PREFIX
        COPIES_WORDS COUNT_WORDS C_CHECK C_FILES C_GB C_HAVE C_NAME C_OTHER C_PHOTO C_VIDEO Cell CloseGuard
        ContestedDialog DEBOUNCE_MS DISKS_WORDS DragTree EVERY EXCEPT EXC_BG EXC_FG FILLED FLUSH_WAIT_MS GRAY
        GRAY_ROLE GREEN HEAD HEAD_BG HtmlDelegate INHERIT JOURNAL LINK MIME MODE_CSS MODE_NOTE MODE_TEXT
        MORE_ROLE Model NO_SPACE N_TYPES OFF_PILL ONLY ORANGE PALE PALETTE PART_ROLE PLATE QAbstractItemView
        QBrush QButtonGroup QColor QComboBox QCoreApplication QDialog QEvent QFont QFontMetrics QFrame
        QGridLayout QGroupBox QHBoxLayout QHeaderView QLabel QMessageBox QMimeData QObject QPalette QPushButton
        QRectF QScrollArea QSize QSizePolicy QSplitter QStyle QStyleOptionComboBox QStylePainter
        QStyledItemDelegate QTabWidget QTextBrowser QTextDocument QThreadPool QTimer QTreeWidget QTreeWidgetItem
        QVBoxLayout QWidget Qt RED ROLE R_DIR R_NONE R_SKIP R_UNSET RazborPage RichCombo SEL_BG SEP SHORT_BG
        SKIP SKIP_INH SKIP_OWN SKIP_TEXT STAY_DIR STAY_NONE Signal StepsBar TAG_ROLE TITLE TextDialog
        TreeDelegate UNDO_MAX UNKNOWN_BG UNSET_BG carrier_text cell_numbers collections copies_word copy_color
        dest_cell_html dest_html dest_info_html dest_places dest_text dir_colors directions_page disk_block_html
        disk_head disk_ui esc files_word folders_mime folders_word free_of gb hb hdds head_html json last
        legend_html letters list_link mime_folders num place place_html plate_html plural row_html rz safe
        short_place spec_keys stay_numbers sv sv_log tasks_check tasks_create tasks_dry tasks_html tb_text time
        timed total_of traceback vol
    ''',
}


def shim_aliases(tree, seen=()):
    """Имена, под которыми в файле доступен модуль-переходник: import razbor_page as rp; from base import * / rp
    (по файлам проекта, в том числе tests/razbor/base.py); rp2 = rp; self.fw = fw (имя - текстом «self.fw»)."""
    alias = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            alias |= {a.asname or a.name for a in n.names if a.name in SHIM_MODS}
        elif isinstance(n, ast.ImportFrom) and not n.level:
            alias |= {a.asname or a.name for a in n.names if a.name in SHIM_MODS}
            src = CAT / (n.module.replace('.', '/') + '.py') if n.module else None
            if src and src.exists() and src not in seen:
                inner = shim_aliases(ast.parse(src.read_text(encoding='utf-8')), (*seen, src))
                alias |= inner if any(a.name == '*' for a in n.names) else                     {a.asname or a.name for a in n.names if a.name in inner}
    for _ in range(3):
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id in alias:
                alias |= {ast.unparse(t) for t in n.targets if isinstance(t, (ast.Name, ast.Attribute))}
    return alias


def shim_patches(src):
    """Строки подмен имени модуля-переходника: patch.object(<псевдоним переходника>, …), patch.multiple(…) и
    patch('…razbor_page.X') строкой. Подмена атрибута класса (rp.RazborPage, 'set_item') разрешена."""
    tree = ast.parse(src)
    alias = shim_aliases(tree)
    bad = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        fname = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ''
        owner = f.value if isinstance(f, ast.Attribute) else None
        owner_name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else ''
        target = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == 'target'), None)
        if fname in ('object', 'multiple') and owner_name == 'patch':
            if isinstance(target, (ast.Name, ast.Attribute)) and ast.unparse(target) in alias:
                bad.append(n.lineno)
        elif fname == 'patch' and isinstance(target, ast.Constant) and isinstance(target.value, str):
            parts = target.value.split('.')
            if any(x in SHIM_MODS and len(parts) - i == 2 for i, x in enumerate(parts)):
                bad.append(n.lineno)
    return bad


class UiLayersTest(unittest.TestCase):
    def test_ui_layers(self):
        """Каждый пакет ui/* (razbor, filelist …): слои по рангам; блоки (view_*) и процессы (flow_*) друг друга не
        импортируют (в том числе «from . import x»); переходники (SHIMS) не импортируются; без __all__ (переходник
        отдаёт имена звёздочкой); тексты без Qt; переходники до 60 строк; __init__ пакета - ниже всех (ничего из пакета не
        импортирует); у частей-«примесей» (класс без баз, от которого наследует класс пакета) нет своего __init__."""
        self.assertEqual(set(ui_packages()), set(UI_RANK), 'пакет ui/* без рангов - добавьте в UI_RANK')
        for mod, _ in imports(CAT / 'ui' / '__init__.py'):
            self.assertNotIn(top(mod), set(SHIMS), f'ui/__init__.py импортирует переходник {mod}')
        for pkg in ui_packages():
            self.check_layers(pkg)
        for name, limit in SHIMS.items():
            n = len((CAT / f'{name}.py').read_text(encoding='utf-8').splitlines())
            self.assertLessEqual(n, limit, f'{name}.py - переходник, не больше {limit} строк')

    def check_layers(self, pkg):
        files = sorted((CAT / 'ui' / pkg).glob('*.py'))
        self.assertTrue(len(files) > 1, pkg)
        classes = [n for f in files for n in ast.parse(f.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef)]
        bases = {ast.unparse(b) for c in classes for b in c.bases}
        for c in classes:
            if not c.bases and c.name in bases:
                self.assertFalse(any(isinstance(m, ast.FunctionDef) and m.name == '__init__' for m in c.body),
                                 f'ui/{pkg}: у части {c.name} свой __init__ - атрибуты создаёт сборка (page)')
        for f in files:
            rank = ui_rank(pkg, f.stem)
            self.assertIsNotNone(rank, f'ui/{pkg}/{f.name}: нет ранга - добавьте в UI_RANK')
            self.assertNotIn('__all__', f.read_text(encoding='utf-8'), f.name)
            for mod, _ in imports(f):
                self.assertNotIn(top(mod), set(SHIMS), f'{f.name} импортирует переходник {mod}')
                if f.stem.startswith('texts_'):
                    self.assertNotEqual(top(mod), 'PySide6', f'{f.name}: тексты без Qt')
            for line, t in ui_targets(f, pkg):
                trank = ui_rank(pkg, t)
                self.assertIsNotNone(trank, f'ui/{pkg}/{f.name}:{line}: импорт неизвестного {t}')
                self.assertLess(trank, rank, f'ui/{pkg}/{f.name}:{line}: импорт вверх или вбок - {t}')

    def test_no_import_cycles_through_ui(self):
        """Граф импортов при загрузке (верхний уровень файла) по всем пакетам ui/* и модулям catalog (service, disk_ui,
        directions_page, commands_page, ui_common, переходники …): циклов нет. Импорт внутри функции цикла не создаёт."""
        cyc = find_cycle(module_graph())
        self.assertIsNone(cyc, 'круговой импорт: ' + ' -> '.join(cyc or []))

    def test_ui_checks_catch_broken_code(self):
        """Проверки слоёв и циклов на нарочно испорченном коде (временный каталог): цикл через __init__ пакета, цикл
        через «from ..x import» (к родительскому пакету), «from . import x, y» - каждое имя; __init__ - ниже всех."""
        import tempfile
        root = Path(tempfile.mkdtemp(prefix='ui_broken_'))
        try:
            src = {'m.py': 'from ui.a import x\n', 'ui/__init__.py': '', 'ui/a/__init__.py': 'import m\n',
                   'ui/a/x.py': '', 'ui/b/__init__.py': '', 'ui/b/y.py': 'from ..a import z\n',
                   'ui/a/z.py': 'from ui.b import y\n', 'ui/a/v.py': 'from . import x, z\nfrom ..b import y\n',
                   'ui/a/w.py': 'from ...q import r\n'}
            for k, v in src.items():
                (root / k).parent.mkdir(parents=True, exist_ok=True)
                (root / k).write_text(v, encoding='utf-8')
            g = module_graph(root)
            self.assertIn('ui.a', g['m'])                                      # импорт ui.a.x загружает ui.a
            self.assertEqual(g['ui.a'], {'m'})                                 # __init__ - в графе
            self.assertEqual(g['ui.b.y'], {'ui', 'ui.a', 'ui.a.z'})           # «..a» - родитель, не ui.b.a
            self.assertTrue(find_cycle({k: g[k] for k in ('m', 'ui.a', 'ui.a.x')}))
            self.assertTrue(find_cycle({k: g[k] for k in ('ui.a.z', 'ui.b.y', 'ui', 'ui.a', 'ui.b')}))
            self.assertEqual(ui_targets(root / 'ui/a/v.py', 'a'), [(1, 'x'), (1, 'z')])   # «..b» - не свой пакет
            self.assertEqual(ui_targets(root / 'ui/a/w.py', 'a'), [(1, '..q')])           # выше корня - неизвестный
            (root / 'ui/a/__init__.py').write_text('from .x import X\n', encoding='utf-8')
            t = ui_targets(root / 'ui/a/__init__.py', 'a')
            self.assertEqual(t, [(1, 'x')])
            self.assertTrue(all(ui_rank(k, '__init__') < min(r.values()) for k, r in UI_RANK.items()))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_shims_keep_old_names(self):
        """Переходники отдают все имена прежних модулей (до разбивки: filelist_window - 91, razbor_page - 175)."""
        code = ('import json, filelist_window as f, razbor_page as r; '
                'print(json.dumps([sorted(vars(f)), sorted(vars(r))]))')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        p = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], cwd=str(CAT), env=env, capture_output=True,
                           text=True, encoding='utf-8', timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        import json
        now = json.loads(p.stdout.splitlines()[-1])
        for (name, old), have in zip(SHIM_NAMES.items(), now):
            old = old.split()
            self.assertEqual(len(old), {'filelist_window': 91, 'razbor_page': 175}[name])
            self.assertEqual(sorted(set(old) - set(have)), [], f'{name}.py потерял прежние имена')

    def test_tests_do_not_patch_shim_names(self):
        """Подмена имени модуля-переходника (mock.patch.object(rp, 'X'), mock.patch('filelist_window.X'), а также через
        self.fw = fw) не действует на код в ui/* - тест проверял бы не то или открыл настоящее окно. Подменять там, где
        имя используется, или у класса (rp.RazborPage.set_item - тот же объект класса, разрешено). Разбор по AST:
        многострочные вызовы, псевдонимы."""
        bad = []
        for p in CAT.rglob('test*.py'):
            if '__pycache__' not in p.parts and p.name not in ('test_modules.py', 'test_ui_layers.py'):
                bad += [f'{p.relative_to(CAT)}:{n}' for n in shim_patches(p.read_text(encoding='utf-8'))]
        self.assertEqual(bad, [], 'подмена имени переходника')


if __name__ == '__main__':
    unittest.main()
