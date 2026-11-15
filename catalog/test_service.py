"""Сценарии из рецензии GPT (14.11.2026) на единый путь записи и состояние заданий. Временные данные.

Запуск из корня проекта:  py -m unittest catalog\\test_service.py
"""
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hashbase as hb       # noqa: E402
import service as sv        # noqa: E402
from test_hashbase import Base, NS, S, make_disk      # noqa: E402


class ServiceTest(Base):
    def setUp(self):
        super().setUp()
        make_disk(self.scans, 'HDD92', 'AAAA0092', [('Фото\\a.jpg', 100, S[6]), ('Фотоархив\\b.jpg', 200, S[7])])
        hb.ensure_tables()

    def manual_count(self):
        return len(hb.manual_rows())

    def paths(self, disk):
        return {r[0] for r in self.db().execute('select path from files where disk=?', (disk,))}

    def test_second_write_after_first_and_rebuild(self):
        self.db()
        self.quiet(sv.add_manual, '01.01.2099', 'перемещено', 'HDD92', 'Фото', 'HDD92', 'Новое\\Фото')
        self.quiet(sv.add_manual, '02.01.2099', 'удалено', 'HDD92', 'Новое\\Фото\\a.jpg')
        self.assertEqual(self.paths('HDD92'), {'Фотоархив\\b.jpg'})
        self.assertEqual(self.manual_count(), 2)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)

    def test_batch_is_written_whole(self):
        self.db()
        res = self.quiet(sv.add_manual_batch, '01.01.2099', [('удалено', 'HDD92', 'Фото'),
                                                             ('перемещено', 'HDD92', 'Фотоархив', 'HDD92', 'Новое')], 'пакет')
        self.assertEqual([ln for _, ln in res], [2, 3])
        self.assertEqual(self.manual_count(), 2)
        self.assertEqual(self.paths('HDD92'), {'Новое\\b.jpg'})            # одно применение - обе строки учтены
        self.assertEqual(len(list((hb.BASE_DIR / 'архив таблиц').glob('*'))), 1)   # одна копия таблицы

    def test_batch_error_writes_nothing(self):
        self.db()
        before = hb.MANUAL.read_bytes()
        for rows in ([('удалено', 'HDD92', 'Фото'), ('удалено', 'HDD92', 'Нет такой')],      # вторая - нет в базе
                     [('удалено', 'HDD92', 'Фото'), ('удалено', 'HDD92', 'Фото')],           # повтор в пакете
                     [('удалено', 'HDD92', 'Фото'), ('стёрто', 'HDD92', 'Фотоархив')]):      # неверное действие
            with self.assertRaises(sv.Refused):
                sv.add_manual_batch('01.01.2099', rows)
            self.assertEqual(hb.MANUAL.read_bytes(), before)                # байт в байт прежняя

    def test_neighbour_names_are_not_touched(self):
        self.db()
        pv = self.quiet(sv.manual_preview, '01.01.2099', 'удалено', 'HDD92', 'Фото')
        self.assertEqual(pv['files'], 1)                                  # «Фотоархив» не задет
        self.quiet(sv.add_manual, '01.01.2099', 'удалено', 'HDD92', 'Фото')
        self.assertEqual(self.paths('HDD92'), {'Фотоархив\\b.jpg'})

    def test_repeat_is_refused(self):
        self.db()
        self.quiet(sv.add_manual, '01.01.2099', 'удалено', 'HDD92', 'Фото')
        with self.assertRaises(sv.Refused):
            sv.manual_preview('01.01.2099', 'удалено', 'HDD92', 'Фото')   # файлов уже нет - и строка уже есть
        self.assertEqual(self.manual_count(), 1)

    def test_backup_is_made_before_write(self):
        self.db()
        before = hb.MANUAL.read_bytes()
        self.quiet(sv.add_manual, '01.01.2099', 'удалено', 'HDD92', 'Фото')
        copies = list((hb.BASE_DIR / 'архив таблиц').glob('*'))
        self.assertTrue(copies)
        self.assertIn(before, [p.read_bytes() for p in copies])          # в архиве - таблица до записи

    def test_refusal_leaves_table_byte_for_byte(self):
        self.db()
        before = hb.MANUAL.read_bytes()
        for bad in (('2099-01-01', 'удалено', 'HDD92', 'Фото'),          # дата не в виде ДД.ММ.ГГГГ
                    ('01.01.2099', 'удалено', 'HDD92', 'Нет такой папки'),  # пустой путь
                    ('01.01.2099', 'удалено', 'HDD00', 'Фото')):         # нет диска
            with self.assertRaises(sv.Refused):
                sv.add_manual(*bad)
        self.assertEqual(hb.MANUAL.read_bytes(), before)

    def test_saved_but_not_applied_is_applied_once_later(self):
        self.db()
        with sv.TableLock():                                             # «сбой» после записи, до применения
            sv.append_row(hb.MANUAL, ['01.01.2099', 'удалено', 'HDD92', 'Фото', '', '', 'проба'])
        self.assertEqual(self.paths('HDD92'), {'Фотоархив\\b.jpg'})      # следующая команда применила
        self.db()
        n = self.db().execute("select count(*) from applied where kind='ручная операция'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_unfinished_row_is_not_applied_and_blocks_writing(self):
        self.db()
        with open(hb.MANUAL, 'ab') as f:
            f.write('01.01.2099\tудалено\tHDD92\tФото'.encode('utf-8'))   # строку ещё пишут: нет перевода строки
        self.assertIn('Фото\\a.jpg', self.paths('HDD92'))
        with self.assertRaises(sv.Refused):
            sv.add_manual('02.01.2099', 'удалено', 'HDD92', 'Фотоархив', apply=False)

    def test_concurrent_writers(self):
        self.db()
        errors = []

        def write(path):
            try:
                sv.add_manual('01.01.2099', 'удалено', 'HDD92', path, apply=False)
            except Exception as e:                                       # noqa: BLE001
                errors.append(e)
        hb.close_last()
        ts = [threading.Thread(target=write, args=(p,)) for p in ('Фото', 'Фотоархив')]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        rows = [f[3] for _, f in hb.manual_rows()]
        self.assertEqual(sorted(rows), ['Фото', 'Фотоархив'])           # обе строки целы
        self.assertEqual(self.paths('HDD92'), set())                     # обе применены
        self.assertTrue(list((hb.BASE_DIR / 'архив таблиц').glob('ручные операции *.tsv')))

    def test_mistaken_row_is_fixed_with_reason(self):
        self.db()
        self.quiet(sv.add_manual, '01.01.2099', 'удалено', 'HDD92', 'Фото')
        self.quiet(sv.fix_manual, 2, ['01.01.2099', 'перемещено', 'HDD92', 'Фото', 'HDD92', 'Разбор\\Фото'], 'это было перемещение')
        self.assertIn('Разбор\\Фото\\a.jpg', self.paths('HDD92'))
        self.assertIn('исправлено', hb.manual_rows()[0][1][6])
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)

    def test_decision_and_exclusion(self):
        self.db()
        with self.assertRaises(sv.Refused):
            sv.decision_preview('HDD92', 'Фото', 'выбросить')            # неизвестное решение
        sv.add_decision('HDD92', 'Фото', 'раздел: Проба')
        with self.assertRaises(sv.Refused):
            sv.add_decision('HDD92', 'Фото', 'раздел: Проба')            # повтор
        self.assertEqual(hb.decision_of('Фото\\a.jpg', hb.decisions_for('HDD92')), 'раздел: Проба')
        self.quiet(sv.add_exclusion, 'HDD92', 'Фотоархив')
        self.assertEqual(self.paths('HDD92'), {'Фото\\a.jpg'})


class TaskStateTest(Base):
    def make_task(self, done_rows):
        t = self.tmp / 'Запускаемые скрипты' / 'Задание'
        t.mkdir(parents=True, exist_ok=True)
        (t / 'список.tsv').write_text('HDD77\ta.jpg\t1\tф\t\nHDD77\tb.jpg\t1\tф\t\n', encoding='utf-8')
        if done_rows is not None:
            (t / 'Журнал копирования 2099-01-01 00-00-00.tsv').write_text(
                'время\tцель\tрезультат\tразмер\tSHA-256 прочитанного\tисточник\tкуда\n' +
                ''.join(f'1\tHDD77\t{r}\t1\t\tK:\\{p}\tS:\\x\\{p}\n' for p, r in done_rows), encoding='utf-8-sig')
        return t

    def test_states(self):
        self.assertEqual(sv.task_state(self.make_task(None), [])['state'], 'не запускалось')
        t = self.make_task([('a.jpg', 'скопирован, размер совпал')])
        self.assertEqual(sv.task_state(t, [])['state'], 'прервано')                   # процесса нет, строк меньше
        self.assertEqual(sv.task_state(t, [f'powershell -File "{t}\\Копировать.ps1"'])['state'], 'идёт')
        self.assertEqual(sv.task_state(t, None)['state'], 'состояние неизвестно')    # процессы узнать не удалось
        t = self.make_task([('a.jpg', 'скопирован, размер совпал'), ('b.jpg', 'ОШИБКА: диск')])
        self.assertEqual(sv.task_state(t, [])['state'], 'готово с ошибками')
        t = self.make_task([('a.jpg', 'уже есть'), ('b.jpg', 'скопирован, размер совпал')])
        self.assertEqual(sv.task_state(t, [])['state'], 'готово')


if __name__ == '__main__':
    unittest.main()
