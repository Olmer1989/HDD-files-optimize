"""«Разбор носителя»: «Без хеша» только для того, что пойдёт на диск (17.11.2026, решение владельца).

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_nohash
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях


class NohashCellTest(PageBase):
    def ready(self):
        self.settle()
        self.assertTrue(wait(lambda: self.p.nohash_result() is not None, 60), self.p.copy_cell.nohash.text())
        return self.p.nohash_result()

    def test_scan_only_these_folders_and_types(self):
        """«Поход 2010» → 45 и 77: без хеша только описание.doc (документ рядом с фото) - кнопка «Начать копирование…»
        недоступна, «Посчитать хеш (1)» открывает окно с этой папкой и только типом «документы»."""
        self.open()
        self.p.apply(['Поход 2010'], N1)
        nh = self.ready()
        self.assertEqual((nh['n'], nh['folders'], nh['cats']), (1, ['Поход 2010'], [hb.CAT_DOC]))
        cell = self.p.copy_cell
        text = cell.nohash.text()
        self.assertIn(f'1. Посчитать хеш на {SRC} — ', text)
        self.assertIn('У 1 из 4 файлов для копирования нет хеша', text)
        self.assertFalse(self.p.tasks_btn.isEnabled())
        self.assertIn('Сначала хеш', self.p.tasks_btn.toolTip())
        self.assertTrue(cell.scan_btn.isVisibleTo(cell) and cell.scan_btn.isEnabled())
        self.assertEqual(cell.scan_btn.text(), 'Посчитать (1)')
        made = []

        class FakeDlg:
            def __init__(self, win, disk, nh, target, check, list_html, show):
                made.append((disk, list(nh['folders']), nh['cats']))
                self.args = check()
                self.running = False
                from PySide6.QtCore import QObject, Signal

                class S(QObject):
                    finished = Signal(int)
                self.s = S()
                self.finished = self.s.finished

            def show(self):
                pass
        with mock.patch('ui.razbor.dialog_hash.HashDialog', FakeDlg):          # своё окно (18.11.2026)
            cell.scan_btn.click()
        self.assertEqual(made, [(SRC, ['Поход 2010'], [hb.CAT_DOC])])
        self.assertEqual(self.p.win.rescan.args[:2], (SRC, self.p.dest))               # повторная проверка - то направление
        dlg = self.p.nohash_link('nh-list:')
        self.assertIn('Поход 2010\\описание.doc', dlg.text.toPlainText())
        dlg.close()

    def test_all_hashed_is_green_and_tasks_allowed(self):
        self.open()
        self.p.apply(['Друзья'], N1)
        nh = self.ready()
        self.assertEqual(nh['n'], 0)
        self.assertIn('✓ 1. Хеш есть у всех файлов для копирования', self.p.copy_cell.nohash.text())
        self.assertFalse(self.p.copy_cell.wait.isVisibleTo(self.p.copy_cell))   # подписи «после шага 1» нет
        self.assertFalse(self.p.copy_cell.scan_btn.isVisibleTo(self.p.copy_cell))
        self.assertTrue(self.p.tasks_btn.isEnabled())

    def test_kinds_tags_and_edit(self):
        """«Что копировать:» плашками (как в карточке) и «Изменить…» - окно карточки (DirectionsSection.edit); после
        «Сохранить» страница пересчитывается, после «Отмена» - нет."""
        import directions_section
        self.open()
        self.p.apply(['Друзья'], N1)
        self.ready()
        k = self.p.copy_cell.kinds
        self.assertTrue(k.isVisibleTo(self.p.copy_cell))
        self.assertEqual(k.tags, ['Фото', 'Видео', 'Документы — только рядом с фото и видео'])
        self.assertEqual(k.note.text(), 'Настройка А1 — общая для всех носителей; уже созданные задания не меняются.')
        self.assertEqual(k.edit_btn.text(), 'Изменить…')
        self.assertEqual(rp.SKIP_TEXT, 'Не копируются (другой тип)')
        for answer, refreshed in ((0, 0), (1, 1)):
            with mock.patch.object(directions_section.DirectionsSection, 'edit', return_value=answer) as ed, \
                    mock.patch.object(type(self.p), 'refresh') as rf:
                k.edit_btn.click()
            ed.assert_called_once_with(self.p.dest)
            self.assertEqual(rf.call_count, refreshed)

    def test_step2_shown_only_with_namesakes(self):
        """Шаг 2 (по желанию) - только когда на диске назначения есть файлы с тем же именем и размером без хеша; кнопка
        делает то же, что прежняя ссылка «отсканировать на H:»."""
        self.open()
        self.p.apply(['Друзья'], N1)
        self.ready()
        c = self.p.copy_cell
        self.assertTrue(c.prep.isVisibleTo(c))
        self.assertEqual(c.prep.step_texts(), {})                              # таких файлов нет - шага 2 нет
        res = dict(self.p.nohash_result(), copies={'HDD45': dict(k=3, folders=['F'], root=0, cats=[], sample=['F\\a'])})
        self.p.got_nohash(self.p.nh['key'], ('ok', res))
        html_, btn = c.prep.step_texts()['HDD45']
        self.assertIn('2. Посчитать хеш у файлов на HDD45 с тем же именем и размером', html_)
        self.assertIn('На HDD45 лежат 3 файла', html_)
        self.assertEqual(btn, 'Посчитать хеш на HDD45 (3)')
        with mock.patch.object(type(self.p), 'rescan') as rs:
            c.prep.steps[0][3].click()
        rs.assert_called_once_with('HDD45', ['F'], None)
        dlg = self.p.nohash_link('nh-clist:HDD45')
        self.assertIn('F\\a', dlg.text.toPlainText())
        dlg.close()

    def test_answer_for_old_state_is_ignored_and_error_shown(self):
        self.open()
        self.p.apply(['Поход 2010'], N1)
        self.ready()
        key = self.p.nh['key']
        self.p.got_nohash(('другой',) + key[1:], ('ok', dict(n=0)))           # чужой ответ - не принят
        self.assertEqual(self.p.nohash_result()['n'], 1)
        self.p.got_nohash(key, ('refused', 'проба'))
        self.assertIn('не посчитано (проба)', self.p.copy_cell.nohash.text())
        self.assertFalse(self.p.tasks_btn.isEnabled())                          # хеш не проверен - заданий нет

    def test_prepare_refuses_files_without_hash(self):
        """Последняя проверка по строкам заданий (сохранённые отметки): файлы без хеша - отказ с объяснением."""
        self.open()
        self.p.apply(['Поход 2010'], N1)
        self.ready()                                                            # настоящий ответ уже пришёл
        with sv_patch('nohash_check', lambda d, n, dr=(): dict(n=0, bytes=0, folders=[], root=0, cats=[], sample=[],
                                                                unread=[], copies={}, errors=[])):
            self.p.nh = None
            self.p.render_cells()
            self.assertTrue(wait(lambda: self.p.tasks_btn.isEnabled(), 30), self.p.tasks_btn.toolTip())
        self.p.prepare()
        self.assertTrue(wait(lambda: any('нет хеша' in str(x) for x in self.asked), 60), self.asked)
        self.assertFalse(self.dialogs)                                          # окно заданий не открывалось


if __name__ == '__main__':
    unittest.main()
