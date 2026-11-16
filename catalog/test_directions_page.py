"""Секция «Направления» в «Обзоре» и описание направления (логика v3, этап 4, 15.11.2026). Qt offscreen, временные данные.

Запуск из корня проекта:  py -m unittest catalog.test_directions_page
Настоящие таблицы, диски и задания не используются.
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QThreadPool, Qt                 # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget       # noqa: E402

import app                                                 # noqa: E402
import directions_page as dp                               # noqa: E402
import hashbase as hb                                      # noqa: E402
import service as sv                                       # noqa: E402
from hb_cmd import directions as c_dirs                    # noqa: E402
from test_hashbase import NS, Base                         # noqa: E402

QAPP = QApplication.instance() or QApplication([])
DIRS = [dict(name='Семейный архив', disks=['HDD45', 'HDD77'], kind=hb.KIND_MEDIA, note=''),
        dict(name='Работа', disks=['HDD91'], kind=hb.KIND_ALL, former=['Сафари'], note=''),
        dict(name='Без диска', disks=[], kind=hb.KIND_ALL, note='')]


def wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        QAPP.processEvents()
        QThreadPool.globalInstance().waitForDone(50)
        QAPP.processEvents()
        if cond():
            return True
    return False


class FakeWin(QWidget):
    """Окно без остальных страниц: фон, список страниц, переход."""

    def __init__(self):
        super().__init__()
        self.bg = app.Background(self)
        self.errors, self.opened = [], []
        self.pages = [('Обзор', None)]

    def show_error(self, text):
        self.errors.append(text)

    def open_page(self, name):
        self.opened.append(name)


class DirBase(Base):
    def setUp(self):
        super().setUp()
        self.quiet(hb.connect)
        sv.add_directions_batch(DIRS)
        self.win = FakeWin()

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(10000)
        super().tearDown()

    def section(self):
        s = dp.DirectionsSection(self.win)
        s.refresh()
        self.assertTrue(wait(lambda: s.t.rowCount() == len(sv.directions())), self.win.errors)
        return s

    def row_of(self, s, num):
        return next(i for i in range(s.t.rowCount()) if s.t.item(i, 0).data(Qt.UserRole) == num)

    def lines(self):
        return [x for x in hb.DIRECTIONS.read_text(encoding='utf-8-sig').splitlines() if x.strip()]


class DescriptionCoreTest(DirBase):
    def test_description_column_is_inherited_and_compatible(self):
        sv.direction_save(num='Н2', desc='рабочие проекты  и   Сафари')
        self.assertEqual(sv.directions()['Н2'].desc, 'рабочие проекты и Сафари')     # пробелы схлопнуты
        self.assertEqual(len(self.lines()[-1].split('\t')), 7)
        with self.assertRaises(sv.Refused):                                         # то же описание - ничего не меняется
            sv.direction_save_preview(num='Н2', desc='рабочие проекты и Сафари')
        sv.add_direction(num='Н2', name='Работа и Сафари')                          # старый путь правки: 6 колонок
        self.assertEqual(len(self.lines()[-1].split('\t')), 6)
        d = sv.directions()['Н2']
        self.assertEqual((d.name, d.desc), ('Работа и Сафари', 'рабочие проекты и Сафари'))   # описание унаследовано
        c_dirs.cmd_direction_edit(NS(direction='Н2', name=None, to=[], add_disk=['HDD90'], what=None, former=None,
                                     note=None, yes=True))                          # команда direction-edit
        self.assertEqual(sv.directions()['Н2'].desc, 'рабочие проекты и Сафари')
        sv.direction_save(num='Н2', desc='')                                        # пустое - стирает
        self.assertEqual(sv.directions()['Н2'].desc, '')
        self.assertEqual(sv.directions()['Н1'].desc, '')                            # у кого не задавали - пусто
        pv = sv.direction_save_preview(name='Новое', disks=[], desc='всё прочее')   # новое направление с описанием
        self.assertEqual(pv['fields'][0], 'Н4')
        self.assertEqual(pv['fields'][6], 'всё прочее')
        with self.assertRaises(sv.Refused):
            sv.direction_save_preview(num='Н3', desc='x' * (sv.DESC_MAX + 1))
        with self.assertRaises(sv.Refused):                                         # табуляция и т. п. схлопнуты, но длина
            sv.direction_save_preview(num='Н3', disks=['HDD45'])                    # чужой диск - отказ ядра

    def test_disk_change_with_tasks_needs_ack(self):
        t = hb.TASKS / 'HDD90 — A — Работа'
        t.mkdir(parents=True)
        (t / 'список.tsv').write_text('HDD91\tA\\1.jpg\t100\tс хешем\t' + 'a' * 64 + '\nHDD91\tA\\2.jpg\t200\tс хешем\t'
                                     + 'b' * 64 + '\n', encoding='utf-8')
        (t / 'разбор.json').write_text(json.dumps({'носитель': 'HDD90', 'направление': 'Н2', 'обязательные диски': ['HDD91'],
                                                   'цели': ['HDD91']}, ensure_ascii=False), encoding='utf-8')
        (t / 'Журнал копирования 2026-11-15 10-00-00.tsv').write_text(
            'время\tцель\tрезультат\tразмер\tSHA-256 прочитанного\tисточник\tкуда\n'
            '10:00:00\tHDD91\tскопирован, размер и SHA-256 совпали\t100\t' + 'A' * 64 + '\tK:\\A\\1.jpg\tL:\\x\\A\\1.jpg\n',
            encoding='utf-8-sig')
        sv.add_marks_batch('HDD90', [('A', 'Н2')])
        use = sv.direction_usage('Н2')
        self.assertEqual(use['tasks'][0]['per'], {'HDD91': (1, 2)})
        self.assertEqual(use['marks'], {'HDD90': 1})
        pv = sv.direction_save_preview(num='Н2', disks=['HDD90'])
        text = '\n'.join(pv['lines'])
        self.assertEqual(pv['needs_ack'], ['HDD91'])
        self.assertIn('HDD91: 1 из 2', text)
        self.assertIn('по-прежнему требуют копий на своих прежних дисках (HDD91)', text)
        self.assertIn('«Скопировано на Работа (91)» на носителях не переименовываются; новые будут «Скопировано на Работа (90)»', text)
        self.assertIn('Отмечено папок этим направлением: HDD90: 1', text)
        before = hb.DIRECTIONS.read_bytes()
        with self.assertRaises(sv.Refused):
            sv.direction_save(num='Н2', disks=['HDD90'])                           # без подтверждения - не записано
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        sv.direction_save(num='Н2', disks=['HDD90'], ack=True)
        self.assertEqual(sv.directions()['Н2'].disks, ('HDD90',))
        pv = sv.direction_save_preview(num='Н3', disks=['HDD91'])                   # освободившийся диск - другому
        self.assertIn('На диск HDD91 раньше шли задания направлений Н2 «Работа»', '\n'.join(pv['lines']))
        self.assertEqual(pv['needs_ack'], [])

    def test_journal_with_and_without_source_mtime_column(self):
        """Шаблон 2.4 пишет 8-ю колонку «дата изменения источника»; сборщик читает журналы обоих видов одинаково."""
        from test_hashbase import LOG_HEAD, S
        self.task('Старый', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-00-00.tsv',
                  LOG_HEAD, [('00:00:01', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', S[2].upper(),
                              'K:\\A\\2.jpg', 'S:\\ПЕРЕНОС с других дисков\\HDD90\\A\\2.jpg')])
        self.task('Новый', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-02 00-00-00.tsv',
                  LOG_HEAD + ('дата изменения источника',),
                  [('00:00:01', 'HDD77', 'скопирован, размер и SHA-256 совпали', '400', S[4].upper(), 'K:\\B\\4.jpg',
                    'S:\\ПЕРЕНОС с других дисков\\HDD90\\B\\4.jpg', '1721142606'),
                   ('00:00:02', 'HDD77', 'нет источника', '500', '', 'K:\\B\\5.jpg', 'S:\\x\\B\\5.jpg', '')])
        self.quiet(hb.connect)
        st = self.state()
        self.assertTrue(st['A\\2.jpg'][1])                                          # старый журнал (7 колонок)
        self.assertTrue(st['B\\4.jpg'][1])                                          # новый журнал (8 колонок)
        self.assertFalse(st['B\\5.jpg'][1])
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС с других дисков\\HDD90\\B\\4.jpg')[:2], (S[4], hb.EV_COPY))
        u = sv.task_state(self.out / 'Новый')                                        # состояние задания тоже читается
        self.assertIsNone(u)                                                         # (нет список.tsv - не задание)

    def test_template_helpers(self):
        t = hb.TASKS / 'задание'
        t.mkdir(parents=True)
        (t / 'Копировать.ps1').write_text('# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ (версия 2.3 от 13.11.2026)\n', encoding='utf-8-sig')
        self.assertEqual(sv.copy_template_version(t), (2, 3))
        self.assertIsNone(sv.copy_template_version(self.tmp))
        (t / 'список.tsv').write_text('HDD45\ta\t10\tx\nHDD77\ta\t10\tx\nHDD45\tb\t5\tx\n', encoding='utf-8')
        (t / 'тома.tsv').write_text('HDD90\tS\nHDD45\tS\nHDD77\tS\n', encoding='utf-8')
        fp = sv.copy_task_fingerprint(t)
        self.assertEqual(fp['per'], {'HDD45': (2, 15), 'HDD77': (1, 10)})
        (t / 'разбор.json').write_text('{}', encoding='utf-8')
        self.assertNotEqual(sv.copy_task_fingerprint(t)['sha'], fp['sha'])         # отпечаток видит и разбор.json


class SectionTest(DirBase):
    def test_table_and_overview(self):
        sv.direction_save(num='Н1', desc='семейные фото и видео всех лет')
        s = self.section()
        self.assertEqual(s.t.rowCount(), 3)
        i1, i3 = self.row_of(s, 'Н1'), self.row_of(s, 'Н3')
        self.assertEqual(s.t.item(i1, 1).text(), 'Н1 Семейный архив')
        self.assertEqual(s.t.item(i1, 2).text(), 'семейные фото и видео всех лет')
        disks = s.t.cellWidget(i1, 3).text()
        self.assertIn('HDD45', disks)
        self.assertIn('HDD77', disks)
        self.assertIn('не подключён', disks)
        self.assertEqual(s.t.item(i1, 5).text(), hb.KIND_MEDIA)
        self.assertEqual(s.t.item(i1, 6).text(), 'Скопировано на Семейный архив (45 и 77)')
        self.assertIn('описания нет', s.t.item(i3, 2).text())
        self.assertIn('диск не назначен', s.t.cellWidget(i3, 3).text())
        self.assertFalse(s.t.item(i3, 0).flags() & Qt.ItemIsUserCheckable)        # без диска - галочки нет
        s.t.selectRow(i3)
        self.assertTrue(s.b_disk.isEnabled())                                       # «Назначить диск» - только без диска
        s.t.selectRow(i1)
        self.assertFalse(s.b_disk.isEnabled())
        self.assertTrue(s.b_edit.isEnabled())
        ov = app.OverviewPage(self.win)                                              # секция стоит в начале «Обзора»
        self.assertIsInstance(ov.dirs, dp.DirectionsSection)
        ov.dirs.refresh()
        self.assertTrue(wait(lambda: ov.dirs.t.rowCount() == 3))

    def test_checkboxes_choice_and_go(self):
        s = self.section()
        self.assertFalse(s.b_go.isEnabled())
        self.assertIn('ещё не готов', s.b_go.toolTip())                             # экрана «Разбор носителя» нет
        s.t.item(self.row_of(s, 'Н1'), 0).setCheckState(Qt.Checked)
        s.t.item(self.row_of(s, 'Н2'), 0).setCheckState(Qt.Checked)
        self.assertEqual(dp.load_choice(), ['Н1', 'Н2'])                            # выбор окна записан сразу
        self.assertEqual([d.num for d in dp.chosen()], ['Н1', 'Н2'])
        self.assertTrue(dp.choice_path().exists())
        self.assertFalse(s.b_go.isEnabled())
        self.win.pages.append((dp.RAZBOR_PAGE, None))                                # экран появился
        s.update_buttons()
        self.assertTrue(s.b_go.isEnabled())
        s.b_go.click()
        self.assertEqual(self.win.opened, [dp.RAZBOR_PAGE])
        s.t.item(self.row_of(s, 'Н2'), 0).setCheckState(Qt.Unchecked)
        self.assertEqual(dp.load_choice(), ['Н1'])
        dp.save_choice(['Н1', 'Н3', 'Н99'])                                         # без диска и несуществующее - не в выборе
        self.assertEqual([d.num for d in dp.chosen()], ['Н1'])
        s2 = self.section()                                                          # галочки - из файла выбора
        self.assertEqual(s2.checked(), ['Н1'])
        dp.choice_path().write_text('не json', encoding='utf-8')
        self.assertEqual(dp.load_choice(), [])

    def test_dialog_saves_at_once(self):
        """Этап 5, п. 2: «Проверить» нет, «Сохранить» активна сразу; новое направление - без переспроса."""
        s = self.section()
        dlg = dp.DirectionDialog(s, s.data, None)
        self.assertFalse(hasattr(dlg, 'b_check'))
        self.assertEqual(dlg.b_write.text(), 'Сохранить')
        self.assertTrue(dlg.b_write.isEnabled())
        own = {dlg.disks.item(i).data(Qt.UserRole): dlg.disks.item(i) for i in range(dlg.disks.count())}
        self.assertEqual(own['HDD45'].flags(), Qt.NoItemFlags)                      # диск другого направления недоступен
        self.assertIn('у Н1 «Семейный архив»', own['HDD45'].text())
        self.assertTrue(own['HDD90'].flags() & Qt.ItemIsUserCheckable)
        asked = []
        dlg.confirm_hook = lambda lines, ack: asked.append(lines) or (True, False)
        dlg.name.setText('Друзья')
        dlg.desc.setText('фото друзей')
        own['HDD90'].setCheckState(Qt.Checked)
        n = len(self.lines())
        dlg.write()
        self.assertTrue(wait(lambda: len(self.lines()) == n + 1))
        self.assertEqual(asked, [])                                                  # не переспрашивали
        d = sv.directions()['Н4']
        self.assertEqual((d.name, d.disks, d.desc, d.kind), ('Друзья', ('HDD90',), 'фото друзей', hb.KIND_ALL))
        self.assertTrue(wait(lambda: s.t.rowCount() == 4))                          # секция перечитана
        self.assertIn('Сохранено', s.hint.text())

    def test_dialog_refusal_writes_nothing(self):
        s = self.section()
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н3'], mode=dp.CARD)
        dlg.name.setText('Сафари')                                                   # прежнее имя другого направления
        before = hb.DIRECTIONS.read_bytes()
        dlg.write()
        self.assertTrue(wait(lambda: 'Нельзя сохранить' in dlg.view.toPlainText()))
        self.assertIn('Сафари', dlg.view.toPlainText())
        self.assertTrue(dlg.b_write.isEnabled())
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        self.assertEqual(self.win.errors, [])                                        # отказ - в диалоге, не ошибкой окна

    def test_card_edit_keeps_disks_without_confirm(self):
        """Второй круг, п. 2: «Изменить…» - только карточка; правка описания у направления с диском и заданием на него
        диски не меняет и не переспрашивает (была ошибка: диалог снимал собственный диск -> «Меняются диски…»)."""
        t = hb.TASKS / 'HDD90 — A — Работа'
        t.mkdir(parents=True)
        (t / 'список.tsv').write_text('HDD91\tA\\1.jpg\t100\tс хешем\t' + 'a' * 64 + '\n', encoding='utf-8')
        (t / 'разбор.json').write_text(json.dumps({'носитель': 'HDD90', 'направление': 'Н2', 'обязательные диски': ['HDD91'],
                                                   'цели': ['HDD91']}, ensure_ascii=False), encoding='utf-8')
        self.assertTrue(sv.direction_usage('Н2')['tasks'])                          # задание на диск направления есть
        s = self.section()
        s.t.selectRow(self.row_of(s, 'Н2'))
        made = []
        orig = dp.DirectionDialog.exec
        dp.DirectionDialog.exec = lambda self_: made.append(self_) or 0
        try:
            s.b_edit.click()
        finally:
            dp.DirectionDialog.exec = orig
        dlg = made[0]
        self.assertEqual(dlg.mode, dp.CARD)
        self.assertIsNone(dlg.disks)                                                 # списка дисков нет
        self.assertIsNone(dlg.values()['disks'])                                     # в сервис - «оставить как есть»
        asked = []
        dlg.confirm_hook = lambda lines, ack: asked.append(lines) or (True, False)
        dlg.desc.setText('рабочие проекты')
        dlg.write()
        self.assertTrue(wait(lambda: sv.directions()['Н2'].desc == 'рабочие проекты'), dlg.view.toPlainText())
        self.assertEqual(sv.directions()['Н2'].disks, ('HDD91',))                   # диски не изменились
        self.assertEqual(asked, [])                                                  # переспроса нет
        cd = dp.ConfirmDialog(s, ['строка'], ['HDD91'])                              # окно переспроса осталось: без галочки нельзя
        self.assertFalse(cd.ok.isEnabled())
        cd.ack.setChecked(True)
        self.assertTrue(cd.ok.isEnabled())

    def test_assign_only_without_disk(self):
        """Второй круг, п. 3: «Назначить диск…» - только у направления без диска: только список дисков."""
        s = self.section()
        s.t.selectRow(self.row_of(s, 'Н2'))
        self.assertFalse(s.b_disk.isEnabled())
        made = []
        orig = dp.DirectionDialog.exec
        dp.DirectionDialog.exec = lambda self_: made.append(self_) or 0
        try:
            s.assign()                                                               # у направления с диском - ничего
            self.assertEqual(made, [])
            s.t.selectRow(self.row_of(s, 'Н3'))
            self.assertTrue(s.b_disk.isEnabled())
            s.b_disk.click()
        finally:
            dp.DirectionDialog.exec = orig
        dlg = made[0]
        self.assertEqual(dlg.mode, dp.ASSIGN)
        self.assertFalse(dlg.card.isVisibleTo(dlg))                                  # карточки нет
        self.assertFalse(dlg.b_write.isEnabled())                                    # диск не отмечен
        it = {dlg.disks.item(i).data(Qt.UserRole): dlg.disks.item(i) for i in range(dlg.disks.count())}
        self.assertEqual(it['HDD91'].flags(), Qt.NoItemFlags)                        # чужой - выбрать нельзя
        it['HDD90'].setCheckState(Qt.Checked)
        self.assertTrue(dlg.b_write.isEnabled())
        self.assertEqual(dlg.values(), dict(num='Н3', name=None, disks=['HDD90'], kind=None, desc=None))
        saved = []
        s.on_saved = lambda: saved.append(1)
        dlg.write()
        self.assertTrue(wait(lambda: sv.directions()['Н3'].disks == ('HDD90',)))
        d = sv.directions()['Н3']
        self.assertEqual((d.name, d.kind), ('Без диска', hb.KIND_ALL))               # остальное не тронуто
        self.assertTrue(wait(lambda: saved == [1]))                                  # «Обзор» перечитывается

    def test_unrecognized_kind_and_change_during_confirm(self):
        """Замечания 8 и 6: нераспознанное «что копировать» - все галочки сняты и «Сохранить» неактивна; поля
        поменяли, пока был открыт переспрос, - ничего не сохраняется."""
        with open(hb.DIRECTIONS, 'a', encoding='utf-8') as f:
            f.write('Н2\tРабота\tСафари\tHDD91\tчто-то странное\t\n')
        s = self.section()
        self.assertIn('не распознано', s.t.item(self.row_of(s, 'Н2'), 5).text())
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н2'])
        self.assertEqual(dlg.chosen_cats(), frozenset())
        self.assertFalse(dlg.b_write.isEnabled())
        dlg.cat_boxes[hb.CAT_PHOTO].setChecked(True)
        self.assertTrue(dlg.b_write.isEnabled())
        dlg2 = dp.DirectionDialog(s, s.data, s.data['dirs']['Н1'])
        dlg2.desc.setText('семейное')
        real = sv.direction_save_preview
        sv.direction_save_preview = lambda **kw: dict(real(**kw), confirm=True)     # переспрос - на всякий случай
        self.addCleanup(setattr, sv, 'direction_save_preview', real)

        def meddle(lines, ack):
            dlg2.name.setText('Другое имя')                                         # поменяли поле во время переспроса
            return True, False
        dlg2.confirm_hook = meddle
        before = hb.DIRECTIONS.read_bytes()
        dlg2.write()
        self.assertTrue(wait(lambda: 'Значения изменились' in dlg2.view.toPlainText()))
        QThreadPool.globalInstance().waitForDone(5000)
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        self.assertTrue(dlg2.b_write.isEnabled())

    def test_confirm_only_when_disks_change_with_tasks_or_data(self):
        pv = sv.direction_save_preview(num='Н2', desc='новое описание')            # только описание - сразу
        self.assertFalse(pv['confirm'])
        pv = sv.direction_save_preview(num='Н2', disks=['HDD91', 'HDD90'])         # только добавление диска - сразу
        self.assertFalse(pv['confirm'])
        pv = sv.direction_save_preview(num='Н2', kind=(frozenset({hb.CAT_PHOTO}), False))
        self.assertFalse(pv['confirm'])
        pv = sv.direction_save_preview(num='Н1', disks=['HDD45'])                  # убирается 77, на нём есть файлы
        self.assertTrue(pv['confirm'])
        self.assertEqual(pv['needs_ack'], [])                                       # заданий нет - галочка не нужна
        self.assertIn('направлению больше не засчитывается', '\n'.join(pv['lines']))

    def test_kind_checkboxes(self):
        """Этап 5, п. 3: галочки «что копировать», «Все файлы», «только рядом»; старые значения читаются."""
        s = self.section()
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н1'])                  # «фото, видео и документы рядом»
        on = {c for c, b in dlg.cat_boxes.items() if b.isChecked()}
        self.assertEqual(on, {hb.CAT_PHOTO, hb.CAT_VIDEO, hb.CAT_DOC})
        self.assertTrue(dlg.near.isChecked() and dlg.near.isEnabled())
        self.assertEqual(dlg.all_box.checkState(), Qt.PartiallyChecked)
        self.assertIn('в её подпапках', dlg.near.toolTip())
        dlg.cat_boxes[hb.CAT_DOC].setChecked(False)
        self.assertFalse(dlg.near.isEnabled())                                      # без документов «рядом» не действует
        self.assertEqual(dlg.values()['kind'], (frozenset({hb.CAT_PHOTO, hb.CAT_VIDEO}), False))
        dlg.all_box.click()                                                          # не все -> все
        self.assertEqual(dlg.chosen_cats(), hb.ALL_CATS)
        self.assertEqual(dlg.all_box.checkState(), Qt.Checked)
        dlg.all_box.click()                                                          # все -> ничего
        self.assertEqual(dlg.chosen_cats(), frozenset())
        self.assertFalse(dlg.b_write.isEnabled())                                   # замечание 8: пустой набор
        self.assertIn('хотя бы один тип', dlg.b_write.toolTip())
        with self.assertRaises(sv.Refused):                                         # и сервис отказывает
            sv.direction_save_preview(num='Н1', kind=(frozenset(), False))
        dlg.cat_boxes[hb.CAT_PHOTO].setChecked(True)
        dlg.cat_boxes[hb.CAT_MUSIC].setChecked(True)
        dlg.confirm_hook = lambda lines, ack: (True, False)
        dlg.write()
        self.assertTrue(wait(lambda: sv.directions()['Н1'].kind == 'фото, музыка'))
        self.assertEqual(self.lines()[-1].split('\t')[4], 'фото, музыка')
        sv.direction_save(num='Н1', kind=(hb.ALL_CATS, False))                     # набор старого значения - старым текстом
        self.assertEqual(sv.directions()['Н1'].kind, hb.KIND_ALL)
        sv.direction_save(num='Н1', kind=(frozenset({hb.CAT_PHOTO, hb.CAT_VIDEO, hb.CAT_DOC}), True))
        self.assertEqual(sv.directions()['Н1'].kind, hb.KIND_MEDIA)
        s2 = self.section()
        self.assertEqual(s2.t.item(self.row_of(s2, 'Н2'), 5).text(), 'все файлы (кроме программ и временных)')

    def test_disk_colors(self):
        """Второй круг, п. 1 и 4: в таблице диски зелёные; оранжевые - только у отмеченных галочкой (сразу при щелчке);
        неподключённые - бледнее и с подписью «не подключён». В «Новом направлении» - голубой фон «выбран сейчас»."""
        import disk_ui
        self.assertEqual(disk_ui.dir_disk_color(True, False), (disk_ui.DIR_ON, True))
        self.assertEqual(disk_ui.dir_disk_color(False, False), (disk_ui.DIR_OFF, False))
        self.assertEqual(disk_ui.dir_disk_color(True, True), (disk_ui.ASSIGNED_ON, True))
        self.assertEqual(disk_ui.dir_disk_color(False, True), (disk_ui.ASSIGNED_OFF, False))
        s = self.section()
        s.data['disks'] = [dict(r, letter='Z:') if r['disk'] in ('HDD45', 'HDD90') else r for r in s.data['disks']]
        s.data['by'] = {r['disk']: r for r in s.data['disks']}
        s.render(s.data)
        cell = lambda num: s.t.cellWidget(self.row_of(s, num), 3).text()
        self.assertIn(f'<b style="color:{disk_ui.DIR_ON}">● HDD45', cell('Н1'))        # не отмечено - зелёный
        self.assertIn(f'<span style="color:{disk_ui.DIR_OFF}">HDD77', cell('Н1'))       # не подключён - бледнее
        self.assertIn('не подключён', cell('Н1'))
        self.assertNotIn(disk_ui.ASSIGNED_ON, cell('Н1') + cell('Н2'))
        s.t.item(self.row_of(s, 'Н1'), 0).setCheckState(Qt.Checked)                  # щелчок галочки - сразу
        self.assertIn(f'<b style="color:{disk_ui.ASSIGNED_ON}">● HDD45', cell('Н1'))
        self.assertIn(f'<span style="color:{disk_ui.ASSIGNED_OFF}">HDD77', cell('Н1'))
        self.assertNotIn(disk_ui.ASSIGNED_OFF, cell('Н2'))                          # не отмеченное - зелёное
        s.t.item(self.row_of(s, 'Н1'), 0).setCheckState(Qt.Unchecked)
        self.assertNotIn(disk_ui.ASSIGNED_ON, cell('Н1'))
        # диалог «Новое направление»: оранжевый - уже у другого направления; голубой фон - выбран сейчас
        dlg = dp.DirectionDialog(s, s.data, None)
        it = {dlg.disks.item(i).data(Qt.UserRole): dlg.disks.item(i) for i in range(dlg.disks.count())}
        color = lambda d: it[d].data(Qt.ForegroundRole).color().name()
        self.assertEqual(color('HDD45'), disk_ui.ASSIGNED_ON)                       # у Н1, подключён
        self.assertEqual(color('HDD77'), disk_ui.ASSIGNED_OFF)                      # у Н1, не подключён
        self.assertEqual(color('HDD90'), '#1b5e20')                                 # свободен, подключён
        self.assertEqual(dlg.disks.item(0).data(Qt.UserRole), 'HDD45')              # подключённые - сверху
        self.assertIsNone(it['HDD90'].data(Qt.BackgroundRole))
        it['HDD90'].setCheckState(Qt.Checked)                                        # щелчок - сразу голубой фон
        self.assertEqual(it['HDD90'].data(Qt.BackgroundRole).color().name(), disk_ui.SELECTED_BG)
        self.assertEqual(it['HDD90'].checkState(), Qt.Checked)                       # галочка остаётся
        self.assertEqual(color('HDD90'), '#1b5e20')
        it['HDD90'].setCheckState(Qt.Unchecked)
        self.assertIsNone(it['HDD90'].data(Qt.BackgroundRole))
        legend = ''.join(x.text() for x in dlg.findChildren(dp.QLabel))
        self.assertIn('выбран сейчас', legend)
        self.assertIn('уже у другого направления', legend)
        s.data['disks'] = [dict(r, letter='') if r['disk'] == 'HDD90' else r for r in s.data['disks']]
        dlg2 = dp.DirectionDialog(s, s.data, None)
        it2 = {dlg2.disks.item(i).data(Qt.UserRole): dlg2.disks.item(i) for i in range(dlg2.disks.count())}
        self.assertEqual(it2['HDD90'].data(Qt.ForegroundRole).color().name(), '#8a8a8a')   # свободен, не подключён

    def test_go_opens_razbor_with_chosen(self):
        """Этап 5, п. 4: кнопка перехода просит экран разбора поставить отмеченное направление."""
        s = self.section()
        got = []

        class Page:
            def use_choice(self):
                got.append(dp.load_choice())
        self.win.pages.append((dp.RAZBOR_PAGE, Page()))
        self.win.page = lambda name: dict(self.win.pages)[name]
        s.t.item(self.row_of(s, 'Н2'), 0).setCheckState(Qt.Checked)
        s.update_buttons()
        s.b_go.click()
        self.assertEqual(got, [['Н2']])
        self.assertEqual(self.win.opened, [dp.RAZBOR_PAGE])



class OverviewTest(DirBase):
    """Второй круг, п. 5 и 6: нижняя таблица «Обзора» по дискам направлений и «Требует внимания» по группам."""

    def page(self):
        ov = app.OverviewPage(self.win)
        ov.refresh()
        self.assertTrue(wait(lambda: ov.ov is not None and ov.dirs.data is not None), self.win.errors)
        return ov

    def table(self, ov):
        return [[ov.dt.item(i, j).text() for j in range(ov.dt.columnCount())] for i in range(ov.dt.rowCount())]

    def test_service_counts_direction_disks(self):
        import sqlite3
        with sqlite3.connect(hb.DB) as c:                                            # временная база теста
            c.execute("update files set ev='Z' where disk='HDD91'")
            c.execute("update files set ev='U' where disk='HDD45' and path='X\\2.jpg'")
        hb.close_last()
        ov = sv.overview()
        self.assertEqual(list(ov['disks_info']), ['HDD45', 'HDD77', 'HDD91'])        # все диски направлений, по порядку
        self.assertEqual(ov['disks_info']['HDD45']['ev'], {'S': 1, 'U': 1})
        self.assertEqual(ov['disks_info']['HDD77']['ev'], {'S': 1})
        self.assertEqual(ov['disks_info']['HDD91']['ev'], {'Z': 1})
        self.assertTrue(ov['disks_info']['HDD45']['in_base'])
        self.assertAlmostEqual(ov['disks_info']['HDD45']['gib'] * hb.GIB, 300)
        self.assertEqual(ov['disks_info']['HDD45']['letter'], '')
        self.assertFalse(sv.overview(disks=['HDD99'])['disks_info']['HDD99']['in_base'])   # назначен, описи нет
        self.assertNotIn('main', ov)
        # окно: ничего не отмечено - все диски и приписка; отмечено Н2 - только его диск; Z/U/X красным с подсказкой
        page = self.page()
        rows = self.table(page)
        self.assertEqual([r[0] for r in rows], ['HDD45', 'HDD77', 'HDD91'])
        self.assertEqual(page.all_note.text(), 'галочек нет — показаны все')
        self.assertEqual(rows[0][1], 'нет')                                          # не подключён
        self.assertEqual(rows[0][2], '—')
        heads = [page.dt.horizontalHeaderItem(j).text().replace('\n', ' ') for j in range(page.dt.columnCount())]
        self.assertEqual(heads, ['Диск', 'Подключён', 'Свободно', 'Общий объём файлов, ГБ',
                                 'Проверено по хешу при сканировании', 'Скопировано программой, хеш сверен',
                                 'Скопировано, сверен только размер', 'Со слов «Я сделал в Проводнике»',
                                 'Изменились после проверки'])
        self.assertFalse(any(f'({x})' in ' '.join(heads) for x in 'SCZUX'))          # букв в заголовках нет
        self.assertEqual(rows[0][4:], ['1', '0', '0', '1', '0'])
        u = page.dt.item(0, 7)
        self.assertEqual(u.foreground().color().name(), app.RED)
        self.assertIn('пересканировать папку', u.toolTip())
        z = page.dt.item(2, 6)
        self.assertEqual(z.foreground().color().name(), app.RED)
        self.assertIn('пересчитать хеши', z.toolTip())
        self.assertNotEqual(page.dt.item(0, 6).foreground().color().name(), app.RED)    # 0 - не красным
        s = page.dirs
        s.t.item(self.row_of(s, 'Н2'), 0).setCheckState(Qt.Checked)                  # щелчок - сразу
        self.assertEqual([r[0] for r in self.table(page)], ['HDD91'])
        self.assertEqual(page.all_note.text(), '')
        s.t.item(self.row_of(s, 'Н1'), 0).setCheckState(Qt.Checked)
        self.assertEqual([r[0] for r in self.table(page)], ['HDD45', 'HDD77', 'HDD91'])
        self.assertEqual(page.all_note.text(), '')
        self.assertNotIn('База собрана', page.text.toPlainText())

    def test_review_fixes(self):
        """Проверка кода этапа 7: отмечено только направление без диска - не «показаны все»; задание «идёт» с
        ошибками - в группе ошибок; высота таблицы дисков - не больше 8 строк."""
        dirs = sv.directions()
        self.assertEqual(app.shown_disks(dirs, []), (['HDD45', 'HDD77', 'HDD91'], True, 'галочек нет — показаны все'))
        self.assertEqual(app.shown_disks(dirs, ['Н3']), ([], False, 'у Н3 диск не назначен'))
        self.assertEqual(app.shown_disks(dirs, ['Н2', 'Н3']), (['HDD91'], False, 'у Н3 диск не назначен'))
        self.assertEqual(app.shown_disks(dirs, ['Н2']), (['HDD91'], False, ''))
        s = self.section()                                                           # в окне без диска не отметить
        self.assertFalse(s.t.item(self.row_of(s, 'Н3'), 0).flags() & Qt.ItemIsUserCheckable)
        tasks = [dict(task='Т1', state='идёт', done=2, total=9, errors=1),
                 dict(task='Т2', state='идёт', done=2, total=9, errors=0),
                 dict(task='Т3', state='не запускалось', done=0, total=9, errors=3),
                 dict(task='Т4', state='готово', done=9, total=9, errors=0)]
        g = sv.attention(dict(skipped=[], unique=[], warn=[]), tasks)
        self.assertEqual([t['task'] for t in g[0]['items']], ['Т1'])
        page = self.page()
        many = {f'HDD{i}': dict(ev={}, gib=0.0, in_base=True, letter='') for i in range(100, 120)}
        page.ov['disks_info'] = many
        page.current_dirs = lambda: ({'Н9': type('D', (), dict(num='Н9', disks=tuple(many)))()}, [])
        page.paint_disks()
        self.assertEqual(page.dt.rowCount(), 20)
        rows8 = page.dt.horizontalHeader().height() + sum(page.dt.rowHeight(i) for i in range(app.MAX_DISK_ROWS)) + 6
        self.assertEqual(page.dt.height(), rows8)                                    # дальше - прокрутка внутри таблицы

    def test_attention_groups(self):
        self.assertEqual(sv.attention(dict(skipped=[], unique=[], warn=[]), []), [])
        self.assertIn('Ничего не требует внимания', app.attention_html([]))
        tasks = [dict(task='Т1', state='готово с ошибками', done=5, total=5, errors=2),
                 dict(task='Т2', state='прервано', done=3, total=10, errors=0),
                 dict(task='Т3', state='не запускалось', done=0, total=4, errors=0),
                 dict(task='Т4', state='готово', done=4, total=4, errors=0),
                 dict(task='Т5', state='идёт', done=1, total=4, errors=0),
                 dict(task='Т6', state='состояние неизвестно', done=1, total=4, errors=0)]
        g = sv.attention(dict(skipped=['Журнал копирования 1.tsv'], unique=[], warn=['ручные операции: непонятное']),
                         tasks)
        self.assertEqual([x['key'] for x in g], ['tasks', 'logs', 'warn'])           # пустая группа не показана
        self.assertEqual([t['task'] for t in g[0]['items']], ['Т1', 'Т2', 'Т6'])
        html = app.attention_html(g)
        self.assertIn('Задания с ошибками или прерванные', html)
        self.assertIn('«Т1» — готово с ошибками: сделано 5 из 5, ошибок 2', html)
        self.assertIn('«Т6» — состояние неизвестно', html)
        self.assertIn('href="tasks:"', html)
        self.assertIn('Журналы, которые программа не смогла прочитать', html)
        self.assertIn('Прочие предупреждения базы', html)
        self.assertNotIn('Т3', html)                                                  # «Ждут запуска» - не здесь
        # файлы, которых больше нигде нет: два носителя; числа - из отчёта сборки, путь - только в ссылке
        sv.add_exclusion('HDD90', 'B')
        sv.add_exclusion('HDD91', 'Z')
        ov = sv.overview()
        u = {x['disk']: x for x in ov['unique']}
        self.assertEqual(set(u), {'HDD90', 'HDD91'})
        self.assertEqual((u['HDD90']['files'], u['HDD90']['bytes'], u['HDD90']['small']), (2, 900, 2))
        self.assertEqual((u['HDD91']['files'], u['HDD91']['bytes']), (1, 400))
        self.assertTrue(Path(u['HDD90']['list']).exists())
        self.assertTrue(all('нигде нет' not in w for w in ov['warn']))               # не дублируется в «прочих»
        for d in ('HDD90', 'HDD91'):                                                 # база старой версии - из файла списка
            old = sv._unique_from_list(d)
            self.assertEqual({k: old[k] for k in ('files', 'bytes', 'small', 'nohash')},
                             {k: u[d][k] for k in ('files', 'bytes', 'small', 'nohash')})
        self.assertTrue(sv._unique_from_list('HDD99')['missing'])
        page = self.page()
        text = page.text.toPlainText()
        self.assertIn('Файлы, которых больше нигде нет', text)
        self.assertIn('HDD90 — 2 фото и видео, 0,0 ГБ', text)
        self.assertIn('Открыть список', text)
        self.assertIn('мелких картинок', text)
        self.assertNotIn(str(hb.ANSWERS), page.text.toHtml().replace('href="list:', ''))   # длинного пути в тексте нет
        self.assertIn('пересоберите базу', app.attention_html([dict(key='unique', title='x',
                                                                    items=[dict(disk='HDD99', missing=True)])]))
        opened = []
        real = os.startfile
        os.startfile = opened.append
        try:
            from PySide6.QtCore import QUrl
            page.link(QUrl('list:HDD91'))
            page.link(QUrl('tasks:'))
        finally:
            os.startfile = real
        self.assertEqual(opened, [u['HDD91']['list']])
        self.assertEqual(self.win.opened, ['Задания'])

if __name__ == '__main__':
    unittest.main()
