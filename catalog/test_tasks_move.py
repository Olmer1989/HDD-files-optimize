"""Перемещение на источнике для любых дисков-целей и раздел окна «Задания» (15.11.2026).

Запуск из корня проекта:  py -m unittest catalog.test_tasks_move
Временные данные; настоящие диски и задания не используются. Шаблон перемещения запускается настоящий
(Windows PowerShell 5.1) на временной папке вместо диска.
"""
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import hashbase as hb                                       # noqa: E402
import service as sv                                        # noqa: E402
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
import tasks_page as tp                                     # noqa: E402
from ui.tasks import model_load                             # noqa: E402 - подмены там, где имя используется
from hb_cmd import mvlist as mv                             # noqa: E402
from test_hashbase import LOG_HEAD, NS, S, Base, make_disk  # noqa: E402

QAPP = QApplication.instance() or QApplication([])
OK = 'скопирован, размер и SHA-256 совпали'
OK_NOHASH = 'скопирован, размер совпал'
DOC_SHA = 'ab' * 32                                         # хеш прочитанного у файла без хеша в описи
MOVE_SUFFIX = ' - разложить на источнике'                 # имя задания mvlist --task по умолчанию (команда)
DST = 'L:\\ПЕРЕНОС с других дисков\\HDD90\\'


def args(**kw):
    a = dict(disk=None, name=None, folder=None, dry=False, task=None, allow_main=False, recheck=None, task_root='scripts')
    a.update(kw)
    return NS(**a)


class FolderNameTest(unittest.TestCase):
    def test_names_for_any_targets(self):
        self.assertEqual(hb.moved_folder(['HDD45', 'HDD77']), 'ПЕРЕНЕСЕНО → 45 и 77')       # прежние имена
        self.assertEqual(hb.moved_folder(['HDD45']), 'ПЕРЕНЕСЕНО → только 45')
        self.assertEqual(hb.moved_folder(['HDD77']), 'ПЕРЕНЕСЕНО → только 77')
        self.assertEqual(hb.moved_folder(['HDD78']), 'ПЕРЕНЕСЕНО → 78')
        self.assertEqual(hb.moved_folder(['HDD78', 'HDD45']), 'ПЕРЕНЕСЕНО → 45 и 78')
        self.assertEqual(hb.moved_folder(['HDD78', 'HDD77', 'HDD45']), 'ПЕРЕНЕСЕНО → 45, 77 и 78')
        self.assertEqual(hb.moved_folder(['HDD09', 'HDD100']), 'ПЕРЕНЕСЕНО → 09 и 100')       # по номеру, не по тексту
        self.assertEqual(hb.moved_folder(['Flash05']), 'ПЕРЕНЕСЕНО → Flash05')
        for targets, old in hb.MOVED_FOLDER.items():                                           # совместимость
            self.assertEqual(hb.moved_folder(targets), old)

    def test_base_understands_new_names(self):
        p = 'ПЕРЕНЕСЕНО → 45, 77 и 78\\Котуй 2026\\Валере\\1.jpg'
        self.assertTrue(hb.is_moved_dir('ПЕРЕНЕСЕНО → 78'))
        self.assertEqual(hb.original_path(p), 'Котуй 2026\\Валере\\1.jpg')
        self.assertEqual(hb.decision_of(p, [('Котуй 2026', 'раздел: Работа')]), 'раздел: Работа')
        self.assertEqual(hb.moved_rel('F:\\Котуй 2026\\Валере\\1.jpg', 'F:\\ПЕРЕНЕСЕНО → 78\\Котуй 2026\\Валере\\1.jpg'),
                         ('Котуй 2026\\Валере\\1.jpg', 'ПЕРЕНЕСЕНО → 78\\Котуй 2026\\Валере\\1.jpg'))


class MoveAnyTargetTest(Base):
    """mvlist для цели не из 45/77: HDD90 -> HDD91 (тематический диск)."""

    def setUp(self):
        super().setUp()
        for job in self.scans.glob('*/*'):                     # описи - 2020 год, журналы копирования - 2025
            for fn in ('inventory.sqlite', 'hashes.sqlite'):
                os.utime(job / fn, (1580000000, 1580000000))
        tpl = self.out / '_ШАБЛОН перемещения'
        tpl.mkdir()
        real = Path(__file__).resolve().parents[1] / 'Каталог дисков' / '_ШАБЛОН перемещения'
        for name in ('Переместить.ps1', 'Запустить.cmd'):
            shutil.copy2(real / name, tpl / name)

    def copy_task(self, name, rows, logs=(), src=('HDD90', 'AAAA0090'), target=('HDD91', 'AAAA0091')):
        """Задание копирования в «Запускаемые скрипты»: rows - (путь, размер, sha); logs - {имя журнала: строки}."""
        t = hb.TASKS / name
        t.mkdir(parents=True)
        (t / 'тома.tsv').write_text('\t'.join(src) + '\n' + '\t'.join(target) + '\n', encoding='utf-8')
        (t / 'список.tsv').write_text(''.join(f'{target[0]}\t{p}\t{s}\tф\t{h}\n' for p, s, h in rows), encoding='utf-8')
        for log, lines in dict(logs).items():
            (t / log).write_text('\t'.join(LOG_HEAD) + '\n' + ''.join('\t'.join(x) + '\n' for x in lines),
                                 encoding='utf-8-sig')
        return t

    def line(self, res, path, size, sha, target='HDD91'):
        return ('10:00:01', target, res, str(size), sha, 'K:\\' + path, DST + path)

    def done_task(self):
        rows = [('A\\1.jpg', 100, S[1]), ('A\\2.jpg', 200, S[2]), ('A\\sub\\3.mp4', 300, S[3]),
                ('A\\заметки.doc', 10, ''), ('B\\5.jpg', 500, S[5])]
        logs = {'Журнал копирования 2025-01-01 00-00-00.tsv': [
            self.line(OK, 'A\\1.jpg', 100, S[1]), self.line(OK, 'A\\2.jpg', 200, S[2]),
            self.line(OK, 'A\\sub\\3.mp4', 300, S[3]), self.line(OK_NOHASH, 'A\\заметки.doc', 10, DOC_SHA),
            self.line('ОШИБКА: диск не отвечает', 'B\\5.jpg', 500, '')]}
        return self.copy_task('1 - HDD90 на 91', rows, logs)

    def lines(self, task):
        return {tuple(x.split('\t')[i] for i in (0, 3)) for x in
                (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()}

    def test_task_mode_any_target_keeps_paths(self):
        self.done_task()
        # второе задание (не запускалось) тоже берёт A\2.jpg - на другой диск: A\2.jpg ждёт его
        self.copy_task('2 - HDD90 на 45', [('A\\2.jpg', 200, S[2])], target=('HDD45', 'AAAA0045'))
        self.quiet(mv.cmd_mvlist, args(task='1 - HDD90 на 91', dry=True))
        self.assertIn('ПЕРЕНЕСЕНО → 91\\<тот же путь>: 3 файлов', self.printed)
        self.assertIn('ждут задания «2 - HDD90 на 45»: 1 файлов', self.printed)
        self.assertIn('копирование не удалось', self.printed)                   # B\5.jpg - ошибка
        self.assertFalse((hb.TASKS / ('1 - HDD90 на 91' + MOVE_SUFFIX)).exists())          # --dry ничего не создаёт
        self.quiet(mv.cmd_mvlist, args(task='1 - HDD90 на 91'))
        task = hb.TASKS / ('1 - HDD90 на 91' + MOVE_SUFFIX)
        self.assertEqual(self.lines(task), {('A\\1.jpg', 'ПЕРЕНЕСЕНО → 91'), ('A\\sub\\3.mp4', 'ПЕРЕНЕСЕНО → 91'),
                                            ('A\\заметки.doc', 'ПЕРЕНЕСЕНО → 91')})   # файл без хеша - по журналу
        doc = next(x.split('\t') for x in (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()
                   if x.startswith('A\\заметки'))
        self.assertEqual(doc[4], DOC_SHA.upper())
        # настоящий шаблон на временной папке: все папки и подпапки сохранены
        disk = self.tmp / 'диск HDD90'
        for rel, size in (('A\\1.jpg', 100), ('A\\2.jpg', 200), ('A\\sub\\3.mp4', 300), ('A\\заметки.doc', 10)):
            p = disk / rel.replace('\\', '/')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * size)
            os.utime(p, (0, 0))
        proc = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(task / 'Переместить.ps1'), '-TestRoots', f'HDD90={disk}'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode('utf-8', errors='replace'))
        moved = disk / 'ПЕРЕНЕСЕНО → 91'
        self.assertTrue((moved / 'A' / 'sub' / '3.mp4').exists())
        self.assertTrue((moved / 'A' / 'заметки.doc').exists())
        self.assertTrue((disk / 'A' / '2.jpg').exists())                         # ждёт задания 2 - на месте
        self.assertFalse((disk / 'A' / '1.jpg').exists())
        # база: новый путь, решение владельца по исходному пути действует
        paths = {r[0] for r in self.db().execute("select path from files where disk='HDD90'")}
        self.assertIn('ПЕРЕНЕСЕНО → 91\\A\\sub\\3.mp4', paths)
        self.assertNotIn('A\\sub\\3.mp4', paths)
        self.decide('HDD90\tA\\sub\tраздел: Работа\tпо исходному пути')
        self.assertEqual(hb.decision_of('ПЕРЕНЕСЕНО → 91\\A\\sub\\3.mp4', hb.decisions_for('HDD90')), 'раздел: Работа')
        self.quiet(mv.cmd_mvlist, args(disk='HDD90', name='Ещё', dry=True))       # перенесённое второй раз не берётся
        self.assertNotIn('ПЕРЕНЕСЕНО → 91\\<тот же путь>', self.printed)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)

    def test_unfinished_task_is_refused(self):
        self.copy_task('Недоделано', [('A\\1.jpg', 100, S[1]), ('A\\2.jpg', 200, S[2])],
                       {'Журнал копирования 2025-01-01 00-00-00.tsv': [self.line(OK, 'A\\1.jpg', 100, S[1])]})
        with self.assertRaises(SystemExit) as e:
            self.quiet(mv.cmd_mvlist, args(task='Недоделано', dry=True))
        self.assertIn('обработано 1 из 2', str(e.exception))

    def test_resume_after_q_still_confirmed(self):
        # первый запуск скопировал файл, после Q повторный запуск написал «уже есть»: с 15.11.2026 сборка оставляет C
        self.copy_task('Повтор', [('A\\1.jpg', 100, S[1])],
                       {'Журнал копирования 2025-01-01 00-00-00.tsv': [self.line(OK, 'A\\1.jpg', 100, S[1])],
                        'Журнал копирования 2025-01-02 00-00-00.tsv': [self.line('уже есть', 'A\\1.jpg', 100, '')]})
        self.quiet(mv.cmd_mvlist, args(task='Повтор', dry=True))
        printed = self.printed
        self.assertEqual(self.row('HDD91', 'ПЕРЕНОС с других дисков\\HDD90\\A\\1.jpg')[1], hb.EV_COPY)   # не понижено
        self.assertIn('ПЕРЕНЕСЕНО → 91\\<тот же путь>: 1 файлов', printed)
        # «уже есть» без своего «скопирован» в том же задании подтверждением не считается
        shutil.rmtree(hb.TASKS / 'Повтор')
        self.copy_task('Только уже есть', [('A\\1.jpg', 100, S[1])],
                       {'Журнал копирования 2025-01-03 00-00-00.tsv': [self.line('уже есть', 'A\\1.jpg', 100, '')]})
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.quiet(mv.cmd_mvlist, args(task='Только уже есть', dry=True))
        self.assertIn('Ждут: копия ещё не подтверждена - 1 файлов', self.printed)

    def test_main_disk_source_needs_consent(self):
        self.copy_task('С 45', [('X\\2.jpg', 200, S[2])],
                       {'Журнал копирования 2025-01-01 00-00-00.tsv': [
                           ('10:00:01', 'HDD91', OK, '200', S[2], 'H:\\X\\2.jpg', 'L:\\ПЕРЕНОС с других дисков\\HDD45\\X\\2.jpg')]},
                       src=('HDD45', 'AAAA0045'))
        with self.assertRaises(SystemExit) as e:
            self.quiet(mv.cmd_mvlist, args(task='С 45'))
        self.assertIn('главный архивный диск', str(e.exception))
        self.quiet(mv.cmd_mvlist, args(task='С 45', dry=True))
        self.assertIn('ВНИМАНИЕ: HDD45 - главный архивный диск', self.printed)
        self.assertFalse((hb.TASKS / ('С 45' + MOVE_SUFFIX)).exists())
        self.quiet(mv.cmd_mvlist, args(task='С 45', allow_main=True))
        self.assertEqual(self.lines(hb.TASKS / ('С 45' + MOVE_SUFFIX)), {('X\\2.jpg', 'ПЕРЕНЕСЕНО → 91')})

    def test_long_path_moves(self):
        # 17.11.2026: ограничение «путь после переноса не длиннее 259» снято (шаблон перемещения 1.3 - через \\?\)
        long = 'Д' * 120 + '\\' + 'е' * 125 + '.jpg'                  # 250 символов: после переноса > 259
        make_disk(self.scans, 'HDD92', 'AAAA0092', [(long, 700, S[7]), ('Коротко\\7.jpg', 700, S[8])])
        for job in self.scans.glob('HDD92*/*'):
            for fn in ('inventory.sqlite', 'hashes.sqlite'):
                os.utime(job / fn, (1580000000, 1580000000))
        self.copy_task('Длинные', [(long, 700, S[7]), ('Коротко\\7.jpg', 700, S[8])],
                       {'Журнал копирования 2025-01-01 00-00-00.tsv': [
                           ('1', 'HDD91', OK, '700', S[7], 'K:\\' + long, 'L:\\П\\' + long),
                           ('2', 'HDD91', OK, '700', S[8], 'K:\\Коротко\\7.jpg', 'L:\\П\\Коротко\\7.jpg')]},
                       src=('HDD92', 'AAAA0092'))
        self.quiet(mv.cmd_mvlist, args(task='Длинные', dry=True))
        self.assertNotIn('длиннее', self.printed)
        self.assertIn('Можно перенести: 2 файлов', self.printed)
        self.quiet(mv.cmd_mvlist, args(task='Длинные'))
        self.assertIn((long, 'ПЕРЕНЕСЕНО → 91'), self.lines(hb.TASKS / ('Длинные' + MOVE_SUFFIX)))

    def test_recheck_sees_new_copy_task(self):
        self.done_task()
        self.quiet(mv.cmd_mvlist, args(task='1 - HDD90 на 91'))
        name = '1 - HDD90 на 91' + MOVE_SUFFIX
        self.quiet(mv.cmd_mvlist, args(recheck=name))
        self.assertIn('по-прежнему верны', self.printed)
        self.copy_task('3 - новое на 45', [('A\\1.jpg', 100, S[1])], target=('HDD45', 'AAAA0045'))
        with self.assertRaises(SystemExit) as e:
            self.quiet(mv.cmd_mvlist, args(recheck=name))
        self.assertIn('Соберите задание заново', str(e.exception))


# ---------- раздел «Задания» ----------

class _Bar:
    def showMessage(self, *a):                                   # noqa: N802
        pass

    def clearMessage(self):                                      # noqa: N802
        pass


class _Bg:
    def run(self, fn, *a, ok=None, quiet=False):
        res = fn(*a)
        if ok:
            ok(res)


class FakeWin:
    def __init__(self):
        self.bg = _Bg()
        self._bar = _Bar()

    def statusBar(self):                                         # noqa: N802
        return self._bar


def copy_log(task, stamp, lines):
    (task / f'Журнал копирования {stamp}.tsv').write_text(
        '\t'.join(LOG_HEAD) + '\n' + ''.join('\t'.join(x) + '\n' for x in lines), encoding='utf-8-sig')


class TasksPageTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='tasks_page_'))
        self.root = self.tmp / 'Запускаемые скрипты'
        self.root.mkdir()
        self.mb = 1024 ** 2
        self._load = tp.load

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, name, n=4, size=None, log=None, stamp='2026-11-15 10-00-00', mark=False, toma='HDD58\tS58\nHDD78\tS78\n'):
        t = self.root / name
        t.mkdir()
        size = size or 100 * self.mb
        (t / 'тома.tsv').write_text(toma, encoding='utf-8')
        (t / 'список.tsv').write_text(''.join(f'HDD78\tP\\{i}.mp4\t{size}\tф\t\n' for i in range(n)), encoding='utf-8')
        (t / 'Запустить.cmd').write_text('rem', encoding='utf-8')
        if log is not None:
            copy_log(t, stamp, log)
        if mark:
            sv.mark_task_move(t, 'HDD58')
        return t

    def rows(self, running=(), now=None):
        with sv_patch('running_scripts', return_value=[f'powershell -File "{self.root / r}\\Копировать.ps1"'
                                                                    for r in running]), \
                sv_patch('volumes', return_value={'S78': 'L:'}), \
                mock.patch.object(model_load, 'serial_names', return_value={'S58': 'HDD58', 'S78': 'HDD78'}):
            return self._load(self.root, now=now)

    def test_progress_and_eta_from_journal(self):
        size = 100 * self.mb
        lines = [(f'10:0{i}:00', 'HDD78', OK, str(size), 'h', f'D:\\P\\{i}.mp4', f'L:\\П\\P\\{i}.mp4') for i in range(1, 3)]
        self.make('4 - HDD58 на L', n=10, log=lines)
        start = time.mktime((2026, 11, 15, 10, 0, 0, 0, 0, -1))
        r = self.rows(running=['4 - HDD58 на L'], now=start + 200)[0]
        self.assertEqual(r['state'], 'идёт')
        self.assertEqual((r['done'], r['total']), (2, 10))
        self.assertAlmostEqual(r['speed'], 2 * size / 200)                        # байты этого запуска / время до «сейчас»
        self.assertAlmostEqual(r['eta'], 8 * size / (2 * size / 200))            # 800 с
        self.assertEqual(r['eta_text'], '~14 мин')
        self.assertEqual(r['disks'], 'HDD58 → HDD78 (L:)')
        self.assertEqual(tp.state_text(r)[0], 'Идёт · 1,0 МБ/с · осталось 14 мин')     # скорость и остаток - в «Состоянии»
        self.assertEqual(tp.what_where(r), ('4 - HDD58 на L', '→ HDD58 → HDD78 (L:)'))   # задание без разбор.json
        self.assertEqual(tp.fmt_eta(4200), '~1 ч 10 мин')

    def test_midnight_and_small_amount(self):
        lines = [('23:59:50', 'HDD78', OK, str(self.mb), 'h', 'D:\\P\\0.mp4', 'L:\\П\\0.mp4'),
                 ('00:00:20', 'HDD78', OK, str(self.mb), 'h', 'D:\\P\\1.mp4', 'L:\\П\\1.mp4')]
        self.make('Ночь', n=3, size=self.mb, log=lines, stamp='2026-11-15 23-59-30')
        start = time.mktime((2026, 11, 15, 23, 59, 30, 0, 0, -1))
        r = self.rows(running=['Ночь'], now=start + 400)[0]
        self.assertAlmostEqual(r['ago'], 400 - 50)                                # последняя строка - через полночь
        self.assertEqual(r['eta_text'], 'оценка появится позже')                  # меньше 10 МБ скопировано

    def test_checkboxes_count_and_launch(self):
        lines = [(f'10:00:0{i}', 'HDD78', OK, str(100 * self.mb), 'h', f'D:\\P\\{i}.mp4', 'L:\\x') for i in range(4)]
        self.make('5 - готовое', log=lines, mark=True)
        for i in range(6, 9):
            self.make(f'{i} - ждёт', toma=f'HDD{i}0\tS{i}0\nHDD78\tS78\n')
        page = tp.TasksPage(FakeWin())
        page.render(self.rows())
        QAPP.processEvents()
        self.assertFalse(hasattr(page, 'offer_move'))                             # старой «раскладки» в окне нет
        self.assertEqual([c.text() for c in page.chips if c.text()],
                         ['Идёт: 0', 'Ждут запуска: 3', 'Прервано, с ошибками: 0', 'Готово: 1'])
        self.assertEqual(page.t.rowCount(), 3)                                    # готовое - не в таблице, а в «Готово»
        self.assertEqual(page.done_btn.text(), '▸ Готово (1)')
        self.assertEqual(page.t.item(0, 2).text(), 'Ждёт запуска')
        self.assertEqual(page.run_btn.text(), 'Запустить отмеченные (0)')
        page.t.item(0, 0).setCheckState(Qt.Checked)
        page.t.item(1, 0).setCheckState(Qt.Checked)
        self.assertEqual(page.checked, {'6 - ждёт', '7 - ждёт'})
        self.assertEqual(page.run_btn.text(), 'Запустить отмеченные (2)')          # число обновляется сразу
        page.render(self.rows())                                                  # галочки переживают обновление
        self.assertEqual(page.t.item(0, 0).checkState(), Qt.Checked)
        self.assertEqual(page.run_btn.text(), 'Запустить отмеченные (2)')
        # два задания пишут на один диск (HDD78): вопрос «по очереди / все сразу» - как раньше
        started, asked = [], []
        page.start_file = started.append
        page.choose = lambda text, buttons: asked.append((text, buttons)) or 'Все сразу'
        page.launch_checked()
        self.assertIn('общий диск', asked[0][0])
        self.assertEqual(asked[0][1][0], 'По очереди')                            # при общем диске рекомендовано по очереди
        self.assertEqual([Path(x).parent.name for x in started], ['6 - ждёт', '7 - ждёт'])
        # «Запустить все по очереди»: все ждущие - одним .cmd очереди (тот же путь, что «По очереди»)
        started.clear()
        asks = []
        page.ask = lambda text: asks.append(text) or True
        with mock.patch.object(tp.hb, 'BASE_DIR', self.tmp):
            page.launch_all()
        self.assertIn('по очереди в одном окне', asks[0])
        self.assertEqual([Path(x).name for x in started], ['очередь заданий.cmd'])
        self.assertEqual(page.queue, ['6 - ждёт', '7 - ждёт', '8 - ждёт'])
        page.render(self.rows())
        self.assertEqual(page.t.item(2, 2).text(), 'В очереди')
        self.assertIn('Ждут запуска: 3 (в очереди 3)', [c.text() for c in page.chips])

    def test_old_buttons_removed(self):
        page = tp.TasksPage(FakeWin())
        page.render([])
        texts = {b.text() for b in page.findChildren(tp.QPushButton)}
        for gone in ('Разложить на источнике…', 'Сводка для чата', 'По очереди', 'Открыть папку'):
            self.assertNotIn(gone, texts)
        for there in ('Обновить', 'Запустить отмеченные (0)', 'Запустить все по очереди', 'Открыть журнал',
                      'Открыть папку задания'):
            self.assertIn(there, texts)
        labels = ' '.join(x.text() for x in page.findChildren(tp.QLabel))
        self.assertNotIn('ПЕРЕНЕСЕНО', labels)
        self.assertIn(tp.INTRO, labels)
        self.assertIn(tp.RUN_NOTE, labels)
        self.assertIn(tp.MOVE_EMPTY, labels)

    def test_move_blocked_while_copy_from_same_source_runs(self):
        cp = dict(task='К', kind='копирование', state='идёт', src_serial='S58', serials={'S58', 'S78'})
        mvr = dict(task='П', kind='перемещение', state='не запускалось', src_serial='S58', serials={'S58'})
        self.assertTrue(tp.move_blocks([mvr], [cp, mvr]))
        self.assertFalse(tp.move_blocks([mvr], [dict(cp, src_serial='S09', serials={'S09'}), mvr]))
        self.assertEqual(tp.conflicts([cp, dict(mvr, serials={'S99'})]), [])

    def test_queue_cmd_runs_one_after_another(self):
        dirs = []
        for name in ('Первое — тест', 'Второе задание'):
            d = self.root / name
            d.mkdir()
            (d / 'Запустить.cmd').write_bytes(b'@echo off\r\necho %~n0 >> "%~dp0..\\order.txt"\r\n'
                                              b'echo ok > "%~dp0done.txt"\r\n')
            dirs.append(d)
        q = tp.queue_cmd(dirs, self.tmp / 'очередь заданий.cmd')
        p = subprocess.run(['cmd.exe', '/c', str(q)], input=b'\r\n', stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout.decode('cp866', errors='replace'))
        self.assertTrue(all((d / 'done.txt').exists() for d in dirs), p.stdout.decode('utf-8', errors='replace'))
        self.assertEqual(len((self.root / 'order.txt').read_text(encoding='ascii', errors='replace').splitlines()), 2)


if __name__ == '__main__':
    unittest.main()
