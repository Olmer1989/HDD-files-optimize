"""Шаблон копирования 2.8 из частей - проверка целостности одинаково в Python (hb_core.paths) и в Копировать.ps1:
таблица $PartSha разбирается строго (непонятная строка - «повреждён», а не пропуск), строгий UTF-8 (битые байты -
ошибка в обоих языках), одно правило концов строк (CRLF и одиночный CR -> LF), copy_template пишет ровно те байты,
которые проверил. Критики по готовому коду 17.11.2026 (GPT 1-3, DeepSeek - одиночный CR).

Запуск из корня проекта:  py -m unittest catalog.test_copy_template_parts
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CAT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAT))
from hb_core import paths                                                       # noqa: E402
from hb_core.paths import (TemplateBroken, copy_template, parse_parts, part_sha,  # noqa: E402
                           template_parts, template_problems)
import service as sv                                                            # noqa: E402  (версия шаблона)

COPY_TPL = CAT.parent / 'Каталог дисков' / '_ШАБЛОН копирования'
MAIN = 'Копировать.ps1'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tpl_parts2_'))
        self.tpl = self.tmp / 'tpl'
        shutil.copytree(COPY_TPL, self.tpl)
        self.parts = template_parts(self.tpl / MAIN)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main_text(self):
        return (self.tpl / MAIN).read_bytes().decode('utf-8')

    def set_main(self, text):
        (self.tpl / MAIN).write_bytes(text.encode('utf-8'))

    def assert_broken(self, word):
        bad = template_problems(self.tpl, MAIN)
        self.assertTrue(bad and word in bad[0], bad)
        with self.assertRaises(RuntimeError):
            copy_template(self.tpl, self.tmp, MAIN)
        self.assertIsNone(sv.copy_template_version(self.tpl))


class PartTable(Base):
    def test_shortened_hash_is_broken_not_skipped(self):
        name, sha = self.parts[0]
        self.set_main(self.main_text().replace(sha, sha[:-1]))
        (self.tpl / name).unlink()                           # раньше: строка выпадала, части «не нужно»
        self.assert_broken('не разобрана')

    def test_unknown_line_inside_table(self):
        name, sha = self.parts[1]
        self.set_main(self.main_text().replace(f"'{name}' = '{sha}'", f"'{name}' = '{sha}' # комментарий"))
        self.assert_broken('не разобрана')
        self.set_main(self.main_text().replace(' # комментарий', '').replace(f"'{name}'", f'"{name}"'))
        self.assert_broken('не разобрана')

    def test_table_removed_but_used(self):
        t = self.main_text()
        a = t.index('$PartSha = [ordered]@{'); b = t.index('}', a)
        self.set_main(t[:a] + t[b + 1:])
        self.assert_broken('не разобрана')

    def test_empty_duplicate_unclosed(self):
        with self.assertRaises(TemplateBroken):
            parse_parts('$PartSha = [ordered]@{\n}\n')
        line = f"    'a.psm1' = '{'A' * 64}'\n"
        with self.assertRaises(TemplateBroken):
            parse_parts('$PartSha = [ordered]@{\n' + line + line + '}\n')
        with self.assertRaises(TemplateBroken):
            parse_parts('$PartSha = [ordered]@{\n' + line)
        self.assertEqual(parse_parts('# однофайловый шаблон 2.7\nparam()\n'), [])
        self.assertEqual(parse_parts('$PartSha = [ordered]@{\r\n' + line + '}\r\n'), [('a.psm1', 'A' * 64)])

    def test_real_template_is_whole(self):
        self.assertEqual(len(self.parts), 3)
        self.assertEqual(template_problems(COPY_TPL, MAIN), [])


class CopyIsOneSnapshot(Base):
    def test_written_bytes_are_the_checked_bytes(self):
        dst = self.tmp / 'task'; dst.mkdir()
        victim = self.tpl / self.parts[0][0]
        real = shutil.copystat

        def change_source(src, d, **kw):                     # эталон меняется во время доставки
            real(src, d, **kw)
            with open(victim, 'a', encoding='utf-8') as f:
                f.write('# подмена во время копирования\n')
        with mock.patch.object(paths.shutil, 'copystat', side_effect=change_source):
            names = copy_template(self.tpl, dst, MAIN)
        self.assertEqual(len(names), 5)
        self.assertEqual(template_problems(dst, MAIN), [])  # доставлен проверенный снимок, а не изменённый файл

    def test_failed_write_check_removes_written_files(self):
        dst = self.tmp / 'task'; dst.mkdir()
        orig = Path.read_bytes
        calls = {'n': 0}

        def flaky(p):
            data = orig(p)
            if p.parent == dst and p.name == self.parts[1][0]:
                return data + b'x'                           # записанное «не совпало»
            return data
        with mock.patch.object(Path, 'read_bytes', flaky):
            with self.assertRaises(RuntimeError):
                copy_template(self.tpl, dst, MAIN)
        self.assertEqual(list(dst.iterdir()), [])            # полкомплекта не остаётся


@unittest.skipUnless(sys.platform == 'win32', 'нужен Windows PowerShell')
class SameRuleInPowerShell(Base):
    """Python и Копировать.ps1 приходят к одному ответу на тех же байтах."""

    def run_ps(self):
        src = self.tmp / 'src'; src.mkdir(exist_ok=True); (src / '1.jpg').write_bytes(b'G' * 100)
        dst = self.tmp / 'dst'; dst.mkdir(exist_ok=True)
        (self.tpl / 'тома.tsv').write_text('HDD90\tA\nHDD77\tB\n', encoding='utf-8')
        (self.tpl / 'список.tsv').write_text('HDD77\t1.jpg\t100\tтест\n', encoding='utf-8')
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.tpl / MAIN),
                            '-TestRoots', f'HDD90={src};HDD77={dst}'], capture_output=True, timeout=120,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.decode('utf-8', errors='replace')

    def rewrite_part(self, k, data):
        name, sha = self.parts[k]
        (self.tpl / name).write_bytes(data)
        return name, sha

    def test_lone_cr_same_hash(self):
        name, sha = self.parts[0]
        data = (self.tpl / name).read_bytes() + b'# a\r# b\r\n'     # одиночный CR - конец строки и там, и там
        self.rewrite_part(0, data)
        self.set_main(self.main_text().replace(sha, part_sha(data)))
        self.assertEqual(template_problems(self.tpl, MAIN), [])
        code, out = self.run_ps()
        self.assertEqual(code, 0, out)

    def test_bad_utf8_refused_by_both(self):
        name, sha = self.parts[2]
        good = (self.tpl / name).read_bytes() + '# �\r\n'.encode('utf-8')
        self.set_main(self.main_text().replace(sha, part_sha(good)))
        self.rewrite_part(2, good.replace('�'.encode('utf-8'), b'\xff'))   # заменяющий декодер дал бы тот же текст
        bad = template_problems(self.tpl, MAIN)
        self.assertTrue(bad and 'не UTF-8' in bad[0], bad)
        code, out = self.run_ps()
        self.assertEqual(code, 5, out)
        self.assertIn('не UTF-8', out)


if __name__ == '__main__':
    unittest.main()
