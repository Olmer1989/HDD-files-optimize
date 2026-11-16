"""Страница «Разбор носителя» (логика v3, этап 2, 15.11.2026) без экрана (Qt offscreen) на временных данных.

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
from PySide6.QtCore import QThreadPool                     # noqa: E402
from PySide6.QtWidgets import QDialog                      # noqa: E402

import app                                                 # noqa: E402
import hashbase as hb                                      # noqa: E402
import razbor_page as rp                                   # noqa: E402
import service as sv                                       # noqa: E402
from hb_core import razbor as rz                           # noqa: E402
from test_app import put, wait                             # noqa: E402
from test_hashbase import make_disk, S                     # noqa: E402
from test_logic_v3 import SRC, FILES, V3Base               # noqa: E402

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
        self.open()
        root = self.p.items['']
        names = {root.child(i).text(0) for i in range(root.childCount())}
        self.assertTrue({'Поход 2010', 'Работа', 'Друзья', 'Документы', 'Смешанная', MOVED} <= names, names)
        self.assertIn('режим не выбран', self.to(''))
        self.assertEqual(self.to('Поход 2010'), 'не отмечено')
        self.assertEqual(self.item('Поход 2010').text(rp.C_FILES), '7')
        self.assertEqual(self.item('Поход 2010').text(rp.C_PHOTO), '2')
        # режим «всё - в Семейный архив»: черновик пустого пути, у папок - серым «от режима»
        self.p.mode_dir.setCurrentIndex(self.p.mode_dir.findData(N1))
        self.p.mode_all.setChecked(True)
        self.assertEqual(self.p.model.drafts['']['verdict'], N1)
        self.assertEqual(self.to('Поход 2010'), '• Семейный архив (45 и 77) — от режима')
        it = self.item('Поход 2010')                                             # унаследованное - бледный цвет Н1
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.dir_colors('Н1')[1])
        self.assertTrue(it.text(rp.C_NAME).startswith('• '))                      # не сохранено
        self.assertIn('(от режима всего носителя)', it.toolTip(rp.C_NAME))
        # исключение в подпапке: своя (несохранённая) отметка синим, соседние подпапки - по-прежнему от режима
        self.p.apply(['Поход 2010\\Монтаж'], rp.SKIP)
        self.assertEqual(self.to('Поход 2010\\Монтаж'), '• не копировать')
        it = self.item('Поход 2010\\Монтаж')
        self.assertEqual(it.foreground(rp.C_NAME).color().name(), rp.BLUE.lower())
        self.assertTrue(it.font(rp.C_NAME).strikeOut())                          # «не копировать» - зачёркнуто
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.SKIP_OWN)
        self.assertIn('от режима', self.to('Поход 2010\\Фото'))
        # несколько папок сразу - панелью «Применить к выделенным»
        self.p.tree.clearSelection()
        for f in ('Друзья', 'Работа'):
            self.item(f).setSelected(True)
        self.assertIn('2', self.p.apply_btn.text())
        self.p.apply_box.setCurrentIndex(self.p.apply_box.findData(N2))
        self.p.apply_selected()
        self.assertEqual({self.p.model.drafts[k]['verdict'] for k in ('друзья', 'работа')}, {N2})
        self.assertEqual(self.to('Друзья\\Наши'), '• Работа (91) — от «Друзья»')
        # служебная папка: отметить нельзя, внутри - «уже перенесено», режим туда не наследуется
        self.assertIn('служебная папка', self.to(MOVED))
        self.assertFalse(self.p.model.markable(MOVED))
        self.assertEqual(self.p.model.set_mark([MOVED], N2), 0)
        self.assertEqual(self.to(MOVED + '\\Старое'), 'уже перенесено')
        # отменить последнее - пакет из двух папок уходит целиком
        self.p.undo()
        self.assertNotIn('друзья', self.p.model.drafts)
        self.assertNotIn('работа', self.p.model.drafts)
        self.assertIn('поход 2010\\монтаж', self.p.model.drafts)
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
        """Этап 5, п. 4: «Перейти к написанию команды…» - в «Куда» и «Всё — в» отмеченное в «Обзоре» направление
        (несколько - первое по номеру), а не первое в списке; сохранённый режим носителя не меняется."""
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.open()
        self.assertEqual(self.p.apply_box.currentData(), N2)
        self.assertEqual(self.p.mode_dir.currentData(), N2)
        self.assertIn('Копирование: Н2 Работа — диск 91', self.p.where.text())
        self.assertEqual(self.p.model.drafts, {})                                # ничего не отмечено молча
        self.p.apply_box.setCurrentIndex(0)                                      # владелец выбрал другое
        dp.save_choice(['Н2', 'Н1'])                                             # снова из «Обзора»: по номеру - Н1
        self.p.use_choice()
        self.assertEqual(self.p.apply_box.currentData(), N1)
        self.mark(('', 'Н2'))                                                    # сохранённый режим - «всё в Н2»
        dp.save_choice(['Н1'])
        self.p.load_disk(SRC, keep=False)
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.loading is None))
        self.p.use_choice()
        self.assertEqual(self.p.apply_box.currentData(), N1)
        self.assertEqual(self.p.mode_dir.currentData(), N2)                      # сохранённое не перебито
        self.assertIn('Сохранённый режим этого носителя', self.p.mode_note.text())
        self.settle()


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
        self.p.mode_dir.setCurrentIndex(self.p.mode_dir.findData(N1))
        self.p.mode_all.setChecked(True)
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
        # «ничего, кроме отмеченных»: всё - «не копировать», кроме уже перенесённого; писать нечего
        self.p.mode_none.setChecked(True)
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
        self.p.mode_all.setChecked(True)
        self.p.changed()                                    # правка во время расчёта: ревизия растёт сразу
        self.assertNotEqual(self.p.plan_rev, self.p.rev)
        self.settle()
        self.assertEqual(self.p.plan_rev, self.p.rev)


class SaveTest(PageBase):
    def rows(self):
        return hb.DECISIONS.read_text(encoding='utf-8-sig').splitlines() if hb.DECISIONS.exists() else []

    def test_save_marks_batch_and_prune(self):
        self.open()
        self.p.mode_all.setChecked(True)
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
        self.p.mode_all.setChecked(True)
        self.p.apply(['Работа'], N2)
        self.p.prepare(['Н1', 'Н2'])         # черновик есть - сначала сохранить (предпросмотр), затем задания
        self.assertTrue(wait(lambda: self.made() and not self.p.writing, 60), self.asked)
        self.assertTrue(any('Задания строятся только из сохранённых' in x for x in self.asked), self.asked)
        self.assertTrue(any(f'{SRC} — Работа — Работа' in x for x in self.dialogs), self.dialogs)
        self.assertIn(f'{SRC} — Работа — Работа', self.made())
        self.assertTrue(list(hb.RAZBORY.glob(f'{SRC} *.json')))
        self.assertIs(self.w.stack.currentWidget(), self.w.page('Задания'))
        self.assertTrue(any(x.startswith('Создано заданий') for x in self.asked), self.asked)

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


class DropCellsTest(PageBase):
    """Этап 6: перетаскивание в ячейки, цвета и подсказки дерева, содержимое ячеек, «Куда»."""

    def test_drop_marks_and_child_mark_is_stronger(self):
        self.mark(('Поход 2010\\Монтаж', 'Н2'))
        self.open()
        m = self.p.model
        self.assertEqual(set(self.p.cells), {'Н1', 'Н2', SKIP_KEY, INHERIT_KEY})     # «Обзор» пуст: все с дисками
        # мышью: данные перетаскивания из дерева - только отмечаемые папки (не весь носитель, не служебная)
        md = self.p.tree.mimeData([self.p.items[''], self.item('Поход 2010'), self.item(MOVED)])
        self.assertEqual(rp.mime_folders(md), ['Поход 2010'])
        self.assertFalse(self.p.items[''].flags() & rp.Qt.ItemIsDragEnabled)
        # сброс родителя в «Не копировать»: своя отметка подпапки не стирается
        self.assertEqual(self.p.cells[SKIP_KEY].drop_folders(['Поход 2010']), 1)
        self.assertEqual(m.drafts['поход 2010']['verdict'], rp.SKIP)
        self.assertEqual(m.route['Поход 2010\\Монтаж'].num, 'Н2')
        self.assertEqual(m.route['Поход 2010\\Фото'].state, rp.R_SKIP)
        # цвета и подсказки: своя - насыщенный цвет направления, от папки - бледный серый и зачёркнуто
        it = self.item('Поход 2010\\Монтаж')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.dir_colors('Н2')[0])
        self.assertEqual(it.toolTip(rp.C_NAME), 'Н2 Работа (91) (своя отметка).')
        it = self.item('Поход 2010\\Фото')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.SKIP_INH)
        self.assertTrue(it.font(rp.C_NAME).strikeOut())
        self.assertIn('(от папки «Поход 2010»)', it.toolTip(rp.C_NAME))
        self.assertIn('НЕ СОХРАНЕНО', it.toolTip(rp.C_NAME))
        # сброс в ячейку направления и снятие своей отметки ячейкой «Снять свою отметку»
        self.p.cells['Н1'].drop_folders(['Поход 2010'])
        self.assertEqual(m.route['Поход 2010\\Фото'].num, 'Н1')
        self.assertEqual(self.item('Поход 2010\\Фото').background(rp.C_NAME).color().name(), rp.dir_colors('Н1')[1])
        self.p.cells[INHERIT_KEY].drop_folders(['Поход 2010\\Монтаж'])
        self.assertEqual(m.drafts['поход 2010\\монтаж']['verdict'], rp.INHERIT)
        self.assertEqual(m.route['Поход 2010\\Монтаж'].num, 'Н1')
        # весь носитель и служебная папка не принимаются
        self.assertEqual(self.p.cells['Н2'].drop_folders(['', MOVED]), 0)
        self.p.undo()
        self.assertEqual(m.route['Поход 2010\\Монтаж'].num, 'Н2')
        self.assertEqual(self.asked, [])

    def test_cells_content_and_where(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        self.open()
        self.assertEqual(list(self.p.cells), ['Н1', 'Н2', SKIP_KEY, INHERIT_KEY])  # Н2 - из-за отметок носителя
        self.assertIn('Копирование: Н1 Семейный архив — диски 45 и 77 (два задания)', self.p.where.text())
        P = self.plan()
        c1 = self.p.cells['Н1'].body.text()
        have = P.part_a[(rz.O_HAVE, 'Н1')]
        self.assertIn(f'Уже есть на всех дисках направления: <b>{rp.gb(have[1])} ГБ', c1)
        self.assertIn('<b>на 45</b>', c1)
        self.assertIn('<b>на 77</b>', c1)
        self.assertIn('диск не подключён — место не проверено', c1)
        self.assertEqual(self.p.cells['Н1'].state, 'unknown')
        self.assertIn('Не отмечено в «Обзоре»', self.p.cells['Н2'].body.text())
        self.assertIn('Отмечено: <b>', self.p.cells[SKIP_KEY].body.text())
        self.assertTrue(self.p.cells['Н1'].btn.isEnabled())
        self.assertTrue(self.p.tasks_btn.isEnabled())
        dp.save_choice([])
        self.p.use_choice()
        self.assertFalse(self.p.tasks_btn.isEnabled())                          # пустой «Обзор» - общая кнопка нет
        self.assertIn('не отмечено ни одного направления', self.p.where.text())


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
        """Не помещается на 45 (на 77 место неизвестно) - ячейка Н1 красная, её кнопка неактивна; общая подготовка
        создаёт задания только Н2, у Н1 - ни на 45, ни на 77."""
        import directions_page as dp
        dp.save_choice(['Н1', 'Н2'])
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        space = {'HDD45': ('F:', 1000, 10 ** 12, 4096)}
        with mock.patch.object(sv, 'disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}), \
                mock.patch.object(sv, 'toc_check', lambda *a, **k: TOC_OK):
            self.open()
            self.plan()
            c = self.p.cells['Н1']
            self.assertEqual(c.state, 'short')
            self.assertIn('не помещается', c.body.text())
            self.assertFalse(c.btn.isEnabled())
            self.assertTrue(self.p.cells['Н2'].btn.isEnabled())
            self.assertIn('Не помещаются (заданий не будет): Н1', self.p.tasks_btn.toolTip())
            self.p.prepare()
            self.assertTrue(wait(lambda: not self.p.writing and hb.TASKS.exists() and
                                 any(x.name.startswith(SRC) for x in hb.TASKS.iterdir()), 60), self.asked)
        made = sorted(x.name for x in hb.TASKS.iterdir() if x.name.startswith(SRC))
        self.assertEqual(made, [f'{SRC} — Работа — Работа'])
        self.assertIn('Семейный архив не помещается', self.dialogs[0])


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
        html_, state = rp.dir_cell_html(d, P, cap, True, str)
        self.assertIn('<b>на 45</b>: копировать', html_)
        self.assertIn('помещается', html_)
        self.assertIn('<b>на 77</b>: копировать', html_)
        self.assertIn('диск не подключён — место не проверено', html_)
        self.assertEqual(state, 'unknown')
        cap2 = sv.capacity({}, space, {}, disks=['HDD45', 'HDD77'])
        html_, state = rp.dir_cell_html(d, P, cap2, True, str)
        self.assertIn('<b>на 45</b>: копировать нечего · свободно 500,0 ГБ', html_)
        self.assertIn('<b>на 77</b>: копировать нечего', html_)
        self.assertNotIn('место не проверено', html_)
        self.assertEqual(state, 'ok')
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


SKIP_KEY, INHERIT_KEY = rp.SKIP, rp.INHERIT


if __name__ == '__main__':
    unittest.main()
