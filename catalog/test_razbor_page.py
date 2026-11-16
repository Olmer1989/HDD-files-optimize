"""Страница «Разбор носителя» (логика v3, этапы 2, 6, 8; 15-16.11.2026) без экрана (Qt offscreen) на временных данных.

Запуск из корня проекта:  py -m unittest catalog.test_razbor_page
Настоящие диски, таблицы и задания не используются.
"""
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QPoint, QPointF, QThreadPool    # noqa: E402
from PySide6.QtWidgets import QDialog                      # noqa: E402

import app                                                 # noqa: E402
import hashbase as hb                                      # noqa: E402
import razbor_page as rp                                   # noqa: E402
import service as sv                                       # noqa: E402
from hb_core import razbor as rz                           # noqa: E402
from test_app import put, wait                             # noqa: E402
from test_hashbase import make_disk, S                     # noqa: E402
from test_logic_v3 import SRC, FILES, H, V3Base            # noqa: E402

N1 = 'направление: Н1 Семейный архив'
N2 = 'направление: Н2 Работа'
N3 = 'направление: Н3 Без диска'
MOVED = 'ПЕРЕНЕСЕНО → 45 и 77'
H50 = f'{50:064x}'


def reference_route(model, f, ms):
    """Независимо от окна и ядра: самая глубокая отметка над папкой (по частям пути, без регистра); внутри служебной
    папки - только явные отметки исходного пути, сама служебная папка и наследование режима - нет."""
    parts = f.split('\\') if f else []
    if parts and parts[0] in model.roots:
        if len(parts) == 1:
            return None
        parts = parts[1:]
        cands = ['\\'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    else:
        cands = [''] + ['\\'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    best = None
    for c in cands:
        m = ms.by_key.get(c.lower())
        if m is not None:
            best = m
    return best


class PageBase(V3Base):
    def setUp(self):
        super().setUp()
        self.asked, self.dialogs = [], []
        self.answer = rp.QMessageBox.Yes

        def ask(*a, **k):
            self.asked.append(a[2])
            return self.answer

        self.dlgs = []

        def exec_(dlg):
            self.dlgs.append(dlg)
            self.dialogs.append(dlg.text.toPlainText())
            return QDialog.Accepted
        self.patches = [mock.patch.object(rp.QMessageBox, 'question', ask),
                        mock.patch.object(rp.QMessageBox, 'information', lambda *a, **k: self.asked.append(a[2])),
                        mock.patch.object(rp.QMessageBox, 'warning', lambda *a, **k: self.asked.append(a[2])),
                        mock.patch.object(rp.TextDialog, 'exec', exec_)]
        for x in self.patches:
            x.start()
        self.w = app.Window()
        self.w.show_error = self.asked.append
        self.assertTrue(wait(lambda: not self.w.updating), 'первая сборка базы в фоне не закончилась')
        self.p = self.w.page('Разбор носителя')
        self.w.open_page('Разбор носителя')
        self.assertTrue(wait(lambda: self.p.disk_rows))

    def tearDown(self):
        if self.p.model is not None:
            self.p.model.drafts.clear()
        self.w.timer.stop()
        QThreadPool.globalInstance().waitForDone(20000)
        self.w.close()
        for x in self.patches:
            x.stop()
        super().tearDown()

    # --- помощники ---
    def open(self, disk=SRC):
        self.p.choose_disk(disk)
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.model.disk == disk), 'дерево не прочиталось')
        self.settle()

    def settle(self):
        self.assertTrue(wait(lambda: self.p.plan_rev == self.p.rev and not self.p.sum_busy and not self.p.have_busy
                             and not self.p.writing and self.p.model.have is not None, 60), self.p.sum_state.text())

    def item(self, path):
        parts = path.split('\\')
        for i in range(1, len(parts)):
            self.p.items['\\'.join(parts[:i])].setExpanded(True)
        return self.p.items[path]

    def to(self, path):
        """Текст «куда» папки (колонки «Куда» с этапа 6 нет - тот же текст даёт Model.cell, цвет - Model.look)."""
        if path:
            self.item(path)
        return self.p.model.cell(path)['text']

    def plan(self):
        self.settle()
        return self.p.plan[0]


class TreeTest(PageBase):
    def test_tree_inheritance_exceptions_and_display(self):
        """Этап 8: колонка галочек слева; своя отметка D - активная галочка и зелёный фон; подпапки - серая
        неактивная галочка, бледный текст, тот же фон; служебная папка и весь носитель - без галочки."""
        self.open()
        root = self.p.items['']
        names = {root.child(i).text(rp.C_NAME) for i in range(root.childCount())}
        self.assertTrue({'Поход 2010', 'Работа', 'Друзья', 'Документы', 'Смешанная', MOVED} <= names, names)
        self.assertEqual(self.p.dest, 'Н1')                       # «Обзор» пуст, режима нет - первое с диском
        self.assertTrue(self.p.mode_only.isChecked())
        self.assertIn('режим не выбран', self.to(''))
        self.assertEqual(self.item('Поход 2010').text(rp.C_FILES), '7')
        self.assertEqual(self.item('Поход 2010').text(rp.C_PHOTO), '2')
        self.assertEqual(root.checkState(rp.C_CHECK), rp.Qt.Unchecked)            # у носителя - «выбрать все»
        self.assertIsNone(self.item(MOVED).data(rp.C_CHECK, rp.Qt.CheckStateRole))
        it = self.item('Поход 2010')
        self.assertEqual(it.checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.assertTrue(it.flags() & rp.Qt.ItemIsUserCheckable)
        it.setCheckState(rp.C_CHECK, rp.Qt.Checked)                              # как щелчок владельца
        self.assertEqual(self.p.model.drafts['поход 2010']['verdict'], N1)
        it = self.item('Поход 2010')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.SEL_BG)
        self.assertTrue(it.text(rp.C_NAME).startswith('• '))                      # не сохранено
        self.assertTrue(it.font(rp.C_NAME).italic())
        ch = self.item('Поход 2010\\Фото')
        self.assertEqual(ch.checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertTrue(ch.data(rp.C_CHECK, rp.GRAY_ROLE))                        # серая, неактивная
        self.assertFalse(ch.flags() & rp.Qt.ItemIsUserCheckable)
        self.assertEqual(ch.foreground(rp.C_NAME).color().name(), rp.PALE)
        self.assertEqual(ch.background(rp.C_NAME).color().name(), rp.SEL_BG)     # один зелёный фон
        self.assertIn('вместе с родительской', ch.toolTip(rp.C_NAME))
        self.assertEqual(self.p.toggle(['Поход 2010\\Фото'], False), 0)          # серую не снять
        # снять галочку = снять свою отметку: черновик пуст, папка снова не выбрана
        self.item('Поход 2010').setCheckState(rp.C_CHECK, rp.Qt.Unchecked)
        self.assertEqual(self.p.model.drafts, {})
        self.assertEqual(self.item('Поход 2010\\Фото').checkState(rp.C_CHECK), rp.Qt.Unchecked)
        # подпапка, отмеченная отдельно, внутри выбранной: снятие её галочки - исключение («не копировать»)
        self.p.toggle(['Поход 2010\\Монтаж'], True)
        self.p.toggle(['Поход 2010'], True)
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], N1)   # своя осталась
        self.p.toggle(['Поход 2010\\Монтаж'], False)
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], rp.SKIP)
        self.assertEqual(self.item('Поход 2010\\Монтаж').checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.undo()
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], N1)
        self.assertFalse(self.p.model.markable(MOVED))
        self.assertEqual(self.to(MOVED + '\\Старое'), 'уже перенесено')
        self.assertEqual(self.asked, [])

    def test_route_contract_against_reference(self):
        """Маршрут окна = независимый расчёт (самая глубокая отметка, последняя строка, снятие, служебная папка) - для
        КАЖДОЙ папки и с указанием решающей отметки (а не только суммы)."""
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('ДРУЗЬЯ', 'не копировать'), ('Друзья\\Наши', 'Н3'),
                  (MOVED + '\\Старое', 'Н2'), ('Смешанная', 'Н3'))
        self.mark(('Смешанная', 'как у родителя'), ('Друзья\\Наши', 'Н2'))
        self.open()
        m = self.p.model
        self.p.apply(['Поход 2010\\Монтаж'], rp.SKIP)
        self.p.apply(['Работа'], rp.INHERIT)                   # снятие сохранённой отметки - черновиком
        for ms, route in ((m.full_ms, m.route), (m.saved_ms, m.route_saved)):
            for f in m.folders:
                ref = reference_route(m, f, ms)
                r = route[f]
                self.assertEqual(r.mark.row if r.mark else None, ref.row if ref else None, f)
                if ref is not None:
                    exp = rz._mark_route(ref, m.dirs)
                    self.assertEqual((r.state, r.num), (exp.state, exp.num), f)
        self.assertEqual(m.route['Друзья\\Наши'].num, 'Н2')          # последняя строка пути
        self.assertEqual(m.route['Смешанная'].state, m.route[''].state)   # «как у родителя» сняла отметку
        self.assertEqual(m.cell('Работа')['dirty'], 'drop')
        self.assertTrue(m.cell('Работа')['text'].startswith('• снять свою отметку → Семейный архив'))
        self.assertEqual(m.cell(MOVED + '\\Старое')['kind'], 'own')
        # итог ядра с тем же черновиком: файлы «не копировать» - те, что окно показывает «не копировать»
        P = self.plan()
        skip_files = sum(1 for p, _s, _h in FILES if m.route[hb.parent_of(p)].state == rp.R_SKIP)
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], skip_files)

    def test_same_original_path_inside_and_outside_moved_folder(self):
        make_disk(self.scans, 'HDD61', 'AAAA0061', [('Поход\\a.jpg', 10, S[7]), (MOVED + '\\Поход\\b.jpg', 20, S[8])])
        self.quiet(hb.connect)
        m = rp.Model(sv.razbor_tree('HDD61'))
        self.assertEqual(m.set_mark([MOVED + '\\Поход'], N2), 1)
        self.assertEqual(list(m.drafts), ['поход'])                     # одна отметка по исходному пути
        self.assertEqual(m.route['Поход'].num, 'Н2')
        self.assertEqual(m.route[MOVED + '\\Поход'].num, 'Н2')
        self.assertIn('Та же отметка действует и на', m.cell('Поход')['tip'])
        self.assertEqual(len(m.batch()[0]), 1)

    def test_have_column(self):
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        self.open()
        self.assertEqual(self.item('Поход 2010\\Фото').text(rp.C_HAVE), '1')     # 1.jpg есть на 45 и 77, 2.jpg - только на 45
        self.assertEqual(self.item('Поход 2010').text(rp.C_HAVE), '1')
        self.assertEqual(self.item('Работа').text(rp.C_HAVE), '0')               # направление с диском, ничего нет
        self.assertEqual(self.item('Друзья').text(rp.C_HAVE), '—')               # не копировать
        self.assertEqual(self.p.items[''].text(rp.C_HAVE), '1')
        self.p.apply(['Поход 2010\\Фото'], N2)                                   # исключение в подпапке: своё направление
        self.assertEqual(self.item('Поход 2010\\Фото').text(rp.C_HAVE), '0')
        self.assertEqual(self.item('Поход 2010').text(rp.C_HAVE), '0')


class ChoiceTest(PageBase):
    def test_opens_with_direction_chosen_in_overview(self):
        """Этап 8: диск назначения - первое по номеру направление, отмеченное в «Обзоре»; сохранённая отметка всего
        носителя не меняется; если она про другое направление - строка под переключателями."""
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.open()
        self.assertEqual(self.p.dest, 'Н2')
        self.assertEqual(self.p.dest_box.currentData(), 'Н2')
        self.assertIn('Работа', self.p.where.text())
        self.assertIn('HDD91 по журналу сканирования дисков', self.p.where.text())
        self.assertEqual(self.p.model.drafts, {})                                # ничего не отмечено молча
        self.p.set_dest('Н1')                                                    # владелец выбрал другое
        self.assertEqual(self.p.dest, 'Н1')
        dp.save_choice(['Н2', 'Н1'])                                             # снова из «Обзора»: по номеру - Н1
        self.p.set_dest('Н2')
        self.p.use_choice()
        self.assertEqual(self.p.dest, 'Н1')
        self.mark(('', 'Н2'))                                                    # сохранённый режим - «всё в Н2»
        dp.save_choice(['Н1'])
        self.p.load_disk(SRC, keep=False)
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.loading is None))
        self.p.use_choice()
        self.assertEqual(self.p.dest, 'Н1')
        self.assertTrue(self.p.mode_only.isChecked())                            # корень ≠ Н1 - «Только выбранные»
        self.assertIn('Весь носитель отмечен «Всё — в Работа (91)»', self.p.mode_note.text())
        self.assertEqual(self.p.model.drafts, {})
        self.p.set_dest('Н2')                                                    # для Н2 корень = Н2 - «Все папки»
        self.assertTrue(self.p.mode_every.isChecked())
        self.assertNotIn('Весь носитель отмечен', self.p.mode_note.text())
        self.settle()


class LayoutTest(PageBase):
    """Этап 8: тексты списков «Выберите носитель» и «Диск назначения», заголовок, «Задания на копирование»."""

    def test_texts_of_lists_and_head(self):
        import types
        rows = [dict(disk='HDD09', label='SN850X - 2 ТБ - Монтаж - SN850', letter='F:'),
                dict(disk='HDD45', label='WD20 - 2 ТБ - Бэкап фото и видео', letter='H:'),
                dict(disk='HDD77', label='WD40 - 4 ТБ - Путешествия', letter='')]
        self.assertEqual(rp.carrier_text(rows[0]), 'F: Монтаж - SN850 — HDD09 (по журналу сканирования дисков)')
        self.assertEqual(rp.carrier_text(rows[2]), 'Путешествия (не подключён) — HDD77 (по журналу '
                                                   'сканирования дисков)')
        self.assertEqual(rp.carrier_text(dict(disk='HDD61', label='ACASIS EC-7352 - 750 ГБ', letter='')),
                         'Накопитель (не подключён) — HDD61 (по журналу сканирования дисков)')   # метки нет - «Накопитель»
        d1 = sv.directions()['Н1']
        # этап 12: направление на двух дисках - коротко, диски не сливаются в одну строку
        self.assertEqual(rp.dest_text(d1, rows), 'Н1 Семейный архив — H: и HDD77 (две копии)')
        self.assertIn(f'<span style="color:{rp.ORANGE}"><b>Н1 Семейный архив</b></span>', rp.dest_html(d1, rows))
        h = rp.head_html(d1, rows, {'HDD45': ('H:', 421 * 1024 ** 3, 2000 * 1024 ** 3, 4096)})
        self.assertTrue(h.startswith('Диск: Семейный архив — две копии<br>'), h)
        self.assertIn(f'<span style="color:{rp.ORANGE}"><b>Н1 Семейный архив</b></span> · два задания — по одному на '
                      'каждый диск', h)
        lines = h.split('<br>')
        self.assertEqual(len(lines), 4)                                        # заголовок, направление, два диска
        self.assertTrue(lines[2].endswith('H: Бэкап фото и видео — HDD45 <span style="color:#33691e">· свободно '
                                          '421,0 ГБ</span>'), lines[2])
        self.assertIn('Путешествия — HDD77 <span', lines[3])
        self.assertIn('не подключён', lines[3])                                 # плашка - у своего диска
        self.assertNotIn('не подключён', lines[2])
        d3 = types.SimpleNamespace(num='Н3', name='Фильмы', disks=('HDD55',))
        h = rp.head_html(d3, [dict(disk='HDD55', label='WD20 - 2 ТБ - My Book', letter='I:')],
                         {'HDD55': ('I:', 421 * 1024 ** 3, 2000 * 1024 ** 3, 4096)})
        self.assertIn('Диск: I: My Book<br>', h)
        self.assertNotIn('не подключён', h)
        self.assertIn('HDD55 по журналу сканирования дисков · свободно 421,0 ГБ', h)
        self.assertNotIn('задани', h)
        for x in (h, rp.carrier_text(rows[0]), rp.dest_text(d1, rows)):
            self.assertNotIn('ТБ)', x)                                          # ни модели, ни объёма
        # в окне: строки списков по той же схеме, подключённые сверху (в тестах дисков нет - все «не подключён»)
        self.open()
        texts = [self.p.disk_box.itemText(i) for i in range(self.p.disk_box.count())]
        self.assertTrue(all(t.endswith('(по журналу сканирования дисков)') for t in texts if t), texts)
        by = {r['disk']: r for r in self.p.disk_rows}
        pl = lambda d: rp.place(by[d], d)                                                     # noqa: E731
        self.assertTrue(pl('HDD60').endswith('(не подключён)'))
        self.assertIn(rp.carrier_text(by['HDD60']), texts)
        dest = [self.p.dest_box.itemText(i) for i in range(self.p.dest_box.count())]
        self.assertEqual(dest, ['Н1 Семейный архив — HDD45 и HDD77 (две копии)',
                                f'{pl("HDD91")} — Н2 Работа — HDD91 (по журналу сканирования дисков)'])  # Н3 без диска
        self.assertIn(rp.ORANGE, self.p.dest_box.current_html())
        self.assertEqual([w.text() for w in (self.p.mode_only, self.p.mode_every, self.p.mode_except)],
                         ['Только выбранные папки', 'Все папки', 'Все, кроме выбранных'])
        self.assertEqual(self.p.copy_cell.title.text(), 'Копировать на два диска — две копии')
        # п. 3 этапа 12: имя направления под заголовком - оранжевым и жирным, номера HDD - обычным текстом
        self.assertEqual(self.p.copy_cell.sub.text(), f'<span style="color:{rp.ORANGE}"><b>Семейный архив</b></span>, '
                                                      'HDD45 и HDD77')
        self.assertNotIn('color', self.p.copy_cell.sub.styleSheet())           # не серая строка
        self.p.set_dest('Н2')
        self.assertEqual(self.p.copy_cell.title.text(), 'Копировать на диск ' + rp.short_place(by['HDD91'], 'HDD91'))
        self.assertEqual(self.p.copy_cell.sub.text(), f'<span style="color:{rp.ORANGE}"><b>Работа</b></span>, HDD91')
        self.assertEqual(self.p.copy_cell.blocks, [])                          # один диск - блоков нет
        self.p.set_dest('Н1')
        self.assertFalse(hasattr(self.p, 'stay_cell'))                         # ячейку «Остаётся» владелец убрал
        self.assertTrue(self.p.copy_cell.acceptDrops())
        self.assertIn('Shift/Ctrl — несколько папок сразу', self.p.tree_hint.text())
        for gone in ('apply_box', 'apply_btn', 'unmark_btn', 'mode_dir'):
            self.assertFalse(hasattr(self.p, gone), gone)
        self.assertEqual(self.p.tree.headerItem().text(rp.C_NAME), 'Папка')
        self.assertNotIn('Куда', [self.p.tree.headerItem().text(i) for i in range(self.p.tree.columnCount())])


class ModesTest(PageBase):
    """Этап 8: три режима ↔ отметки ядра, галочки нескольких выделенных, папки другого направления, бросок в ячейку,
    числа ячеек = план ядра."""

    def check_consistent(self):
        """Галочки на экране = маршрут ядра (Model.routes): в «Только»/«Все папки» галочка ⇔ папка идёт в D, в
        «Все, кроме» ⇔ «не копировать»."""
        m, mode = self.p.model, self.p.mode()
        for f, it in self.p.items.items():
            ck = m.check(f, self.p.dest, mode)
            if ck is None:
                continue
            r = m.route[f]
            want = r.state == rp.R_SKIP if mode == rp.EXCEPT else m.is_dir(r, self.p.dest)
            self.assertEqual(it.checkState(rp.C_CHECK) == rp.Qt.Checked, want, f)

    def test_three_modes_map_to_core_marks(self):
        self.open()
        m = self.p.model
        self.assertEqual(self.p.mode(), rp.ONLY)
        self.p.toggle(['Поход 2010', 'Работа'], True)                           # «Только выбранные»: галочка = Н1
        self.assertEqual({k: d['verdict'] for k, d in m.drafts.items()}, {'поход 2010': N1, 'работа': N1})
        self.item('Поход 2010\\Фото')
        self.check_consistent()
        # «Все папки»: весь носитель - в Н1
        self.p.mode_every.setChecked(True)
        self.assertEqual(m.drafts['']['verdict'], N1)
        self.assertEqual(self.p.mode(), rp.EVERY)
        self.assertTrue(self.p.mode_hint.text().startswith('•'))
        self.item('Друзья\\Наши')
        self.check_consistent()
        self.assertTrue(self.p.items['Друзья'].data(rp.C_CHECK, rp.GRAY_ROLE))   # всё - от всего носителя, серым
        # «Все, кроме выбранных»: галочка = «не копировать»
        self.p.mode_except.setChecked(True)
        self.assertEqual(self.p.mode(), rp.EXCEPT)
        self.assertEqual(self.p.items['Друзья'].checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.items['Друзья'].setCheckState(rp.C_CHECK, rp.Qt.Checked)
        self.assertEqual(m.drafts['друзья']['verdict'], rp.SKIP)
        self.assertEqual(self.p.items['Друзья\\Наши'].checkState(rp.C_CHECK), rp.Qt.Checked)     # исключена с родителем
        self.assertTrue(self.p.items['Друзья\\Наши'].data(rp.C_CHECK, rp.GRAY_ROLE))
        self.check_consistent()
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], 2)                     # a.jpg и b.jpg
        self.assertIn('Отмечено: весь носитель, кроме 1 папки', self.p.copy_cell.body.text())
        self.p.items['Друзья'].setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # снять исключение
        self.assertNotIn('друзья', m.drafts)
        self.p.toggle(['Друзья'], True)
        # «Все папки» снимает исключения одним шагом отмены
        self.p.mode_every.setChecked(True)
        self.assertNotIn('друзья', m.drafts)
        self.p.undo()
        self.assertEqual(m.drafts['друзья']['verdict'], rp.SKIP)
        # обратно «Только выбранные»: сохранённой отметки носителя нет - «ничего, кроме отмеченных»; свои Н1 остались
        self.p.mode_only.setChecked(True)
        self.assertEqual(m.drafts['']['verdict'], rp.SKIP)
        self.assertEqual(m.drafts['поход 2010']['verdict'], N1)
        self.assertEqual(self.p.mode(), rp.ONLY)
        self.check_consistent()
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_NONE, None)][0] if (rz.O_NONE, None) in P.part_a else 0, 0)
        self.assertEqual(self.asked, [])

    def test_only_returns_to_saved_mode_of_other_direction(self):
        self.mark(('', 'Н2'))
        self.open()
        self.assertEqual(self.p.dest, 'Н2')                                     # «Обзор» пуст - направление носителя
        self.p.set_dest('Н1')
        self.assertTrue(self.p.mode_only.isChecked())
        self.p.mode_except.setChecked(True)                                      # корень - Н1 черновиком
        self.assertEqual(self.p.model.drafts['']['verdict'], N1)
        self.p.mode_only.setChecked(True)                                        # вернуть сохранённое «всё в Н2»
        self.assertNotIn('', self.p.model.drafts)
        self.assertEqual(self.p.model.route[''].num, 'Н2')
        self.settle()

    def test_check_applies_to_all_selected(self):
        """Решение 16.11: выделение нескольких папок (Shift/Ctrl) сразу ставит галочки всем выделенным (один шаг
        отмены); щелчок по галочке потом снимает только её."""
        self.open()
        m = self.p.model
        self.p.tree.clearSelection()
        for f in ('Друзья', 'Работа', 'Документы'):
            self.item(f).setSelected(True)

        class Ev:
            def __init__(self, mods):
                self.mods = mods

            def modifiers(self):
                return self.mods

            def position(self):
                return QPointF(-5, -5)                                        # не по колонке галочек
        self.p.tree.multi(Ev(rp.Qt.NoModifier))                                  # без Shift/Ctrl - ничего
        wait(lambda: False, 0.5)
        self.assertEqual(m.drafts, {})
        self.p.tree.multi(Ev(rp.Qt.ControlModifier))                             # Ctrl-щелчок - всем сразу
        self.assertTrue(wait(lambda: len(m.drafts) == 3))
        self.assertEqual({k: d['verdict'] for k, d in m.drafts.items()}, {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # один шаг отмены
        self.assertTrue(wait(lambda: len(self.p.selected_folders()) == 3))       # выделение осталось
        self.item('Документы').setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # этап 12: у всей выделенной группы
        self.assertEqual(set(m.drafts), set())
        self.assertEqual(len(m.undo_stack), 2)
        self.p.check_selected()                                                  # повтор: уже отмеченные не трогаются
        self.assertEqual(set(m.drafts), {'друзья', 'работа', 'документы'})
        self.settle()

    def test_folder_of_other_direction(self):
        self.mark(('Работа', 'Н2'), ('Смешанная', 'Н2'))
        self.open()
        it = self.item('Работа')
        self.assertEqual(it.checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.assertEqual(it.data(rp.C_NAME, rp.TAG_ROLE), 'Н2')                  # мелкая серая метка
        self.assertIn('Папка отмечена для «Н2 Работа» (91)', it.toolTip(rp.C_NAME))
        self.assertIn('перейдёт на этот диск', it.toolTip(rp.C_NAME))
        it.setCheckState(rp.C_CHECK, rp.Qt.Checked)                              # перенос - без переспроса
        self.assertEqual(self.p.model.drafts['работа']['verdict'], N1)
        self.assertIsNone(self.item('Работа').data(rp.C_NAME, rp.TAG_ROLE))
        self.assertTrue(self.item('Работа').text(rp.C_NAME).startswith('• '))
        self.assertEqual(self.asked, [])
        # «Все, кроме выбранных»: галочка = исключение, папку другого направления так не перенести - только бросок
        self.p.mode_except.setChecked(True)
        ck = self.p.model.check('Смешанная', 'Н1', rp.EXCEPT)
        self.assertFalse(ck['checkable'])
        self.assertEqual(ck['tag'], 'Н2')
        self.assertIn('перетащите', ck['tip'])
        self.assertEqual(self.p.toggle(['Смешанная'], True), 0)
        self.assertEqual(self.p.copy_cell.drop_folders(['Смешанная']), 1)
        self.assertEqual(self.p.model.route['Смешанная'].num, 'Н1')
        self.settle()

    def test_drop_into_copy_cell(self):
        self.open()
        m = self.p.model
        md = self.p.tree.mimeData([self.p.items[''], self.item('Поход 2010'), self.item(MOVED)])
        self.assertEqual(rp.mime_folders(md), ['Поход 2010'])                     # не весь носитель, не служебная
        self.assertFalse(self.p.items[''].flags() & rp.Qt.ItemIsDragEnabled)
        self.assertEqual(self.p.copy_cell.drop_folders(['Поход 2010', '', MOVED]), 1)
        self.assertEqual(m.drafts['поход 2010']['verdict'], N1)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertEqual(self.p.copy_cell.drop_folders(['Поход 2010\\Фото']), 0)  # уже идёт с родителем - ничего
        self.p.mode_except.setChecked(True)                                      # в «Все, кроме» бросок снимает исключение
        self.p.toggle(['Друзья'], True)
        self.assertEqual(m.drafts['друзья']['verdict'], rp.SKIP)
        self.assertEqual(self.p.copy_cell.drop_folders(['Друзья']), 1)
        self.assertNotIn('друзья', m.drafts)
        self.settle()

    def test_cell_numbers_match_plan(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        self.mark(('', 'не копировать'), ('Поход 2010', 'Н1'), ('Работа', 'Н1'), ('Поход 2010\\Монтаж', 'не копировать'))
        self.open()
        self.assertEqual(self.p.mode(), rp.ONLY)
        P = self.plan()
        cp, hv = P.part_a[(rz.O_COPY, 'Н1')], P.part_a.get((rz.O_HAVE, 'Н1'), (0, 0))
        body = self.p.copy_cell.body.text()
        self.assertIn(f'Отмечено 2 папки · {rp.files_word(cp[0] + hv[0])} · {rp.gb(cp[1] + hv[1])} ГБ', body)
        # этап 12: два диска - два блока «Копия 1 / Копия 2», числа каждого - по плану ядра для этого диска
        texts = self.p.copy_cell.block_texts()
        self.assertEqual(list(texts), ['HDD45', 'HDD77'])
        by = {r['disk']: r for r in self.p.disk_rows}
        total = (cp[0] + hv[0], cp[1] + hv[1])
        self.assertEqual(total, (5, 400))            # 1.jpg, 2.jpg, описание.doc, схема.jpg, отчёт.doc
        have = self.p.model.have_on_disk('Н1')
        self.assertEqual(have, {'HDD45': (2, 300), 'HDD77': (1, 100)})          # 1.jpg - на обоих, 2.jpg - только на 45
        self.assertEqual(min(have.values()), tuple(hv))                          # «на всех дисках» = часть А ядра
        for i, x in enumerate(('HDD45', 'HDD77'), 1):
            t = texts[x]
            pb = P.part_b[x]
            self.assertEqual(pb[0], total[0] - have[x][0])                       # недостающее на диске = часть Б ядра
            self.assertIn(f'Копия {i} — {rp.esc(rp.disk_ui.disk_place(by[x]))} ({x})', t)
            self.assertIn(f'Копировать <b>{rp.gb(pb[1])} ГБ</b> ({rp.files_word(pb[0])})', t)
            self.assertIn(f'Уже есть на диске: <b>{rp.gb(have[x][1])} ГБ ({round(100 * have[x][1] / total[1])} %)</b>', t)
            self.assertIn(rp.files_word(have[x][0]), t)
            self.assertIn('место не проверено (диск не подключён)', t)
        self.assertIn('(75 %)', texts['HDD45'])
        self.assertIn('(25 %)', texts['HDD77'])
        self.assertNotIn('Уже есть на обоих', body)                              # общая часть - одна строка «Отмечено»
        self.assertNotIn('место не проверено', body)
        self.assertNotIn('на 45', body + ''.join(texts.values()))                # никаких голых «на 45»
        self.assertEqual(self.p.copy_cell.block_states(), {'HDD45': 'unknown', 'HDD77': 'unknown'})
        blocks = [b[1] for b in self.p.copy_cell.blocks]
        lay = self.p.copy_cell.layout()
        self.assertLess(lay.indexOf(self.p.copy_cell.body), lay.indexOf(self.p.copy_cell.blocks_box))
        self.assertLess(lay.indexOf(self.p.copy_cell.blocks_box), lay.indexOf(self.p.tasks_btn))   # кнопка - под блоками
        self.assertTrue(all('border:1px solid' in b.styleSheet() for b in blocks))   # у каждого блока - рамка
        n, b = rp.stay_numbers(P)
        moved = P.part_a.get((rz.O_MOVED, None), (0, 0))[0]
        self.assertEqual(cp[0] + hv[0] + n + moved, P.total[0])                  # отмечено + остаётся + перенесено = опись
        self.assertEqual(self.p.copy_cell.state, 'unknown')
        self.assertTrue(self.p.tasks_btn.isEnabled())
        self.assertIs(self.p.tasks_btn, self.p.copy_cell.btn)


class HaveNearTest(PageBase):
    def test_have_docs_only_near_matches_planner(self):
        """Замечание 2: «Уже есть» при «документы только рядом» = ядро: документ без фото рядом - не в «Уже есть»."""
        make_disk(self.scans, 'HDD64', 'AAAA0064', [('A\\x.doc', 10, S[1]), ('B\\y.doc', 10, S[1]),
                                                     ('B\\z.jpg', 10, H50)])
        hb.close_last()
        self.quiet(hb.connect)
        self.mark(('', 'Н1'), disk='HDD64')
        self.p.refresh()
        self.assertTrue(wait(lambda: any(r['disk'] == 'HDD64' for r in self.p.disk_rows)))
        self.open('HDD64')
        self.assertEqual(self.item('A').text(rp.C_HAVE), '0')                    # документ без фото рядом
        self.assertEqual(self.item('B').text(rp.C_HAVE), '1')                    # y.doc - рядом с z.jpg, есть на 45 и 77
        P = sv.razbor('HDD64')
        self.assertEqual(P.part_a[(rz.O_HAVE, 'Н1')][0], int(self.p.items[''].text(rp.C_HAVE)))
        self.assertEqual(P.part_a[(rz.O_TYPE, 'Н1')][0], 1)


class SummaryTest(PageBase):
    def test_modes_and_summary_equals_inventory(self):
        self.open()
        self.p.mode_every.setChecked(True)                                     # диск назначения - Н1
        P = self.plan()
        self.assertEqual(P.errors, [])
        self.assertEqual(P.total[0], len(FILES))
        self.assertEqual(sum(v[0] for v in P.part_a.values()), len(FILES))
        text = self.p.summary.toPlainText()
        self.assertIn('Итого = опись носителя', text)
        self.assertIn('HDD45', text)
        self.assertIn('не подключён — место не проверено', text)
        self.assertIn('сравнение только по имени и размеру', text)              # описание.doc без хеша
        self.assertIn('с несохранёнными', self.p.sum_state.text())
        # «Только выбранные» = «ничего, кроме отмеченных»: всё - «не копировать», кроме уже перенесённого
        self.p.mode_only.setChecked(True)
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], len(FILES) - 1)
        self.assertEqual(P.part_a[(rz.O_MOVED, None)][0], 1)
        self.assertIn('Писать на диски нечего', self.p.summary.toPlainText())
        self.p.apply(['Друзья'], N2)
        P = self.plan()
        self.assertEqual(dict(P.part_b), {'HDD91': [2, 185]})
        self.assertEqual(self.p.model.drafts['']['verdict'], rp.SKIP)

    def test_stale_answer_is_not_shown(self):
        self.open()
        self.p.mode_every.setChecked(True)
        self.p.changed()                                    # правка во время расчёта: ревизия растёт сразу
        self.assertNotEqual(self.p.plan_rev, self.p.rev)
        self.settle()
        self.assertEqual(self.p.plan_rev, self.p.rev)


class SaveTest(PageBase):
    def rows(self):
        return hb.DECISIONS.read_text(encoding='utf-8-sig').splitlines() if hb.DECISIONS.exists() else []

    def test_save_marks_batch_and_prune(self):
        self.open()
        self.p.mode_except.setChecked(True)
        self.p.apply(['Поход 2010\\Монтаж', 'Друзья'], rp.SKIP)
        self.p.apply(['Работа'], N2)
        self.assertEqual(self.p.save_btn.text(), 'Сохранить отметки (4)')
        before = self.rows()
        real = sv.add_marks_batch
        with mock.patch.object(sv, 'add_marks_batch', side_effect=real) as spy:
            self.p.save()
            self.assertTrue(wait(lambda: not self.p.writing and not self.p.model.drafts), self.asked)
        self.assertEqual(spy.call_count, 1)                                     # одним пакетом
        new = self.rows()[len(before):]
        self.assertEqual(len(new), 4, new)
        self.assertTrue(any(f'{SRC}\t\t{N1}' in x for x in new), new)
        self.assertIn('Было → станет', self.dialogs[-1])
        self.assertIn('было «режим не выбран', self.dialogs[-1])
        self.assertFalse(self.p.save_btn.isEnabled())
        self.assertEqual(self.to('Работа'), 'Работа (91)')                      # своя сохранённая - без «•»
        # снаружи записали то же, что в черновике - черновик сам очищается; другое - конфликт в предпросмотре
        self.p.apply(['Документы'], rp.SKIP)
        self.p.apply(['Смешанная'], N2)
        sv.add_marks_batch(SRC, [('Документы', 'не копировать'), ('Смешанная', 'Н3')])
        self.p.refresh()
        self.assertTrue(wait(lambda: 'документы' not in self.p.model.drafts and self.p.loading is None))
        self.settle()
        self.assertIn('смешанная', self.p.model.drafts)
        _lines, conflicts, _nested = self.p.model.change_lines()
        self.assertTrue(conflicts and 'изменили в другом месте' in conflicts[0], conflicts)

    def test_refused_write_keeps_drafts(self):
        self.open()
        self.p.apply(['Работа'], N2)
        with mock.patch.object(sv, 'add_marks_batch', side_effect=sv.Refused('проба отказа')):
            self.p.save()
            self.assertTrue(wait(lambda: not self.p.writing))
        self.assertIn('работа', self.p.model.drafts)
        self.assertTrue(any('проба отказа' in x for x in self.asked), self.asked)

    def test_close_and_disk_change_ask_about_drafts(self):
        self.open()
        self.p.apply(['Работа'], N2)
        self.answer = rp.QMessageBox.No
        self.assertFalse(self.w.close())                                        # окно не закрылось
        self.assertTrue(any('несохранённые отметки (1)' in x for x in self.asked), self.asked)
        self.p.disk_box.setCurrentText('HDD90')                                 # смена носителя - тот же вопрос
        self.assertEqual(self.p.disk, SRC)
        self.assertEqual(self.p.disk_box.value(), SRC)
        self.answer = rp.QMessageBox.Yes


TOC_OK = dict(connected=True, reason='', letter='K:', checked=5, problems=[])


class TasksTest(PageBase):
    def setUp(self):
        super().setUp()
        self.toc_calls = []

        def toc(*a, **k):
            self.toc_calls.append(a)
            return TOC_OK
        self.toc_patch = mock.patch.object(sv, 'toc_check', toc)       # носителя в тестах нет - сверка отдельно
        self.toc_patch.start()

    def tearDown(self):
        self.toc_patch.stop()
        super().tearDown()

    def made(self):
        return sorted(x.name for x in hb.TASKS.iterdir() if x.name.startswith(SRC)) if hb.TASKS.exists() else []

    def test_prepare_tasks_after_saving_drafts(self):
        self.open()
        self.p.mode_every.setChecked(True)
        self.p.apply(['Работа'], N2)
        self.p.prepare(['Н1', 'Н2'])         # черновик есть - сначала сохранить (предпросмотр), затем задания
        self.assertTrue(wait(lambda: self.made() and not self.p.writing, 60), self.asked)
        self.assertTrue(any('Задания строятся только из сохранённых' in x for x in self.asked), self.asked)
        self.assertTrue(any(f'{SRC} — Работа — Работа' in x for x in self.dialogs), self.dialogs)
        self.assertIn(f'{SRC} — Работа — Работа', self.made())
        self.assertTrue(list(hb.RAZBORY.glob(f'{SRC} *.json')))
        self.assertIs(self.w.stack.currentWidget(), self.w.page('Задания на копирование'))
        self.assertTrue(any(x.startswith('Создано заданий') and 'Задания на копирование' in x for x in self.asked),
                        self.asked)

    def test_list_changed_before_create_is_shown_again(self):
        self.mark(('', 'Семейный архив'))
        self.open()
        real = rp.tasks_dry
        calls = []

        def dry(disk, nums=None):            # между показом и созданием кто-то добавил отметку
            calls.append(disk)
            if len(calls) == 1:
                sv.add_marks_batch(SRC, [('Работа', 'Н2')])
            return real(disk, nums)
        with mock.patch.object(rp, 'tasks_dry', dry):
            self.p.prepare(['Н1', 'Н2'])
            self.assertTrue(wait(lambda: len(calls) >= 2 and self.made() and not self.p.writing, 60), self.asked)
        self.assertTrue(any('проверьте окно ещё раз' in x for x in self.dialogs), self.dialogs)
        self.assertIn(f'{SRC} — Работа — Работа', self.made())

    def test_source_is_direction_disk(self):
        sv.add_marks_batch('HDD45', [('', 'Семейный архив')])
        self.open('HDD45')
        self.assertTrue(self.p.banner.isVisibleTo(self.p))
        self.assertIn('перемещать на нём ничего нельзя', self.p.banner.text())
        P = self.plan()
        self.assertEqual(set(P.part_b), {'HDD77'})                              # копировать можно - на 77
        self.p.prepare(['Н1'])
        self.assertTrue(wait(lambda: self.dialogs and not self.p.writing, 60), self.asked)
        self.assertIn('сам диск направления', self.dialogs[0])
        self.assertTrue(any(x.name.startswith('HDD45 —') for x in hb.TASKS.iterdir()))


class ContestedTest(PageBase):
    def test_contested_dialog_and_rescan(self):
        self.open('HDD90')
        self.p.contested()                                                      # ничего не выделено - весь носитель
        dlg = self.p._contested
        self.assertEqual(dlg.folder, '')
        self.assertTrue(wait(lambda: dlg.rows is not None))
        self.assertIn('не подключён', dlg.text.toPlainText())                  # в тестах дисков нет
        opened = []

        class Fake:
            running = False

            def __init__(self, win, disk, folders):
                opened.append((disk, folders))

            def show(self):
                pass
        fake = [('HDD90', 'K:', [('A', 1), ('', 2)]), ('HDD45', '', [('X', 3)])]
        with mock.patch.object(sv, 'contested', lambda d, f: fake), mock.patch('rescan_dialog.RescanDialog', Fake):
            dlg.load()
            self.assertTrue(wait(lambda: dlg.buttons.count() == 1))
            text = dlg.text.toPlainText()
            self.assertIn('полное сканирование HDD90', text)
            self.assertIn('HDD45: не подключён', text)
            dlg.buttons.itemAt(0).widget().click()
        self.assertEqual(opened, [('HDD90', ['A'])])                           # корень в пересканирование не идёт

    def test_commands_page_offers_contested_after_no(self):
        cp = self.w.page('Команды')
        self.w.open_page('Команды')
        self.assertTrue(wait(lambda: cp.disks))
        f = cp.select('candel')
        put(f, disk='HDD90', folder='A')
        cp.execute()
        self.assertTrue(wait(lambda: cp.run is None, 90))
        self.assertTrue(any(x.startswith('ОТВЕТ: НЕТ') for x in cp.lines), cp.lines)
        self.assertTrue(cp.btn_contested.isVisibleTo(cp))
        with mock.patch.object(rp.ContestedDialog, 'show', lambda s: None):
            cp.btn_contested.click()
        self.assertEqual((cp.contested_dlg.disk, cp.contested_dlg.folder), ('HDD90', 'A'))
        put(f, folder='B')                                                      # следующий запуск прячет кнопку
        cp.execute()
        self.assertFalse(cp.btn_contested.isVisibleTo(cp))
        self.assertTrue(wait(lambda: cp.run is None, 90))


class CapacityTest(PageBase):
    def test_capacity_math(self):
        G = 1024 ** 3
        cap = sv.capacity({'HDD45': [10, 100 * G], 'HDD77': [0, 0], 'HDD91': [1, 1]},
                          {'HDD45': ('F:', 103 * G, 1000 * G, 4096)}, {'HDD45': [1, G]})
        x = cap['HDD45']
        self.assertEqual(x['reserve'], 10 * G)                                  # 1 % от 1000 ГБ > 2 ГиБ
        self.assertEqual(x['need'], 100 * G + 10 * 4096 + G)                     # + кластеры + очередь
        self.assertEqual(x['state'], 'short')
        self.assertEqual(cap['HDD77']['state'], 'none')
        self.assertEqual(cap['HDD91']['state'], 'unknown')
        self.assertEqual(sv.reserve_of(50 * G), sv.RESERVE_MIN)                  # маленький диск - 2 ГиБ
        self.assertEqual(sv.capacity({'HDD45': [1, G]}, {'HDD45': ('F:', 4 * G, 100 * G, 4096)})['HDD45']['state'], 'ok')

    def test_short_disk_turns_cell_red_and_blocks_direction(self):
        """Не помещается на 45 (на 77 место неизвестно) - ячейка «Копировать на диски» красная, кнопка неактивна;
        другой диск назначения (Н2) - задания создаются, у Н1 - ни на 45, ни на 77."""
        import directions_page as dp
        dp.save_choice(['Н1', 'Н2'])
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        space = {'HDD45': ('F:', 1000, 10 ** 12, 4096)}
        with mock.patch.object(sv, 'disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}), \
                mock.patch.object(sv, 'toc_check', lambda *a, **k: TOC_OK):
            self.open()
            self.plan()
            c = self.p.copy_cell
            self.assertEqual(self.p.dest, 'Н1')
            self.assertEqual(c.state, 'short')
            self.assertIn('не помещается', c.block_texts()['HDD45'])           # в блоке своего диска (этап 12)
            self.assertEqual(c.block_states(), {'HDD45': 'short', 'HDD77': 'unknown'})
            self.assertIn('место не проверено (диск не подключён)', c.block_texts()['HDD77'])
            self.assertFalse(c.btn.isEnabled())
            self.assertIn('снимите галочки', c.btn.toolTip())
            self.p.prepare(['Н1', 'Н2'])                                         # Н1 исключается целиком
            self.assertTrue(wait(lambda: not self.p.writing and hb.TASKS.exists() and
                                 any(x.name.startswith(SRC) for x in hb.TASKS.iterdir()), 60), self.asked)
            self.p.set_dest('Н2')
            self.assertNotEqual(self.p.copy_cell.state, 'short')
        made = sorted(x.name for x in hb.TASKS.iterdir() if x.name.startswith(SRC))
        self.assertEqual(made, [f'{SRC} — Работа — Работа'])
        self.assertIn('Семейный архив не помещается', self.dialogs[0])
        self.assertIn('Снимите галочки у части папок', self.dialogs[0])
        self.assertTrue(any('Задания на копирование' in x for x in self.asked), self.asked)
        self.assertIs(self.w.stack.currentWidget(), self.w.page('Задания на копирование'))


class TocTest(PageBase):
    """Сверка оглавления на временной папке, изображающей подключённый носитель (настоящие диски не трогаются)."""

    def make_root(self):
        root = self.tmp / 'носитель'
        for p, size, _h in FILES:
            f = root / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b'x' * size)
            os.utime(f, (0, 0))                                                 # в описи тестов mtime = 0
        return root

    def test_toc_check_on_temp_folder(self):
        root = self.make_root()
        with mock.patch.object(sv, 'volumes', return_value={'AAAA0060': str(root)}):
            ok = sv.toc_check(SRC, ['Поход 2010', 'Работа'], True)
            self.assertTrue(ok['connected'])
            self.assertEqual(ok['problems'], [])
            (root / 'Поход 2010' / 'Фото' / '1.jpg').unlink()                   # исчез
            (root / 'Поход 2010' / 'Фото' / 'новый.jpg').write_bytes(b'n')       # новый
            (root / 'Работа' / 'схема.jpg').write_bytes(b'y' * 71)               # другой размер
            os.utime(root / 'Работа' / 'схема.jpg', (0, 0))
            os.utime(root / 'Работа' / 'отчёт.doc', (5, 5))                      # другая дата
            res = sv.toc_check(SRC, ['Поход 2010', 'Работа'], True)
            by = {p['folder']: p for p in res['problems']}
            self.assertEqual((by['Поход 2010']['gone'], by['Поход 2010']['new']), (1, 1))
            self.assertEqual((by['Работа']['size'], by['Работа']['date']), (1, 1))
            self.assertNotIn(None, by)                                           # файлы корня не менялись
            lines = '\n'.join(sv.toc_lines(res))
            self.assertIn('Поход 2010 — исчезли 1, новые 1', lines)
            # подпапка с отметкой другого направления не сверяется, а более глубокая отметка того же - снова да
            z = sv.toc_check(SRC, ['Поход 2010'], False, [('Поход 2010\\Фото', False)])
            self.assertEqual(z['problems'], [])
            z = sv.toc_check(SRC, ['Поход 2010'], False, [('Поход 2010', True), ('Поход 2010\\Фото', False)])
            self.assertEqual(z['problems'], [])
        res = sv.toc_check(SRC, ['Поход 2010'])                                  # носитель не подключён
        self.assertFalse(res['connected'])
        self.assertIn('Носитель не подключён — сверка оглавления с описью невозможна', sv.toc_lines(res)[0])

    def test_targets_and_zones(self):
        self.mark(('', 'Н1'), ('Поход 2010\\Монтаж', 'не копировать'), ('Работа', 'Н2'))
        P = sv.razbor_tasks(SRC, dry=True)['plan']
        specs = [s for s in sv.razbor_tasks(SRC, dry=True)['specs'] if s['num'] == 'Н1']
        folders, root, zones = sv.toc_targets(P, specs)
        self.assertIn('Поход 2010', folders)
        self.assertIn(('Поход 2010\\Монтаж', False), zones)

    def test_page_blocks_tasks_on_mismatch_and_offers_rescan(self):
        self.mark(('', 'Н1'))
        root = self.make_root()
        (root / 'Поход 2010' / 'Фото' / '2.jpg').unlink()
        opened = []
        with mock.patch.object(sv, 'volumes', return_value={'AAAA0060': str(root)}):
            self.open()
            self.p.rescan = lambda d, f: opened.append((d, f))
            self.p.prepare(['Н1'])
            self.assertTrue(wait(lambda: self.dialogs and not self.p.writing, 60), self.asked)
        self.assertIn('Задания не создаются: оглавление носителя не совпадает с описью', self.dialogs[0])
        self.assertIn('Поход 2010 — исчезли 1', self.dialogs[0])
        self.assertIsNone(self.dlgs[0].ok)                                      # кнопки «Создать» нет
        self.dlgs[0].extra.click()                                               # «Пересканировать эти папки…»
        self.assertEqual(opened, [(SRC, ['Поход 2010'])])
        self.assertFalse(hb.TASKS.exists() and any(x.name.startswith(SRC) for x in hb.TASKS.iterdir()))
        # не подключён - тоже не создаются
        self.dialogs.clear()
        self.p.prepare(['Н1'])
        self.assertTrue(wait(lambda: self.dialogs and not self.p.writing, 60), self.asked)
        self.assertIn('Носитель не подключён', self.dialogs[0])
        self.assertFalse(hb.TASKS.exists() and any(x.name.startswith(SRC) for x in hb.TASKS.iterdir()))


class Review6Test(PageBase):
    """Проверка кода этапа 6 критиками: сверка перед самым созданием, фильтр направлений, 4 сочетания места,
    одно правило пропуска для описи и оглавления, очередь с числом файлов."""

    def test_toc_rechecked_right_before_create(self):
        self.mark(('', 'Н1'))
        answers = [TOC_OK, dict(connected=True, reason='', letter='K:', checked=5, problems=[
            dict(folder='Поход 2010', gone=1, new=0, size=0, date=0, unread=0,
                 examples=dict(gone=['Поход 2010\\Фото\\1.jpg'], new=[], size=[], date=[], unread=[]))])]
        calls = []

        def toc(*a, **k):
            calls.append(a)
            return answers[min(len(calls) - 1, 1)]
        with mock.patch.object(sv, 'toc_check', toc):
            self.open()
            self.p.prepare(['Н1'])
            self.assertTrue(wait(lambda: len(self.dialogs) >= 2 and not self.p.writing, 60), self.asked)
        self.assertEqual(len(calls), 2)                                          # при показе и перед созданием
        self.assertIn('сам носитель изменились', self.dialogs[1])
        self.assertIn('Поход 2010 — исчезли 1', self.dialogs[1])
        self.assertIsNone(self.dlgs[1].ok)
        self.assertFalse(hb.TASKS.exists() and any(x.name.startswith(SRC) for x in hb.TASKS.iterdir()))

    def test_only_selected_directions_and_queue_of_this_carrier(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        space = {'HDD45': ('F:', 1000, 10 ** 12, 4096)}                          # Н1 не помещается на 45
        with mock.patch.object(sv, 'disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}), \
                mock.patch.object(sv, 'toc_check', lambda *a, **k: TOC_OK):
            v = rp.tasks_check(SRC, ['Н2'])
            self.assertEqual(v['short'], [])                                    # Н1 в выбор не входит - не мешает
            self.assertEqual({s['num'] for s in v['specs']}, {'Н2'})
            body, new = rp.tasks_html(v, str)
            self.assertNotIn('HDD45', body)                                      # место - только дисков выбранных
            self.assertNotIn('HDD77', body)
            sv.razbor_tasks(SRC, dry=False, only=['Н2'])
        self.assertEqual(sv.queued_copy(SRC), {})                               # свои задания уже в части Б
        q = sv.queued_copy('HDD99')
        self.assertEqual(q['HDD91'][0], 1)
        self.assertEqual(q['HDD91'][2], 2)                                       # отчёт.doc и схема.jpg

    def test_four_space_combinations(self):
        import types
        G = 1024 ** 3
        space = {'HDD45': ('F:', 500 * G, 1000 * G, 4096), 'HDD91': ('H:', 100 * G, 1000 * G, 4096)}
        cap = sv.capacity({'HDD45': [3, G], 'HDD77': [2, G]}, space, {}, disks=['HDD45', 'HDD77', 'HDD91', 'HDD92'])
        self.assertEqual(cap['HDD45']['state'], 'ok')                           # копировать, подключён
        self.assertEqual(cap['HDD77']['state'], 'unknown')                      # копировать, не подключён
        self.assertEqual((cap['HDD91']['state'], cap['HDD91']['free']), ('none', 100 * G))   # нечего, подключён
        self.assertEqual((cap['HDD92']['state'], cap['HDD92']['free']), ('none', None))      # нечего, не подключён
        d = sv.directions()['Н1']
        P = types.SimpleNamespace(part_a={}, disk=SRC)
        name = {'HDD45': 'F: Бэкап', 'HDD77': 'Путешествия (не подключён)'}.get
        html_, state = rp.dest_cell_html(d, P, cap, rp.ONLY, 0, 0, name)
        self.assertIn('Копировать на диск F: Бэкап (HDD45): <b>1,0 ГБ</b>', html_)
        self.assertIn('помещается: свободно 500,0 ГБ', html_)
        self.assertIn('Копировать на диск Путешествия (не подключён) (HDD77): <b>1,0 ГБ</b>', html_)
        self.assertIn('место не проверено (диск не подключён)', html_)
        self.assertEqual(state, 'unknown')
        cap2 = sv.capacity({}, space, {}, disks=['HDD45', 'HDD77'])
        html_, state = rp.dest_cell_html(d, P, cap2, rp.ONLY, 0, 0, name)
        self.assertIn('Копировать на диск F: Бэкап (HDD45): копировать нечего', html_)
        self.assertNotIn('место не проверено', html_)
        self.assertEqual(state, 'ok')
        cap3 = sv.capacity({'HDD45': [3, 600 * G]}, space, {}, disks=['HDD45', 'HDD77'])
        html_, state = rp.dest_cell_html(d, P, cap3, rp.ONLY, 0, 0, name)
        self.assertIn('не помещается: нужно', html_)
        self.assertIn('свободно 500,0 ГБ', html_)
        self.assertEqual(state, 'short')
        q = sv.capacity({'HDD45': [1, G]}, space, {'HDD45': [1, G, 10]})['HDD45']
        self.assertEqual(q['need'], G + 4096 + G + 10 * 4096)                   # кластер и на файлы очереди

    def test_same_skip_rule_for_inventory_and_disk(self):
        root = TocTest.make_root(self)
        self.assertTrue((root / 'Поход 2010' / 'Фото' / 'Thumbs.db').exists())  # Thumbs.db в описи и на диске
        (root / 'Поход 2010' / '$RECYCLE.BIN').mkdir()                           # служебная папка - опись её не видит
        (root / 'Поход 2010' / '$RECYCLE.BIN' / 'x.jpg').write_bytes(b'1')
        (root / 'Поход 2010' / 'Фото' / 'ключи.env').write_bytes(b'1')          # .env - опись пропускает
        sv.add_exclusion(SRC, 'Документы')                                       # исключённая владельцем папка
        (root / 'Документы' / 'новое.doc').write_bytes(b'1')
        with mock.patch.object(sv, 'volumes', return_value={'AAAA0060': str(root)}):
            res = sv.toc_check(SRC, ['Поход 2010', 'Документы'])
        self.assertEqual(res['problems'], [])
        (root / 'Поход 2010' / 'Фото' / 'desktop.ini').write_bytes(b'1')        # опись его описала бы - «новый»
        with mock.patch.object(sv, 'volumes', return_value={'AAAA0060': str(root)}):
            res = sv.toc_check(SRC, ['Поход 2010'])
        self.assertEqual([(p['folder'], p['new']) for p in res['problems']], [('Поход 2010', 1)])


class Review8Test(PageBase):
    """Проверка кода этапа 8 критиками: «Только выбранные» при носителе в другом направлении, «Все папки» снимает
    только исключения внутри D, «кроме N папок» - свои исключения, «Ничего не отмечено», длинный текст списка."""

    def test_only_with_carrier_in_other_direction_says_where_rest_goes(self):
        self.mark(('', 'Н2'))
        self.open()
        self.p.set_dest('Н1')
        self.p.toggle(['Поход 2010'], True)
        self.p.mode_except.setChecked(True)
        self.p.mode_only.setChecked(True)                                        # корень - снова сохранённый Н2
        self.assertEqual(self.p.model.route[''].num, 'Н2')
        P = self.plan()
        note = self.p.mode_note.text()
        self.assertIn('Весь носитель отмечен «Всё — в Работа (91)»: папки без галочки идут туда', note)
        v = [P.part_a.get((o, 'Н2'), (0, 0)) for o in (rz.O_COPY, rz.O_HAVE)]
        self.assertIn(rp.files_word(v[0][0] + v[1][0]), note)
        self.p.set_dest('Н2')                                                    # для Н2 это «Все папки» - строки нет
        self.assertNotIn('Весь носитель отмечен', self.p.mode_note.text())

    def test_every_drops_only_exclusions_inside_dest(self):
        self.mark(('Друзья', 'Н2'), ('Друзья\\Наши', 'не копировать'), ('Документы', 'не копировать'))
        self.open()
        self.assertEqual(self.p.dest, 'Н1')
        self.p.mode_every.setChecked(True)
        d = {k: x['verdict'] for k, x in self.p.model.drafts.items()}
        self.assertEqual(d, {'': N1, 'документы': rp.INHERIT})                  # «Наши» внутри Н2 - не тронута
        self.assertEqual(self.p.model.route['Друзья\\Наши'].state, rp.R_SKIP)
        self.settle()

    def test_except_counts_only_own_exclusions(self):
        self.mark(('Смешанная', 'Н2'))
        self.open()
        self.p.mode_except.setChecked(True)
        self.p.toggle(['Друзья'], True)
        self.p.toggle(['Друзья\\Наши'], True)                                   # серая - не меняется
        self.assertEqual(self.p.counts()[1], 1)                                  # Смешанная (Н2) и служебная - не «кроме»
        self.plan()
        self.assertIn('Отмечено: весь носитель, кроме 1 папки ·', self.p.copy_cell.body.text())

    def test_nothing_marked_and_long_dest_text(self):
        self.open()
        self.plan()
        self.assertIn('Ничего не отмечено — поставьте галочки у папок', self.p.copy_cell.body.text())
        self.assertNotIn('Отмечено 0', self.p.copy_cell.body.text())
        box = self.p.dest_box
        longest = max(box.html_width(box.itemData(i, rp.Qt.UserRole + 5)) for i in range(box.count()))
        self.assertGreaterEqual(box.view().minimumWidth(), longest)              # список во всю ширину пункта
        box.setMinimumWidth(0)
        box.setFixedWidth(160)                                                   # закрытое поле узкое - «…»
        box.grab()
        self.assertEqual(box.toolTip(), box.currentText())


class Round3Test(PageBase):
    """Третий круг «Разбора» (решения владельца 16.11): режим выбран всегда, «выбрать все», красный в «Все, кроме»,
    «Идёт пересчёт», верхний блок формой, ячейки «Остаётся» нет."""

    def test_default_mode_and_form(self):
        self.open()
        self.assertTrue(self.p.mode_only.isChecked())                            # по умолчанию - «Только выбранные»
        self.assertTrue(all(w.isCheckable() for w in self.p.mode_btn.values()))
        self.assertIsInstance(self.p.mode_only, rp.QPushButton)                  # кнопки, не переключатели
        self.assertEqual(self.p.mode_note.text(), rp.MODE_NOTE[rp.ONLY])          # строка пояснения режима
        page_text = ' '.join(w.text() for w in self.p.findChildren(rp.QLabel))
        self.assertNotIn('Сначала выберите режим', page_text)
        self.assertIn('не подключён', self.p.info.text())                        # плашка под полем носителя
        self.assertIn('опись от', self.p.info.text())
        info = self.p.dest_info.text().split('<br>')                           # диски теста не подключены
        self.assertEqual(len(info), 3)                                           # по строке на каждый диск
        self.assertIn('Копия 1 — ', info[0])
        self.assertIn('(HDD45): подключите диск, чтобы проверить свободное место.', info[0])
        self.assertIn('(HDD77): подключите диск', info[1])
        self.assertGreaterEqual(self.p.dest_box.minimumHeight(),
                                rp.QFontMetrics(self.p.dest_box.font()).height() + 16)   # поле выше - низ не обрезан
        self.p.mode_except.setChecked(True)
        self.assertTrue(self.p.mode_except.isChecked() and not self.p.mode_only.isChecked())
        self.assertEqual(self.p.mode_note.text(), rp.MODE_NOTE[rp.EXCEPT])
        self.p.dest = None                                                       # без диска назначения - всё равно режим
        self.p.sync_mode()
        self.assertTrue(self.p.mode_only.isChecked())
        self.assertFalse(self.p.mode_only.isEnabled())
        self.p.set_dest('Н1')
        self.settle()

    def test_select_all_at_root(self):
        self.open()
        m = self.p.model
        tops = self.p.tops()
        self.assertNotIn(MOVED, tops)                                            # служебная - не участвует
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.toggle(['Работа'], True)
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)
        undo = len(m.undo_stack)
        self.p.items[''].setCheckState(rp.C_CHECK, rp.Qt.Checked)               # щелчок - все верхние
        self.assertTrue(all(m.is_dir(m.route[f], 'Н1') for f in tops))
        self.assertEqual(len(m.undo_stack), undo + 1)                            # одним шагом
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertNotIn('', m.drafts)                                           # весь носитель не трогается
        self.p.items[''].setCheckState(rp.C_CHECK, rp.Qt.Unchecked)             # снять все
        self.assertFalse(any(m.is_dir(m.route[f], 'Н1') for f in tops))
        self.p.mode_every.setChecked(True)                                       # в других режимах у корня галочки нет
        self.assertIsNone(self.p.items[''].data(rp.C_CHECK, rp.Qt.CheckStateRole))
        self.settle()

    def test_except_mode_is_red_without_green(self):
        self.open()
        self.p.mode_except.setChecked(True)
        self.p.toggle(['Друзья'], True)                                          # «не копировать»
        it = self.item('Друзья')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.EXC_BG)
        self.assertEqual(it.foreground(rp.C_NAME).color().name(), rp.BLUE)      # не сохранено - синий курсив
        sub = self.item('Друзья\\Наши')
        self.assertEqual(sub.background(rp.C_NAME).color().name(), rp.EXC_BG)  # вместе с родителем - тоже красный фон
        greens = [f for f, x in self.p.items.items() if x.background(rp.C_NAME).color().name() == rp.SEL_BG]
        self.assertEqual(greens, [])                                             # зелёного в этом режиме нет
        self.assertIn('красный фон', self.p.tree_legend.text())
        self.assertNotIn('зелёный фон', self.p.tree_legend.text())
        self.p.mode_only.setChecked(True)
        self.assertIn('зелёный фон', self.p.tree_legend.text())
        self.settle()

    def test_busy_label_while_recount(self):
        self.open()
        self.assertFalse(self.p.busy_lab.isVisibleTo(self.p))
        self.p.toggle(['Работа'], True)
        self.assertTrue(self.p.busy_lab.isVisibleTo(self.p))                     # сразу после правки
        self.assertTrue(self.p.blink.isActive())
        self.assertIn('Идёт пересчёт', self.p.busy_lab.text())
        self.settle()
        self.assertTrue(wait(lambda: not self.p.busy_lab.isVisibleTo(self.p)))
        self.assertFalse(self.p.blink.isActive())


class Stage12Test(PageBase):
    """Этап 12 (решения владельца 16.11): шаги - в самом верху, групповые галочки мышью, 45 и 77 раздельно."""

    def show(self, w=1600, h=1000):
        from test_app import QAPP
        self.w.resize(w, h)
        self.w.show()
        QAPP.processEvents()

    def test_steps_above_head(self):
        lay = self.p.layout()
        self.assertEqual(lay.indexOf(self.p.steps), 0)                          # первым в странице
        self.open()
        self.show()
        self.assertLess(self.p.steps.mapTo(self.p, QPoint(0, 0)).y(), self.p.where.mapTo(self.p, QPoint(0, 0)).y())
        self.assertLess(self.p.steps.geometry().bottom(), self.p.where.mapTo(self.p, QPoint(0, 0)).y())

    def click_check(self, path, mods=None, double=False):
        """Настоящий щелчок мышью по индикатору галочки строки (как владелец)."""
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QStyleOptionViewItem
        from test_app import QAPP
        it = self.item(path)
        tree = self.p.tree
        tree.scrollToItem(it)
        QAPP.processEvents()
        idx = tree.indexFromItem(it, rp.C_CHECK)
        opt = QStyleOptionViewItem()
        tree.itemDelegate().initStyleOption(opt, idx)
        opt.rect = tree.visualRect(idx)
        r = tree.style().subElementRect(rp.QStyle.SE_ItemViewItemCheckIndicator, opt, tree)
        self.assertTrue(r.isValid() and r.width() > 0, path)
        mods = rp.Qt.NoModifier if mods is None else mods
        if double:                                    # как настоящий двойной щелчок: щелчок, затем «двойное» нажатие
            QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
            QTest.mouseDClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
        else:
            QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
        QAPP.processEvents()

    def test_group_checks_by_mouse(self):
        self.open()
        self.show()
        m = self.p.model
        group = ('Друзья', 'Работа', 'Документы')
        self.p.tree.clearSelection()
        for f in group:
            self.item(f).setSelected(True)
        self.assertEqual(m.drafts, {})
        self.click_check('Работа')                                               # галочка одной из выделенных
        self.assertEqual({k: d['verdict'] for k, d in m.drafts.items()}, {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # одним шагом отмены
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))   # выделение осталось
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Checked for f in group))
        self.click_check('Друзья')                                               # снять - тоже у всей группы
        self.assertEqual(m.drafts, {})
        self.assertEqual(len(m.undo_stack), 2)
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))
        self.click_check('Смешанная')                                            # невыделенная - только она
        self.assertEqual({k: d['verdict'] for k, d in m.drafts.items()}, {'смешанная': N1})
        self.assertEqual(len(m.undo_stack), 3)
        self.assertEqual(sorted(self.p.selected_folders()), sorted(group))         # Qt: щелчок по галочке выделение не меняет
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.click_check('Смешанная')                                            # снова невыделенная - только она
        self.assertEqual(m.drafts, {})
        self.p.undo()                                                            # «Отменить последнее» - шагами
        self.assertEqual(set(m.drafts), {'смешанная'})
        self.p.undo()
        self.p.undo()
        self.assertEqual(set(m.drafts), {'друзья', 'работа', 'документы'})
        self.assertIsNone(self.p.tree.press_sel)                                 # после щелчка не осталось
        self.settle()

    def test_one_disk_direction_has_no_blocks(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Работа', 'Н2'))
        self.open()
        self.plan()
        self.assertEqual(self.p.dest, 'Н2')
        c = self.p.copy_cell
        self.assertEqual(c.blocks, [])
        self.assertFalse(c.blocks_box.isVisibleTo(c))
        self.assertIn('Уже есть на диске', c.body.text())
        self.assertIn('Копировать на диск ', c.body.text())
        h = self.p.where.text()
        self.assertTrue(h.startswith('Диск: '))
        self.assertNotIn('копии', h)
        self.assertNotIn('Копия', self.p.dest_info.text())

    def test_disk_block_states(self):
        import types
        G = 1024 ** 3
        P = types.SimpleNamespace(part_a={}, disk=SRC)
        space = {'HDD45': ('H:', 500 * G, 1000 * G, 4096)}
        cap = sv.capacity({'HDD45': [3, G], 'HDD77': [2, G]}, space, {}, disks=['HDD45', 'HDD77'])
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (5, 4 * G), (2, 3 * G), 'H: Бэкап фото и видео')
        self.assertEqual(st, 'ok')
        self.assertIn('Копия 1 — H: Бэкап фото и видео (HDD45)', t)
        self.assertIn('Копировать <b>1,0 ГБ</b> (3 файла)', t)
        self.assertIn('Уже есть на диске: <b>3,0 ГБ (75 %)</b>', t)
        self.assertIn('помещается: свободно 500,0 ГБ', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (5, 4 * G), None, 'Путешествия')
        self.assertEqual(st, 'unknown')
        self.assertIn('Уже есть на диске: считаю…', t)
        self.assertIn('место не проверено (диск не подключён)', t)
        cap = sv.capacity({'HDD45': [3, 600 * G]}, space, {}, disks=['HDD45', 'HDD77'])
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (5, 4 * G), (0, 0), 'H: Бэкап')
        self.assertEqual(st, 'short')
        self.assertIn('не помещается: нужно', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (5, 4 * G), (5, 4 * G), 'Путешествия')
        self.assertEqual(st, 'none')
        self.assertIn('Копировать нечего — всё отмеченное уже есть на этом диске', t)
        self.assertIn('(100 %)', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (0, 0), None, 'Путешествия')
        self.assertNotIn('Уже есть', t)                                          # отмечено пусто - процента нет
        t, st = rp.disk_block_html(1, SRC, cap['HDD77'], P, (5, 4 * G), None, 'Носитель')
        self.assertIn('Это сам носитель', t)
        # проверка кода (п. 2): «копировать нечего» - единообразно, с местом или «диск не подключён»
        cap = sv.capacity({}, space, {}, disks=['HDD45', 'HDD77'])
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (5, 4 * G), (5, 4 * G), 'H: Бэкап')
        self.assertIn('Копировать нечего — всё отмеченное уже есть на этом диске <span style="color:#2e7d32">'
                      '· свободно 500,0 ГБ</span>', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (5, 4 * G), (5, 4 * G), 'Путешествия')
        self.assertIn(f'Копировать нечего — всё отмеченное уже есть на этом диске <span style="color:{rp.ORANGE}">'
                      '· диск не подключён</span>', t)
        self.assertEqual(st, 'none')

    def test_disk_missing_from_rows(self):
        """Проверка кода (п. 1): диска направления нет в списке дисков - подписи не падают, диск - номером."""
        import types
        d = types.SimpleNamespace(num='Н9', name='Проба', disks=('HDD45', 'HDD99'))
        rows = [dict(disk='HDD45', label='WD - 2 ТБ - Бэкап фото и видео', letter='H:', free_gib=10.0)]
        info = rp.dest_info_html(d, rows)
        self.assertIn('Копия 1 — H: Бэкап фото и видео (HDD45): свободно 10,0 ГБ', info)
        self.assertIn('Копия 2 — Накопитель (HDD99): подключите диск', info)
        h = rp.head_html(d, rows)
        self.assertIn('Накопитель — HDD99', h)
        self.assertEqual(rp.dest_text(d, rows), 'Н9 Проба — H: и HDD99 (две копии)')
        self.assertEqual(rp.disk_ui.disk_place('HDD99'), 'Накопитель')            # строка - через as_row

    def test_blocks_follow_state(self):
        """Проверка кода (п. 6): те же диски - блоки не пересоздаются, но текст и рамка меняются по состоянию."""
        c = self.p.copy_cell
        c.set_blocks([('HDD45', 'не помещается', 'short'), ('HDD77', 'место не проверено', 'unknown')])
        frames = [b[1] for b in c.blocks]
        self.assertIn(rp.BLOCK_LOOK['short'][0], frames[0].styleSheet())
        c.set_blocks([('HDD45', 'помещается', 'ok'), ('HDD77', 'место не проверено', 'unknown')])
        self.assertEqual([b[1] for b in c.blocks], frames)                      # те же рамки
        self.assertIn(rp.BLOCK_LOOK['ok'][0], frames[0].styleSheet())
        self.assertNotIn(rp.BLOCK_LOOK['short'][0], frames[0].styleSheet())
        self.assertEqual(c.block_texts()['HDD45'], 'помещается')
        self.assertEqual(c.block_states(), {'HDD45': 'ok', 'HDD77': 'unknown'})
        c.set_blocks([])
        self.assertEqual(c.blocks, [])
        self.assertFalse(c.blocks_box.isVisibleTo(c))

    def test_group_applied_once(self):
        """Проверка кода (п. 4): групповое действие - ровно один раз (один шаг отмены) и при Ctrl-щелчке по галочке,
        и при двойном щелчке; Ctrl-щелчок по имени - галочки выделенным один раз (нажатие и отпускание)."""
        from PySide6.QtTest import QTest
        from test_app import QAPP
        self.open()
        self.show()
        m, tree = self.p.model, self.p.tree
        group = ('Друзья', 'Работа', 'Документы')
        tree.clearSelection()
        for f in group:
            self.item(f).setSelected(True)
        steps = len(m.undo_stack)
        self.click_check('Работа', rp.Qt.ControlModifier)                       # Ctrl-щелчок по галочке выделенной
        wait(lambda: False, 0.3)
        self.assertEqual(set(m.drafts), {'друзья', 'работа', 'документы'})
        self.assertEqual(len(m.undo_stack), steps + 1)
        self.click_check('Работа', double=True)                                   # двойной щелчок
        wait(lambda: False, 0.3)
        states = {self.item(f).checkState(rp.C_CHECK) for f in group}
        self.assertEqual(len(states), 1)                                         # у всей группы одинаково
        self.assertEqual(len(m.undo_stack), steps + 2)                           # двойной щелчок - одно переключение
        self.assertEqual(set(m.drafts), set())                                   # у всей группы - снято
        self.assertIsNone(tree.press_sel)
        # Ctrl-щелчок по ИМЕНИ ещё одной папки: выделенным ставятся галочки - одним шагом (нажатие + отпускание)
        before = len(m.undo_stack)
        it = self.item('Смешанная')
        tree.scrollToItem(it)
        QAPP.processEvents()
        QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, rp.Qt.ControlModifier,
                         tree.visualItemRect(it).center())
        wait(lambda: len(self.p.selected_folders()) == 4)
        wait(lambda: False, 0.3)
        self.assertEqual(set(m.drafts), {'друзья', 'работа', 'документы', 'смешанная'})
        self.assertEqual(len(m.undo_stack), before + 1)
        self.settle()


class MovedPartialTest(PageBase):
    """Проверка кода (п. 5): папка перенесена на носителе раньше («ПЕРЕНЕСЕНО → 45 и 77»), её файл есть только на
    45 - в ядре «копировать» (недостаёт на 77); «уже есть» по дискам: на 45 - да, на 77 - нет; есть на обоих - в ядре
    «перенесено», в «отмечено» и «уже есть» не входит."""

    def rescan(self, disk, serial, folder, files):
        """Пересканирование папки диска (частичный скан с хешами) и пересборка временной базы."""
        from test_hashbase import make_partial
        make_partial(self.scans, disk, serial, [folder], files, name=f'part_{len(files)}')
        self.quiet(hb.connect)

    def check(self, want_total, want_have):
        self.open()
        P = self.plan()
        cp = P.part_a.get((rz.O_COPY, 'Н1'), (0, 0))
        hv = P.part_a.get((rz.O_HAVE, 'Н1'), (0, 0))
        total = (cp[0] + hv[0], cp[1] + hv[1])
        self.assertEqual(total, want_total)
        have = self.p.model.have_on_disk('Н1')
        self.assertEqual(have, want_have)
        for x in ('HDD45', 'HDD77'):                                             # недостающее = часть Б ядра
            self.assertEqual(P.part_b.get(x, [0, 0])[0], total[0] - have[x][0], x)
        return P

    def test_moved_partial(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        base45 = [('X\\1.jpg', 100, S[1]), ('X\\2.jpg', 200, S[2])]
        base77 = [('Y\\1.jpg', 100, S[1])]
        self.rescan('HDD45', 'AAAA0045', 'X', base45 + [('X\\z.jpg', 300, H[25])])   # z.jpg - только на 45
        self.mark(('Старое', 'Н1'), ('Работа', 'Н1'))
        P = self.check((3, 300 + 20 + 70), {'HDD45': (1, 300), 'HDD77': (0, 0)})
        self.assertEqual(P.part_a.get((rz.O_MOVED, None), (0, 0))[0], 0)
        self.p.model.drafts.clear()
        self.p.choose_disk('HDD45')                                              # уйти с носителя, чтобы перечитать
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.model.disk == 'HDD45'))
        self.settle()
        QThreadPool.globalInstance().waitForDone(20000)                          # окно не читает базу во время сборки
        self.rescan('HDD77', 'AAAA0077', 'Y', base77 + [('Y\\z.jpg', 300, H[25])])   # z.jpg - и на 77
        P = self.check((2, 20 + 70), {'HDD45': (0, 0), 'HDD77': (0, 0)})
        self.assertEqual(P.part_a.get((rz.O_MOVED, None), (0, 0)), [1, 300])


if __name__ == '__main__':
    unittest.main()
