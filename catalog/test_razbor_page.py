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
                             and not self.p.writing and not self.p.saving and not self.p.save_timer.isActive()
                             and self.p.model.have is not None, 60), self.p.sum_state.text())

    def own(self, path):
        """Своя действующая отметка папки: черновик или уже сохранённая (этап 16: отметки сохраняются сразу)."""
        return self.p.model.own_verdict(path.lower())

    def owns(self):
        """Все свои отметки носителя (черновик поверх сохранённых), кроме «как у родителя»: {путь: отметка}."""
        m = self.p.model
        keys = set(m.drafts) | set(m.saved_ms.by_key) | set(m.inflight)
        return {k: m.own_verdict(k) for k in keys if m.own_verdict(k) != rp.INHERIT}

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
        self.assertTrue(ch.data(rp.C_CHECK, rp.GRAY_ROLE))                        # бледная (вместе с родителем)
        self.assertTrue(ch.flags() & rp.Qt.ItemIsUserCheckable)                   # этап 17: но активная
        self.assertEqual(ch.foreground(rp.C_NAME).color().name(), rp.PALE)
        self.assertEqual(ch.background(rp.C_NAME).color().name(), rp.SEL_BG)     # один зелёный фон
        self.assertIn('вместе с родительской', ch.toolTip(rp.C_NAME))
        self.assertIn('Снимите галочку', ch.toolTip(rp.C_NAME))
        self.assertEqual(self.p.toggle(['Поход 2010\\Фото'], False), 1)          # этап 17: снять = исключить
        self.assertEqual(self.p.model.drafts['поход 2010\\фото']['verdict'], rp.SKIP)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)   # исключение внутри
        self.assertEqual(self.p.toggle(['Поход 2010\\Фото'], True), 1)           # поставить = снять исключение
        self.assertNotIn('поход 2010\\фото', self.p.model.drafts)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.Checked)
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
        self.assertFalse(self.p.dest_box.isVisibleTo(self.p))                 # этап 16: строки выбора диска нет
        self.assertTrue(self.p.where.text().startswith('Диск назначения: Накопитель — HDD91'), self.p.where.text())
        self.assertNotIn('Работа', self.p.where.text())                        # имя направления - в ячейке, не в плашке
        self.assertNotIn('отмечено ещё', self.p.where.text())
        self.assertEqual(self.p.model.drafts, {})                                # ничего не отмечено молча
        self.p.set_dest('Н1')                                                    # владелец выбрал другое
        self.assertEqual(self.p.dest, 'Н1')
        dp.save_choice(['Н2', 'Н1'])                                             # снова из «Обзора»: по номеру - Н1
        self.p.set_dest('Н2')
        self.p.use_choice()
        self.assertEqual(self.p.dest, 'Н1')
        self.assertIn('В «Обзоре» отмечено ещё: Н2 Работа', self.p.where.text())   # первое по номеру - и сказано
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
        h = rp.head_html(d1, rows, {'HDD45': ('H:', 421 * 1024 ** 3, 2 * 10 ** 12, 4096)})
        # этап 16: «Диск назначения: H: Бэкап фото и видео — HDD45, 2 ТБ · свободно …» - диск вместо направления
        self.assertTrue(h.startswith('Диск назначения — две копии:<br>'), h)
        self.assertNotIn('Семейный архив', h)
        lines = h.split('<br>')
        self.assertEqual(len(lines), 3)                                        # заголовок, два диска
        self.assertTrue(lines[1].endswith('H: Бэкап фото и видео — HDD45, 2 ТБ <span style="color:#33691e">· свободно '
                                          '421,0 ГБ</span>'), lines[1])
        self.assertIn('Путешествия — HDD77 <span', lines[2])
        self.assertIn('не подключён', lines[2])                                 # плашка - у своего диска
        self.assertNotIn('не подключён', lines[1])
        d3 = types.SimpleNamespace(num='Н3', name='Фильмы', disks=('HDD55',))
        h = rp.head_html(d3, [dict(disk='HDD55', label='WD20 - 2 ТБ - My Book', letter='I:')],
                         {'HDD55': ('I:', 421 * 1024 ** 3, 16000900165632, 4096)})
        self.assertEqual(h, 'Диск назначения: I: My Book — HDD55, 16 ТБ <span style="color:#33691e">· свободно 421,0 ГБ'
                            '</span>')
        off = rp.head_html(d3, [dict(disk='HDD55', label='WD20 - 2 ТБ - My Book', letter='')])
        self.assertTrue(off.startswith('Диск назначения: My Book — HDD55 <span'), off)   # объём не известен - нет
        self.assertIn('не подключён', off)
        self.assertNotIn('Фильмы', h + off)
        self.assertEqual(rp.tb_text(500107862016), '500 ГБ')
        self.assertEqual(rp.tb_text(4000787030016), '4 ТБ')
        self.assertEqual(rp.tb_text(1500301910016), '1,5 ТБ')
        o = rp.head_html(d3, [dict(disk='HDD55', label='', letter='I:')], others=[types.SimpleNamespace(num='Н7',
                                                                                                         name='Ещё')])
        self.assertIn('отмечено ещё: Н7 Ещё', o)
        for x in (rp.carrier_text(rows[0]), rp.dest_text(d1, rows)):
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
        self.assertEqual(self.owns(), {'поход 2010': N1, 'работа': N1})
        self.item('Поход 2010\\Фото')
        self.check_consistent()
        # «Все папки»: весь носитель - в Н1
        self.p.mode_every.setChecked(True)
        self.assertEqual(self.own(''), N1)
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
        self.assertEqual(self.own('друзья'), rp.SKIP)
        self.assertEqual(self.p.items['Друзья\\Наши'].checkState(rp.C_CHECK), rp.Qt.Checked)     # исключена с родителем
        self.assertTrue(self.p.items['Друзья\\Наши'].data(rp.C_CHECK, rp.GRAY_ROLE))
        self.check_consistent()
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], 2)                     # a.jpg и b.jpg
        self.assertIn('Отмечено: весь носитель, кроме 1 папки', self.p.copy_cell.body.text())
        self.p.items['Друзья'].setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # снять исключение
        self.assertEqual(self.own('друзья'), rp.INHERIT)
        self.p.toggle(['Друзья'], True)
        # «Все папки» снимает исключения одним шагом отмены
        self.p.mode_every.setChecked(True)
        self.assertEqual(self.own('друзья'), rp.INHERIT)
        self.p.undo()
        self.assertEqual(self.own('друзья'), rp.SKIP)
        # обратно «Только выбранные»: отметки носителя до «Все папки» не было - «ничего, кроме отмеченных»; свои Н1
        self.p.mode_only.setChecked(True)
        self.assertEqual(self.own(''), rp.SKIP)
        self.assertEqual(self.own('поход 2010'), N1)
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
        self.p.mode_except.setChecked(True)                                      # корень - Н1
        self.assertEqual(self.own(''), N1)
        self.settle()                                                            # этап 16: Н1 уже записано в таблицу
        self.p.mode_only.setChecked(True)                                        # вернуть прежнее «всё в Н2»
        self.assertEqual(self.own(''), sv.directions()['Н2'].verdict())
        self.assertEqual(self.p.model.route[''].num, 'Н2')
        self.settle()
        self.assertEqual(self.p.model.saved_ms.get('').num, 'Н2')

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
        self.assertEqual(self.owns(), {})
        self.p.tree.multi(Ev(rp.Qt.ControlModifier))                             # Ctrl-щелчок - всем сразу
        self.assertTrue(wait(lambda: len(self.owns()) == 3))
        self.assertEqual(self.owns(), {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # один шаг отмены
        self.assertTrue(wait(lambda: len(self.p.selected_folders()) == 3))       # выделение осталось
        self.item('Документы').setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # этап 12: у всей выделенной группы
        self.assertEqual(self.owns(), {})
        self.assertEqual(len(m.undo_stack), 2)
        self.p.check_selected()                                                  # повтор: уже отмеченные не трогаются
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
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
        self.assertIn('Посчитано в', self.p.sum_state.text())
        # «Только выбранные» = «ничего, кроме отмеченных»: всё - «не копировать», кроме уже перенесённого
        self.p.mode_only.setChecked(True)
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], len(FILES) - 1)
        self.assertEqual(P.part_a[(rz.O_MOVED, None)][0], 1)
        self.assertIn('Писать на диски нечего', self.p.summary.toPlainText())
        self.p.apply(['Друзья'], N2)
        P = self.plan()
        self.assertEqual(dict(P.part_b), {'HDD91': [2, 185]})
        self.assertEqual(self.own(''), rp.SKIP)

    def test_stale_answer_is_not_shown(self):
        self.open()
        self.p.mode_every.setChecked(True)
        self.p.changed()                                    # правка во время расчёта: ревизия растёт сразу
        self.assertNotEqual(self.p.plan_rev, self.p.rev)
        self.settle()
        self.assertEqual(self.p.plan_rev, self.p.rev)


class SaveTest(PageBase):
    """Этап 16 (решение владельца): кнопки «Сохранить отметки» нет - отметка пишется в решения.tsv сразу, без вопроса;
    «Отменить последнее» - новой строкой с прежней отметкой."""

    def rows(self):
        return hb.DECISIONS.read_text(encoding='utf-8-sig').splitlines() if hb.DECISIONS.exists() else []

    def test_marks_are_saved_at_once_and_undo_writes_back(self):
        self.open()
        for gone in ('save_btn', 'discard_btn'):
            self.assertFalse(hasattr(self.p, gone), gone)
        before = self.rows()
        real = sv.add_marks_batch
        with mock.patch.object(sv, 'add_marks_batch', side_effect=real) as spy:
            self.p.mode_except.setChecked(True)
            self.p.apply(['Поход 2010\\Монтаж', 'Друзья'], rp.SKIP)          # одно событие - один пакет
            self.settle()
            self.p.apply(['Работа'], N2)
            self.settle()
        self.assertEqual(spy.call_count, 2)
        new = self.rows()[len(before):]
        self.assertEqual(len(new), 4, new)
        self.assertTrue(any(f'{SRC}\t\t{N1}' in x for x in new), new)
        self.assertEqual(self.dialogs, [])                                      # без окна «Было → станет»
        self.assertEqual(self.p.model.drafts, {})
        self.assertEqual(self.to('Работа'), 'Работа (91)')                      # своя сохранённая - без «•»
        self.assertEqual(len(self.p.model.undo_stack), 3)
        self.p.undo()                                                            # «Работа» - снова как у родителя
        self.settle()
        last = self.rows()[-1]
        self.assertTrue(last.startswith(f'{SRC}\tРабота\tкак у родителя'), last)
        self.assertIsNone(self.p.model.saved_ms.get('Работа'))
        self.p.undo()                                                            # исключения сняты (шаг 2)
        self.settle()
        self.assertIsNone(self.p.model.saved_ms.get('Друзья'))
        self.assertEqual(self.p.model.saved_ms.get('').num, 'Н1')               # режим носителя ещё стоит
        self.p.undo()                                                            # шаг 1 - режим «Все, кроме»
        self.settle()
        self.assertIsNone(self.p.model.saved_ms.get(''))
        self.assertFalse(self.p.undo_btn.isEnabled())                            # отменять больше нечего
        self.assertEqual(self.asked, [])

    def test_edit_while_writing_is_kept(self):
        """Правка во время записи сравнивается с пакетом, который пишется (Model.inflight), и пишется следующим."""
        self.open()
        self.p.apply(['Работа'], N2)
        self.p.save_timer.stop()
        self.p.autosave()                                                        # пакет «Работа → Н2» в пути
        self.assertTrue(self.p.saving)
        self.p.apply(['Работа'], rp.INHERIT)                                     # владелец передумал до конца записи
        self.assertEqual(self.p.model.drafts['работа']['verdict'], rp.INHERIT)
        self.settle()
        self.assertIsNone(self.p.model.saved_ms.get('Работа'))                  # последнее слово - «как у родителя»
        self.assertEqual(self.p.model.drafts, {})

    def test_refused_write_is_reported_and_forgotten(self):
        self.open()
        with mock.patch.object(sv, 'add_marks_batch', side_effect=sv.Refused('проба отказа')):
            self.p.apply(['Работа'], N2)
            self.settle()
        self.assertEqual(self.p.model.drafts, {})                               # на экране - сохранённое
        self.assertIsNone(self.p.model.saved_ms.get('Работа'))
        self.assertTrue(any('проба отказа' in x for x in self.asked), self.asked)

    def test_close_and_disk_change_write_drafts_first(self):
        self.open()
        self.p.apply(['Работа'], N2)
        self.p.save_timer.stop()                                                 # запись ещё не началась
        self.p.disk_box.setCurrentText('HDD90')                                 # смена носителя - сначала запись
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.model.disk == 'HDD90'))
        self.assertTrue(any(f'{SRC}\tРабота\t{N2}' in x for x in self.rows()), self.rows())
        self.settle()
        self.p.apply(['A'], N2)
        self.p.save_timer.stop()
        with mock.patch.object(sv, 'add_marks_batch', side_effect=sv.Refused('проба отказа')):
            self.answer = rp.QMessageBox.No
            self.assertFalse(self.w.close())                                    # не записалось - окно не закрылось
        self.assertTrue(any('Отметки не сохранились: проба отказа' in x for x in self.asked), self.asked)
        self.answer = rp.QMessageBox.Yes
        self.p.model.drafts.clear()


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
        self.p.prepare(['Н1', 'Н2'])         # черновик есть - сначала записывается (этап 16: без вопроса), затем задания
        self.assertTrue(wait(lambda: self.made() and not self.p.writing, 60), self.asked)
        self.assertFalse(any('несохранённ' in x for x in self.asked), self.asked)
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
        self.assertEqual(self.owns(), {})
        self.click_check('Работа')                                               # галочка одной из выделенных
        self.assertEqual(self.owns(), {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # одним шагом отмены
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))   # выделение осталось
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Checked for f in group))
        self.click_check('Друзья')                                               # снять - тоже у всей группы
        self.assertEqual(self.owns(), {})
        self.assertEqual(len(m.undo_stack), 2)
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))
        self.click_check('Смешанная')                                            # невыделенная - только она
        self.assertEqual(self.owns(), {'смешанная': N1})
        self.assertEqual(len(m.undo_stack), 3)
        self.assertEqual(sorted(self.p.selected_folders()), sorted(group))         # Qt: щелчок по галочке выделение не меняет
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.click_check('Смешанная')                                            # снова невыделенная - только она
        self.assertEqual(self.owns(), {})
        self.p.undo()                                                            # «Отменить последнее» - шагами
        self.assertEqual(set(self.owns()), {'смешанная'})
        self.p.undo()
        self.p.undo()
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
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
        self.assertTrue(h.startswith('Диск назначения: '))
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
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
        self.assertEqual(len(m.undo_stack), steps + 1)
        self.click_check('Работа', double=True)                                   # двойной щелчок
        wait(lambda: False, 0.3)
        states = {self.item(f).checkState(rp.C_CHECK) for f in group}
        self.assertEqual(len(states), 1)                                         # у всей группы одинаково
        self.assertEqual(len(m.undo_stack), steps + 2)                           # двойной щелчок - одно переключение
        self.assertEqual(set(self.owns()), set())                                   # у всей группы - снято
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
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы', 'смешанная'})
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



class CopiedRootMarksTest(V3Base):
    """Этап 13: «Скопировано на …» (из журнала перемещения) и папки внутри можно отметить для ДРУГОГО направления;
    отметка - по нынешнему пути, действует только там; отметка носителя и исходные отметки внутрь не проникают."""
    ROOT = 'Скопировано на Работа (91)'

    def setUp(self):
        super().setUp()
        os.utime(next(self.scans.glob('HDD60 - тест/*')) / 'inventory.sqlite', (1580000000, 1580000000))
        t = self.out / 'Перенос HDD60'
        t.mkdir()
        (t / 'тома.tsv').write_text('HDD60\tAAAA0060\n', encoding='utf-8')
        (t / 'Журнал перемещения 2025-01-01 00-00-00.tsv').write_text(
            'время\tрезультат\tразмер\tsha-256\tоткуда\tкуда\n'
            f'10:00\tперемещён\t70\t{H[21]}\tK:\\Работа\\схема.jpg\tK:\\{self.ROOT}\\Работа\\схема.jpg\n',
            encoding='utf-8-sig')
        self.quiet(hb.connect)
        self.mark(('', 'Н1'), ('Работа', 'Н2'))

    def test_marks_inside_copied_root(self):
        R = self.ROOT
        m = rp.Model(sv.razbor_tree(SRC))
        self.assertIn(R, m.roots)
        self.assertFalse(m.is_service(R))
        self.assertTrue(m.markable(R))
        self.assertTrue(m.is_service(MOVED))                                 # старая «ПЕРЕНЕСЕНО» - по-прежнему нет
        # без своей отметки - «уже перенесено»: ни отметка носителя (Н1), ни исходная «Работа» (Н2) не проникают
        self.assertEqual((m.route[R].state, m.route[R + '\\Работа'].state), (rp.R_NONE, rp.R_NONE))
        self.assertEqual(m.look(R + '\\Работа')['kind'], 'moved')
        ck = m.check(R, 'Н1', 'only')
        self.assertEqual((ck['on'], ck['checkable']), (False, True))
        # галочка всей служебной папки для Н1 - отметка по нынешнему пути; подпапка - вместе с ней (серая)
        pairs = m.include_pairs([R], 'Н1')
        self.assertEqual(pairs, [(R, sv.directions()['Н1'].verdict())])
        m.set_marks(pairs)
        self.assertEqual(list(m.drafts), [R.lower()])
        self.assertEqual(m.drafts[R.lower()]['path'], R)
        r = m.route[R + '\\Работа']
        self.assertEqual((r.state, r.num), (rp.R_DIR, 'Н1'))
        self.assertTrue(rz.is_second(r, m.roots))
        self.assertIn('ещё одна копия', m.look(R + '\\Работа')['tip'])
        self.assertTrue(m.check(R + '\\Работа', 'Н1', 'only')['gray'])
        self.assertEqual(m.route['Работа'].num, 'Н2')                        # исходная папка - не задета
        # запись и ядро: отметка хранится нынешним путём, ядро считает так же, как окно
        sv.add_marks_batch(SRC, m.batch()[0])
        P = sv._plan(SRC)
        self.assertEqual(P.errors, [])
        self.assertEqual(P.part_a[(rz.O_COPY, 'Н1')][1] >= 70, True)          # схема (нет на 45 и 77) - копировать
        groups = {g['folder']: g for g in rz.group_states(P)}
        self.assertEqual(groups[R]['num'], 'Н1')
        dirs = sv.directions()
        ms = hb.MarkSet.build(hb.mark_rows(SRC, hb.table_bytes(hb.DECISIONS)), dirs)
        self.assertEqual(sv.folder_mark(R + '\\Работа', ms, dirs, m.roots)['text'], 'Н1 Семейный архив')
        self.assertEqual(sv.folder_mark(R, ms, dirs, m.roots)['own'], True)


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
                         ['Папка', 'Имя', 'Тип', 'Размер', 'Дата', 'Хеш', 'Почему'])
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
        self.assertEqual(m.data(m.index(0, 0)), '(корень носителя)')
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
        self.assertEqual(m.export_rows()[0][:2], ['X', 'c.doc'])
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
        with mock.patch.object(fw, 'XLSX_MAX', 1), self.assertRaises(sv.Refused):
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
        self.fwp = [mock.patch.object(fw.QMessageBox, 'information', lambda *a, **k: self.fw_asked.append(a[2])),
                    mock.patch.object(fw.QMessageBox, 'question',
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
        with mock.patch.object(self.fw.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out), '')):
            w.save_excel()
        self.assertTrue(wait(lambda: out.exists() and w.state.text().startswith('Сохранено'), 30), w.state.text())
        ws = load_workbook(out).active
        self.assertEqual([c.value for c in next(ws.iter_rows())][:3], ['Папка', 'Имя', 'Тип'])
        self.assertEqual(ws.max_row, 2)
        out2 = out.with_suffix('.csv')
        with mock.patch.object(self.fw, 'XLSX_MAX', 0), \
                mock.patch.object(self.fw.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out2), '')):
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
        with mock.patch.object(sv, 'disk_letter', side_effect=sv.Refused('HDD60 не подключён: подключите диск')):
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
        with mock.patch.object(sv, 'disk_letter', lambda d: str(root)), \
                mock.patch.object(self.fw.subprocess, 'Popen', lambda cmd, *a, **k: calls.append(cmd)):
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
        with mock.patch.object(sv, 'contested_count', lambda d, f='': dict(total=0, carrier=0, copies=0)):
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


class CodeReview16UiTest(PageBase):
    """Этап 16, замечания критиков по коду окна: число спорных не посчитано - без ложного числа; пустые «Почему» и
    «Где копия» сортируются; строки Excel готовятся в фоне из снимка; выделены только файлы корня - кнопка неактивна."""

    def test_contested_count_error_has_no_false_number(self):
        self.open()
        with mock.patch.object(sv, 'contested_count', side_effect=sv.Refused('проба')):
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
        with mock.patch.object(sv, 'add_marks_batch', slow), mock.patch.object(rp, 'FLUSH_WAIT_MS', 200):
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
        with mock.patch.object(sv, 'razbor_tree', once):
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
        with mock.patch.object(sv, 'add_marks_batch', boom):
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
