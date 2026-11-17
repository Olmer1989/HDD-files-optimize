"""Проверки шаблона копирования по замечаниям критика (13.11.2026). Только временные папки.

Запуск из корня проекта:  py -m unittest catalog\\test_copy_template_review.py
Шаблон запускается в Windows PowerShell 5.1 с параметром -TestRoots (папки вместо дисков).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service as sv                                         # noqa: E402  (отпечаток задания, версия шаблона)
from hb_core.paths import copy_template, template_parts      # noqa: E402  (шаблон 2.8 - главный и части)

TEMPLATE = Path(__file__).resolve().parent.parent / 'Каталог дисков' / '_ШАБЛОН копирования' / 'Копировать.ps1'
DEST = 'ПЕРЕНОС с других дисков'
TMP_NAME = '_ВРЕМЕННО - копирование (можно удалить)'


@unittest.skipUnless(sys.platform == 'win32' and TEMPLATE.exists(), 'нужны Windows и шаблон копирования')
class TemplateReview(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tpl_review_'))
        self.task = self.tmp / 'task'; self.task.mkdir()
        self.src = self.tmp / 'src'; (self.src / 'A').mkdir(parents=True)
        self.dst = self.tmp / 'dst'; self.dst.mkdir()
        copy_template(TEMPLATE.parent, self.task, TEMPLATE.name, extra=())     # главный и части (шаблон 2.8)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_template(self, toma, lines, roots):
        (self.task / 'тома.tsv').write_text(toma, encoding='utf-8-sig')
        (self.task / 'список.tsv').write_text(''.join(x + '\n' for x in lines), encoding='utf-8-sig')
        for old in self.task.glob('Журнал*.tsv'):
            old.unlink()
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / TEMPLATE.name),
                            '-TestRoots', roots], capture_output=True, timeout=120)
        logs = list(self.task.glob('Журнал*.tsv'))
        rows = [x.split('\t') for x in logs[0].read_text(encoding='utf-8-sig').splitlines()[1:]] if logs else []
        return p, rows

    def test_08_foreign_part_file_is_not_deleted(self):
        content = b'G' * 100
        (self.src / 'A' / '1.jpg').write_bytes(content)
        final = self.dst / DEST / 'HDD90' / 'A' / '1.jpg'
        final.parent.mkdir(parents=True)
        foreign = final.with_name(final.name + '.part')
        foreign.write_bytes(b'UNRELATED PREEXISTING DATA')
        p, rows = self.run_template('HDD90\tAAAA0090\nHDD77\tAAAA0077\n',
                                    ['HDD77\tA\\1.jpg\t100\tтест\t' + hashlib.sha256(content).hexdigest()],
                                    f'HDD90={self.src};HDD77={self.dst}')
        self.assertEqual(p.returncode, 0, p.stdout.decode('cp866', errors='replace'))
        self.assertEqual(final.read_bytes(), content)
        self.assertEqual(foreign.read_bytes(), b'UNRELATED PREEXISTING DATA')     # чужой файл цел
        self.assertFalse((self.dst / TMP_NAME).exists())                           # своя временная папка убрана
        self.assertTrue(rows[0][2].startswith('скопирован, размер и SHA-256 совпали'))

    def test_08_own_leftover_is_cleaned(self):
        content = b'G' * 100
        (self.src / 'A' / '1.jpg').write_bytes(content)
        own = self.dst / TMP_NAME
        own.mkdir()
        (own / 'run20200101000000_1_1.part').write_bytes(b'x' * 10)
        p, rows = self.run_template('HDD90\tAAAA0090\nHDD77\tAAAA0077\n',
                                    ['HDD77\tA\\1.jpg\t100\tтест\t' + hashlib.sha256(content).hexdigest()],
                                    f'HDD90={self.src};HDD77={self.dst}')
        self.assertEqual(p.returncode, 0)
        self.assertFalse(own.exists())

    def test_01_existing_same_size_other_content_is_a_conflict(self):
        content = b'G' * 100
        (self.src / 'A' / '1.jpg').write_bytes(content)
        final = self.dst / DEST / 'HDD90' / 'A' / '1.jpg'
        final.parent.mkdir(parents=True)
        final.write_bytes(b'B' * 100)                      # тот же размер, другое содержимое
        p, rows = self.run_template('HDD90\tAAAA0090\nHDD77\tAAAA0077\n',
                                    ['HDD77\tA\\1.jpg\t100\tтест\t' + hashlib.sha256(content).hexdigest()],
                                    f'HDD90={self.src};HDD77={self.dst}')
        # шаблон 2.5: файл того же размера прочитан, SHA-256 другой - КОНФЛИКТ (до 2.5 было «уже есть» без сверки)
        self.assertEqual(rows[0][2], 'КОНФЛИКТ: на месте назначения другой файл того же размера (SHA-256 отличается)')
        self.assertEqual(rows[0][4], '')                   # хеша нет: базе нечем подтвердить такую «копию»
        self.assertEqual(final.read_bytes(), b'B' * 100)   # существующий файл не тронут
        self.assertEqual(p.returncode, 1)

    def test_09_source_subfolder_does_not_bypass_same_volume_guard(self):
        volume = self.tmp / 'volume'; (volume / 'sub').mkdir(parents=True)
        (volume / 'sub' / 'a.jpg').write_bytes(b'good')
        p, rows = self.run_template('HDD90\tSAME\tsub\nHDD77\tSAME\n',
                                    ['HDD77\ta.jpg\t4\tтест\t' + hashlib.sha256(b'good').hexdigest()],
                                    f'HDD90={volume};HDD77={volume}')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((volume / DEST).exists())
        self.assertEqual(rows, [])

    def test_five_errors_in_a_row_stop_the_run(self):
        lines = []
        for i in range(8):                                  # в описи другой хеш: каждая строка даёт ошибку
            (self.src / 'A' / f'{i}.jpg').write_bytes(b'x' * 10)
            lines.append(f'HDD77\tA\\{i}.jpg\t10\tтест\t' + 'a' * 64)
        p, rows = self.run_template('HDD90\tAAAA0090\nHDD77\tAAAA0077\n', lines, f'HDD90={self.src};HDD77={self.dst}')
        self.assertEqual(len(rows), 5)                      # после пятой ошибки подряд остановка
        self.assertIn('ошибок подряд', rows[-1][2])
        self.assertNotEqual(p.returncode, 0)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_sparse(path, size, head=b'begin', tail=b'end'):
    """Разрежённый файл (место на диске почти не занимает): начало, хвост, между ними нули."""
    import ctypes
    from ctypes import wintypes
    with open(path, 'wb') as f:
        f.write(head)
        k32 = ctypes.windll.kernel32
        import msvcrt
        h = msvcrt.get_osfhandle(f.fileno())
        ret = wintypes.DWORD()
        k32.DeviceIoControl(wintypes.HANDLE(h), 0x000900C4, None, 0, None, 0, ctypes.byref(ret), None)  # FSCTL_SET_SPARSE
        f.seek(size - len(tail))
        f.write(tail)
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


@unittest.skipUnless(sys.platform == 'win32' and TEMPLATE.exists(), 'нужны Windows и шаблон копирования')
class Template24(unittest.TestCase):
    """Версия 2.4 (логика v3, этап 4): очередь окна (-Confirmed -Expect), коды выхода, разбор.json, манифест,
    запасной экземпляр дубля, пропавший том, файл больше 2 ГБ. Windows PowerShell 5.1, -TestRoots."""
    TOMA = 'HDD90\tAAAA0090\nHDD45\tAAAA0045\nHDD77\tAAAA0077\n'
    setUp0, tearDown = TemplateReview.setUp, TemplateReview.tearDown

    def setUp(self):
        self.setUp0()
        self.dst2 = self.tmp / 'dst2'; self.dst2.mkdir()
        self.roots = f'HDD90={self.src};HDD45={self.dst};HDD77={self.dst2}'

    def write_task(self, toma, lines, razbor=None):
        (self.task / 'тома.tsv').write_text(toma, encoding='utf-8')
        (self.task / 'список.tsv').write_text(''.join(x + '\n' for x in lines), encoding='utf-8')
        if razbor is not None:
            (self.task / 'разбор.json').write_text(json.dumps(razbor, ensure_ascii=False), encoding='utf-8')

    def run_ps(self, *extra, roots=None, timeout=300):
        for old in self.task.glob('Журнал*.tsv'):
            old.unlink()
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / TEMPLATE.name),
                            '-TestRoots', roots or self.roots, *extra], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        logs = list(self.task.glob('Журнал*.tsv'))
        rows = [x.split('\t') for x in logs[0].read_text(encoding='utf-8-sig').splitlines()[1:]] if logs else []
        return p, rows, p.stdout.decode('cp866', errors='replace') + p.stdout.decode('utf-8', errors='replace')

    def fingerprint(self):
        return sv.copy_task_fingerprint(self.task)['sha']

    def razbor(self, **kw):
        r = {'носитель': 'HDD90', 'направление': 'Н1', 'обязательные диски': ['HDD45', 'HDD77'],
             'цели': ['HDD45', 'HDD77'], 'манифест': 'HDD90 2026-11-15 10-00-00.json', 'зависимые': {}}
        r.update(kw)
        return r

    def one_file(self, name='1.jpg', content=b'G' * 100):
        (self.src / 'A' / name).write_bytes(content)
        return f'A\\{name}\t{len(content)}\tтест\t{sha(content)}'

    def test_version_line_and_no_pause_guard(self):
        lines = TEMPLATE.read_text(encoding='utf-8-sig').splitlines()
        self.assertIn('версия 2.8', lines[0])
        self.assertEqual(sv.copy_template_version(TEMPLATE.parent), (2, 8))
        self.assertTrue(sv.copy_template_version(TEMPLATE.parent) >= (2, 4))     # очередь: 2.8 - как 2.4
        for name, _ in template_parts(TEMPLATE):                                  # части (2.8): пауз в них нет
            self.assertNotIn('Read-Host', (TEMPLATE.parent / name).read_text(encoding='utf-8-sig'), name)
        for v in ('2.4', '2.5', '2.6', '2.7'):
            old = TEMPLATE.parent / f'Копировать - версия {v}.ps1.txt'
            self.assertIn(f'версия {v}', old.read_text(encoding='utf-8-sig').splitlines()[0])
        for i, x in enumerate(lines):
            if 'Read-Host' in x:                       # каждая пауза и вопрос - под одним флагом «без пауз»
                self.assertTrue(any('if (-not $NoPause)' in y for y in lines[max(0, i - 2):i + 1]), f'строка {i + 1}: {x}')
        cmd = (TEMPLATE.parent / 'Запустить.cmd').read_text(encoding='ascii')
        self.assertIn('%*', cmd)                       # аргументы очереди доходят до шаблона
        self.assertIn('exit /b %errorlevel%', cmd)     # код шаблона доходит до очереди

    def test_confirmed_requires_matching_fingerprint(self):
        self.write_task(self.TOMA, ['HDD45\t' + self.one_file()])
        p, rows, _ = self.run_ps('-Confirmed')
        self.assertEqual(p.returncode, 5)              # без отпечатка - не начато
        self.assertEqual(rows, [])
        p, rows, _ = self.run_ps('-Confirmed', '-Expect', '0' * 64)
        self.assertEqual(p.returncode, 5)              # задание изменилось после подтверждения
        self.assertFalse((self.dst / DEST).exists())
        p, rows, out = self.run_ps('-Confirmed', '-Expect', self.fingerprint().lower())
        self.assertEqual(p.returncode, 10, out)        # очередь: 10 - всё прошло
        self.assertTrue(rows[0][2].startswith('скопирован, размер и SHA-256 совпали'))
        head = next(self.task.glob('Журнал*.tsv')).read_text(encoding='utf-8-sig').splitlines()[0].split('\t')
        self.assertEqual(head[7], 'дата изменения источника')
        self.assertEqual(rows[0][7], str(int((self.src / 'A' / '1.jpg').stat().st_mtime)))   # секунды UTC, как в описи
        p, rows, _ = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        self.assertEqual(p.returncode, 10)             # повтор: «уже есть, SHA-256 совпал» - тоже всё прошло
        self.assertEqual(rows[0][2], 'уже есть, SHA-256 совпал')
        self.assertEqual(rows[0][4], sha(b'G' * 100).upper())

    def test_exit_codes(self):
        ok = self.one_file()
        self.write_task(self.TOMA, ['HDD45\t' + ok])
        self.assertEqual(self.run_ps()[0].returncode, 0)
        self.write_task(self.TOMA, ['HDD45\tA\\нет такого.jpg\t5\tтест\t' + 'a' * 64])
        p, rows, _ = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        self.assertEqual(p.returncode, 11)             # закончено не всё (нет источника) - очередь идёт дальше
        self.assertEqual(rows[0][2], 'нет источника')
        self.write_task(self.TOMA, ['HDD45\t' + ok, 'HDD77\t' + ok])
        p, rows, out = self.run_ps(roots=f'HDD90={self.src};HDD45={self.dst};HDD77={self.tmp / "нет"}')
        self.assertEqual(p.returncode, 1, out)         # цель 77 не подключена - не всё
        self.assertIn('Не подключены: HDD77', out)
        self.write_task(self.TOMA, ['HDD45\tA\\1.jpg\tне число\tтест'])
        self.assertEqual(self.run_ps()[0].returncode, 5)   # ошибка в файлах задания - не начато
        self.write_task(self.TOMA, ['HDD45\t' + ok])
        self.assertEqual(self.run_ps(roots=f'HDD90={self.tmp / "нет"};HDD45={self.dst}')[0].returncode, 5)  # нет источника
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / TEMPLATE.name),
                            '-TestRoots', self.roots, '-НетТакогоПараметра'], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertNotIn(p.returncode, (10, 11))       # отказ запуска очередь не примет за «дальше»

    def test_razbor_json_fixes_disk_set(self):
        line = self.one_file()
        self.write_task(self.TOMA, ['HDD45\t' + line], self.razbor(цели=['HDD45'], **{'обязательные диски': ['HDD45']}))
        p, rows, out = self.run_ps()
        self.assertEqual(p.returncode, 5, out)         # в тома.tsv лишняя цель 77
        self.assertIn('не совпадает с разбор.json', out)
        self.write_task(self.TOMA, ['HDD45\t' + line], self.razbor(носитель='HDD17'))
        self.assertEqual(self.run_ps()[0].returncode, 5)   # другой носитель
        self.write_task(self.TOMA, ['HDD45\t' + line], self.razbor(зависимые={'HDD45': [['..\\x.jpg', 'a' * 64, 'A\\1.jpg']]}))
        self.assertEqual(self.run_ps()[0].returncode, 5)   # недопустимый путь дубля
        self.assertFalse((self.dst / DEST).exists())

    def test_one_target_of_two_required(self):
        """Этап 5: задание на один диск «Семейного архива» (цель 45, обязательные 45 и 77) шаблон 2.4 принимает как
        есть; 77 он не трогает."""
        line = self.one_file()
        self.write_task('HDD90\tAAAA0090\nHDD45\tAAAA0045\n', ['HDD45\t' + line],
                        self.razbor(цели=['HDD45'], группа='HDD90 — A — Семейный архив'))
        p, rows, out = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        self.assertIn(p.returncode, (10, 11), out)
        self.assertTrue(rows[0][2].startswith('скопирован, размер и SHA-256 совпали'), out)
        self.assertEqual({r[1] for r in rows}, {'HDD45'})
        self.assertTrue((self.dst / DEST).exists())
        self.assertFalse(any(self.dst2.iterdir()))

    def test_manifest_only_warns(self):
        line = self.one_file()
        self.write_task(self.TOMA, ['HDD45\t' + line, 'HDD77\t' + line], self.razbor())
        p, rows, out = self.run_ps()
        self.assertEqual(p.returncode, 0, out)         # манифеста нет - предупреждение, но копирование идёт
        self.assertIn('не найден', out)
        self.assertEqual(len(rows), 2)
        # настоящая раскладка: <корень>\Запускаемые скрипты\<задание>, манифест - <корень>\Каталог дисков\_БАЗА\разборы
        root = self.tmp / 'проект'
        task = root / 'Запускаемые скрипты' / 'HDD90 — A — Семейный архив'
        shutil.copytree(self.task, task)
        man_dir = root / 'Каталог дисков' / '_БАЗА' / 'разборы'
        man_dir.mkdir(parents=True)
        man = man_dir / 'HDD90 2026-11-15 10-00-00.json'
        for status, warned in (('создаётся', True), ('готово', False)):
            man.write_text(json.dumps({'носитель': 'HDD90', 'статус': status, 'задания': [{'имя': task.name}]},
                                      ensure_ascii=False), encoding='utf-8')
            self.task = task
            p, rows, out = self.run_ps()
            self.assertEqual(p.returncode, 0, out)
            self.assertEqual('не подтверждён как готовый' in out, warned, out)

    def test_spare_copy_of_duplicate(self):
        content = b'D' * 300
        (self.src / 'B').mkdir()
        (self.src / 'B' / 'копия.jpg').write_bytes(content)          # представителя A\1.jpg на источнике нет
        (self.src / 'B' / 'ещё.jpg').write_bytes(content)
        h = sha(content)
        deps = {'HDD45': [['B\\копия.jpg', h, 'A\\1.jpg'], ['B\\ещё.jpg', h, 'A\\1.jpg']]}
        self.write_task(self.TOMA, [f'HDD45\tA\\1.jpg\t300\tтест\t{h}'], self.razbor(цели=['HDD45'], **{'обязательные диски': ['HDD45'], 'зависимые': deps}))
        (self.task / 'тома.tsv').write_text('HDD90\tAAAA0090\nHDD45\tAAAA0045\n', encoding='utf-8')
        p, rows, out = self.run_ps()
        self.assertEqual(p.returncode, 1, out)         # основной не скопирован - «не всё», но содержимое на месте
        self.assertEqual(rows[0][2].split(' | ')[0], 'нет источника')
        self.assertIn('запасной экземпляр «B\\копия.jpg»', rows[0][2])
        self.assertEqual(rows[1][2], 'скопирован, размер и SHA-256 совпали (запасной экземпляр вместо «A\\1.jpg»)')
        self.assertEqual(rows[1][4], h.upper())
        self.assertEqual((self.dst / DEST / 'HDD90' / 'B' / 'копия.jpg').read_bytes(), content)   # на СВОЙ путь
        self.assertEqual(len(rows), 2)                 # третий дубль не понадобился
        # 2.5: у запасного «уже есть, SHA-256 совпал» - копия подтверждена, следующий не нужен
        p, rows, out = self.run_ps()
        self.assertEqual([r[2].split(' | ')[0] for r in rows], ['нет источника', 'уже есть, SHA-256 совпал (запасной экземпляр вместо «A\\1.jpg»)'])
        self.assertEqual(rows[1][4], h.upper())

    def test_big_sparse_file_then_source_vanishes(self):
        """Файл больше 2 ГБ копируется и сверяется по SHA-256; затем том источника пропадает - код 4 сразу."""
        real = self.tmp / 'настоящий источник'; (real / 'A').mkdir(parents=True)
        big = 2 ** 31 + 4099
        h_big = make_sparse(real / 'A' / 'большой.bin', big)
        (real / 'A' / 'маленький.jpg').write_bytes(b's' * 10)
        link = self.tmp / 'источник-ссылка'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(real)], check=True, capture_output=True)
        lines = [f'HDD45\tA\\большой.bin\t{big}\tтест\t{h_big}', f'HDD45\tA\\маленький.jpg\t10\tтест\t{sha(b"s" * 10)}']
        self.write_task('HDD90\tAAAA0090\nHDD45\tAAAA0045\n', lines)
        roots = f'HDD90={link};HDD45={self.dst}'
        cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.task / TEMPLATE.name),
               '-TestRoots', roots, '-Confirmed', '-Expect', self.fingerprint()]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        tmpdir = self.dst / TMP_NAME
        end = time.time() + 120
        while time.time() < end and not (tmpdir.exists() and list(tmpdir.glob('run*.part'))):
            time.sleep(0.02)
        os.rmdir(link)                                 # «диск отключили» посреди большого файла
        out, _ = proc.communicate(timeout=600)
        logs = list(self.task.glob('Журнал*.tsv'))
        rows = [x.split('\t') for x in logs[0].read_text(encoding='utf-8-sig').splitlines()[1:]]
        got = self.dst / DEST / 'HDD90' / 'A' / 'большой.bin'
        self.assertEqual(rows[0][2], 'скопирован, размер и SHA-256 совпали', out.decode('cp866', errors='replace'))
        self.assertEqual(got.stat().st_size, big)
        self.assertEqual(rows[0][4], h_big.upper())   # SHA-256 прочитанного = описи
        self.assertTrue(rows[1][2].startswith('нет источника | диск HDD90 пропал'), rows[1][2])
        self.assertEqual(proc.returncode, 4)           # аварийная остановка - очередь стоит



def lock_exclusive(path):
    """Открыть файл без совместного доступа (как чужая программа, держащая файл): чтение шаблоном даст ошибку."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)      # GENERIC_READ, share 0, OPEN_EXISTING
    assert h and h != wintypes.HANDLE(-1).value
    return lambda: k32.CloseHandle(wintypes.HANDLE(h))


@unittest.skipUnless(sys.platform == 'win32' and TEMPLATE.exists(), 'нужны Windows и шаблон копирования')
class Template25(unittest.TestCase):
    """Версия 2.5 (логика v3, этап 15): файл того же размера на месте назначения читается и сверяется по SHA-256.
    Windows PowerShell 5.1, -TestRoots, только временные папки."""
    tearDown, write_task, run_ps, fingerprint, razbor = (Template24.tearDown, Template24.write_task,
                                                         Template24.run_ps, Template24.fingerprint, Template24.razbor)
    TOMA = 'HDD90\tAAAA0090\nHDD45\tAAAA0045\n'
    CONFLICT = 'КОНФЛИКТ: на месте назначения другой файл того же размера (SHA-256 отличается)'

    def setUp(self):
        TemplateReview.setUp(self)
        self.roots = f'HDD90={self.src};HDD45={self.dst}'
        self.final = lambda rel: self.dst / DEST / 'HDD90' / rel

    def put_dst(self, rel, content):
        f = self.final(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
        return f

    def test_same_size_same_sha_is_confirmed_with_and_without_list_hash(self):
        good = b'G' * 100
        (self.src / 'A' / '1.jpg').write_bytes(good)
        (self.src / 'A' / '2.jpg').write_bytes(good)
        f1, f2 = self.put_dst('A\\1.jpg', good), self.put_dst('A\\2.jpg', good)
        before = (f1.stat().st_mtime_ns, f2.stat().st_mtime_ns)
        self.write_task(self.TOMA, [f'HDD45\tA\\1.jpg\t100\tтест\t{sha(good)}',     # хеш из описи
                                    'HDD45\tA\\2.jpg\t100\tтест'])                      # без хеша - сверка с источником
        p, rows, out = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        self.assertEqual(p.returncode, 10, out)
        self.assertEqual([r[2] for r in rows], ['уже есть, SHA-256 совпал'] * 2)
        self.assertEqual([r[4] for r in rows], [sha(good).upper()] * 2)                # SHA-256 прочитанного в цели
        self.assertEqual((f1.stat().st_mtime_ns, f2.stat().st_mtime_ns), before)       # ничего не перезаписано
        self.assertFalse((self.dst / TMP_NAME).exists())
        self.assertTrue(all(sv.hb.copy_ok(r[2]) and r[2].startswith(sv.hb.HAVE_SHA) for r in rows))

    def test_same_size_other_sha_is_conflict_and_spare_is_tried(self):
        good, bad = b'D' * 300, b'E' * 300
        (self.src / 'A' / '1.jpg').write_bytes(good)
        (self.src / 'B').mkdir()
        (self.src / 'B' / 'копия.jpg').write_bytes(good)
        h = sha(good)
        f1 = self.put_dst('A\\1.jpg', bad)
        deps = {'HDD45': [['B\\копия.jpg', h, 'A\\1.jpg']]}
        self.write_task(self.TOMA, [f'HDD45\tA\\1.jpg\t300\tтест\t{h}'],
                        self.razbor(цели=['HDD45'], **{'обязательные диски': ['HDD45'], 'зависимые': deps}))
        p, rows, out = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        self.assertEqual(p.returncode, 11, out)                   # конфликт - «не всё», очередь идёт дальше
        self.assertEqual(rows[0][2].split(' | ')[0], self.CONFLICT)
        self.assertIn('запасной экземпляр «B\\копия.jpg»', rows[0][2])
        self.assertEqual(rows[0][4], '')                          # хеш чужого файла в журнал не пишется
        self.assertEqual(f1.read_bytes(), bad)                    # конфликтный файл не тронут
        self.assertEqual(rows[1][2], 'скопирован, размер и SHA-256 совпали (запасной экземпляр вместо «A\\1.jpg»)')
        self.assertEqual(self.final('B\\копия.jpg').read_bytes(), good)   # запасной - на свой путь
        self.assertFalse(sv.hb.copy_ok(rows[0][2]))
        # без хеша в списке: эталон - прочитанный источник; другой SHA - тоже КОНФЛИКТ, код 1
        self.write_task(self.TOMA, ['HDD45\tA\\1.jpg\t300\tтест'], self.razbor(цели=['HDD45'], **{'обязательные диски': ['HDD45']}))
        p, rows, out = self.run_ps()
        self.assertEqual(p.returncode, 1, out)
        self.assertEqual([r[2] for r in rows], [self.CONFLICT])
        self.assertEqual(f1.read_bytes(), bad)
        # другой размер - как раньше
        f1.write_bytes(b'E' * 10)
        p, rows, out = self.run_ps()
        self.assertTrue(rows[0][2].startswith('КОНФЛИКТ: в цели другой размер (10)'), rows)
        self.assertEqual(f1.read_bytes(), b'E' * 10)

    def test_destination_read_error_is_an_error_and_spare_is_tried(self):
        good = b'D' * 300
        (self.src / 'A' / '1.jpg').write_bytes(good)
        (self.src / 'B').mkdir()
        (self.src / 'B' / 'копия.jpg').write_bytes(good)
        h = sha(good)
        f1 = self.put_dst('A\\1.jpg', good)
        deps = {'HDD45': [['B\\копия.jpg', h, 'A\\1.jpg']]}
        self.write_task(self.TOMA, [f'HDD45\tA\\1.jpg\t300\tтест\t{h}'],
                        self.razbor(цели=['HDD45'], **{'обязательные диски': ['HDD45'], 'зависимые': deps}))
        unlock = lock_exclusive(f1)
        try:
            p, rows, out = self.run_ps('-Confirmed', '-Expect', self.fingerprint())
        finally:
            unlock()
        self.assertEqual(p.returncode, 11, out)
        self.assertTrue(rows[0][2].startswith('ОШИБКА: '), rows[0][2])
        self.assertIn('запасной экземпляр «B\\копия.jpg»', rows[0][2])
        self.assertEqual(rows[1][2], 'скопирован, размер и SHA-256 совпали (запасной экземпляр вместо «A\\1.jpg»)')
        self.assertEqual(f1.read_bytes(), good)

    def test_big_sparse_same_file_without_list_hash(self):
        """Файл больше 2 ГБ на источнике и в цели, хеша в списке нет: читаются оба, SHA-256 совпал."""
        big = 2 ** 31 + 4099
        h = make_sparse(self.src / 'A' / 'большой.bin', big)
        f = self.final('A\\большой.bin'); f.parent.mkdir(parents=True)
        self.assertEqual(make_sparse(f, big), h)
        self.write_task(self.TOMA, [f'HDD45\tA\\большой.bin\t{big}\tтест'])
        p, rows, out = self.run_ps(timeout=900)
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual((rows[0][2], rows[0][4]), ('уже есть, SHA-256 совпал', h.upper()))


@unittest.skipUnless(sys.platform == 'win32' and TEMPLATE.exists(), 'нужны Windows и шаблон копирования')
class Template26(unittest.TestCase):
    """Версия 2.6 (этап 16, решение владельца): место нужно только под файлы, которых на месте назначения ещё нет;
    папка цели из тома.tsv не обрезается по пробелам. -TestFreeBytes - свободное место для теста. Только временные
    папки, Windows PowerShell 5.1."""
    tearDown, write_task, run_ps, fingerprint = (Template24.tearDown, Template24.write_task, Template24.run_ps,
                                                 Template24.fingerprint)
    TOMA = 'HDD90\tAAAA0090\nHDD45\tAAAA0045\n'
    GB = 1024 ** 3

    def setUp(self):
        TemplateReview.setUp(self)
        self.roots = f'HDD90={self.src};HDD45={self.dst}'

    def put(self, rel, content, root=None):
        f = (root or self.dst / DEST / 'HDD90') / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
        return f

    def lines(self):
        old, new = b'O' * 3000, b'N' * 2000
        (self.src / 'A' / 'old.jpg').write_bytes(old)
        (self.src / 'A' / 'new.jpg').write_bytes(new)
        return old, new, [f'HDD45\tA\\old.jpg\t3000\tтест\t{sha(old)}', f'HDD45\tA\\new.jpg\t2000\tтест\t{sha(new)}']

    def test_space_counts_only_files_not_yet_on_target(self):
        old, new, lines = self.lines()
        f = self.put('A\\old.jpg', old)                                          # уже лежит, тот же размер
        before = f.stat().st_mtime_ns
        self.write_task(self.TOMA, lines)
        p, rows, out = self.run_ps('-TestFreeBytes', str(self.GB + 2500))       # хватает на новый, не на оба (5000)
        self.assertEqual(p.returncode, 0, out)
        self.assertIn('уже лежат на цели с тем же размером: 1', out)
        self.assertEqual(sorted(r[2] for r in rows), ['скопирован, размер и SHA-256 совпали', 'уже есть, SHA-256 совпал'])
        self.assertEqual(f.stat().st_mtime_ns, before)                           # лежавший файл не тронут
        (self.dst / DEST / 'HDD90' / 'A' / 'new.jpg').unlink()
        p, rows, out = self.run_ps('-TestFreeBytes', str(self.GB + 1500))       # на новый (2000) не хватает
        self.assertEqual(p.returncode, 5, out)
        self.assertIn('не хватает места', out)
        self.assertEqual(rows, [])                                               # ничего не начато

    def test_other_size_on_target_is_conflict_and_needs_no_space(self):
        old, new, lines = self.lines()
        f = self.put('A\\old.jpg', b'x' * 10)                                    # другой размер - КОНФЛИКТ
        self.write_task(self.TOMA, lines)
        p, rows, out = self.run_ps('-TestFreeBytes', str(self.GB + 2500))
        self.assertEqual(p.returncode, 1, out)                                   # не всё: конфликт
        self.assertIn('лежат на цели с другим размером: 1', out)
        got = {r[6].rsplit('\\', 1)[-1]: r[2] for r in rows}
        self.assertTrue(got['old.jpg'].startswith('КОНФЛИКТ: в цели другой размер'), got)
        self.assertEqual(f.read_bytes(), b'x' * 10)                              # не перезаписан
        self.assertTrue(got['new.jpg'].startswith('скопирован'))

    def test_no_target_folder_counts_all_and_case_of_names(self):
        old, new, lines = self.lines()
        self.write_task(self.TOMA, lines)
        p, rows, out = self.run_ps('-TestFreeBytes', str(self.GB + 4000))       # ничего не лежит - нужно 5000
        self.assertEqual(p.returncode, 5, out)
        self.put('a\\OLD.JPG', old)                                              # регистр имени - тот же файл (Windows)
        p, rows, out = self.run_ps('-TestFreeBytes', str(self.GB + 2500))
        self.assertEqual(p.returncode, 0, out)

    def test_target_folder_with_spaces_is_kept(self):
        old, new, lines = self.lines()
        self.write_task('HDD90\tAAAA0090\nHDD45\tAAAA0045\t Моя папка\n', lines[1:])
        p, rows, out = self.run_ps()
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual((self.dst / ' Моя папка' / 'HDD90' / 'A' / 'new.jpg').read_bytes(), new)
        self.assertFalse((self.dst / 'Моя папка').exists())


if __name__ == '__main__':
    unittest.main()
