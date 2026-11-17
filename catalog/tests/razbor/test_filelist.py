"""«Разбор носителя»: Окно «Список файлов» (этап 16): модель и окно.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_filelist
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
from PySide6.QtWidgets import QFileDialog                 # noqa: E402 - окно сохранения подменяется у класса
from ui.filelist import model_rows, view_buttons         # noqa: E402 - подмены там, где имя используется


class FileModelTest(unittest.TestCase):
    """Этап 16: модель окна «Список файлов» без базы - сортировка всего набора (пустые - в конце), фильтры без обрезки
    пробелов, итог по фильтру, выгрузка."""

    def rows(self):
        import filelist_window as fw
        from hb_core.consts import F_ARCH, F_MUSIC, F_PHOTO, F_TEXT, F_VIDEO
        data = {'rows': [
            ('HDD62', ' X\\a.jpg', 300, 1700000000, 'S', F_PHOTO, '', ''),
            ('HDD62', 'X \\B.mp4', None, 1600000000, None, F_VIDEO, '', ''),          # размер неизвестен
            ('HDD62', 'X\\c.doc', 100, None, 'Z', F_TEXT, '⚠ проба', ''),             # дата неизвестна
            ('HDD62', 'X\\d.zip', 200, 0, 'U', F_ARCH, '', ''),                       # нулевая дата - как пустая
            ('HDD62', 'e.mp3', 50, 1800000000, 'X', F_MUSIC, '', ''),                  # файл в корне
        ]}
        return fw, fw.prepare(data)['model_rows']

    def names(self, m):
        return [m.row(i)[2] for i in range(m.rowCount())]

    def test_sort_filter_totals(self):
        fw, rows = self.rows()
        m = fw.FileModel('nohash')
        m.set_rows('nohash', rows)
        self.assertEqual([m.headerData(i, rp.Qt.Horizontal) for i in range(m.columnCount())],
                         ['Где лежит', 'Имя', 'Тип', 'Размер', 'Дата', 'Хеш', 'Почему'])
        size, date, hsh = m.cols.index(fw.C_SIZE), m.cols.index(fw.C_DATE), m.cols.index(fw.C_HASH)
        m.sort(size, rp.Qt.AscendingOrder)
        self.assertEqual(self.names(m), ['e.mp3', 'c.doc', 'd.zip', 'a.jpg', 'B.mp4'])     # пустой размер - в конце
        m.sort(size, rp.Qt.DescendingOrder)
        self.assertEqual(self.names(m), ['a.jpg', 'd.zip', 'c.doc', 'e.mp3', 'B.mp4'])     # и при обратном порядке
        m.sort(date, rp.Qt.DescendingOrder)
        self.assertEqual(self.names(m), ['e.mp3', 'a.jpg', 'B.mp4', 'c.doc', 'd.zip'])     # без даты - в конце
        self.assertEqual(m.data(m.index(4, date)), '—')
        self.assertEqual(m.data(m.index(2, size)), '—')
        m.sort(hsh)
        self.assertEqual([m.data(m.index(i, hsh)) for i in range(5)],
                         ['посчитан сканером', 'сверен только размер', 'со слов владельца', 'файл изменился',
                          'не считался'])
        m.sort(0)                                                                # по папке: корень, « X», «X», «X »
        self.assertEqual(m.data(m.index(0, 0)), 'HDD62\\')       # корень: «HDD62\» (этап 18)
        self.assertEqual(self.names(m), ['e.mp3', 'a.jpg', 'c.doc', 'd.zip', 'B.mp4'])
        m.set_filter(folder_sub=' x')                                            # пробел ввода не обрезается
        self.assertEqual(self.names(m), ['a.jpg'])
        m.set_filter(folder_sub='x ')
        self.assertEqual(self.names(m), ['B.mp4'])
        m.set_filter(folder_sub='', name_sub='.MP')                              # без учёта регистра
        self.assertEqual(sorted(self.names(m)), ['B.mp4', 'e.mp3'])
        m.set_filter(name_sub='', types={2, 3})                                  # документы и архивы
        self.assertEqual(sorted(self.names(m)), ['c.doc', 'd.zip'])
        self.assertEqual(m.totals(), (2, 300, [0, 0, 1, 1, 0], [0, 0, 100, 200, 0]))
        self.assertEqual(m.totals(visible=False)[0], 5)
        self.assertEqual(m.totals(visible=False)[2], [1, 1, 1, 1, 1])            # музыка - «другие»
        self.assertIn('2 файла · 0,0 ГБ', fw.totals_line(m.totals()))
        self.assertEqual(m.export_rows()[0][:2], ['HDD62\\X', 'c.doc'])     # «Где лежит» - полный путь
        self.assertEqual(m.data(m.index(0, m.cols.index(fw.C_WHY)), rp.Qt.ForegroundRole).name(), '#c62828')
        m.set_filter(types=set(range(5)))
        self.assertFalse(m.filtered())

    def test_columns_of_lists_and_big_set(self):
        import time as _t
        fw, rows = self.rows()
        self.assertEqual(fw.columns('contested')[0], fw.C_DISK)
        self.assertEqual(fw.head('contested', fw.C_WHY), 'Почему спорный')
        self.assertIn(fw.C_WHERE, fw.columns('have'))
        self.assertEqual(fw.collapse(['A\\B', 'A', ' A', 'a\\c']), [' A', 'A'])
        big = rows * 60000                                                       # 300 тыс. строк
        m = fw.FileModel('nohash')
        m.set_rows('nohash', big)
        t0 = _t.time()
        m.sort(m.cols.index(fw.C_SIZE), rp.Qt.DescendingOrder)
        m.sort(m.cols.index(fw.C_NAME))
        m.set_filter(name_sub='.jpg')
        self.assertLess(_t.time() - t0, 15)                                     # без прокси: секунды, не минуты
        self.assertEqual(m.rowCount(), 60000)

    def test_save_csv_and_xlsx(self):
        import csv as _csv
        import tempfile
        from openpyxl import load_workbook
        fw, rows = self.rows()
        tmp = Path(tempfile.mkdtemp(prefix='filelist_'))
        heads = ['Папка', 'Имя']
        data = [[' X', 'a;"b".jpg'], ['X ', 'c.doc']]
        fw.save_table(str(tmp / 'a.csv'), heads, data)
        with open(tmp / 'a.csv', encoding='utf-8-sig', newline='') as f:
            self.assertEqual(list(_csv.reader(f, delimiter=';')), [heads] + data)    # «;» и кавычки не ломают столбцы
        fw.save_table(str(tmp / 'a.xlsx'), heads, data)
        ws = load_workbook(tmp / 'a.xlsx').active
        self.assertEqual([[c.value for c in r] for r in ws.iter_rows()], [heads] + data)
        with mock.patch.object(model_rows, 'XLSX_MAX', 1), self.assertRaises(sv.Refused):
            fw.save_table(str(tmp / 'b.xlsx'), heads, data)


class FileWindowTest(PageBase):
    """Этап 16: окно «Список файлов» из «Разбора носителя» на временной базе: ссылки ячейки, число спорных, Проводник,
    Excel/CSV, пересканирование папок выделенных."""

    def setUp(self):
        super().setUp()
        import filelist_window as fw
        self.fw = fw
        self.fw_asked = []
        self.fw_answer = rp.QMessageBox.Yes
        self.fwp = [mock.patch.object(QMessageBox, 'information', lambda *a, **k: self.fw_asked.append(a[2])),
                    mock.patch.object(QMessageBox, 'question',
                                      lambda *a, **k: self.fw_asked.append(a[2]) or self.fw_answer)]
        for x in self.fwp:
            x.start()

    def tearDown(self):
        for w in list(getattr(self.w, 'file_lists', [])):
            w.close()
        for x in self.fwp:
            x.stop()
        super().tearDown()

    def loaded(self, w):
        self.assertTrue(wait(lambda: w.data is not None, 60), w.total.text())
        return w

    def test_links_open_lists_matching_cell(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Работа', 'Н2'), ('Документы', 'Н2'))
        self.open()
        P = self.plan()
        body = self.p.copy_cell.body.text()
        self.assertIn('href="copy:HDD91"', body)
        w = self.loaded(self.p.show_list('copy:HDD91'))
        self.assertEqual(w.model.rowCount(), P.part_b['HDD91'][0])               # список = число в ячейке
        self.assertTrue(w.title.text().startswith(f'{SRC} · к копированию на '), w.title.text())
        self.assertIn('HDD91', w.title.text())
        self.assertIn('Почему эти файлы: отмечены для «Н2 Работа»', w.sub.text())
        self.assertIn('Всего: <b>3 файла', w.total.text())
        self.assertIn('Показаны все: 3 файла', w.shown.text())
        w.folder_edit.setText('докум')
        w.apply_filter()
        self.assertEqual(w.model.rowCount(), 1)
        self.assertIn('Показаны по фильтру: <b>1 файл', w.shown.text())
        # Excel: весь отфильтрованный набор
        import tempfile
        from openpyxl import load_workbook
        out = Path(tempfile.mkdtemp(prefix='filelist_')) / 'список.xlsx'
        with mock.patch.object(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out), '')):
            w.save_excel()
        self.assertTrue(wait(lambda: out.exists() and w.state.text().startswith('Сохранено'), 30), w.state.text())
        ws = load_workbook(out).active
        self.assertEqual([c.value for c in next(ws.iter_rows())][:3], ['Где лежит', 'Имя', 'Тип'])
        self.assertEqual(ws.max_row, 2)
        out2 = out.with_suffix('.csv')
        with mock.patch.object(view_buttons, 'XLSX_MAX', 0), mock.patch.object(model_rows, 'XLSX_MAX', 0), \
                mock.patch.object(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out2), '')):
            w.save_excel()                                                       # больше листа Excel - вопрос и CSV
        self.assertTrue(wait(lambda: out2.exists() and w.state.text().startswith('Сохранено'), 30), w.state.text())
        self.assertTrue(any('больше, чем помещается на лист Excel' in x for x in self.fw_asked), self.fw_asked)
        # «уже есть» и «не подходит по типу»
        w2 = self.loaded(self.p.show_list('type:'))
        self.assertEqual(w2.model.rowCount(), P.part_a.get((rz.O_TYPE, 'Н2'), (0, 0))[0])
        self.assertTrue(w2.title.text().endswith('не подходит по типу для «Н2 Работа»'), w2.title.text())

    def test_explorer_rescan_and_refresh(self):
        self.open()
        w = self.loaded(self.p.show_list('contested'))
        self.assertGreater(w.model.rowCount(), 0)
        self.assertEqual(w.model.cols[0], self.fw.C_DISK)
        self.assertEqual(w.model.headerData(len(w.model.cols) - 1, rp.Qt.Horizontal), 'Почему спорный')
        w.view.selectAll()
        rows = w.selected_rows()
        self.assertTrue(wait(lambda: 'файл' in w.rescan_btn.text() or 'папок)' in w.rescan_btn.text(), 10),
                        w.rescan_btn.text())
        # не подключён - подсказка
        with sv_patch('disk_letter', side_effect=sv.Refused('HDD60 не подключён: подключите диск')):
            w.open_explorer()
            self.assertTrue(wait(lambda: any('не подключён' in x for x in self.fw_asked), 10), self.fw_asked)
        # подключён - папка файла с выделением
        import tempfile
        root = Path(tempfile.mkdtemp(prefix='letter_'))
        w.view.clearSelection()
        w.view.selectRow(next(i for i in range(w.model.rowCount()) if w.model.row(i)[1]))
        r = w.current()
        (root / r[1]).mkdir(parents=True, exist_ok=True)
        (root / r[1] / r[2]).write_bytes(b'x')
        calls = []
        with sv_patch('disk_letter', lambda d: str(root)), \
                mock.patch('subprocess.Popen', lambda cmd, *a, **k: calls.append(cmd)):
            w.open_explorer()
            self.assertTrue(wait(lambda: calls, 10))
        self.assertEqual(calls[0], f'explorer /select,"{root}\\{r[1]}\\{r[2]}"')
        # пересканирование папок выделенных: один диск, вопрос с числами, окно пересканирования, «данные устарели»
        w.view.clearSelection()
        own = [i for i in range(w.model.rowCount()) if w.model.row(i)[0] == SRC and w.model.row(i)[1]]
        from PySide6.QtCore import QItemSelectionModel
        for i in own:
            w.view.selectionModel().select(w.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        made = []

        class FakeDlg:
            def __init__(self, win, disk, folders):
                made.append((disk, folders))
                self.running = False
                from PySide6.QtCore import QObject, Signal

                class S(QObject):
                    finished = Signal(int)
                self.s = S()
                self.finished = self.s.finished

            def show(self):
                pass
        with mock.patch('rescan_dialog.RescanDialog', FakeDlg):
            w.rescan()
        self.assertEqual(made[0][0], SRC)
        self.assertEqual(made[0][1], self.fw.collapse(w.model.row(i)[1] for i in own))
        self.assertTrue(any(x.startswith(f'Пересканировать {len(made[0][1])} папок {SRC} — ') for x in self.fw_asked),
                        self.fw_asked)
        self.w.rescan.finished.emit(0)
        self.assertTrue(w.stale.isVisibleTo(w))
        w.load()
        self.loaded(w)
        self.assertTrue(wait(lambda: not w.stale.isVisibleTo(w), 30))

    def test_contested_button_counts_and_unique(self):
        self.open()
        self.assertTrue(wait(lambda: getattr(self.p, 'cont_n', None) is not None, 30))
        n = sv.contested_count(SRC)['total']
        self.assertGreater(n, 0)
        self.assertEqual(self.p.contested_btn.text(), f'Пересчитать хеши спорных файлов ({n})…')
        self.assertTrue(self.p.contested_btn.isEnabled() and self.p.contested_list_btn.isEnabled())
        self.assertIn('Спорные — файлы, чью копию нельзя проверить по SHA-256', self.p.contested_note.text())
        with sv_patch('contested_count', lambda d, f='': dict(total=0, carrier=0, copies=0)):
            self.p.run_contested_count()
            self.assertTrue(wait(lambda: self.p.cont_n == 0, 10))
        self.assertFalse(self.p.contested_btn.isEnabled())                       # 0 - неактивна
        self.assertFalse(self.p.contested_list_btn.isEnabled())
        self.item('Работа').setSelected(True)                                    # выделена папка - число для неё
        self.assertTrue(wait(lambda: self.p.cont_n == sv.contested_count(SRC, 'Работа')['total'], 30))
        w = self.loaded(self.p.show_list('unique'))
        self.assertEqual({w.model.row(i)[2] for i in range(w.model.rowCount())}, {'схема.jpg'})
        self.assertIn('без хеша', w.notes.text())
        w.close()
        self.assertTrue(w.closed)
        w.got(w.req, ('ok', {}))                                                 # ответ после закрытия не показывается


if __name__ == '__main__':
    unittest.main()
