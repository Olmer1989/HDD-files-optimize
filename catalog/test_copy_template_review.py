"""Проверки шаблона копирования по замечаниям критика (13.11.2026). Только временные папки.

Запуск из корня проекта:  py -m unittest catalog\\test_copy_template_review.py
Шаблон запускается в Windows PowerShell 5.1 с параметром -TestRoots (папки вместо дисков).
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        shutil.copy2(TEMPLATE, self.task / TEMPLATE.name)

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

    def test_01_existing_same_size_file_is_reported_as_already_there_without_hash(self):
        content = b'G' * 100
        (self.src / 'A' / '1.jpg').write_bytes(content)
        final = self.dst / DEST / 'HDD90' / 'A' / '1.jpg'
        final.parent.mkdir(parents=True)
        final.write_bytes(b'B' * 100)                      # тот же размер, другое содержимое
        p, rows = self.run_template('HDD90\tAAAA0090\nHDD77\tAAAA0077\n',
                                    ['HDD77\tA\\1.jpg\t100\tтест\t' + hashlib.sha256(content).hexdigest()],
                                    f'HDD90={self.src};HDD77={self.dst}')
        self.assertEqual(rows[0][2], 'уже есть')
        self.assertEqual(rows[0][4], '')                   # хеша нет: базе нечем подтвердить такую «копию»
        self.assertEqual(final.read_bytes(), b'B' * 100)   # существующий файл не тронут

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


if __name__ == '__main__':
    unittest.main()
