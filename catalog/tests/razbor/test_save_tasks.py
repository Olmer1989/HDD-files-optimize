"""«Разбор носителя»: Сохранение отметок, задания, спорные, место на дисках, сверка оглавления (и замечания этапа 6 - берут TocTest.make_root).

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_save_tasks
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях


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
        with sv_patch('add_marks_batch', side_effect=real) as spy:
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
        with sv_patch('add_marks_batch', side_effect=sv.Refused('проба отказа')):
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
        with sv_patch('add_marks_batch', side_effect=sv.Refused('проба отказа')):
            self.answer = rp.QMessageBox.No
            self.assertFalse(self.w.close())                                    # не записалось - окно не закрылось
        self.assertTrue(any('Отметки не сохранились: проба отказа' in x for x in self.asked), self.asked)
        self.answer = rp.QMessageBox.Yes
        self.p.model.drafts.clear()


class TasksTest(PageBase):
    def setUp(self):
        super().setUp()
        self.toc_calls = []

        def toc(*a, **k):
            self.toc_calls.append(a)
            return TOC_OK
        self.toc_patch = sv_patch('toc_check', toc)       # носителя в тестах нет - сверка отдельно
        self.toc_patch.start()

    def tearDown(self):
        self.toc_patch.stop()
        super().tearDown()

    def made(self):
        return sorted(x.name for x in hb.TASKS.iterdir() if x.name.startswith(SRC)) if hb.TASKS.exists() else []

    def test_prepare_tasks_after_saving_drafts(self):
        self.skip_hash_gate()                                                   # см. test_nohash
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
        self.skip_hash_gate()                                                   # см. test_nohash
        self.mark(('', 'Семейный архив'))
        self.open()
        real = flow_tasks.tasks_dry
        calls = []

        def dry(disk, nums=None):            # между показом и созданием кто-то добавил отметку
            calls.append(disk)
            if len(calls) == 1:
                sv.add_marks_batch(SRC, [('Работа', 'Н2')])
            return real(disk, nums)
        with mock.patch.object(flow_tasks, 'tasks_dry', dry):
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
        with sv_patch('contested', lambda d, f: fake), mock.patch('rescan_dialog.RescanDialog', Fake):
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
        self.skip_hash_gate()                                                   # см. test_nohash
        import directions_page as dp
        dp.save_choice(['Н1', 'Н2'])
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        space = {'HDD45': ('F:', 1000, 10 ** 12, 4096)}
        with sv_patch('disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}), \
                sv_patch('toc_check', lambda *a, **k: TOC_OK):
            self.open()
            self.plan()
            c = self.p.copy_cell
            self.assertEqual(self.p.dest, 'Н1')
            self.assertEqual(c.state, 'short')
            self.assertIn('Не помещается', c.block_texts()['HDD45'])           # в блоке своего диска (этап 12)
            self.assertIn(f'bgcolor="#ffebee"><span style="color:{rp.RED}"><b>Не помещается', c.block_texts()['HDD45'])
            self.assertEqual(c.block_states(), {'HDD45': 'short', 'HDD77': 'unknown'})
            self.assertIn('Место не проверено: HDD77 не подключён', c.block_texts()['HDD77'])
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
        with sv_patch('volumes', return_value={'AAAA0060': str(root)}):
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
        self.skip_hash_gate()                                                   # см. test_nohash
        self.mark(('', 'Н1'))
        root = self.make_root()
        (root / 'Поход 2010' / 'Фото' / '2.jpg').unlink()
        opened = []
        with sv_patch('volumes', return_value={'AAAA0060': str(root)}):
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
        self.skip_hash_gate()                                                   # см. test_nohash
        self.mark(('', 'Н1'))
        answers = [TOC_OK, dict(connected=True, reason='', letter='K:', checked=5, problems=[
            dict(folder='Поход 2010', gone=1, new=0, size=0, date=0, unread=0,
                 examples=dict(gone=['Поход 2010\\Фото\\1.jpg'], new=[], size=[], date=[], unread=[]))])]
        calls = []

        def toc(*a, **k):
            calls.append(a)
            return answers[min(len(calls) - 1, 1)]
        with sv_patch('toc_check', toc):
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
        with sv_patch('disk_space', lambda dd: {d: v for d, v in space.items() if d in dd}), \
                sv_patch('toc_check', lambda *a, **k: TOC_OK):
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
        d = types.SimpleNamespace(num='Н9', disks=('HDD45',))                   # этап 18: направление на один диск
        P = types.SimpleNamespace(part_a={(rz.O_COPY, 'Н9'): [3, G], (rz.O_HAVE, 'Н9'): [2, G // 2],
                                          (rz.O_TYPE, 'Н9'): [1, 5000]}, junk_dir={'Н9': [1, 50]}, disk=SRC)
        label = {'HDD45': 'F:'}.get
        html_, state = rp.dest_cell_html(d, P, cap, rp.EVERY, 0, 0, label)
        self.assertIn(f'Отмечено: весь носитель · 7 файлов · {rp.vol(G + G // 2 + 5050)}', html_)   # сумма трёх строк
        self.assertIn(f'<td style="color:{rp.GREEN}"><b>Копировать на F:</b>', html_)              # > 0 - зелёным
        self.assertIn('Уже есть на F:</td><td align="right">2 файла', html_)
        self.assertIn(f'{rp.SKIP_TEXT}</td><td align="right" style="color:{rp.GRAY}">2 файла', html_)
        self.assertIn('<b>5 КБ</b>', html_)                                       # малое - в КБ
        self.assertIn('Поместится: нужно', html_)
        self.assertEqual(state, 'ok')
        self.assertEqual(html_.count('Показать</a>'), 3)
        P0 = types.SimpleNamespace(part_a={(rz.O_HAVE, 'Н9'): [1, 100]}, junk_dir={}, disk=SRC)
        cap2 = sv.capacity({}, space, {}, disks=['HDD45'])
        html_, state = rp.dest_cell_html(d, P0, cap2, rp.EVERY, 0, 0, label)
        self.assertIn(f'<td style="color:{rp.RED}"><b>Копировать на F:</b>', html_)                # 0 - красным
        self.assertIn(f'<span style="color:{rp.RED}"><b>Копировать нечего: все файлы выбранного в настройках типа уже '
                      'есть на F:</b>', html_)                                    # правка владельца: красная
        self.assertEqual(html_.count('Показать</a>'), 1)                         # только у ненулевой
        self.assertEqual(state, 'none')
        cap3 = sv.capacity({'HDD45': [3, 600 * G]}, space, {}, disks=['HDD45'])
        html_, state = rp.dest_cell_html(d, P, cap3, rp.EVERY, 0, 0, label)
        self.assertIn('Не помещается: нужно', html_)
        self.assertIn('свободно 500,0 ГБ', html_)
        self.assertEqual(state, 'short')
        d2 = types.SimpleNamespace(num='Н9', disks=('HDD77',))
        html_, state = rp.dest_cell_html(d2, P, sv.capacity({'HDD77': [3, G]}, space, {}, disks=['HDD77']), rp.EVERY, 0,
                                         0, lambda x: x)
        self.assertIn(f'<span style="color:{rp.ORANGE}"><b>Место не проверено: HDD77 не подключён', html_)
        self.assertEqual(state, 'unknown')
        self.assertEqual((rp.vol(0), rp.vol(300), rp.vol(5 * 1024 ** 2), rp.vol(2 * G)), ('0 ГБ', '1 КБ', '5,0 МБ',
                                                                                         '2,0 ГБ'))
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
        with sv_patch('volumes', return_value={'AAAA0060': str(root)}):
            res = sv.toc_check(SRC, ['Поход 2010', 'Документы'])
        self.assertEqual(res['problems'], [])
        (root / 'Поход 2010' / 'Фото' / 'desktop.ini').write_bytes(b'1')        # опись его описала бы - «новый»
        with sv_patch('volumes', return_value={'AAAA0060': str(root)}):
            res = sv.toc_check(SRC, ['Поход 2010'])
        self.assertEqual([(p['folder'], p['new']) for p in res['problems']], [('Поход 2010', 1)])


if __name__ == '__main__':
    unittest.main()
