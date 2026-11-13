import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import copy_workflow as cw

PROJECT=Path(r'C:\course_claude\Диски с фото и видео - оптимизация каталог')

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='.test_hdd51_',dir=Path(__file__).resolve().parent)
        self.root=Path(self.tmp.name)
        self.roots={d:self.root/d for d in ('HDD51',)+cw.MAIN}
        for p in self.roots.values():p.mkdir()
        self.task=self.root/'task'
        self.c=sqlite3.connect(':memory:')
        self.c.execute('create table files(disk,path,size,sha,mtime,origin,ev,sha_exp,name_lc)')
        self.c.execute('create index files_sha on files(sha,disk) where sha is not null')
        self.c.execute('create index files_exp on files(sha_exp,disk) where sha_exp is not null')
        self.c.execute('create index files_name on files(name_lc,size,disk)')
        self.c.execute('create table meta(key,value)')
        self.c.execute("insert into meta values('built','test')")
        self.data=b'synthetic photo only'
        self.sha=hashlib.sha256(self.data).hexdigest()
        p=self.roots['HDD51']/'Фото';p.mkdir()
        for name in ('a.jpg','duplicate.jpg'):
            f=p/name;f.write_bytes(self.data)
            self.c.execute('insert into files values(?,?,?,?,?,?,?,?,?)',('HDD51','Фото\\'+name,len(self.data),self.sha,f.stat().st_mtime_ns//10**9,'опись','S',None,name.lower()))
        self.hb=SimpleNamespace(connect=lambda:(self.c,{}),serial_map=lambda j:{'A':'HDD51','B':'HDD45','C':'HDD77'},
                                bp=SimpleNamespace(OUT_DIR=self.root/'logs'),TEMPLATE=PROJECT/'Каталог дисков'/'_ШАБЛОН копирования')

    def tearDown(self):
        self.c.close();self.tmp.cleanup()

    def prepare(self):
        with patch.object(cw,'volumes',return_value=self.roots):
            cw.prepare(self.hb,SimpleNamespace(disk='HDD51',output=self.task))
        return json.loads((self.task/'План.json').read_text(encoding='utf-8'))

    def log_and_copy(self,plan):
        with (self.task/'Журнал копирования 2026-11-13 20-00-00.tsv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['цель','результат','размер','SHA-256 прочитанного','источник','куда'],delimiter='\t');w.writeheader()
            for e in plan['copy']:
                p=self.roots[e['target']].joinpath(*cw.clean_rel(e['path']));p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(self.data)
                w.writerow({'цель':e['target'],'результат':'скопирован, размер и SHA-256 совпали','размер':e['size'],'SHA-256 прочитанного':self.sha,'источник':'J:\\'+e['source'],'куда':('G:' if e['target']=='HDD45' else 'S:')+'\\'+e['path']})

    def test_source_seconds_and_duplicate_hash_copy_once(self):
        p=self.prepare()
        self.assertEqual(len(p['items']),2)
        self.assertEqual(p['copy_counts'],{'HDD45':1,'HDD77':1})
        self.log_and_copy(p)
        self.assertTrue(cw.verify(self.task,self.roots)['ok'])

    def test_existing_same_size_without_operation_never_passes(self):
        p=self.prepare()
        for e in p['copy']:
            f=self.roots[e['target']].joinpath(*cw.clean_rel(e['path']));f.parent.mkdir(parents=True);f.write_bytes(b'x'*e['size'])
        result=cw.verify(self.task,self.roots)
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['errors']),2)
        self.assertFalse(cw.verify(self.task,self.roots,preflight=True)['ok'])

    def test_missing_target_and_changed_source_block_check(self):
        p=self.prepare();self.log_and_copy(p)
        e=p['copy'][0];self.roots[e['target']].joinpath(*cw.clean_rel(e['path'])).unlink()
        self.assertFalse(cw.verify(self.task,self.roots)['ok'])
        (self.roots['HDD51']/'Фото'/'a.jpg').write_bytes(b'changed')
        self.assertFalse(cw.verify(self.task,self.roots)['ok'])

    def test_recovery_and_image_not_entered(self):
        r=self.roots['HDD51']/'ВОССТАНОВЛЕНО_HDD61';r.mkdir();(r/'private.jpg').write_bytes(b'x')
        (self.roots['HDD51']/'HDD61_2026-11-12.img.dsk').write_bytes(b'x')
        p=self.prepare()
        self.assertEqual(len(p['items']),2)
        self.assertIn('ВОССТАНОВЛЕНО_HDD61',p['excluded'])

    def test_unrelated_document_and_music_cover_do_not_become_family(self):
        self.assertEqual(cw.classify({'path':'Music\\Album\\cover.jpg'},set())[0][0],'4')
        self.assertEqual(cw.classify({'path':'Документы\\a.docx'}, {'Фото'})[0][0],'4')
        self.assertEqual(cw.classify({'path':'Фото\\a.xmp'}, {'Фото'})[0][0],'3')

    def test_path_escape_and_secret_refused(self):
        for s in ('..\\escape.jpg','J:\\file.jpg','a\\.env','keys\\secret.pem'):
            with self.assertRaises(ValueError):cw.clean_rel(s)

    def test_already_there_not_successful_copy(self):
        self.prepare()
        (self.task/'Журнал копирования 2026-11-13 20-00-00.tsv').write_text('цель\tрезультат\tразмер\tисточник\tкуда\nHDD45\tуже есть\t20\tJ:\\Фото\\a.jpg\tG:\\some.jpg\n',encoding='utf-8-sig')
        self.assertEqual(cw.successful_logs(self.task),{})

    def test_old_uppercase_header_lowercase_drive_and_truncated_tail(self):
        logfile=self.root/'old.tsv'
        logfile.write_text('Время\tРезультат\tОткуда\tКуда\tРазмер\n12:00\tскопирован\tj:\\Фото\\a.jpg\tG:\\old\\a.jpg\t20\n12:01\tскопирован\tJ:\\broken.jpg\n',encoding='utf-8-sig')
        cache={}
        self.assertTrue(cw.old_success(logfile,'Фото\\a.jpg','old\\a.jpg',20,cache))
        self.assertFalse(cw.old_success(logfile,'Фото\\other.jpg','old\\a.jpg',20,cache))
        self.assertTrue(cache[('warnings',)])

    def test_same_name_size_from_other_source_is_not_a_copy(self):
        f=self.roots['HDD45']/'other'/'a.jpg';f.parent.mkdir();f.write_bytes(self.data)
        logroot=self.root/'logs';logroot.mkdir()
        (logroot/'old.tsv').write_text(f'Время\tРезультат\tОткуда\tКуда\tРазмер\n12:00\tскопирован\tJ:\\Чужая папка\\a.jpg\tG:\\other\\a.jpg\t{len(self.data)}\n',encoding='utf-8-sig')
        self.c.execute('insert into files values(?,?,?,?,?,?,?,?,?)',('HDD45','other\\a.jpg',len(self.data),None,0,'журнал: old.tsv','Z',None,'a.jpg'))
        row={'path':'Фото\\a.jpg','size':len(self.data),'sha':None}
        self.assertIsNone(cw.known_copy(self.c,'HDD51',row,'HDD45',self.roots,{},logroot))

    def test_preflight_checks_source_before_copy(self):
        self.prepare()
        self.assertTrue(cw.verify(self.task,self.roots,preflight=True)['ok'])
        (self.roots['HDD51']/'Фото'/'a.jpg').write_bytes(b'changed')
        self.assertFalse(cw.verify(self.task,self.roots,preflight=True)['ok'])

    def test_corrupt_new_log_tail_does_not_crash_checker(self):
        self.prepare()
        (self.task/'Журнал копирования 2026-11-13 21-00-00.tsv').write_text('цель\tрезультат\tразмер\tисточник\tкуда\nHDD45\tскопирован, размер совпал\t',encoding='utf-8-sig')
        self.assertEqual(cw.successful_logs(self.task),{})

    def test_movie_inside_mixed_folder_excluded(self):
        self.assertEqual(cw.classify({'path':'Смешанная папка\\Dobrinya.Nikitich.I.Zmey.Gorinich.2006.mkv'},set())[0][0],'4')

    def test_utf8_cmd_stops_before_copy_when_preflight_fails(self):
        self.task.mkdir();cw.write_launchers(self.task)
        (self.task/'Проверить.py').write_text('raise SystemExit(2)\n',encoding='utf-8')
        (self.task/'Копировать.ps1').write_text("Set-Content -LiteralPath (Join-Path $PSScriptRoot 'must-not-run') -Value 'BAD'",encoding='utf-8-sig')
        subprocess.run(['cmd.exe','/c',str(self.task/'1 — Копировать.cmd')],input=b'\n',capture_output=True,timeout=30)
        self.assertFalse((self.task/'must-not-run').exists())

    def test_utf8_cmd_calls_copy_and_postcheck(self):
        self.task.mkdir();cw.write_launchers(self.task)
        (self.task/'Проверить.py').write_text("from pathlib import Path\np=Path(__file__).parent/'checks'\np.write_text(p.read_text()+'x' if p.exists() else 'x')\n",encoding='utf-8')
        (self.task/'Копировать.ps1').write_text("Set-Content -LiteralPath (Join-Path $PSScriptRoot 'did-run') -Value 'OK'",encoding='utf-8-sig')
        p=subprocess.run(['cmd.exe','/c',str(self.task/'1 — Копировать.cmd')],input=b'\n',capture_output=True,timeout=30)
        self.assertTrue((self.task/'did-run').exists(),p.stdout+p.stderr)
        self.assertEqual((self.task/'checks').read_text(),'xx')

if __name__=='__main__':unittest.main()
