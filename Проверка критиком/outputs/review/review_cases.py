"""Independent regression probes. Only synthetic temporary data is modified."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parent / 'review-package'
CAT = ROOT / '2 Программа быстрых ответов'
sys.path.insert(0, str(CAT))
import hashbase as hb
from test_hashbase import HashBaseTest, S


def capture(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args)
    return result, buf.getvalue()


class ReviewCases(HashBaseTest):
    # Restrict discovery to the probes below, without inherited fixture tests.
    def verdict(self, disk, folder):
        return capture(hb.cmd_candel, argparse.Namespace(disk=disk, folder=folder))[1]

    def probe_ignored_unique_database(self):
        job = next((self.scans / 'HDD90 - тест').iterdir())
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('insert into files values (?,?,?,?,?,?,?)',
                      ('A\\unique.mdb', 1234, '0', '0', '', 32, 'other'))
        text = self.verdict('HDD90', 'A\\1.jpg')
        # Restrict the folder to one verified image and one unique database.
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute("delete from files where path not in (?,?)", ('A\\1.jpg', 'A\\unique.mdb'))
        with sqlite3.connect(job / 'hashes.sqlite') as c:
            c.execute('delete from hashes where path<>?', ('A\\1.jpg',))
        text = self.verdict('HDD90', 'A')
        self.assertIn('ОТВЕТ: ДА', text)
        print('CONFIRMED: unique .mdb ignored -> YES')

    def probe_target_self_counted(self):
        job = next((self.scans / 'HDD90 - тест').iterdir())
        with sqlite3.connect(job / 'hashes.sqlite') as c:
            c.execute('delete from hashes where sha256=?',(S[1],))
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('delete from files where path=?',('A\\1.jpg',))
        text = self.verdict('HDD45', 'X\\1.jpg')
        self.assertIn('ОТВЕТ: ДА', text)
        print('CONFIRMED: deleting from HDD45 still counts HDD45 as retained copy -> YES')

    def probe_partial_inventory(self):
        job = next((self.scans / 'HDD90 - тест').iterdir())
        (job / 'result.json').write_text(json.dumps({'disk_id':'HDD90', 'status':'complete_with_inventory_errors', 'inventory_errors':1}))
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('delete from files where path<>?',('A\\1.jpg',))
            c.execute('create table errors(path text,operation text,message text)')
            c.execute('insert into errors values (?,?,?)', ('A\\unreadable', 'scandir', 'Access denied'))
        with sqlite3.connect(job / 'hashes.sqlite') as c:
            c.execute('delete from hashes where path<>?',('A\\1.jpg',))
        text = self.verdict('HDD90', 'A')
        self.assertIn('ОТВЕТ: ДА', text)
        self.assertNotIn('inventory_errors', text)
        print('CONFIRMED: incomplete scan accepted with no verdict warning')

    def probe_stale_hash_overrides_inventory(self):
        job = next((self.scans / 'HDD90 - тест').iterdir())
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('update files set size=999,mtime_ns=? where path=?',('2000000000','A\\1.jpg'))
        text = self.verdict('HDD90','A\\1.jpg')
        self.assertIn('ОТВЕТ: ДА',text)
        c,_ = capture(hb.connect)[0]
        self.assertEqual(c.execute('select size from files where disk=? and path=?',('HDD90','A\\1.jpg')).fetchone()[0],100)
        print('CONFIRMED: stale hash row overrides newer inventory with different size -> YES')

    def probe_unhashed_probable_copy_returns_yes(self):
        job = next((self.scans / 'HDD91 - тест').iterdir())
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('insert into files values (?,?,?,?,?,?,?)',('Z\\заметки.doc',10,'0','0','',32,'other'))
        text = self.verdict('HDD90','A\\заметки.doc')
        self.assertIn('ОТВЕТ: ДА по фото и видео',text)
        self.assertIn('файлов с SHA-256 0',text)
        print('CONFIRMED: unhashed document with one probable copy gets YES by photo/video')

    def probe_old_log_resurrects_file(self):
        job = next((self.scans / 'HDD77 - тест').iterdir())
        # A later inventory says the old copy no longer exists.
        with sqlite3.connect(job / 'inventory.sqlite') as c:
            c.execute('delete from files')
        with sqlite3.connect(job / 'hashes.sqlite') as c:
            c.execute('delete from hashes')
        self.task('OldCopy', [('HDD90','AAAA0090'),('HDD77','AAAA0077')],
                  'Журнал копирования 2020-01-01 00-00-00.tsv',
                  ('время','цель','результат','размер','SHA-256 прочитанного','источник','куда'),
                  [('00:00:01','HDD77','скопирован, размер и SHA-256 совпали','100',S[1],'K:\\A\\1.jpg','S:\\old\\1.jpg')])
        log=next((self.out/'OldCopy').glob('Журнал*.tsv'))
        os.utime(log,(1577836800,1577836800))
        text = self.verdict('HDD90', 'A\\1.jpg')
        self.assertIn('ОТВЕТ: ДА', text)
        print('CONFIRMED: old log resurrects absent copy after new inventory -> YES')

    def probe_move_twice_same_day(self):
        hb.ensure_tables()
        hb.MANUAL.write_text(hb.MANUAL_HEAD+'\n'
            '13.11.2026\tперемещено\tHDD90\tB\tHDD90\tC\tfirst\n'
            '13.11.2026\tперемещено\tHDD90\tC\tHDD90\tD\tsecond\n', encoding='utf-8-sig')
        c,_ = capture(hb.connect)[0]
        paths = [r[0] for r in c.execute('select path from files where disk=?', ('HDD90',))]
        self.assertIn('C\\5.jpg', paths)
        self.assertIn('D\\5.jpg', paths)
        print('CONFIRMED: two same-day manual moves leave phantom source C\\5.jpg')

    def probe_cmp_unhashed(self):
        text = capture(hb.cmd_cmp, argparse.Namespace(disk_a='HDD90',folder_a='A\\заметки.doc',disk_b='HDD91',folder_b='missing'))[1]
        self.assertIn('папки одинаковы по содержимому', text)
        self.assertIn('только в A 1', text)
        print('CONFIRMED: cmp announces equal contents before reporting unique unhashed document')

    def probe_decision_hides_unbacked_file(self):
        hb.ensure_tables()
        hb.DECISIONS.write_text(hb.DECISION_HEAD+'\nHDD90\tB\tраздел: Архив\tretain elsewhere\n',encoding='utf-8-sig')
        text = capture(hb.cmd_mklist, argparse.Namespace(disk='HDD90',to=['HDD45','HDD77'],name='Plan',folder=['B'],dry=True))[1]
        self.assertIn('Копировать нечего', text)
        print('CONFIRMED: section assignment silently removes unbacked files from copy plan')

    def probe_copy_existing_wrong_content_and_part_collision(self):
        template = ROOT / '3 Шаблон копирования' / 'Копировать.ps1'
        task = self.out / 'Copy'; task.mkdir()
        src = self.tmp / 'src'; src.mkdir()
        dst = self.tmp / 'dst'; dst.mkdir()
        content = b'G' * 100
        digest = hashlib.sha256(content).hexdigest()
        (src / 'A').mkdir()
        (src / 'A' / '1.jpg').write_bytes(content)
        final = dst / 'ПЕРЕНОС с других дисков' / 'HDD90' / 'A' / '1.jpg'
        final.parent.mkdir(parents=True)
        final.write_bytes(b'B' * 100)
        # Align source and known HDD45 hashes with the actual good bytes.
        for disk in ['HDD90','HDD45']:
            job = next((self.scans / (disk + ' - тест')).iterdir())
            with sqlite3.connect(job / 'hashes.sqlite') as c:
                c.execute('update hashes set sha256=? where sha256=?', (digest,S[1]))
        job77 = next((self.scans / 'HDD77 - тест').iterdir())
        with sqlite3.connect(job77 / 'hashes.sqlite') as c:
            c.execute('delete from hashes')
        with sqlite3.connect(job77 / 'inventory.sqlite') as c:
            c.execute('delete from files')
        shutil.copy2(template,task / template.name)
        (task/'тома.tsv').write_text('HDD90\tAAAA0090\nHDD77\tAAAA0077\n',encoding='utf-8-sig')
        (task/'список.tsv').write_text('HDD77\tA\\1.jpg\t100\ttest\t'+digest+'\n',encoding='utf-8-sig')
        args = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(task/template.name),'-TestRoots',f'HDD90={src};HDD77={dst}']
        proc = subprocess.run(args,capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stdout.decode(errors='replace'))
        self.assertNotEqual(hashlib.sha256(final.read_bytes()).hexdigest(), digest)
        # TestRoots emulates volume roots. Translate only the two temporary
        # mount-point prefixes to drive-letter roots for the log consumer.
        for log in task.glob('Журнал*.tsv'):
            raw=log.read_text(encoding='utf-8-sig')
            log.write_text(raw.replace(str(src),'K:').replace(str(dst),'S:'),encoding='utf-8-sig')
        self.assertIn('ОТВЕТ: ДА',self.verdict('HDD90','A\\1.jpg'))
        print('CONFIRMED END TO END: wrong same-size destination -> skipped -> source hash inherited -> candel YES')
        # A pre-existing unrelated .part is deleted, then replaced with the copy.
        final.unlink()
        part = final.with_name(final.name+'.part')
        part.write_bytes(b'UNRELATED PREEXISTING DATA')
        proc = subprocess.run(args,capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stdout.decode(errors='replace'))
        self.assertFalse(part.exists())
        self.assertEqual(final.read_bytes(),content)
        print('CONFIRMED: unrelated pre-existing .part is deleted without ownership check')

    def probe_source_subfolder_bypasses_same_volume_guard(self):
        template = ROOT / '3 Шаблон копирования' / 'Копировать.ps1'
        task = self.out / 'SameVolume';task.mkdir()
        volume = self.tmp / 'volume'; (volume/'sub').mkdir(parents=True)
        content=b'good';(volume/'sub'/'a.jpg').write_bytes(content)
        shutil.copy2(template,task/template.name)
        (task/'тома.tsv').write_text('HDD90\tSAME\tsub\nHDD77\tSAME\n',encoding='utf-8-sig')
        (task/'список.tsv').write_text('HDD77\ta.jpg\t4\ttest\t'+hashlib.sha256(content).hexdigest()+'\n',encoding='utf-8-sig')
        args=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(task/template.name),'-TestRoots',f'HDD90={volume};HDD77={volume}']
        proc=subprocess.run(args,capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stdout.decode(errors='replace'))
        self.assertTrue((volume/'ПЕРЕНОС с других дисков'/'HDD90'/'a.jpg').exists())
        print('CONFIRMED: source subfolder bypasses same-volume guard; writes on source volume')


if __name__ == '__main__':
    suite = unittest.TestSuite(ReviewCases(name) for name in sorted(ReviewCases.__dict__) if name.startswith('probe_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
