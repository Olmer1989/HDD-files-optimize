"""Размер файлов вне catalog\\*.py (правило владельца 17.11.2026: цель до 400 строк, 600 - предел) и устройство
шаблона копирования из частей (2.8): сканер scanner\\*.py, шаблоны «Каталог дисков\\_ШАБЛОН *\\*.ps1» и их части
*.psm1. catalog\\*.py проверяет test_modules.test_file_size. Диски и данные не нужны.

Запуск из корня проекта:  py -m unittest catalog.test_file_sizes_other
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CAT = Path(__file__).resolve().parent
ROOT = CAT.parent
sys.path.insert(0, str(CAT))
from hb_core.paths import copy_template, part_sha, template_parts, template_problems      # noqa: E402

FILE_MAX = 600
PART_MAX = 400             # части шаблона созданы под цель 400 - так и держим
# Долг: уже больше предела. Расти нельзя, только уменьшаться; после разбивки - убрать из списка.
FILE_DEBT = {'scanner/portable.py': 1234}
COPY_TPL = ROOT / 'Каталог дисков' / '_ШАБЛОН копирования'
MAIN = 'Копировать.ps1'


def lines(p):
    return len(p.read_text(encoding='utf-8-sig').splitlines())


def checked_files():
    res = [p for p in (ROOT / 'scanner').glob('*.py')]
    for tpl in (ROOT / 'Каталог дисков').glob('_ШАБЛОН *'):
        res += list(tpl.glob('*.ps1')) + list(tpl.glob('*.psm1'))
    return res


class FileSizesOther(unittest.TestCase):
    def test_file_size(self):
        bad = []
        files = checked_files()
        self.assertTrue(any(p.suffix == '.psm1' for p in files) and any(p.parent.name == 'scanner' for p in files))
        for p in files:
            key = p.relative_to(ROOT).as_posix()
            limit = max(FILE_MAX, FILE_DEBT.get(key, 0))
            if p.suffix == '.psm1':
                limit = PART_MAX
            n = lines(p)
            if n > limit:
                bad.append(f'{key}: {n} строк (предел {limit})')
        self.assertEqual(bad, [], 'Файл вырос сверх предела - вынесите часть в отдельный файл')

    def test_debt_files_exist(self):
        for key in FILE_DEBT:             # долг погашен или файл переименован - уберите строку из FILE_DEBT
            self.assertTrue((ROOT / key).exists(), key)


class CopyTemplateParts(unittest.TestCase):
    """Шаблон копирования 2.8: главный + части *.psm1, SHA-256 текста частей записан в главном (таблица $PartSha)."""

    def test_part_table_matches_files(self):
        parts = template_parts(COPY_TPL / MAIN)
        self.assertEqual(sorted(n for n, _ in parts), sorted(p.name for p in COPY_TPL.glob('*.psm1')),
                         'таблица $PartSha в Копировать.ps1 и файлы *.psm1 рядом не совпадают')
        self.assertGreaterEqual(len(parts), 3)
        for name, sha in parts:            # правили часть - впишите новый SHA-256 в таблицу $PartSha
            self.assertEqual(part_sha(COPY_TPL / name), sha, f'{name}: в $PartSha записать {part_sha(COPY_TPL / name)}')
        self.assertEqual(template_problems(COPY_TPL, MAIN), [])
        self.assertLessEqual(lines(COPY_TPL / MAIN), PART_MAX)

    def test_launcher_starts_only_the_main_script(self):
        # «Запустить.cmd» запускает все *.ps1 папки: в шаблоне .ps1 - только главный, части - .psm1
        self.assertEqual([p.name for p in COPY_TPL.glob('*.ps1')], [MAIN])
        with tempfile.TemporaryDirectory(prefix='tpl_cmd_') as tmp:
            for n in copy_template(COPY_TPL, tmp, MAIN):
                self.assertTrue((Path(tmp) / n).is_file())
            cmd = ('@echo off\r\nfor %%F in ("%~dp0*.ps1") do echo FOUND %%~nxF\r\n').encode('ascii')
            (Path(tmp) / 'список.cmd').write_bytes(cmd)
            out = subprocess.run(['cmd', '/c', str(Path(tmp) / 'список.cmd')], capture_output=True).stdout
            self.assertEqual(out.count(b'FOUND'), 1, out)

    def test_copy_refuses_broken_reference_and_sees_broken_task(self):
        with tempfile.TemporaryDirectory(prefix='tpl_bad_') as tmp:
            src, dst = Path(tmp) / 'src', Path(tmp) / 'dst'
            shutil.copytree(COPY_TPL, src); dst.mkdir()
            part = template_parts(src / MAIN)[0][0]
            with open(src / part, 'a', encoding='utf-8') as f:
                f.write('# подмена\n')
            with self.assertRaises(RuntimeError):
                copy_template(src, dst, MAIN)
            (src / part).unlink()
            self.assertEqual(template_problems(src, MAIN), [f'нет части «{part}»'])

    def test_no_direct_template_copy_left(self):
        # все места, где готовится задание копирования, кладут шаблон через copy_template (главный + части)
        bad = []
        for p in CAT.rglob('*.py'):
            if p.name.startswith('test') or '__pycache__' in p.parts:
                continue
            s = p.read_text(encoding='utf-8')
            if "'Копировать.ps1', 'Запустить.cmd'" in s or "'Копировать.ps1','Запустить.cmd'" in s or \
                    "TEMPLATE/'Копировать.ps1'" in s or "TEMPLATE / 'Копировать.ps1'" in s:
                bad.append(p.relative_to(CAT).as_posix())
        self.assertEqual(bad, [])


@unittest.skipUnless(sys.platform == 'win32', 'нужен Windows PowerShell')
class CopyTemplateRuns(unittest.TestCase):
    """Задание 2.8 без части или с изменённой частью не начинается (код 5); однофайловое 2.7 работает как раньше."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tpl_parts_'))
        self.task = self.tmp / 'task'; self.task.mkdir()
        self.src = self.tmp / 'src'; self.src.mkdir(); self.dst = self.tmp / 'dst'; self.dst.mkdir()
        (self.src / '1.jpg').write_bytes(b'G' * 100)
        (self.task / 'тома.tsv').write_text('HDD90\tAAAA0090\nHDD77\tAAAA0077\n', encoding='utf-8')
        (self.task / 'список.tsv').write_text('HDD77\t1.jpg\t100\tтест\n', encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self):
        # через «Запустить.cmd», как запускает окно: аргументы доходят до шаблона, код - обратно
        p = subprocess.run(['cmd', '/c', str(self.task / 'Запустить.cmd'), '-TestRoots', f'HDD90={self.src};HDD77={self.dst}'],
                           capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.decode('utf-8', errors='replace') + p.stdout.decode('cp866', errors='replace')

    def copied(self):
        return (self.dst / 'ПЕРЕНОС с других дисков' / 'HDD90' / '1.jpg').exists()

    def test_full_task_runs(self):
        copy_template(COPY_TPL, self.task, MAIN)
        code, out = self.run_cmd()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.copied())

    def test_missing_or_changed_part_stops_before_start(self):
        copy_template(COPY_TPL, self.task, MAIN)
        part = template_parts(COPY_TPL / MAIN)[1][0]
        with open(self.task / part, 'a', encoding='utf-8') as f:
            f.write('Write-Host 1\n')
        code, out = self.run_cmd()
        self.assertEqual(code, 5, out); self.assertIn('изменена', out)
        (self.task / part).unlink()
        code, out = self.run_cmd()
        self.assertEqual(code, 5, out); self.assertIn('Нет части шаблона', out)
        self.assertFalse(self.copied())
        self.assertEqual(list(self.task.glob('Журнал*.tsv')), [])

    def test_old_single_file_task_still_runs(self):
        shutil.copy2(COPY_TPL / 'Копировать - версия 2.7.ps1.txt', self.task / MAIN)
        shutil.copy2(COPY_TPL / 'Запустить.cmd', self.task / 'Запустить.cmd')
        code, out = self.run_cmd()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.copied())


if __name__ == '__main__':
    unittest.main()
