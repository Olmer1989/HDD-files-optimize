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
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н3'], disks_only=True)
        dlg.name.setText('Сафари')                                                   # прежнее имя другого направления
        before = hb.DIRECTIONS.read_bytes()
        dlg.write()
        self.assertTrue(wait(lambda: 'Нельзя сохранить' in dlg.view.toPlainText()))
        self.assertIn('Сафари', dlg.view.toPlainText())
        self.assertTrue(dlg.b_write.isEnabled())
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        self.assertEqual(self.win.errors, [])                                        # отказ - в диалоге, не ошибкой окна

    def test_dialog_ack_for_removed_disk(self):
        t = hb.TASKS / 'HDD90 — A — Работа'
        t.mkdir(parents=True)
        (t / 'список.tsv').write_text('HDD91\tA\\1.jpg\t100\tс хешем\t' + 'a' * 64 + '\n', encoding='utf-8')
        (t / 'разбор.json').write_text(json.dumps({'носитель': 'HDD90', 'направление': 'Н2', 'обязательные диски': ['HDD91'],
                                                   'цели': ['HDD91']}, ensure_ascii=False), encoding='utf-8')
        s = self.section()
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н2'])
        items = {dlg.disks.item(i).data(Qt.UserRole): dlg.disks.item(i) for i in range(dlg.disks.count())}
        self.assertEqual(items['HDD91'].checkState(), Qt.Checked)
        items['HDD91'].setCheckState(Qt.Unchecked)
        items['HDD90'].setCheckState(Qt.Checked)
        asked = []
        dlg.confirm_hook = lambda lines, ack: asked.append((lines, ack)) or (False, False)    # «Отмена»
        before = hb.DIRECTIONS.read_bytes()
        dlg.write()
        self.assertTrue(wait(lambda: asked and dlg.b_write.isEnabled()))
        lines, ack = asked[0]
        text = '\n'.join(lines)
        self.assertEqual(ack, ['HDD91'])                                            # нужна галочка «Понимаю…»
        self.assertIn('не запускалось', text)                                       # журналов нет
        self.assertIn('направлению больше не засчитывается', text)                  # п. F
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        dlg.confirm_hook = lambda lines, ack: (True, True)                          # «Понимаю…» и «Сохранить»
        dlg.write()
        self.assertTrue(wait(lambda: sv.directions()['Н2'].disks == ('HDD90',)))
        cd = dp.ConfirmDialog(s, ['строка'], ['HDD91'])                              # окно переспроса: без галочки нельзя
        self.assertFalse(cd.ok.isEnabled())
        cd.ack.setChecked(True)
        self.assertTrue(cd.ok.isEnabled())
        self.assertIn('больше не засчитывается', cd.ack.text())

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
        items = {dlg2.disks.item(i).data(Qt.UserRole): dlg2.disks.item(i) for i in range(dlg2.disks.count())}
        items['HDD77'].setCheckState(Qt.Unchecked)                                  # переспрос будет (данные на 77)

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
        """Этап 5, п. 1: оранжевый - назначен (бледный - не подключён), зелёный - подключён и свободен, серый - нет."""
        import disk_ui
        self.assertEqual(disk_ui.disk_color(True, True), (disk_ui.ASSIGNED_ON, True))
        self.assertEqual(disk_ui.disk_color(False, True), (disk_ui.ASSIGNED_OFF, False))
        self.assertEqual(disk_ui.disk_color(True, False), ('#1b5e20', True))
        self.assertEqual(disk_ui.disk_color(False, False), ('#8a8a8a', False))
        s = self.section()
        s.data['disks'] = [dict(r, letter='Z:') if r['disk'] in ('HDD45', 'HDD90') else r for r in s.data['disks']]
        s.data['by'] = {r['disk']: r for r in s.data['disks']}
        s.render(s.data)
        html = s.t.cellWidget(self.row_of(s, 'Н1'), 3).text()
        self.assertIn(f'<b style="color:{disk_ui.ASSIGNED_ON}">● HDD45', html)      # назначен и подключён
        self.assertIn(f'<span style="color:{disk_ui.ASSIGNED_OFF}">HDD77', html)    # назначен, не подключён
        dlg = dp.DirectionDialog(s, s.data, s.data['dirs']['Н2'])
        it = {dlg.disks.item(i).data(Qt.UserRole): dlg.disks.item(i) for i in range(dlg.disks.count())}
        color = lambda d: it[d].data(Qt.ForegroundRole).color().name()
        self.assertEqual(color('HDD45'), disk_ui.ASSIGNED_ON)                       # чужой (Н1), подключён
        self.assertIn('у Н1 «Семейный архив»', it['HDD45'].text())
        self.assertEqual(color('HDD77'), disk_ui.ASSIGNED_OFF)                      # чужой, не подключён
        self.assertEqual(color('HDD91'), disk_ui.ASSIGNED_OFF)                      # свой, не подключён
        self.assertEqual(color('HDD90'), '#1b5e20')                                 # свободен, подключён
        self.assertEqual(dlg.disks.item(0).data(Qt.UserRole), 'HDD45')              # подключённые - сверху
        s.data['disks'] = [dict(r, letter='') if r['disk'] == 'HDD90' else r for r in s.data['disks']]
        dlg2 = dp.DirectionDialog(s, s.data, s.data['dirs']['Н2'])
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


if __name__ == '__main__':
    unittest.main()
