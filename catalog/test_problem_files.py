"""Проблемные файлы в шаблонах копирования (2.7) и перемещения (1.3), решение владельца 17.11.2026: длинные пути,
занятые файлы, нет прав, имена, которые Windows не разрешает, сбойные сектора (имитация). Только временные папки.

Запуск из корня проекта:  py -m unittest catalog.test_problem_files
Шаблоны запускаются в Windows PowerShell 5.1 с параметром -TestRoots (папки вместо дисков).
"""
import getpass
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hb_core.consts import copy_ok                           # noqa: E402  (разбор строк журнала сборкой)
from hb_core.paths import copy_template                      # noqa: E402  (шаблон 2.8 - главный и части)

BASE = Path(__file__).resolve().parent.parent / 'Каталог дисков'
COPY_TPL = BASE / '_ШАБЛОН копирования' / 'Копировать.ps1'
MOVE_TPL = BASE / '_ШАБЛОН перемещения' / 'Переместить.ps1'
DEST = 'ПЕРЕНОС с других дисков'
SEG = 'длинная папка ' + 'д' * 50                             # 64 знака: пять таких - путь длиннее 260
ROOT45 = 'Скопировано на 45'


def L(p):
    """Путь для Python без предела 260 знаков (в тесте; шаблоны делают то же сами)."""
    return '\\\\?\\' + str(p)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def put(path, data):
    os.makedirs(L(os.path.dirname(path)), exist_ok=True)
    with open(L(path), 'wb') as f:
        f.write(data)


def exists(path):
    return os.path.exists(L(path))


def read(path):
    with open(L(path), 'rb') as f:
        return f.read()


@unittest.skipUnless(sys.platform == 'win32' and COPY_TPL.exists(), 'нужны Windows и шаблон копирования')
class CopyProblems(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tpl_problem_'))
        self.task = self.tmp / 'task'; self.task.mkdir()
        self.src = str(self.tmp / 'src'); self.dst = str(self.tmp / 'dst')
        os.makedirs(self.src); os.makedirs(self.dst)
        copy_template(COPY_TPL.parent, self.task, COPY_TPL.name, extra=())     # главный и части (шаблон 2.8)

    def tearDown(self):
        subprocess.run(['cmd', '/c', 'rd', '/s', '/q', L(self.tmp)], capture_output=True)

    def run_copy(self, lines, *extra, src=None, dst=None, keep=False):
        """keep - прежние журналы остаются (как при повторном запуске задания), под другим именем: время в имени -
        до секунды, повтор в ту же секунду иначе перезаписал бы журнал."""
        (self.task / 'тома.tsv').write_text('HDD90\tAAAA0090\nHDD45\tAAAA0045\n', encoding='utf-8-sig')
        (self.task / 'список.tsv').write_text(''.join(x + '\n' for x in lines), encoding='utf-8-sig')
        for n, old in enumerate(list(self.task.glob('Журнал*.tsv')) + list(self.task.glob('Проблемные файлы*.txt'))):
            if keep and old.name.startswith('Журнал копирования 2'):
                old.rename(old.with_name(f'Журнал копирования прежний {n}.tsv'))
            elif not keep or old.name.startswith('Проблемные'):
                old.unlink()
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / COPY_TPL.name),
                            '-TestRoots', f'HDD90={src or self.src};HDD45={dst or self.dst}', *extra],
                           capture_output=True, timeout=180)
        logs = list(self.task.glob('Журнал копирования 2*.tsv'))
        rows = [x.split('\t') for x in logs[0].read_text(encoding='utf-8-sig').splitlines()[1:]] if logs else []
        probs = list(self.task.glob('Проблемные файлы*.txt'))
        prob = probs[0].read_text(encoding='utf-8-sig') if probs else ''
        return p, rows, prob

    def row(self, rel, data):
        put(os.path.join(self.src, rel), data)
        return f'HDD45\t{rel}\t{len(data)}\tтест\t{sha(data)}'

    def test_long_paths_source_and_target(self):
        rel = '\\'.join([SEG] * 4) + '\\фото.jpg'
        deep_dst = os.path.join(self.dst, *([SEG] * 2))
        os.makedirs(L(deep_dst))
        line = self.row(rel, b'L' * 1000)
        self.assertGreater(len(os.path.join(self.src, rel)), 300)
        p, rows, prob = self.run_copy([line], dst=deep_dst)
        out = p.stdout.decode('cp866', errors='replace')
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(rows[0][2], 'скопирован, размер и SHA-256 совпали')
        final = os.path.join(deep_dst, DEST, 'HDD90', rel)
        self.assertGreater(len(final), 400)
        self.assertEqual(read(final), b'L' * 1000)
        self.assertEqual((rows[0][5], rows[0][6]), (os.path.join(self.src, rel), final))   # журнал - без \\?\
        self.assertEqual(prob, '')
        p, rows, _ = self.run_copy([line], dst=deep_dst)                     # повтор: копия найдена и сверена
        self.assertEqual(p.returncode, 0)
        self.assertEqual(rows[0][2], 'уже есть, SHA-256 совпал')

    def test_unc_long_path(self):
        unc = '\\\\localhost\\' + self.src[0] + '$' + self.src[2:]
        if not os.path.isdir(unc):
            self.skipTest('административный общий ресурс \\\\localhost\\C$ недоступен - \\\\?\\UNC\\ проверен только чтением кода')
        rel = '\\'.join([SEG] * 4) + '\\сеть.jpg'
        p, rows, _ = self.run_copy([self.row(rel, b'U' * 10)], src=unc)
        self.assertEqual(p.returncode, 0, p.stdout.decode('cp866', errors='replace'))
        self.assertEqual(rows[0][2], 'скопирован, размер и SHA-256 совпали')
        self.assertTrue(rows[0][5].startswith('\\\\localhost\\'))

    def test_busy_files_do_not_stop_copying(self):
        lines = [self.row(f'A\\{i}.jpg', bytes([i]) * 50) for i in range(6)] + [self.row('A\\ok.jpg', b'K' * 50)]
        held = [open(os.path.join(self.src, 'A', f'{i}.jpg'), 'r+b') for i in range(6)]    # другая программа пишет
        try:
            p, rows, prob = self.run_copy(lines)
        finally:
            for h in held:
                h.close()
        self.assertEqual(p.returncode, 1, p.stdout.decode('cp866', errors='replace'))      # не всё, но не авария
        self.assertEqual(len(rows), 7)
        for r in rows[:6]:
            self.assertEqual(r[2], 'ОШИБКА: файл занят другой программой - закройте её и нажмите «Повторить копирование»')
            self.assertFalse(copy_ok(r[2]))
        self.assertEqual(rows[6][2], 'скопирован, размер и SHA-256 совпали')   # 6 занятых подряд - не «сбой диска»
        self.assertIn('Файл занят другой программой', prob)
        self.assertFalse(exists(os.path.join(self.dst, DEST, 'HDD90', 'A', '0.jpg')))

    def test_no_read_rights(self):
        line = self.row('A\\закрыт.jpg', b'R' * 20)
        f = os.path.join(self.src, 'A', 'закрыт.jpg')
        user = getpass.getuser()
        r = subprocess.run(['icacls', f, '/deny', f'{user}:(R)'], capture_output=True)
        try:
            try:
                open(f, 'rb').close()
                self.skipTest('не удалось закрыть чтение временного файла (icacls)')
            except PermissionError:
                pass
            p, rows, prob = self.run_copy([line])
        finally:
            subprocess.run(['icacls', f, '/remove:d', user], capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(p.returncode, 1)
        self.assertTrue(rows[0][2].startswith('ОШИБКА: нет прав на чтение (файл или его папка на источнике) - программа права не меняет'),
                        rows[0][2])
        self.assertIn('Безопасность - Дополнительно - Владелец', prob)
        self.assertIn('от имени администратора', prob)

    def test_windows_forbidden_names(self):
        lines = [self.row('A\\a.', b'1' * 11), self.row('A\\b ', b'2' * 12), self.row('A\\CON.jpg', b'3' * 13),
                 self.row('Отпуск.\\1.jpg', b'4' * 14), self.row('A\\c_', b'5' * 15), self.row('A\\c.', b'5' * 15),
                 self.row('A\\e.', b'8' * 15), self.row('A\\e ', b'8' * 15),
                 self.row('A\\CON.2026.jpg', b'9' * 9), self.row('A\\nul.txt', b'0' * 9), self.row('A\\COM0.jpg', b'c' * 9),
                 self.row('A\\CON .txt', b's' * 9), self.row('...\\1.jpg', b'p' * 9), self.row('A\\d.', b'D' * 9),
                 self.row('A\\папка_цели.jpg', b'P' * 9),
                 'HDD45\tA\\x?y.jpg\t10\tтест\t' + 'AB' * 32, 'HDD45\tA\\a:b.jpg\t10\tтест', 'HDD45\tC:1.jpg\t10\tтест',
                 self.row('A\\ok.jpg', b'7' * 16)]
        base = os.path.join(self.dst, DEST, 'HDD90')
        put(os.path.join(base, 'A', 'd_'), b'D' * 9)                    # в цели уже лежит чужой «d_» с тем же содержимым
        os.makedirs(L(os.path.join(base, 'A', 'папка_цели.jpg')))       # на месте будущего файла - папка
        p, rows, prob = self.run_copy(lines)
        self.assertEqual(p.returncode, 1, p.stdout.decode('cp866', errors='replace'))     # задание не прервано
        got = {r[5][len(self.src) + 1:]: r for r in rows}
        for rel, new in (('A\\a.', 'A\\a_'), ('A\\b ', 'A\\b_'), ('A\\CON.jpg', 'A\\CON_.jpg'), ('Отпуск.\\1.jpg', 'Отпуск_\\1.jpg'),
                         ('A\\CON.2026.jpg', 'A\\CON_.2026.jpg'), ('A\\nul.txt', 'A\\nul_.txt'), ('A\\CON .txt', 'A\\CON_ .txt'),
                         ('...\\1.jpg', '___\\1.jpg'), ('A\\e.', 'A\\e_')):
            r = got[rel]
            self.assertTrue(r[2].startswith('скопирован, размер и SHA-256 совпали (имя изменено: «'), r[2])
            self.assertTrue(copy_ok(r[2]))
            self.assertEqual(r[6], os.path.join(base, new))                  # «куда» - новое имя, «источник» - исходное
            self.assertTrue(exists(os.path.join(base, new)))
        # два разных исходника не сливаются в одну копию, даже с одинаковым содержимым
        self.assertTrue(got['A\\c.'][2].startswith('ОШИБКА: имя после замены совпадает с другим файлом «A\\c_»'), got['A\\c.'][2])
        self.assertTrue(got['A\\e '][2].startswith('ОШИБКА: имя после замены совпадает с другим файлом «A\\e.»'), got['A\\e '][2])
        self.assertFalse(copy_ok(got['A\\c.'][2]))
        self.assertTrue(got['A\\d.'][2].startswith('КОНФЛИКТ: в цели уже есть файл с заменённым именем'), got['A\\d.'][2])
        self.assertTrue(got['A\\папка_цели.jpg'][2].startswith('КОНФЛИКТ: в цели на месте файла лежит папка'))
        self.assertEqual(got['A\\COM0.jpg'][2], 'скопирован, размер и SHA-256 совпали')          # COM0 - обычное имя
        self.assertEqual(read(os.path.join(base, 'A', 'c_')), b'5' * 15)
        self.assertTrue(got['A\\x?y.jpg'][2].startswith('ОШИБКА: в имени запрещённый в Windows символ «?» в «x?y.jpg»'))
        self.assertTrue(got['A\\a:b.jpg'][2].startswith('ОШИБКА: в имени запрещённый в Windows символ «:»'))
        self.assertTrue(got['C:1.jpg'][2].startswith('ОШИБКА: в имени запрещённый в Windows символ «:» в «C:1.jpg»'))
        self.assertEqual(got['A\\ok.jpg'][2], 'скопирован, размер и SHA-256 совпали')
        self.assertIn('Скопированы под другим именем', prob)
        self.assertIn('Windows не открывает', prob)
        p, rows, _ = self.run_copy(lines, keep=True)                         # повтор: замена та же, своя копия найдена
        got = {r[5][len(self.src) + 1:]: r[2] for r in rows}
        self.assertTrue(got['A\\CON.jpg'].startswith('уже есть, SHA-256 совпал (имя изменено: «CON.jpg» -> «CON_.jpg»)'))
        self.assertTrue(got['A\\d.'].startswith('КОНФЛИКТ: в цели уже есть файл с заменённым именем'))

    def test_bad_sector_simulated(self):
        lines = [self.row('A\\сбой.jpg', b'B' * 30), self.row('A\\ok.jpg', b'K' * 30)]
        p, rows, prob = self.run_copy(lines, '-TestReadError', 'A\\сбой.jpg=23')
        self.assertEqual(p.returncode, 1)
        self.assertEqual(rows[0][2], 'ОШИБКА: сбойный сектор или ошибка ввода-вывода при чтении источника (код Windows 23: данные не '
                                     'читаются (ошибка CRC)) - файл не скопирован, диск стоит проверить')
        self.assertEqual(rows[1][2], 'скопирован, размер и SHA-256 совпали')
        self.assertFalse(exists(os.path.join(self.dst, DEST, 'HDD90', 'A', 'сбой.jpg')))
        tmp = os.path.join(self.dst, '_ВРЕМЕННО - копирование (можно удалить)')
        self.assertFalse(os.path.exists(tmp) and os.listdir(tmp))           # недописанный файл убран
        self.assertIn('Сбойный сектор', prob)
        # сбойные сектора - признак сбоя диска: 5 подряд останавливают копирование (код 4)
        lines = [self.row(f'B\\{i}.jpg', bytes([i]) * 9) for i in range(6)]
        p, rows, prob = self.run_copy(lines, '-TestReadError', ';'.join(f'B\\{i}.jpg=1117' for i in range(6)))
        self.assertEqual(p.returncode, 4)
        self.assertEqual(len(rows), 5)
        self.assertIn('5 ошибок подряд', rows[4][2])
        self.assertIn('не обработано строк: 1 - причина: 5 ошибок подряд', prob)       # остаток - тоже в списке

    def test_bad_relative_paths_refused(self):
        for rel in ('A\\.\\1.jpg', '.\\1.jpg', 'A\\\\1.jpg', 'A\\.', '\\1.jpg'):
            p, rows, _ = self.run_copy([f'HDD45\t{rel}\t1\tтест'])
            self.assertEqual(p.returncode, 5, rel)                            # ничего не начато
            self.assertEqual(rows, [])


@unittest.skipUnless(sys.platform == 'win32' and MOVE_TPL.exists(), 'нужны Windows и шаблон перемещения')
class MoveProblems(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tpl_mvproblem_'))
        self.task = self.tmp / 'task'; self.task.mkdir()
        self.disk = str(self.tmp / 'диск')
        shutil.copy2(MOVE_TPL, self.task / MOVE_TPL.name)

    def tearDown(self):
        subprocess.run(['cmd', '/c', 'rd', '/s', '/q', L(self.tmp)], capture_output=True)

    def test_long_path_busy_and_read_open(self):
        rels = {'long': '\\'.join([SEG] * 4) + '\\фото.jpg', 'busy': 'A\\пишется.jpg', 'read': 'A\\читается.jpg', 'ok': 'A\\ок.jpg'}
        for r in rels.values():
            put(os.path.join(self.disk, r), b'M' * 40)
            os.utime(L(os.path.join(self.disk, r)), (0, 0))
        (self.task / 'тома.tsv').write_text('HDD55\tAAAA0055\n', encoding='utf-8')
        (self.task / 'перемещение.tsv').write_text(''.join(f'{r}\t40\t0\t{ROOT45}\t{"AB" * 32}\tпроверка\n' for r in rels.values()),
                                                  encoding='utf-8')
        (self.task / 'корни.tsv').write_text(f'{ROOT45}\tновый\n', encoding='utf-8')
        busy = open(os.path.join(self.disk, rels['busy']), 'r+b')               # открыт на запись
        reading = open(os.path.join(self.disk, rels['read']), 'rb')             # открыт на чтение без права удаления
        try:
            p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / MOVE_TPL.name),
                                '-TestRoots', f'HDD55={self.disk}'], capture_output=True, timeout=120)
        finally:
            busy.close(); reading.close()
        self.assertEqual(p.returncode, 1, p.stdout.decode('cp866', errors='replace'))
        log = next(self.task.glob('Журнал перемещения *.tsv'))
        res = {}
        for f in log.read_text(encoding='utf-8-sig').splitlines()[1:]:
            f = f.split('\t')
            if f[1] != 'начато':
                res[f[4][len(self.disk) + 1:]] = (f[1], f[5])
        self.assertEqual(res[rels['long']][0], 'перемещён')
        moved = os.path.join(self.disk, ROOT45, rels['long'])
        self.assertGreater(len(moved), 300)
        self.assertTrue(exists(moved))
        self.assertEqual(res[rels['long']][1], moved)                          # журнал - без \\?\
        for k in ('busy', 'read'):
            self.assertEqual(res[rels[k]][0], 'ОШИБКА: файл занят другой программой - закройте её и запустите перемещение ещё раз')
            self.assertTrue(exists(os.path.join(self.disk, rels[k])))          # остался на месте
        self.assertEqual(res[rels['ok']][0], 'перемещён')
        prob = next(self.task.glob('Проблемные файлы *.txt')).read_text(encoding='utf-8-sig')
        self.assertIn('Файл занят другой программой', prob)
        self.assertIn(rels['busy'], prob)

    def test_whole_folder_problems_go_file_by_file(self):
        files = {'B\\1.jpg': b'1' * 40, 'B\\2.jpg': b'2' * 40, 'C\\3.jpg': b'3' * 40, 'C\\4.jpg': b'4' * 40}
        for r, b in files.items():
            put(os.path.join(self.disk, r), b)
            os.utime(L(os.path.join(self.disk, r)), (0, 0))
        (self.task / 'тома.tsv').write_text('HDD55\tAAAA0055\n', encoding='utf-8')
        (self.task / 'перемещение.tsv').write_text(''.join(f'{r}\t40\t0\t{ROOT45}\t{"AB" * 32}\tпроверка\n' for r in files),
                                                  encoding='utf-8')
        (self.task / 'папки целиком.tsv').write_text(f'B\t{ROOT45}\t2\t80\nC\t{ROOT45}\t2\t80\n', encoding='utf-8')
        (self.task / 'корни.tsv').write_text(f'{ROOT45}\tновый\n', encoding='utf-8')
        user, folder_c = getpass.getuser(), os.path.join(self.disk, 'C')
        subprocess.run(['icacls', folder_c, '/deny', f'{user}:(RD)'], capture_output=True)    # оглавление C не читается
        busy = open(os.path.join(self.disk, 'B', '1.jpg'), 'r+b')
        try:
            if os.access(folder_c, os.R_OK) and self._listable(folder_c):
                self.skipTest('не удалось закрыть оглавление временной папки (icacls)')
            p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / MOVE_TPL.name),
                                '-TestRoots', f'HDD55={self.disk}'], capture_output=True, timeout=120)
        finally:
            busy.close()
            subprocess.run(['icacls', folder_c, '/remove:d', user], capture_output=True)
        out = p.stdout.decode('cp866', errors='replace')
        self.assertEqual(p.returncode, 1, out)                                    # не авария: сценарий дошёл до конца
        res = {}
        for f in next(self.task.glob('Журнал перемещения *.tsv')).read_text(encoding='utf-8-sig').splitlines()[1:]:
            f = f.split('\t')
            if f[1] != 'начато':
                res[f[4][len(self.disk) + 1:]] = f[1]
        self.assertEqual(res['B\\1.jpg'], 'ОШИБКА: файл занят другой программой - закройте её и запустите перемещение ещё раз')
        self.assertEqual((res['B\\2.jpg'], res['C\\3.jpg'], res['C\\4.jpg']), ('перемещён',) * 3)   # по файлам
        self.assertIn('B\\1.jpg', next(self.task.glob('Проблемные файлы *.txt')).read_text(encoding='utf-8-sig'))

    @staticmethod
    def _listable(path):
        try:
            os.listdir(path)
            return True
        except PermissionError:
            return False


if __name__ == '__main__':
    unittest.main()
