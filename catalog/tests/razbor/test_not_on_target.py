"""«Разбор носителя»: строка «На HDD60 нет на H: …» над «Что копировать с носителя» и окно «Показать по папкам»
(18.11.2026, решение владельца); кнопки «Файлы только на этом носителе…» и группы «больше нигде нет» в «Обзоре» нет.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_not_on_target
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from PySide6.QtWidgets import QGridLayout, QPushButton   # noqa: E402

HASHED = 10                  # файлы носителя с хешем, кроме мусора (FILES обвязки test_logic_v3)
HASHED_B = 100 + 200 + 600 + 600 + 70 + 90 + 95 + 40 + 300 + 80
NOHASH, NOHASH_B = 6, 10 + 50 + 20 + 30 + 7 + 3          # без хеша, кроме Thumbs.db (мусор)


class NotOnTargetTest(PageBase):

    def nt(self, x):
        self.settle()
        return self.p.model.not_on_disk(self.p.dest)[x]

    def cell_copy(self, x):
        """«Копировать на x» ячейки - по плану ядра (один диск) или по блоку диска (несколько дисков)."""
        P, d = self.plan(), self.p.dest_dir()
        v = rp.cell_numbers(d, P)
        if len(d.disks) == 1:
            return v['copy']
        have = self.p.model.have_on_disk(d.num)[x]
        return (v['copy'][0] + v['have'][0] - have[0], v['copy'][1] + v['have'][1] - have[1])

    def same(self, x):
        v = self.nt(x)
        self.assertEqual(v['marked'], self.cell_copy(x), self.p.mode())
        return v

    def test_numbers_and_three_modes(self):
        self.open()
        self.p.set_dest('Н2')                                                    # «все файлы», диск HDD91 (пустой)
        v = self.same('HDD91')
        self.assertEqual((v['marked'], v['unmarked'], v['nohash']), ((0, 0), (HASHED, HASHED_B), (NOHASH, NOHASH_B)))
        t = self.p.missing.text()
        self.assertIn(f'На {SRC} нет на HDD91 {rp.files_word(HASHED)}', t)
        self.assertIn('все файлы, кроме программ и временных — как в настройках А2', t)
        self.assertIn('в отмеченных папках 0 файлов, 0 ГБ — будут скопированы на HDD91', t)
        self.assertIn(f'в неотмеченных папках {rp.files_word(HASHED)}', t)
        self.assertIn('Показать по папкам', t)
        self.assertIn(f'ещё без хеша {rp.files_word(NOHASH)}', t)                # без хеша - отдельно, не в «нет на»
        self.p.toggle(['Работа'], True)                                           # «Только выбранные»
        v = self.same('HDD91')
        self.assertEqual((v['marked'], v['marked_nohash']), ((2, 90), (1, 20)))  # схема.jpg и отчёт.doc (без хеша)
        self.assertEqual(v['unmarked'], (HASHED - 1, HASHED_B - 70))
        self.assertEqual(v['nohash'], (NOHASH - 1, NOHASH_B - 20))
        self.assertIn('из них без хеша 1', self.p.missing.text())
        self.p.mode_every.setChecked(True)                                       # «Все папки»
        v = self.same('HDD91')
        self.assertEqual(v['unmarked'], (1, 300))                                # z.jpg в «ПЕРЕНЕСЕНО → …»
        self.assertEqual(v['marked'][0] + v['unmarked'][0] + v['nohash'][0], HASHED + NOHASH)
        self.p.mode_except.setChecked(True)                                      # «Все, кроме выбранных»
        self.p.toggle(['Друзья'], True)
        v = self.same('HDD91')
        self.assertEqual(v['unmarked'], (3, 300 + 90 + 95))
        self.assertEqual(v['marked'][0] + v['unmarked'][0] + v['nohash'][0], HASHED + NOHASH)
        self.p.toggle(['Друзья\\Наши'], False)                                   # снятая внутри исключённой
        self.same('HDD91')

    def test_two_disks_and_counting(self):
        self.open()
        self.p.set_dest('Н1')                                                    # 45 и 77: фото, видео, документы рядом
        self.p.toggle(['Поход 2010'], True)
        self.p.toggle(['Поход 2010\\Монтаж'], False)                              # снята внутри отмеченной
        a, b = self.same('HDD45'), self.same('HDD77')
        self.assertEqual(a['marked'], (1, 10))                                   # описание.doc (без хеша)
        self.assertEqual(b['marked'], (2, 210))                                  # + 2.jpg (есть только на 45)
        self.assertEqual(a['unmarked'][0], 9 - 1)                                # 1.jpg и 2.jpg на 45 есть
        t = self.p.missing.text()
        self.assertIn(f'На {SRC} нет на HDD45', t)
        self.assertIn(f'На {SRC} нет на HDD77', t)                               # строка на каждый диск
        self.assertIn('фото, видео и документы рядом с ними — как в настройках А1', t)
        self.p.toggle(['Работа'], True)                                           # отчёт.doc рядом со схема.jpg
        self.same('HDD45')
        self.same('HDD77')
        m = self.p.model                                                          # «Уже есть» ещё не посчитано
        m.set_have(None, [])
        self.p.render_missing()
        self.assertIn(f'На {SRC} нет на HDD45:</b> <span style="color:{rp.GRAY}">считаю…', self.p.missing.text())
        self.p.run_have()
        self.settle()
        self.p.render_missing()
        self.assertNotIn('считаю', self.p.missing.text())

    def test_line_above_modes_and_carrier_is_target(self):
        self.open()
        self.p.set_dest('Н2')
        form = next(x for x in self.p.findChildren(QGridLayout) if x.indexOf(self.p.missing) >= 0)
        row = lambda w: form.getItemPosition(form.indexOf(w))[0]                  # noqa: E731
        self.assertLess(row(self.p.missing), row(self.p.mode_only.parentWidget()))
        self.assertFalse(self.p.missing.isHidden())
        self.p.model.disk = 'HDD91'                                              # носитель сам - диск назначения
        self.p.render_missing()
        self.assertTrue(self.p.missing.isHidden())
        self.p.model.disk = SRC

    def test_folders_window_and_jump(self):
        self.open()
        self.p.set_dest('Н2')
        self.p.toggle(['Работа'], True)
        self.settle()
        dlg = self.p.missing_link('nt:HDD91')
        self.assertIsNotNone(dlg)
        self.assertEqual([dlg.tree.headerItem().text(c) for c in range(4)],
                         ['Папка', 'В неотмеченных', 'В отмеченных', 'Без хеша'])
        root = dlg.items['']
        self.assertEqual(root.text(0), f'{SRC} (весь носитель)')
        self.assertEqual(root.text(1), f'{HASHED - 1} · {rp.vol(HASHED_B - 70)}')
        self.assertEqual(dlg.items['Работа'].text(2), f'2 · {rp.vol(90)}')
        self.assertIn('Поход 2010\\Монтаж', dlg.items)                           # все уровни
        self.assertEqual(dlg.items['Документы'].text(1), '—')                    # письмо.doc - без хеша
        self.assertEqual(dlg.items['Документы'].text(3), f'1 · {rp.vol(30)}')
        kids = [root.child(i).data(0, rp.ROLE) for i in range(root.childCount())]
        self.assertEqual(kids[0], 'Поход 2010')                                  # сортировка по ГБ «в неотмеченных»
        dlg.tree.itemDoubleClicked.emit(dlg.items['Поход 2010\\Монтаж'], 0)
        self.assertEqual(dlg.picked, 'Поход 2010\\Монтаж')
        self.assertEqual(self.p.selected_folders(), ['Поход 2010\\Монтаж'])
        self.assertFalse(dlg.isVisible())
        self.assertIsNone(self.p.missing_link('copy:HDD91'))

    def test_no_unique_button_and_overview_group(self):
        self.open()
        self.assertFalse(hasattr(self.p, 'unique_btn'))
        self.assertFalse([b for b in self.p.findChildren(QPushButton) if 'только на этом носителе' in b.text()])
        ov = dict(skipped=[], unique=[dict(disk='HDD90', files=2, bytes=900, list='x')], warn=[])
        groups = sv.attention(ov, [])
        self.assertEqual(groups, [])
        self.assertNotIn('больше нигде нет', app.attention_html(groups))
