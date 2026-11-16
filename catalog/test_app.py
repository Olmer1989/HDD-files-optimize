"""Дымовой тест окна «Архив дисков» без экрана (Qt offscreen) на временных данных.

Запуск из корня проекта:  py -m unittest catalog\\test_app.py
"""
import json
import os
import sqlite3
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QThreadPool, Qt                 # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import app                                                 # noqa: E402
import commands_page as cpg                                # noqa: E402
import disk_ui                                             # noqa: E402
import hashbase as hb                                      # noqa: E402
from test_hashbase import Base                             # noqa: E402

QAPP = QApplication.instance() or QApplication([])


def wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        QAPP.processEvents()
        QThreadPool.globalInstance().waitForDone(50)
        QAPP.processEvents()
        if cond():
            return True
    return False


class WindowTest(Base):
    def setUp(self):
        super().setUp()
        t = hb.TASKS / 'Задание 1'
        t.mkdir(parents=True)
        (t / 'список.tsv').write_text('HDD77\tA\\2.jpg\t200\tф\t\n', encoding='utf-8')
        (t / 'Запустить.cmd').write_text('rem', encoding='utf-8')
        self.errors = []
        self.w = app.Window()
        self.w.show_error = self.errors.append
        self.assertTrue(wait(lambda: not self.w.updating), 'первая сборка базы в фоне не закончилась')

    def tearDown(self):
        self.w.timer.stop()
        QThreadPool.globalInstance().waitForDone(10000)
        self.w.close()
        super().tearDown()

    def test_pages(self):
        ov = self.w.pages[0][1]
        ov.refresh()
        self.assertTrue(wait(lambda: ov.ov is not None and 'Считаю' not in ov.text.toPlainText()))
        self.assertNotIn('База собрана', ov.text.toPlainText())                # второй круг: она - в подвале окна
        self.assertNotIn('Задание 1', ov.text.toPlainText())                   # «Ждут запуска» убрано из «Обзора»
        names = [self.w.nav.item(i).text() for i in range(self.w.nav.count())]
        self.assertIn('Задания на копирование', names)                          # третий круг «Обзора»
        self.assertNotIn('Задания', names)
        self.w.open_page('Задания на копирование')
        tasks = self.w.page('Задания на копирование')
        self.assertTrue(wait(lambda: tasks.t.rowCount() == 1))
        self.assertTrue(self.w.footer.text().startswith('База собрана '), self.w.footer.text())   # подвал окна
        self.assertIn(': носителей 4, файлов ', self.w.footer.text())
        self.assertEqual(tasks.t.item(0, 2).text(), 'Ждёт запуска')
        self.w.open_page('Диски и папки')
        dp = self.w.page('Диски и папки')
        self.assertTrue(wait(lambda: dp.t.rowCount() == 4))
        row = [r['disk'] for r in dp.rows].index('HDD90')
        dp.t.selectRow(row)
        N = app.T_NAME
        root = dp.tree.topLevelItem(0)
        self.assertTrue(wait(lambda: root.childCount() == 2))                   # A и B, лениво
        names = sorted(root.child(i).text(N) for i in range(2))
        self.assertEqual(names, ['A', 'B'])
        a = next(root.child(i) for i in range(2) if root.child(i).text(N) == 'A')
        a.setExpanded(True)
        self.assertTrue(wait(lambda: a.childCount() == 1 and a.child(0).text(N) == 'sub'))
        dp.tree.setCurrentItem(a)
        import types
        import directions_page
        real = directions_page.chosen
        directions_page.chosen = lambda: [types.SimpleNamespace(disks=('HDD45', 'HDD77'))]
        try:
            dp.presence()
            self.assertTrue(wait(lambda: 'HDD45' in dp.info.text() and 'HDD77' in dp.info.text()), dp.info.text())
        finally:
            directions_page.chosen = real
        self.assertIn('HDD90\\A', dp.info.text())
        dp.search.setText('sub')
        dp.find()
        self.assertTrue(wait(lambda: dp.tree.topLevelItemCount() == 1 and 'A\\sub' in dp.tree.topLevelItem(0).text(N)))
        self.assertEqual(self.errors, [])

    def test_new_journal_is_applied_by_timer(self):
        self.w.check_sources()
        self.assertTrue(wait(lambda: self.w.sig is not None))
        self.task('T', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-00-00.tsv',
                  ('время', 'цель', 'результат', 'размер', 'SHA-256 прочитанного', 'источник', 'куда'),
                  [('1', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', '0' * 63 + '2', 'K:\\A\\2.jpg', 'S:\\П\\2.jpg')])
        self.w.check_sources()
        # строку читаем только на чтение: connect() сам применил бы журнал, и окну было бы нечего применять
        def applied():
            if self.w.updating or not hb.DB.exists():
                return False
            c = sqlite3.connect(f'file:{hb.DB.as_posix()}?mode=ro', uri=True)
            try:
                return c.execute('select 1 from files where disk=? and path=?', ('HDD77', 'П\\2.jpg')).fetchone() is not None
            finally:
                c.close()
        self.assertTrue(wait(applied))
        self.assertIn('Применены новые модули', self.w.statusBar().currentMessage())

    def test_footer_text(self):
        self.assertEqual(app.footer_text(('15.11.2026 22:52', 57, 11_300_000)),
                         'База собрана 15.11 22:52: носителей 57, файлов 11,3 млн')
        self.assertEqual(app.footer_text(('15.11.2026 22:52', 3, 45_600)), 'База собрана 15.11 22:52: носителей 3, файлов 45,6 тыс.')
        self.assertEqual(app.footer_text(('15.11.2026 22:52', 1, 950)), 'База собрана 15.11 22:52: носителей 1, файлов 950')
        self.assertEqual(app.footer_text(None), 'База ещё не собрана')
        info = app.sv.base_info()
        self.assertEqual(self.w.footer.text(), app.footer_text(info))
        self.assertEqual(app.built_short('2026-11-15 22:52:10'), '15.11 22:52')        # ISO - на всякий случай
        self.assertEqual(app.built_short('5.1.2026 9:05'), '05.01 09:05')
        w2 = app.Window()                                                         # подвал - сразу при запуске
        try:
            self.assertEqual(w2.footer.text(), app.footer_text(info))
        finally:
            w2.timer.stop()
            self.assertTrue(wait(lambda: not w2.updating))
            w2.close()


HIDDEN = {'recovery-plan', 'recovery-staging', 'family-plan', 'family-check', 'mvlist', 'manual', 'fix-manual',
          'mklist', 'decide', 'exclude', 'rescan-plan'}    # последние 4 заменил «Разбор носителя» (логика v3, этап 2)


def hidden_form(cp, name):
    """Форма скрытой в окне команды (manual, fix-manual - теперь на странице «Я сделал в Проводнике»): то же
    построение формы, что у видимых, - проверяем, что описание аргументов по-прежнему годится."""
    import hb_cli
    n, h, _, prs = next(c for c in hb_cli.commands() if c[0] == name)
    f = cpg.CommandForm(cp, n, h, prs)
    f.set_disks(cp.disks)
    return f


def show_hidden(cp, name):
    """Скрытая в окне команда (mklist, decide - их заменила страница «Разбор носителя»; в командной строке есть) -
    та же форма и тот же запуск страницы «Команды»: механизм форм, предпросмотра и создания задания проверяется
    по-прежнему."""
    if name not in cp.forms:
        cp.forms[name] = hidden_form(cp, name)
        cp.stack.addWidget(cp.forms[name])
    cp.current = name
    cp.stack.setCurrentWidget(cp.forms[name])
    cp.form_changed()
    return cp.forms[name]


def put(f, **values):
    """Заполнить поля формы, как это сделал бы владелец."""
    for k, v in values.items():
        fld = f.fields[k]
        if fld.kind in ('disk', 'choice') or k in cpg.SUGGEST:
            fld.combo.setCurrentText(v)
        elif fld.kind == 'int':
            fld.widget.setValue(v)
        elif fld.kind == 'check':
            fld.check.setChecked(v)
        elif fld.kind in ('folders', 'lines'):
            fld.edit.setPlainText(v)
        else:
            fld.line.setText(v)


class StepsTest(WindowTest):
    """Этап 11: шаги работы вверху «Обзора», «Разбора носителя» и «Заданий на копирование»; щелчок - своя вкладка."""

    def test_steps_on_three_pages(self):
        from PySide6.QtTest import QTest
        import ui_common
        names = ['Обзор', 'Разбор носителя', disk_ui.TASKS_PAGE]
        for i, name in enumerate(names):
            bar = self.w.page(name).steps
            self.assertIsInstance(bar, ui_common.StepsBar)
            self.assertEqual(bar.current, i)
            self.assertEqual([p.current for p in bar.plates], [j == i for j in range(3)])
        texts = [p.label.text() for p in self.w.page('Обзор').steps.plates]
        self.assertIn('1. Куда копируем', texts[0])
        self.assertIn('выберите диск', texts[0])
        self.assertIn('2. Что копируем', texts[1])
        self.assertIn('папки на носителе', texts[1])
        self.assertIn('3. Копирование', texts[2])
        self.assertIn('запуск заданий', texts[2])
        for name in ('Диски и папки', 'Я сделал в Проводнике', 'Команды'):        # на других вкладках шагов нет
            self.assertEqual(self.w.page(name).findChildren(ui_common.StepsBar), [])
        names_all = [n for n, _ in self.w.pages]
        self.w.resize(1400, 900)
        self.w.show()
        QAPP.processEvents()
        ov = self.w.page('Обзор')
        import directions_page
        # «2. Что копируем» - как «Дальше: выбрать папки на носителе»: без отмеченного диска не переходит
        with mock.patch.object(directions_page, 'chosen', return_value=[]):
            QTest.mouseClick(ov.steps.plates[1].label, Qt.LeftButton)
        self.assertEqual(self.w.nav.currentRow(), 0)
        self.assertTrue(self.w.statusBar().currentMessage().startswith('Сначала отметьте диск'))
        self.assertTrue(ov.steps.last_hint.startswith('Сначала отметьте диск'))
        used = []
        rz_page = self.w.page('Разбор носителя')
        with mock.patch.object(directions_page, 'chosen', return_value=['Н3']), \
                mock.patch.object(rz_page, 'use_choice', lambda: used.append(1)):
            QTest.mouseClick(ov.steps.plates[1].label, Qt.LeftButton)           # щелчок мышью по тексту плашки
        self.assertEqual(self.w.nav.currentRow(), names_all.index('Разбор носителя'))
        self.assertEqual(used, [1])                                             # выбор - в списки «Разбора»
        self.w.page(disk_ui.TASKS_PAGE).steps.open(1)                           # и с «Заданий» - так же (уже там - ничего)
        QTest.mouseClick(self.w.page('Разбор носителя').steps.plates[2], Qt.LeftButton)   # по самой плашке
        self.assertEqual(self.w.nav.currentRow(), names_all.index(disk_ui.TASKS_PAGE))
        self.w.page(disk_ui.TASKS_PAGE).steps.open(2)                            # текущий шаг - ничего
        self.assertEqual(self.w.nav.currentRow(), names_all.index(disk_ui.TASKS_PAGE))
        self.w.page(disk_ui.TASKS_PAGE).steps.open(0)
        self.assertEqual(self.w.nav.currentRow(), 0)
        QThreadPool.globalInstance().waitForDone(10000)


class CommandsTest(WindowTest):
    """Раздел «Команды»: формы из argparse, запуск hashbase.py отдельным процессом на временных данных."""

    def setUp(self):
        super().setUp()
        self.cp = self.w.page('Команды')
        self.asked = []

        def ask(*a, **k):
            self.asked.append(a[2])
            return cpg.QMessageBox.Yes
        self.patches = [mock.patch.object(cpg.QMessageBox, 'question', ask),
                        mock.patch.object(cpg.QMessageBox, 'information', lambda *a, **k: self.asked.append(a[2]))]
        for x in self.patches:
            x.start()
        self.w.open_page('Команды')
        self.assertTrue(wait(lambda: self.cp.disks))

    def tearDown(self):
        for x in self.patches:
            x.stop()
        if self.cp.run:
            self.cp.run.stop()
            wait(lambda: self.cp.run is None)
        super().tearDown()

    test_pages = test_new_journal_is_applied_by_timer = None      # уже проверены в WindowTest

    def run_cmd(self, name, timeout=90, write=False):
        (self.cp.write if write else self.cp.execute)()
        self.assertIsNotNone(self.cp.run, f'{name}: не запустилась; {self.asked}')
        self.assertTrue(wait(lambda: self.cp.run is None, timeout), f'{name}: не закончилась')
        return '\n'.join(self.cp.lines)

    def test_forms_for_all_visible_commands(self):
        names = [n for n, _, _ in self.cp.cmds]
        self.assertFalse(HIDDEN & set(names))
        self.assertEqual(sum(1 for i in range(self.cp.list.count()) if self.cp.list.item(i).data(Qt.UserRole)), len(names))
        for n in names:
            f = self.cp.select(n)
            self.assertFalse(f.unsupported, n)
            self.assertNotIn('yes', f.fields, n)
            args, err = f.argv()
            self.assertTrue(args or err, n)
        f = hidden_form(self.cp, 'manual')
        self.assertEqual(f.fields['date'].text(), time.strftime('%d.%m.%Y'))
        self.assertEqual(f.fields['action'].kind, 'choice')
        self.assertEqual(show_hidden(self.cp, 'mklist').fields['to'].text(), ['HDD45', 'HDD77'])
        combo = self.cp.select('where').fields['disk'].combo
        self.assertIn('HDD90', [combo.itemData(i) for i in range(combo.count())])
        dlg = cpg.FolderDialog(self.w, 'HDD90')                             # «Выбрать…»: дерево папок по базе
        root = dlg.tree.topLevelItem(0)
        self.assertTrue(wait(lambda: root.childCount() == 2))
        a = next(root.child(i) for i in range(2) if root.child(i).text(0) == 'A')
        dlg.tree.setCurrentItem(a)
        dlg.accept()
        self.assertEqual(dlg.chosen, 'A')

    def test_required_fields_and_argv(self):
        show_hidden(self.cp, 'decide')
        self.cp.execute()
        self.assertIsNone(self.cp.run)
        self.assertIn('Заполните', self.asked[-1])
        f = show_hidden(self.cp, 'mklist')
        put(f, disk='HDD90', name='Моё задание', folder='A\nB\\x', dry=True)
        f.fields['to'].boxes['HDD77'].setCheckState(Qt.Unchecked)
        args, err = f.argv()
        self.assertIsNone(err)
        self.assertEqual(args, ['mklist', 'HDD90', '--to', 'HDD45', '--name=Моё задание', '--folder=A', '--folder=B\\x',
                                '--dry'])
        f = hidden_form(self.cp, 'manual')                                  # пустой disk2 перед заполненным path2
        put(f, disk='HDD90', path='A', path2='B', action='удалено')
        args, err = f.argv()
        self.assertIn('Куда: диск', err)
        f = self.cp.select('folders')                                       # значение по умолчанию не передаётся
        put(f, disk='HDD90', depth=1)
        self.assertEqual(f.argv()[0], ['folders', 'HDD90'])

    def test_read_command_in_subprocess(self):
        f = self.cp.select('folders')
        put(f, disk='HDD90', depth=2)
        text = self.run_cmd('folders')
        self.assertIn('Готово', self.cp.state.text(), text)
        self.assertIn('sub', text)                                          # A\sub - на глубине 2
        saved = hb.ANSWERS / cpg.LAST_OUTPUT
        self.assertTrue(saved.exists())
        self.assertIn(str(saved), self.cp.links)                            # путь к файлу - ссылка
        f = show_hidden(self.cp, 'decide')                                        # код выхода 1 - заметно
        put(f, disk='HDD90', path='Нет такой папки', verdict='не нужно')
        self.run_cmd('decide')
        self.assertIn('код выхода 1', self.cp.state.text())
        self.assertIsNone(self.cp.preview)
        self.assertFalse(self.cp.btn_write.isEnabled())

    def test_decide_preview_then_write(self):
        f = show_hidden(self.cp, 'decide')
        put(f, disk='HDD90', path='B', verdict='не нужно')
        rows = lambda: hb.DECISIONS.read_text(encoding='utf-8-sig') if hb.DECISIONS.exists() else ''   # noqa: E731
        text = self.run_cmd('decide')
        self.assertIn('предпросмотр', text)
        self.assertNotIn('не нужно', rows())
        self.assertTrue(self.cp.btn_write.isEnabled())
        put(f, path='B ')                                                   # правка формы гасит «Записать»
        self.assertFalse(self.cp.btn_write.isEnabled())
        self.run_cmd('decide')                       # этап 16: пробел - часть имени, папки «B » в базе нет - отказ
        self.assertIn('код выхода 1', self.cp.state.text())
        self.assertFalse(self.cp.btn_write.isEnabled())
        put(f, path='B')
        self.run_cmd('decide')
        text = self.run_cmd('decide --yes', write=True)
        self.assertIn('Записано', text)
        self.assertIn('B\tне нужно', rows())
        self.assertTrue(any('Записать в таблицу' in x for x in self.asked))
        self.assertFalse(self.cp.btn_write.isEnabled())                    # второй раз - только после нового предпросмотра

    def test_mklist_creates_task_and_offers_tasks_page(self):
        f = show_hidden(self.cp, 'mklist')
        put(f, disk='HDD90', name='Новое задание')
        self.run_cmd('mklist')                                          # «Посчитать» (--dry), затем «Создать задание»
        self.assertFalse((hb.TASKS / 'Новое задание').exists())
        self.run_cmd('mklist create', write=True)
        self.assertTrue((hb.TASKS / 'Новое задание').is_dir(), '\n'.join(self.cp.lines))
        self.assertIn('Создано задание', self.asked[-1])
        self.assertIn('Задания на копирование', self.asked[-1])
        self.assertIs(self.w.stack.currentWidget(), self.w.page('Задания на копирование'))
        tasks = self.w.page('Задания на копирование')
        self.assertTrue(wait(lambda: any(r['task'] == 'Новое задание' for r in tasks.rows)))


ROWS = [{'disk': 'HDD90', 'label': 'ACASIS EC-7352 - 750 ГБ', 'letter': ''},
        {'disk': 'HDD91', 'label': 'ADATA SX8200PNP - 2 ТБ - Исходники', 'letter': 'E:'},
        {'disk': 'HDD45', 'label': 'ST16000NM000J-2TW103 - 16 ТБ - Бэкап', 'letter': ''},
        {'disk': 'HDD77', 'label': '', 'letter': 'S:'}]


class CommandsUiTest(CommandsTest):
    """Понятный раздел «Команды» (15.11.2026): группы, тексты GUI_*, выбор носителя, уровни, пары, режимы mklist."""

    test_forms_for_all_visible_commands = test_required_fields_and_argv = test_read_command_in_subprocess = None
    test_decide_preview_then_write = test_mklist_creates_task_and_offers_tasks_page = None

    def test_groups_order_and_titles(self):
        heads, cmds = [], []
        for i in range(self.cp.list.count()):
            it = self.cp.list.item(i)
            if it.data(Qt.UserRole):
                cmds.append(it.data(Qt.UserRole))
                self.assertFalse(it.text().strip().startswith('py '), it.text())
            else:
                heads.append(it.text())
                self.assertFalse(it.flags() & Qt.ItemIsSelectable)
        known = [g for g in cpg.GROUPS if g in heads]
        self.assertEqual(heads[:len(known)], known)
        self.assertEqual(known, ['Вопросы о диске', 'Обслуживание'])    # «Подготовить задание» и «Записать» - в разборе
        want = ['missing', 'only', 'where', 'cmp', 'candel', 'folders', 'find', 'stats', 'build', 'tasks', 'rebuild']
        self.assertEqual([c for c in cmds if c in want], want)
        self.assertNotIn('mvlist', cmds)                                    # отдельного пункта нет
        self.assertFalse({'mklist', 'decide', 'exclude', 'rescan-plan'} & set(cmds))
        f = self.cp.select('candel')
        self.assertEqual(f.meta['title'], 'Можно ли удалить папку с этого диска?')
        self.assertEqual(f.fields['disk'].label, 'Диск, с которого хотите удалить')
        self.assertEqual(f.fields['folder'].label, 'Папка, которую хотите удалить')
        self.assertIn('НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', f.meta['hint'])
        self.assertEqual(hidden_form(self.cp, 'manual').fields['disk2'].label, 'Куда: диск')

    def test_disk_choice_and_depth_everywhere(self):
        self.cp.got_disks(ROWS)
        for n, _, _ in self.cp.cmds:
            f = self.cp.select(n)
            for d, fld in f.fields.items():
                if fld.kind == 'disk':
                    self.assertIsInstance(fld.combo, cpg.DiskCombo, f'{n} {d}')
                if d == 'depth':
                    self.assertIsInstance(fld.widget, cpg.DepthCombo, n)
                    self.assertEqual(fld.widget.itemData(fld.widget.count() - 1), 0)      # «все уровни»
        combo = self.cp.select('where').fields['disk'].combo
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(combo.itemData(0), 'HDD77')                          # подключённые сверху, по номеру
        self.assertEqual(combo.itemData(1), 'HDD91')
        self.assertEqual(texts[1], '● HDD91 — E: — Исходники')
        self.assertEqual(texts[2], '')                                        # разделитель
        self.assertEqual(texts[3], 'HDD45 — Бэкап — не подключён')            # модели и объёма нет (16.11)
        self.assertIn('HDD90 — Накопитель — не подключён', texts)             # метки тома нет - «Накопитель» и номер
        self.assertTrue(combo.itemData(1, Qt.FontRole).bold())
        self.assertEqual(combo.currentIndex(), -1)
        self.assertEqual(combo.placeholderText(), cpg.CHOOSE_DISK)
        find = self.cp.select('find').fields['disk'].combo
        self.assertEqual((find.itemText(0), find.itemData(0)), (cpg.ALL_DISKS, ''))
        f = self.cp.select('folders')
        put(f, disk='HDD90', depth=0)
        self.assertEqual(f.argv()[0], ['folders', 'HDD90', '--depth=0'])
        put(f, depth=1)
        self.assertEqual(f.argv()[0], ['folders', 'HDD90'])

    def test_to_list_short_by_default(self):
        self.cp.got_disks(ROWS)
        to = show_hidden(self.cp, 'mklist').fields['to']
        self.assertEqual(to.text(), ['HDD45', 'HDD77'])
        shown = [d for d, it in to.boxes.items() if not it.isHidden()]
        self.assertEqual(shown, ['HDD45', 'HDD77', 'HDD91'])                 # основные, затем подключённые
        self.assertTrue(to.more.isVisibleTo(to.widget))
        to.toggle_all()
        self.assertEqual(sorted(d for d, it in to.boxes.items() if not it.isHidden()), ['HDD45', 'HDD77', 'HDD90', 'HDD91'])

    def test_disk_folder_pairs(self):
        self.cp.got_disks(ROWS)
        f = self.cp.select('cmp')
        self.assertIs(f.row_of['disk_a'], f.row_of['folder_a'])            # диск и папка - одной строкой
        self.assertTrue(f.fields['folder_a'].pick_disk)
        m = hidden_form(self.cp, 'manual')
        self.assertIs(m.row_of['disk2'], m.row_of['path2'])
        self.assertEqual(m.fields['disk2'].combo.itemText(0), '— не указан —')
        mk = show_hidden(self.cp, 'mklist')                                       # у диска две папки - выбор только папки
        self.assertFalse(mk.fields['source_folder'].pick_disk)
        dlg = cpg.FolderDialog(self.w, 'HDD90', rows=ROWS)                  # «Выбрать…»: носители, затем их папки
        tops = [dlg.tree.topLevelItem(i).data(2, Qt.UserRole) for i in range(dlg.tree.topLevelItemCount())]
        self.assertEqual(tops, ['HDD77', 'HDD91', 'HDD45', 'HDD90'])
        top = dlg.tree.topLevelItem(3)
        self.assertTrue(wait(lambda: top.childCount() == 2 and top.child(0).text(0) != '…'))
        a = next(top.child(i) for i in range(2) if top.child(i).text(0) == 'A')
        dlg.tree.setCurrentItem(a)
        dlg.accept()
        self.assertEqual((dlg.chosen_disk, dlg.chosen), ('HDD90', 'A'))
        f.fields['disk_a'].combo.setCurrentText(dlg.chosen_disk)
        self.assertEqual(f.fields['disk_a'].text(), 'HDD90')

    def test_mklist_modes_build_arguments(self):
        hb.ensure_tables()
        hb.DECISIONS.write_text(hb.DECISION_HEAD + '\nHDD90\tB\tраздел: Фильмы\tпроба\n', encoding='utf-8-sig')
        f = show_hidden(self.cp, 'mklist')
        modes = [f.mode_box.itemText(i) for i in range(f.mode_box.count())]
        self.assertEqual(len(modes), 4)
        self.assertEqual(f.fields['name'].text(), '')
        put(f, disk='HDD90')
        self.assertTrue(f.fields['name'].text().startswith('HDD90 → HDD45 и HDD77, '))   # имя - само
        self.assertEqual(f.argv()[0][:2], ['mklist', 'HDD90'])
        self.assertNotIn('--whole', f.argv()[0])
        f.mode_box.setCurrentIndex(1)                                       # папки целиком
        self.assertEqual(f.fields['to'].text(), [])
        self.assertIn('Заполните', f.argv()[1])
        put(f, folder='A')
        self.assertIn('Отметьте', f.argv()[1])
        f.fields['to'].boxes['HDD45'].setCheckState(Qt.Checked)
        args = f.argv()[0]
        self.assertIn('--whole', args)
        self.assertIn('--folder=A', args)
        self.assertEqual(args[args.index('--to') + 1], 'HDD45')
        self.assertTrue(f.fields['name'].text().startswith('HDD90 целиком (A) → HDD45'))
        f.mode_box.setCurrentIndex(2)                                       # на диск раздела
        items = [f.fields['section'].combo.itemText(i) for i in range(f.fields['section'].combo.count())]
        self.assertEqual(items, ['раздел: Фильмы'])
        f.fields['section'].combo.setCurrentText('раздел: Фильмы')
        f.fields['to'].boxes['HDD77'].setCheckState(Qt.Checked)
        args = f.argv()[0]
        self.assertIn('--section=раздел: Фильмы', args)
        self.assertNotIn('--whole', args)
        self.assertNotIn(':', f.fields['name'].text().split(',')[0])        # в имени папки нет «:»
        f.mode_box.setCurrentIndex(3)                                       # из копии на другом диске
        put(f, source_folder='A', as_name='HDD17')
        args = f.argv()[0]
        self.assertIn('--source-folder=A', args)
        self.assertIn('--as=HDD17', args)
        self.assertNotIn('--folder=A', args)                                # поле другого режима не идёт
        self.assertNotIn('--section=раздел: Фильмы', args)
        put(f, name='Своё имя')                                             # своё имя владельца не затирается
        put(f, as_name='HDD18')
        self.assertEqual(f.fields['name'].text(), 'Своё имя')

    def test_count_then_create_with_move_mark(self):
        f = show_hidden(self.cp, 'mklist')
        self.assertEqual(self.cp.btn_run.text(), 'Посчитать')
        self.assertEqual(self.cp.btn_write.text(), 'Создать задание')
        self.assertFalse(f.row_of['dry'].isVisibleTo(f))                     # вместо галочки - кнопка
        put(f, disk='HDD90', name='С пометкой', move_after=True)
        self.assertNotIn('move_after', ' '.join(f.argv()[0]))
        self.run_cmd('mklist --dry')
        self.assertIn('--dry', self.cp.lines[0])
        self.assertFalse((hb.TASKS / 'С пометкой').exists())
        self.assertTrue(self.cp.btn_write.isEnabled())
        self.run_cmd('mklist', write=True)
        mark = hb.TASKS / 'С пометкой' / 'после копирования.json'
        self.assertTrue(mark.exists(), '\n'.join(self.cp.lines))
        data = json.loads(mark.read_text(encoding='utf-8'))
        self.assertEqual((data['разложить_на_источнике'], data['диск'], data['папки']), (True, 'HDD90', None))


if __name__ == '__main__':
    unittest.main()
