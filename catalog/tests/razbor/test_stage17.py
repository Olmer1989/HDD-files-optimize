"""«Разбор носителя»: Этапы 16-17: правки по коду, автосохранение, большое дерево, сторож зависания, дерево списка.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_stage17
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях


class CodeReview16UiTest(PageBase):
    """Этап 16, замечания критиков по коду окна: число спорных не посчитано - без ложного числа; пустые «Почему» и
    «Где копия» сортируются; строки Excel готовятся в фоне из снимка; выделены только файлы корня - кнопка неактивна."""

    def test_contested_count_error_has_no_false_number(self):
        self.open()
        with sv_patch('contested_count', side_effect=sv.Refused('проба')):
            self.p.run_contested_count()
            self.assertTrue(wait(lambda: self.p.cont_n == -1, 10))
        self.assertNotRegex(self.p.contested_btn.text(), r'\(\d')
        self.assertIn('не посчитано', self.p.contested_btn.text())
        self.assertIn('проба', self.p.contested_btn.toolTip())
        self.assertTrue(self.p.contested_btn.isEnabled())                       # окно ищет спорные само

    def test_empty_why_sorted_and_export_from_snapshot(self):
        import filelist_window as fw
        from hb_core.consts import F_PHOTO
        data = fw.prepare({'rows': [('HDD62', 'A\\b.jpg', 5, 1, 'S', F_PHOTO, None, None),
                                    ('HDD62', 'c.jpg', None, None, None, F_PHOTO, 'z', '')]})
        m = fw.FileModel('nohash')
        m.set_rows('nohash', data['model_rows'])
        m.sort(m.cols.index(fw.C_WHY))                                           # None -> '' - без ошибки
        self.assertEqual([m.row(i)[2] for i in range(2)], ['b.jpg', 'c.jpg'])
        snap = (m.rows, list(m.idx), list(m.cols))
        m.sort(m.cols.index(fw.C_WHY), rp.Qt.DescendingOrder)                   # окно сортирует дальше
        self.assertEqual([r[1] for r in fw.export_values(*snap)], ['b.jpg', 'c.jpg'])    # снимок не меняется
        self.assertEqual(fw.export_values(*snap)[1][3], '')                     # размер неизвестен - пусто

    def test_root_files_only_disable_rescan(self):
        self.open()
        import filelist_window as fw
        w = fw.open_list(self.w, kind='nohash', disk=SRC, folder='')
        self.assertTrue(wait(lambda: w.data is not None, 60))
        w.view.clearSelection()
        w.view.selectRow(next(i for i in range(w.model.rowCount()) if not w.model.row(i)[1]))   # корень.txt
        w.count_selected()
        self.assertFalse(w.rescan_btn.isEnabled())
        w.view.selectRow(next(i for i in range(w.model.rowCount()) if w.model.row(i)[1]))
        w.count_selected()
        self.assertTrue(wait(lambda: w.rescan_btn.isEnabled() and w.sel_files is not None, 10))
        w.close()


class Stage17AutosaveTest(PageBase):
    """Этап 17, п. 0: запись отметок - не две сразу; записано, но перечитка упала - без повторной записи; отмена после
    автосохранения."""

    def rows(self):
        return hb.DECISIONS.read_text(encoding='utf-8-sig').splitlines() if hb.DECISIONS.exists() else []

    def test_flush_waits_but_never_writes_twice(self):
        import threading
        self.open()
        gate = threading.Event()
        real = sv.add_marks_batch
        calls = []

        def slow(*a, **k):
            calls.append(threading.current_thread() is threading.main_thread())
            gate.wait(10)
            return real(*a, **k)
        with sv_patch('add_marks_batch', slow), mock.patch.object(flow_autosave, 'FLUSH_WAIT_MS', 200):
            self.p.apply(['Работа'], N2)
            self.assertTrue(wait(lambda: self.p.saving, 10))
            self.p.apply(['Друзья'], N2)                                         # правка во время записи
            self.assertFalse(self.p.flush_now('Закрыть?'))                      # запись идёт - отказ, второй нет
            self.assertTrue(any('Запись отметок ещё идёт' in x for x in self.asked), self.asked)
            self.assertEqual(calls, [False])
            gate.set()
            self.settle()
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tРабота\t' in x), 1)
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tДрузья\t' in x), 1)   # следующим пакетом, один раз
        self.assertEqual(self.p.model.drafts, {})

    def test_flush_after_finished_write_takes_its_answer(self):
        self.open()
        self.p.apply(['Работа'], N2)
        self.p.save_timer.stop()
        self.p.autosave()
        QThreadPool.globalInstance().waitForDone(10000)                         # запись закончилась, ответ не принят
        self.assertTrue(self.p.flush_now('Закрыть?'))
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tРабота\t' in x), 1)
        self.assertFalse(any('не сохранились' in x for x in self.asked), self.asked)

    def test_written_but_reread_failed_is_not_written_again(self):
        self.open()
        real = sv.razbor_tree
        fails = []

        def once(disk):
            if not fails:
                fails.append(1)
                raise OSError('проба: база занята')
            return real(disk)
        with sv_patch('razbor_tree', once):
            self.p.apply(['Работа'], N2)
            self.settle()
            self.assertTrue(wait(lambda: self.p.loading is None and self.p.model.inflight == {}, 20))
            self.settle()
        self.assertEqual(fails, [1])
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tРабота\t' in x), 1)    # без дубля
        self.assertEqual(self.p.model.drafts, {})
        self.assertEqual(self.p.model.saved_ms.get('Работа').num, 'Н2')          # перечитано заново

    def test_undo_after_each_autosave(self):
        self.open()
        self.p.apply(['Работа'], N2)
        self.settle()
        self.p.apply(['Работа'], rp.SKIP)
        self.settle()
        self.assertEqual(self.p.model.saved_ms.get('Работа').kind, rp.R_SKIP)
        self.p.undo()
        self.settle()
        self.assertEqual(self.p.model.saved_ms.get('Работа').num, 'Н2')
        self.p.undo()
        self.settle()
        self.assertIsNone(self.p.model.saved_ms.get('Работа'))
        self.assertFalse(self.p.undo_btn.isEnabled())


class Stage17TreeTest(PageBase):
    """Этап 17, п. 1: порции детей большой папки, обновление только изменившихся строк, плашка пересчёта в ячейке."""
    BIG = 1300

    def setUp(self):
        super().setUp()
        make_disk(self.scans, 'HDD64', 'AAAA0064', [(f'Big\\d{i:04d}\\a.jpg', 100, f'{1000 + i:064x}')
                                                     for i in range(self.BIG)])
        self.quiet(hb.connect)

    def test_chunks_and_fast_update(self):
        import time as _t
        self.open('HDD64')
        big = self.item('Big')
        big.setExpanded(True)
        self.assertEqual(big.childCount(), rp.CHUNK + 1)                         # 500 и строка «ещё …»
        more = big.child(rp.CHUNK)
        self.assertEqual(more.data(rp.C_NAME, rp.MORE_ROLE), ('Big', rp.CHUNK))
        self.assertIn(f'ещё {self.BIG - rp.CHUNK}', more.text(rp.C_NAME))
        self.assertTrue(self.p.show_more('Big'))
        self.assertTrue(self.p.show_more('Big'))
        self.assertEqual(big.childCount(), self.BIG)                             # всё показано, строки «ещё» нет
        self.assertFalse(self.p.show_more('Big'))
        self.assertEqual(len(self.p.items), self.BIG + 2)
        changed = []
        real = rp.RazborPage.set_item
        with mock.patch.object(rp.RazborPage, 'set_item',
                               lambda s, it, f, mode=None: changed.append(real(s, it, f, mode)) or changed[-1]):
            self.p.update_items()
        self.assertFalse(any(changed))                                           # ничего не изменилось - сеттеров нет
        t0 = _t.perf_counter()
        self.p.toggle(['Big'], True)                                             # 1 300 подпапок меняют вид
        dt = _t.perf_counter() - t0
        print(f'\nэтап 17: правка папки с {self.BIG} раскрытыми подпапками - {dt:.2f} с')
        self.assertLess(dt, 1.5)
        self.assertEqual(self.p.items['Big\\d0007'].checkState(rp.C_CHECK), rp.Qt.Checked)
        self.p.toggle(['Big\\d0007'], False)                                     # подпапку - исключить
        self.assertEqual(self.p.items['Big'].checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)
        self.p.items['Big'].setCheckState(rp.C_CHECK, rp.Qt.Checked)             # щелчок по частичной - снять всё
        self.assertEqual(self.p.items['Big'].checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.settle()

    def test_busy_plate_inside_copy_cell(self):
        self.open()
        self.assertIs(self.p.busy_lab, self.p.copy_cell.busy)
        self.assertIs(self.p.busy_lab.parentWidget(), self.p.copy_cell)
        self.p.changed(debounce=True)
        self.assertTrue(self.p.busy_lab.isVisibleTo(self.p.copy_cell))
        self.assertIn('#9e9e9e', self.p.copy_cell.body.styleSheet())              # прежний итог - бледно
        self.settle()
        self.assertFalse(self.p.busy_lab.isVisibleTo(self.p.copy_cell))
        self.assertEqual(self.p.copy_cell.body.styleSheet(), '')
        self.assertNotIn('Считаю…', self.p.copy_cell.body.text())


class Stage17WatchdogTest(unittest.TestCase):
    """Этап 17: сторож зависаний пишет стеки (faulthandler) и паузы окна; медленные операции - строкой."""

    def setUp(self):
        import tempfile
        import ui_common
        self.uc = ui_common
        self.tmp = Path(tempfile.mkdtemp(prefix='hang_'))
        self.saved = hb.ANSWERS
        self.p = [mock.patch.object(ui_common.hb, 'ANSWERS', self.tmp), mock.patch.object(ui_common, 'HANG_DUMP_S', 1),
                  mock.patch.object(ui_common, 'HANG_GAP_S', 0.5), mock.patch.object(ui_common, 'SLOW_S', 0.05)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_dump_gap_and_slow(self):
        import time as _t
        from test_app import QAPP
        w = self.uc.Watchdog(interval_ms=100)
        self.assertTrue(w.start())
        for _ in range(3):
            QAPP.processEvents()
            _t.sleep(0.05)
        _t.sleep(1.6)                                                            # главный поток «завис»
        end = _t.time() + 1
        while _t.time() < end:
            QAPP.processEvents()
            _t.sleep(0.02)
        w.stop()
        log = (self.tmp / self.uc.HANG_LOG).read_text(encoding='utf-8', errors='replace')
        self.assertIn('most recent call first', log)                            # стеки всех потоков
        self.assertIn('окно не отвечало', log)

        @self.uc.timed('проба')
        def slow():
            _t.sleep(0.1)
        slow()
        self.assertIn('медленно: проба', (self.tmp / self.uc.HANG_LOG).read_text(encoding='utf-8', errors='replace'))


class Stage17ListTreeTest(PageBase):
    """Этап 17, п. 2: дерево папок в окне «Список файлов» - галочки = отметки «Разбора», снятая папка видна, щелчок -
    фильтр, «меньше N КБ», мелкие картинки, неактивно во время записи."""

    def tearDown(self):
        for w in list(getattr(self.w, 'file_lists', [])):
            w.close()
        super().tearDown()

    def test_folder_tree_marks_and_filters(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Работа', 'Н2'), ('Документы', 'Н2'))
        self.open()
        self.plan()
        w = self.p.show_list('copy:HDD91')
        self.assertTrue(wait(lambda: w.data is not None, 60))
        self.assertEqual(set(w.f_items) - {''}, {'Работа', 'Документы'})
        it = w.f_items['Работа']
        self.assertEqual(it.checkState(0), rp.Qt.Checked)
        self.assertTrue(it.flags() & rp.Qt.ItemIsUserCheckable)
        self.assertIn('Мелкие картинки до 10 КБ: <b>1</b>', w.small.text())
        w.f_clicked(it)                                                          # щелчок по папке - фильтр
        self.assertEqual({w.model.row(i)[1] for i in range(w.model.rowCount())}, {'Работа'})
        w.size_box.setValue(1)                                                    # скрыть меньше 1 КБ (все маленькие)
        w.apply_filter()
        self.assertEqual(w.model.rowCount(), 0)
        w.size_box.setValue(0)
        w.apply_filter()
        w.f_clicked(w.f_items[''])                                               # корень - сброс
        self.assertEqual(w.model.rowCount(), 3)
        it.setCheckState(0, rp.Qt.Unchecked)                                     # снять в окне = отметка «Разбора»
        self.assertIsNone(self.p.model.own_mark('Работа'))                      # своя Н2 снята (родитель не Н2)
        self.settle()
        self.assertTrue(wait(lambda: w.model.rowCount() == 1 and 'Работа' in w.f_items, 30))   # перечитано
        self.assertEqual(w.f_items['Работа'].checkState(0), rp.Qt.Unchecked)    # снятая - видна, 0 файлов
        self.assertEqual(w.f_items['Работа'].text(1), '0')
        w.f_items['Работа'].setCheckState(0, rp.Qt.Checked)                      # вернуть
        self.settle()
        self.assertTrue(wait(lambda: w.model.rowCount() == 3, 30))
        self.assertEqual(self.p.model.saved_ms.get('Работа').num, 'Н2')
        self.p.saving = True                                                     # «Разбор» пишет - галочки неактивны
        w.refresh_checks()
        self.assertFalse(w.f_items['Работа'].flags() & rp.Qt.ItemIsUserCheckable)
        self.assertIn('Идёт запись', w.marks_note.text())
        self.p.saving = False
        w.refresh_checks()
        w.toggle_small()                                                         # только папки с мелкими картинками
        self.assertEqual(set(w.f_items) - {''}, {'Работа'})
        self.assertIn('все папки', w.small.text())
        w.toggle_small()
        self.assertEqual(set(w.f_items) - {''}, {'Работа', 'Документы'})


class Stage17CodeReviewTest(PageBase):
    """Этап 17, критики по коду: ошибка записи не теряет черновик; flush_now ждёт только свою запись; щелчок по галочке
    в дереве окна - не фильтр; закрытое окно отключено от сигналов страницы."""

    def rows(self):
        return hb.DECISIONS.read_text(encoding='utf-8-sig').splitlines() if hb.DECISIONS.exists() else []

    def test_write_error_keeps_drafts_and_retries_on_next_mark(self):
        self.open()
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise OSError('проба: диск занят')
        with sv_patch('add_marks_batch', boom):
            self.p.apply(['Работа'], N2)
            self.settle()
            wait(lambda: False, 0.3)
        self.assertEqual(calls, [1])                                             # без повторов по кругу
        self.assertEqual(self.p.model.drafts['работа']['verdict'], N2)          # отметка владельца не потеряна
        self.assertTrue(any('остались на экране несохранёнными' in x for x in self.asked), self.asked)
        self.assertFalse(any(f'{SRC}\tРабота\t' in x for x in self.rows()))
        self.p.apply(['Друзья'], N2)                                             # следующая правка - пишутся обе
        self.settle()
        self.assertEqual(self.p.model.drafts, {})
        self.assertEqual(self.p.model.saved_ms.get('Работа').num, 'Н2')
        self.assertEqual(self.p.model.saved_ms.get('Друзья').num, 'Н2')

    def test_flush_waits_only_own_write(self):
        import threading
        self.open()
        other = threading.Event()
        self.w.bg.run(lambda: other.wait(10))                                   # посторонняя долгая задача пула
        self.p.apply(['Работа'], N2)
        self.p.save_timer.stop()
        self.p.autosave()
        import time as _t
        t0 = _t.perf_counter()
        self.assertTrue(self.p.flush_now('Закрыть?'))                           # своя запись кончилась - не ждём чужую
        self.assertLess(_t.perf_counter() - t0, 3)
        other.set()
        self.assertFalse(self.p.saving)
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tРабота\t' in x), 1)
        self.settle()                                                            # поздний ответ из очереди пропущен
        self.assertEqual(sum(1 for x in self.rows() if f'{SRC}\tРабота\t' in x), 1)

    def test_check_click_is_not_folder_filter_and_close_disconnects(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Работа', 'Н2'), ('Документы', 'Н2'))
        self.open()
        self.plan()
        w = self.p.show_list('copy:HDD91')
        self.assertTrue(wait(lambda: w.data is not None, 60))
        it = w.f_items['Документы']
        it.setCheckState(0, rp.Qt.Unchecked)                                     # щелчок по галочке ...
        w.f_clicked(it, 0)                                                       # ... Qt шлёт и itemClicked
        self.assertEqual(w.model.folder_prefix, '')                              # фильтр не включился
        w.f_clicked(w.f_items['Работа'], 0)                                      # щелчок по имени - фильтр
        self.assertEqual(w.model.folder_prefix, 'Работа')
        self.settle()
        from PySide6.QtCore import SIGNAL
        n = lambda s: self.p.receivers(SIGNAL(s))                                # noqa: E731
        self.assertGreaterEqual(n('saving_changed(bool)'), 1)
        w.close()
        self.assertEqual((n('saving_changed(bool)'), n('marks_changed(int)')), (0, 0))   # закрытое окно отключено


if __name__ == '__main__':
    unittest.main()
