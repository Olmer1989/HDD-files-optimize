"""Длина пути не ограничена (17.11.2026, решение владельца): разбор не блокирует длинный путь назначения,
перенос не оставляет файл на месте из-за длины. Шаблоны копирования 2.7 и перемещения 1.3 работают через \\\\?\\.

Запуск из корня проекта:  py -m unittest catalog.test_long_paths
Временные данные; настоящие диски, таблицы и задания не используются.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_logic_v3 import H, NS, V3Base, hb, make_disk, rz    # noqa: E402 - V3Base: обвязка без собственных тестов

DISK = 'HDD62'
LONG = 'Поход 2010\\' + 'Д' * 120 + '\\' + 'е' * 120               # без расширения: дальше .jpg / .mp4
COPY_PREFIX = f'X:\\{rz.COPY_ROOT}\\{DISK}\\'


class LongPathTest(V3Base):
    def test_long_destination_is_copied(self):
        files = [(LONG + '.jpg', 500, H[41])]
        unhashed = [(LONG + '.mp4', 700)]
        make_disk(self.scans, DISK, 'AAAA0062', files, unhashed=unhashed)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertGreater(len(COPY_PREFIX + LONG + '.jpg'), 259)       # прежде - «длинный путь», не копировался
        self.mark(('', 'Н1'), disk=DISK)
        P = self.plan(DISK, detail=True)
        self.assertEqual(P.blocked, [])
        g = next(k for k in P.groups if k[1] == 'Поход 2010')
        for d in ('HDD45', 'HDD77'):
            self.assertEqual({r[1] for r in P.rows[(g, d)]}, {LONG + '.jpg', LONG + '.mp4'}, d)
        self.assertFalse([x for x in rz.attention_lines(P) if 'длиннее' in x])


if __name__ == '__main__':
    unittest.main()
