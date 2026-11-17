"""Раздел «Диски и папки» без экрана (Qt offscreen): порядок носителей, столбцы, папки с составом и решением, панель
действий, исправленная ошибка выбора найденной папки (замечание владельца, docx_2 п. 11–13, скриншоты 9–10).

Запуск из корня проекта:  py -m unittest catalog.test_disks_page
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import app                                                 # noqa: E402
import commands_page as cpg                                # noqa: E402
import disk_ui                                             # noqa: E402

QAPP = QApplication.instance() or QApplication([])


def row(disk, letter='', status='complete', label='', partial=0):
    r = dict(disk=disk, label=label, letter=letter, files=10, gib=1.0, status=status, scanned='01.01.2026',
             partial=partial)
    if letter:
        r['free_gib'] = 421.0
    return r


ROWS = [row('Flash01'), row('Flash02', 'G:'), row('HDD09', 'F:', label='WDS200T1X0E - 2 ТБ - Работа - SN850', partial=2),
        row('HDD01', status='running'), row('HDD18', 'K:', status='complete_with_inventory_errors'), row('HDD100')]
MARK_DIR = dict(kind='dir', text='Н2 Работа', own=True, src='')
NOHASH = dict(total=3, media=1, by_type=[1, 0, 1, 0, 1], zux=0, folders={'': 3, 'Фото': 2, 'Прочее': 1})


def hash_info(d):
    return dict(text='опись от 01.01.2026', tip='', hash='⚠ Без хеша 1 фото и видео — копию нельзя проверить',
                alarm=True, nohash=NOHASH)
MARK_SKIP = dict(kind='skip', text='не копировать', own=False, src='весь носитель')


def children(disk, path):
    if path == '':
        return [dict(name='Фото', path='Фото', files=5, gib=0.5, types=[0.5, 0, 0, 0, 0], decision='', mark=MARK_DIR),
                dict(name='Прочее', path='Прочее', files=3, gib=0.2, types=[0, 0.1, 0, 0.1, 0], decision='',
                     mark=MARK_SKIP),
                dict(name='Пусто', path='Пусто', files=1, gib=0.0, types=[0, 0, 0, 0, 0], decision='',
                     mark=dict(kind='', text='', own=False, src=''))]
    return []


class Bg:
    """Фон без потоков: функция выполняется сразу."""
    def __init__(self):
        self.calls = []

    def run(self, fn, *args, ok=None, quiet=False):
        self.calls.append((fn, args))
        res = fn(*args)
        if ok:
            ok(res)


class Win:
    def __init__(self):
        self.bg = Bg()
        self.rescan = None


class DiskUiTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual([r['disk'] for r in disk_ui.ordered(ROWS)],
                         ['HDD09', 'HDD18', 'Flash02', 'HDD01', 'HDD100', 'Flash01'])

    def test_status(self):
        self.assertEqual(disk_ui.status_text('complete'), 'полная')
        self.assertEqual(disk_ui.status_text('complete_with_inventory_errors'), 'полная, есть нечитаемые места')
        self.assertEqual(disk_ui.status_text('running'), 'не закончена')
        self.assertEqual(disk_ui.status_text(''), '—')
        self.assertNotIn('_', disk_ui.status_text('something_new'))

    def test_commands_page_uses_same_functions(self):
        self.assertIs(cpg.split_disks, disk_ui.split_disks)
        self.assertIs(cpg.disk_text, disk_ui.disk_text)
        self.assertIs(cpg.style_item, disk_ui.style_item)

    def test_disk_name_without_model(self):
        """Решение владельца 16.11: модель и док-станцию («JMicron 6 ТБ», «WD 2 ТБ») не показывать нигде - только
        метку тома. Одна функция подписи; прежняя disk_title - её синоним."""
        name = disk_ui.disk_name
        self.assertEqual(name({'label': 'JMicron Tach - 6 ТБ - Работа Сафари 6ТБ'}), 'Работа Сафари 6ТБ')
        self.assertEqual(name({'disk': 'HDD78', 'label': 'HDD78 - JMicron Tach - 6 ТБ - Работа Сафари 6ТБ'}),
                         'Работа Сафари 6ТБ')                                      # номер в подписи - отбрасывается
        self.assertEqual(name({'label': 'ST14000NM000J - 14 ТБ - Фото 2018 - 2025'}), 'Фото 2018 - 2025')   # « - » в метке
        self.assertEqual(name({'label': 'WDC WD6401AALS-00J7B1 - 640 ГБ'}), '')       # метки нет
        self.assertEqual(name({'label': 'WD My Passport 0730 - My Passport - 500гигабайт'}),
                         'My Passport - 500гигабайт')                               # без объёма - всё после модели
        self.assertEqual(name({'label': ''}), '')
        self.assertIs(disk_ui.disk_title, disk_ui.disk_name)
        r = {'disk': 'HDD55', 'label': 'WD My Book 1132 - 2 ТБ - My Book', 'letter': 'I:'}
        self.assertEqual(disk_ui.disk_place(r), 'I: My Book')
        self.assertEqual(disk_ui.disk_text(r), '● HDD55 — I: — My Book')
        self.assertEqual(disk_ui.disk_text({'disk': 'HDD61', 'label': 'ACASIS EC-7352 - 750 ГБ', 'letter': ''}),
                         'HDD61 — Накопитель — не подключён')
        for x in (disk_ui.disk_place(r), disk_ui.disk_text(r)):
            self.assertNotIn('WD', x)
            self.assertNotIn('ТБ', x)


class DisksPageTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(app.sv, disks=lambda: [dict(r) for r in ROWS], folder_children=children,
                                     hash_dates=lambda d, p: dict(text='', hint=''), generation=lambda: 'g1',
                                     disk_hash_info=hash_info, nohash_info=lambda d: NOHASH,
                                     find_folders=lambda words: [dict(disk='HDD09', path='Работа\\Сафари', files=4, gib=0.4,
                                                                      types=[0.3, 0.1, 0, 0, 0], mark=MARK_DIR),
                                                                 dict(disk='HDD01', path='Сафари', files=2, gib=0.1)])
        self.p.start()
        self.win = Win()
        self.page = app.DisksPage(self.win)
        self.page.refresh()

    def tearDown(self):
        self.p.stop()

    def col(self, j):
        return [self.page.t.item(i, j).text() for i in range(self.page.t.rowCount())]

    def root(self):
        return self.page.tree.topLevelItem(0)

    def test_order_and_columns(self):
        self.assertEqual([self.page.t.horizontalHeaderItem(j).text() for j in range(self.page.t.columnCount())],
                         ['Диск', 'Подключён', 'Свободно', 'Файлов', 'ГБ', 'Сканирование'])
        self.assertEqual(self.col(0), ['F: — Работа - SN850 — HDD09', 'K: — Накопитель — HDD18', 'G: — Флешка — Flash02',
                                       'Накопитель — HDD01', 'Накопитель — HDD100', 'Флешка — Flash01'])                                # буква — метка — HDD, без модели
        self.assertEqual(self.col(1), ['да', 'да', 'да', 'нет', 'нет', 'нет'])
        self.assertEqual(self.col(2)[:4], ['421,0 ГБ', '421,0 ГБ', '421,0 ГБ', '—'])
        self.assertTrue(self.page.t.item(0, 0).font().bold())
        self.assertFalse(self.page.t.item(3, 0).font().bold())
        self.assertNotIn('WDS200T1X0E', ' '.join(self.col(0)))
        self.assertIn('Носители (6)', self.page.count_lab.text())

    def test_scan_column(self):
        st = dict(zip([r['disk'] for r in self.page.rows], self.col(5)))
        self.assertEqual(st['HDD09'], '01.01.2026 · полное · после полной описи 2 раза пересканированы выбранные папки')
        self.assertEqual(st['HDD18'], '01.01.2026 · полное, есть нечитаемые места')
        self.assertEqual(st['HDD01'], '01.01.2026 · не закончено')
        self.assertIn('running', self.page.t.item(3, 5).toolTip())

    def test_first_connected_selected_with_folders(self):
        self.assertEqual(self.page.disk, 'HDD09')
        self.assertEqual(self.page.t.currentRow(), 0)
        root = self.root()
        self.assertEqual(root.text(app.T_NAME), 'HDD09 (весь диск)')
        self.assertEqual([root.child(i).text(app.T_NAME) for i in range(root.childCount())], ['Фото', 'Прочее', 'Пусто'])
        self.assertEqual(self.page.tree_title.text(), 'Папки диска F: — Работа - SN850 — HDD09')
        self.assertIn('10 файлов · 1,0 ГБ · опись от 01.01.2026', self.page.tree_sum.text())
        h = self.page.hash_lab.text()                                               # этап 16: вместо «хеш у 73 %»
        self.assertIn('⚠ Без хеша 1 фото и видео', h)
        self.assertIn('Без хеша: <b>2</b> файла (документы, архивы, другие — их тип при сканировании не выбирался)', h)
        self.assertIn('Показать</a>', h)

    def test_tree_columns_bar_and_decision(self):
        heads = [self.page.tree.headerItem().text(j) for j in range(self.page.tree.columnCount())]
        self.assertEqual(heads, ['', 'Папка', 'Файлов', 'ГБ', 'Без хеша', 'фото', 'видео', 'тексты', 'прочие', 'мусор',
                                 'Решение владельца'])
        foto, other, empty = (self.root().child(i) for i in range(3))
        self.assertEqual(foto.text(app.T_GB), '0,5')
        self.assertTrue(foto.font(app.T_GB).bold())                                # ГБ - жирно
        self.assertEqual(foto.font(app.T_GB).pointSizeF(), self.page.tree.font().pointSizeF())   # шрифт дерева
        self.assertEqual(foto.text(app.T_TYPE0), '0,5')
        self.assertEqual(foto.text(app.T_TYPE0 + 1), '—')                          # ноль - серый прочерк
        self.assertEqual(foto.foreground(app.T_TYPE0 + 1).color().name(), '#bdbdbd')
        self.assertEqual(foto.data(app.T_NAME, app.TYPES_ROLE), [0.5, 0, 0, 0, 0])  # полоска состава под именем
        self.assertEqual(foto.data(app.T_DEC, app.MARK_ROLE)['kind'], 'dir')       # оранжевая плашка с направлением
        self.assertEqual(other.data(app.T_DEC, app.MARK_ROLE)['kind'], 'skip')     # серая «не копировать»
        self.assertIn('от «весь носитель»', other.toolTip(app.T_DEC))
        self.assertEqual(empty.text(app.T_DEC), '—')                                # нет решения - прочерк
        self.assertTrue(foto.flags() & Qt.ItemIsUserCheckable)
        self.assertIsNone(self.root().data(app.T_CHECK, Qt.CheckStateRole))        # весь диск не отмечается
        self.page.tree.grab()                                                       # делегат рисует без ошибок

    def test_selection_line_and_actions(self):
        self.assertIn('Выбрано папок: 0', self.page.sel_lab.text())
        self.assertFalse(self.page.rescan_btn.isEnabled())
        foto, other = self.root().child(0), self.root().child(1)
        foto.setCheckState(app.T_CHECK, Qt.Checked)
        other.setCheckState(app.T_CHECK, Qt.Checked)
        self.assertEqual(self.page.sel_lab.text(), 'Выбрано папок: 2 · файлов 8 · 0,7 ГБ')
        self.assertIn('Диск подключён (F:)', self.page.state.text())
        self.assertTrue(self.page.rescan_btn.isEnabled() and self.page.open_btn.isEnabled())
        opened = []
        with mock.patch.object(app.os, 'startfile', opened.append, create=True), \
                mock.patch.object(app.os.path, 'isdir', lambda p: True):
            self.page.open_explorer()
        self.assertEqual(opened, ['F:\\Фото', 'F:\\Прочее'])
        made = []
        with mock.patch.object(app.rescan_dialog, 'RescanDialog',
                               lambda win, disk, folders: made.append((disk, folders)) or mock.Mock(running=False)):
            self.page.rescan()
        self.assertEqual(made, [('HDD09', ['Фото', 'Прочее'])])

    def test_missing_on_direction_disks(self):
        import types
        import directions_page
        self.root().child(0).setCheckState(app.T_CHECK, Qt.Checked)
        got = []

        def fm(disk, path, targets):
            got.append((disk, path, list(targets)))
            return dict(files=5, gib=0.5, nohash=1, missing={'HDD45': (2, 0.2), 'HDD77': (0, 0.0)}, weak={'HDD45': 1},
                        stale=0)
        with mock.patch.object(directions_page, 'chosen', lambda: [types.SimpleNamespace(disks=('HDD45', 'HDD77'))]), \
                mock.patch.object(app.sv, 'folder_missing', fm, create=True):
            self.page.presence()
        self.assertEqual(got, [('HDD09', 'Фото', ['HDD45', 'HDD77'])])            # диски - отмеченных в «Обзоре»
        text = self.page.info.text()
        self.assertIn('нет на HDD45 — <b>2</b> файлов', text)
        self.assertIn('на HDD77 есть всё', text)
        self.assertIn('непроверенная копия', text)
        self.assertIn('без хеша (сравнить нельзя) — 1', text)
        self.assertEqual(self.page.missing_btn.text(), 'Чего нет на дисках направления')
        asked = []
        with mock.patch.object(directions_page, 'chosen', lambda: []), \
                mock.patch.object(app.QMessageBox, 'information', lambda *a: asked.append(a[2])):
            self.page.presence()
        self.assertIn('не отмечено ни одного направления', asked[0])

    def test_found_folder_keeps_its_disk(self):
        """Ошибка владельца (скриншоты 9–10): после поиска выбранная найденная папка - «Выберите диск…». Теперь у
        каждой найденной строки свой диск и путь: пересканирование, Проводник и «чего нет» берут их из строки."""
        self.page.search.setText('Сафари')
        self.page.find()
        self.assertIsNone(self.page.disk)
        a, b = self.page.tree.topLevelItem(0), self.page.tree.topLevelItem(1)
        self.assertEqual(a.text(app.T_NAME), 'HDD09\\Работа\\Сафари')
        self.assertEqual(a.data(app.T_NAME, app.TYPES_ROLE), [0.3, 0.1, 0, 0, 0])   # полоска и типы - как в дереве
        self.assertEqual(a.text(app.T_TYPE0), '0,3')
        self.assertEqual(a.data(app.T_DEC, app.MARK_ROLE)['kind'], 'dir')          # решение владельца - плашкой
        self.page.tree.setCurrentItem(a)                                            # выделена одна найденная строка
        self.assertIn('Выбрано папок: 1', self.page.sel_lab.text())
        self.assertIn('Диск подключён (F:)', self.page.state.text())
        made, asked = [], []
        with mock.patch.object(app.rescan_dialog, 'RescanDialog',
                               lambda win, disk, folders: made.append((disk, folders)) or mock.Mock(running=False)), \
                mock.patch.object(app.QMessageBox, 'information', lambda *a: asked.append(a[2])):
            self.page.rescan()
            self.assertEqual(made, [('HDD09', ['Работа\\Сафари'])])
            self.assertEqual(asked, [])
            a.setCheckState(app.T_CHECK, Qt.Checked)
            b.setCheckState(app.T_CHECK, Qt.Checked)                                # папки двух дисков
            self.assertFalse(self.page.rescan_btn.isEnabled())
            self.assertIn('Подключите HDD01', self.page.state.text())
            self.page.rescan()
        self.assertIn('разных дисков', asked[-1])

    def test_refresh_keeps_choice(self):
        self.page.t.setCurrentCell(4, 0)                 # HDD100
        self.assertEqual(self.page.disk, 'HDD100')
        self.page.refresh()
        self.assertEqual(self.page.disk, 'HDD100')
        self.assertEqual(self.page.rows[self.page.t.currentRow()]['disk'], 'HDD100')

    def test_nohash_column_and_click(self):
        """Этап 16: столбец «Без хеша» (поддерево, один проход на носитель), ноль - серый прочерк, щелчок по числу -
        окно «Список файлов» этой папки; ссылка «Показать» - весь носитель."""
        foto, other, empty = (self.root().child(i) for i in range(3))
        self.assertEqual(self.root().text(app.T_NOHASH), '3')
        self.assertEqual((foto.text(app.T_NOHASH), other.text(app.T_NOHASH), empty.text(app.T_NOHASH)), ('2', '1', '—'))
        self.assertEqual(empty.foreground(app.T_NOHASH).color().name(), '#bdbdbd')
        opened = []
        from ui.filelist import page as filelist_page          # подмена там, где имя используется (disks_page)
        with mock.patch.object(filelist_page, 'open_list', lambda win, **kw: opened.append(kw)):
            self.page.item_clicked(foto, app.T_NOHASH)
            self.page.item_clicked(empty, app.T_NOHASH)                                # ноль - не ссылка
            self.page.item_clicked(foto, app.T_GB)                                     # другой столбец - ничего
            self.page.hash_lab.linkActivated.emit('nohash:')
        self.assertEqual(opened, [dict(kind='nohash', disk='HDD09', folder='Фото'),
                                  dict(kind='nohash', disk='HDD09', folder='')])

    def test_nothing_connected(self):
        with mock.patch.object(app.sv, 'disks', lambda: [row('HDD01'), row('Flash01')]):
            p = app.DisksPage(Win())
            p.refresh()
        self.assertIsNone(p.disk)
        self.assertEqual(p.tree.topLevelItemCount(), 0)


if __name__ == '__main__':
    unittest.main()
