"""«Разбор носителя»: «Начать копирование…» и замечания владельца 18.11.2026 (розовый фон папки без копирования, нет
легенды и «Отменить последнее», «А1» вместо «Н1», окно подтверждения, запуск набора, «Посчитать хеш (N)»).

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_start_copy
Настоящие диски, таблицы и задания не используются; окна PowerShell не открываются (start_file подменён в base).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
from test_tasks_move import OK, copy_log                   # noqa: E402
from ui.razbor import texts_start                          # noqa: E402
from ui.tasks import model_load                            # noqa: E402

TASKS = 'Копирование'
G = 1024 ** 3
SPACE = {'HDD45': ('F:', 500 * G, 2000 * G, 4096), 'HDD77': ('G:', 300 * G, 1000 * G, 4096)}


class ScreenTest(PageBase):
    def test_pink_folder_without_copy_and_green_with_copy(self):
        self.mark(('Друзья', 'Н1'), ('Документы', 'Н1'))                       # в «Документах» - письмо без фото рядом
        self.open()
        self.plan()
        self.assertEqual(self.item('Документы').background(rp.C_NAME).color().name(), '#fde7ea')
        self.assertEqual(self.item('Друзья').background(rp.C_NAME).color().name(), rp.SEL_BG)
        self.assertEqual(self.item('Друзья\\Наши').background(rp.C_NAME).color().name(), rp.SEL_BG)
        self.assertIn('розовый', self.p.tree.headerItem().toolTip(rp.C_NAME))

    def test_no_legend_no_undo_button_and_a_numbers(self):
        self.mark(('Работа', 'Н2'))
        self.open()
        from PySide6.QtWidgets import QLabel, QPushButton
        self.assertFalse(hasattr(self.p, 'undo_btn') or hasattr(self.p, 'tree_legend'))
        texts = [b.text() for b in self.p.findChildren(QPushButton)]
        self.assertNotIn('Отменить последнее', texts)
        self.assertFalse(any('зелёный фон' in x.text() for x in self.p.findChildren(QLabel)))
        self.assertEqual(self.item('Работа').data(rp.C_NAME, rp.TAG_ROLE), 'А2')
        self.assertIn('«А2 Работа»', self.item('Работа').toolTip(rp.C_NAME))
        self.assertEqual(self.p.model.saved_ms.get('Работа').num, 'Н2')                   # в данных номер прежний
        self.assertEqual(self.p.copy_cell.btn.text(), 'Начать копирование…')
        self.assertNotIn('Подготовить задания…', texts)


class StartDialogTest(PageBase):
    def setUp(self):
        super().setUp()
        self.toc = sv_patch('toc_check', lambda *a, **k: TOC_OK)
        self.toc.start()

    def tearDown(self):
        self.toc.stop()
        super().tearDown()

    def made(self):
        return sorted(x.name for x in hb.TASKS.iterdir() if x.name.startswith(SRC)) if hb.TASKS.exists() else []

    def run_prepare(self, n=1):
        self.p.prepare()
        self.assertTrue(wait(lambda: len(self.dlgs) >= n and not self.p.writing, 60), self.asked)
        return self.dlgs[n - 1]

    def test_dialog_table_place_hash_and_time_without_history(self):
        self.mark(('Друзья', 'Н1'), ('Документы', 'Н1'))
        with sv_patch('disk_space', lambda dd: {d: v for d, v in SPACE.items() if d in dd}):
            self.open()
            with mock.patch.object(dialog_start.StartDialog, 'exec', lambda d: self.dlgs.append(d) or 0):
                dlg = self.run_prepare()
        self.assertTrue(dlg.windowTitle().startswith(f'Начать копирование: {SRC} → '), dlg.windowTitle())
        self.assertTrue(dlg.windowTitle().endswith('(А1)'), dlg.windowTitle())
        text, html = dlg.text.toPlainText(), dlg.text.toHtml().lower()
        for x in ('Папка', 'Копировать файлов', 'Уже есть', 'Друзья\n2\n', 'Документы — копировать нечего', 'Итого\n2\n',
                  f'Куда: HDD45\\{rz.COPY_ROOT}\\{SRC}\\…', f'Куда: HDD77\\{rz.COPY_ROOT}\\{SRC}\\…',
                  'HDD45: Поместится: нужно 0,0 ГБ, свободно 500,0 ГБ', 'HDD77: Поместится:',
                  '✔ У всех 2 файлов есть хеш — каждую копию сверим по SHA-256',
                  'Время будет видно после начала копирования',
                  'Файлы на носителе не трогаются. Окно программы можно закрыть — копирование продолжится.'):
            self.assertIn(x, text)
        self.assertIn('#fde7ea', html)                                           # розовая строка «копировать нечего»
        self.assertEqual(dlg.ok.text(), 'Подтвердить и начать копирование')
        self.assertIn('#e3f2fd', dlg.ok.styleSheet())
        self.assertEqual(self.made(), [])                                        # «Отмена» - ничего не создано
        self.assertEqual(self.started, [])

    def test_not_fits_is_red_and_no_start(self):
        self.mark(('Друзья', 'Н1'))
        space = {'HDD45': ('F:', 1000, 10 ** 12, 4096)}
        with sv_patch('disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}):
            self.open()
            dlg = self.run_prepare()
        text = dlg.text.toPlainText()
        self.assertIn('HDD45: Не помещается: нужно', text)
        self.assertIn('А1 Семейный архив не помещается', text)
        self.assertIsNone(dlg.ok)
        self.assertEqual((self.made(), self.started), ([], []))

    def test_time_from_history(self):
        self.mark(('Друзья', 'Н1'))
        self.open()
        with mock.patch.object(flow_tasks, 'tasks_info', lambda names, disks: ({}, {d: 1.0 for d in disks})), \
                mock.patch.object(dialog_start.StartDialog, 'exec', lambda d: self.dlgs.append(d) or 0):
            dlg = self.run_prepare()
        self.assertIn('Примерно 6 мин (по скорости прошлых копирований на HDD45 и HDD77)', dlg.text.toPlainText())
        P = dict(specs=[dict(name='a', targets=['HDD45'], bytes=3 * 3600, files=1, rows=[], exists=False)])
        self.assertIn('Примерно 3 ч 0 мин', texts_start.time_text(dict(P, new=P['specs'], speed={'HDD45': 1.0}), str))
        self.assertIn('Время будет видно', texts_start.time_text(dict(P, new=P['specs'], speed={}), str))

    def test_confirm_creates_new_and_starts_new_and_waiting_without_duplicates(self):
        self.mark(('Друзья', 'Н1'))
        sv.razbor_tasks(SRC, dry=False, only=['Н1'])                             # создано раньше, ждёт запуска
        before = self.made()
        self.assertEqual(len(before), 2)                                         # на 45 и на 77
        self.mark(('Поход 2010\\Монтаж', 'Н1'))
        self.open()
        dlg = self.run_prepare()
        self.assertIn('Созданы раньше и ждут запуска: 2 — запустятся вместе с новыми.', dlg.text.toPlainText())
        self.assertTrue(wait(lambda: self.started, 60), self.asked)
        made = self.made()
        self.assertEqual(len(made), 4)                                           # 2 новых, старые не продублированы
        self.assertTrue(set(before) < set(made))
        tp = self.w.page(TASKS)
        self.assertEqual([Path(x).name for x in self.started], ['очередь заданий.cmd'])
        self.assertEqual(sorted(tp.queue), made)                                 # новые и ждущие - одной очередью
        self.assertIs(self.w.stack.currentWidget(), tp)
        self.assertFalse(any('Запустить' in x or 'Создать' in x for x in self.asked), self.asked)   # без второго вопроса

    def test_all_created_dialog_starts_them(self):
        self.mark(('Друзья', 'Н1'))
        sv.razbor_tasks(SRC, dry=False, only=['Н1'])
        self.open()
        dlg = self.run_prepare()
        self.assertIn('Все задания уже созданы раньше — кнопка запустит их.', dlg.text.toPlainText())
        self.assertEqual(dlg.ok.text(), 'Подтвердить и начать копирование')
        self.assertTrue(wait(lambda: self.started, 60), self.asked)
        self.assertEqual(len(self.made()), 2)
        self.assertEqual(sorted(self.w.page(TASKS).queue), self.made())

    def test_already_running(self):
        self.mark(('Друзья', 'Н1'))
        sv.razbor_tasks(SRC, dry=False, only=['Н1'])
        self.open()
        with mock.patch.object(flow_tasks, 'tasks_info', lambda names, disks: ({n: 'идёт' for n in names}, {})):
            dlg = self.run_prepare()
        self.assertIn('Уже копируется', dlg.text.toPlainText())
        self.assertEqual(dlg.ok.text(), 'Открыть «3. Копирование»')
        self.assertIs(self.w.stack.currentWidget(), self.w.page(TASKS))
        self.assertEqual(self.started, [])

    def test_tasks_info_speed_from_finished_copies(self):
        root = self.tmp / 'задания'
        mb = 1024 ** 2
        for name, target, ser in (('готово 45', 'HDD45', 'S45'), ('готово 77', 'HDD77', 'S77')):
            t = root / name
            t.mkdir(parents=True)
            (t / 'тома.tsv').write_text(f'HDD60\tS60\n{target}\t{ser}\n', encoding='utf-8')
            (t / 'список.tsv').write_text(''.join(f'{target}\tP\\{i}.mp4\t{100 * mb}\tф\t\n' for i in range(2)),
                                         encoding='utf-8')
            copy_log(t, '2026-11-15 10-00-00', [(f'10:0{2 * i + 1}:40', target, OK, str(100 * mb), 'h',
                                                 f'D:\\P\\{i}.mp4', 'L:\\x') for i in range(2)])
        with sv_patch('running_scripts', return_value=[]), \
                mock.patch.object(model_load, 'serial_names', return_value={'S45': 'HDD45', 'S77': 'HDD77'}):
            states, speed = model_load.tasks_info(['готово 45'], ['HDD45', 'HDD91'], root)
        self.assertEqual(states, {'готово 45': 'готово'})
        self.assertAlmostEqual(speed['HDD45'], 200 * mb / 220)                   # 200 МБ за 3 мин 40 с
        self.assertIsNone(speed['HDD91'])                                        # истории нет


class NohashButtonTest(PageBase):
    def test_count_hash_button_and_start_disabled(self):
        self.open()
        self.p.apply(['Поход 2010'], N1)
        self.settle()
        self.assertTrue(wait(lambda: self.p.nohash_result() is not None, 60))
        c = self.p.copy_cell
        self.assertIn('✖ Из 4 файлов, которых нет на Архивных дисках А1 (HDD45 и HDD77), у 1 нет хеша', c.nohash.text())
        self.assertTrue(c.scan_btn.isVisibleTo(c))
        self.assertEqual(c.scan_btn.text(), 'Посчитать хеш (1)')
        self.assertFalse(c.btn.isEnabled())
        self.assertIn('Посчитать хеш', c.btn.toolTip())
        lay = [c.layout().itemAt(i) for i in range(c.layout().count())]
        box = next(x.layout() for x in lay if x.layout() is not None and x.layout().indexOf(c.btn) >= 0)
        self.assertLess(box.indexOf(c.scan_btn), box.indexOf(c.btn))          # «Посчитать хеш» - слева


if __name__ == '__main__':
    unittest.main()
