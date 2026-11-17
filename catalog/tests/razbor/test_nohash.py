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
        self.assertIn('✖ У 1 из 4 файлов нет хеша</b>', text)                   # 18.11.2026 - вид строки владельца
        self.assertIn('в 1 папке', text)
        self.assertFalse(self.p.tasks_btn.isEnabled())
        self.assertIn('Сначала хеш', self.p.tasks_btn.toolTip())
        self.assertTrue(cell.scan_btn.isVisibleTo(cell) and cell.scan_btn.isEnabled())
        self.assertEqual(cell.scan_btn.text(), 'Посчитать хеш (1)')
        made = []

        class FakeDlg:
            def __init__(self, win, disk, folders, cats=None):
                made.append((disk, list(folders), cats))
                self.running = False
                from PySide6.QtCore import QObject, Signal

                class S(QObject):
                    finished = Signal(int)
                self.s = S()
                self.finished = self.s.finished

            def show(self):
                pass
        with mock.patch('rescan_dialog.RescanDialog', FakeDlg):
            cell.scan_btn.click()
        self.assertEqual(made, [(SRC, ['Поход 2010'], [hb.CAT_DOC])])
        dlg = self.p.nohash_link('nh-list:')
        self.assertIn('Поход 2010\\описание.doc', dlg.text.toPlainText())
        dlg.close()

    def test_all_hashed_is_green_and_tasks_allowed(self):
        self.open()
        self.p.apply(['Друзья'], N1)
        nh = self.ready()
        self.assertEqual(nh['n'], 0)
        self.assertIn('есть хеш', self.p.copy_cell.nohash.text())
        self.assertFalse(self.p.copy_cell.scan_btn.isVisibleTo(self.p.copy_cell))
        self.assertTrue(self.p.tasks_btn.isEnabled())

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
