import contextlib
import io
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from catalog.recovery_plan import section, original_candidate, cmd_recovery_plan

class RecoveryPlanTests(unittest.TestCase):
    def test_northern_raw_has_priority(self):
        self.assertEqual(section('Фото\\Мойеро 2023\\DSC.NEF',123)[0],'Сафари')
        self.assertEqual(section('Сашин Винт\\Фото\\DSC.NEF',123)[0],'Саша, Таня, Наташа')

    def test_short_digitized_piece_keeps_group(self):
        self.assertEqual(section('Рим\\кусок.avi',100,{'Рим'})[0],'Оцифрованные источники')

    def test_variant_name_is_not_content_proof(self):
        key,note=original_candidate('Фото\\a.Id1234.jpg',{'фото\\a.jpg':None})
        self.assertEqual(key,'фото\\a.jpg')
        self.assertIn('не проверено',note)

    def test_plan_does_not_verify_or_promote_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'recovered';root.mkdir()
            (root/'a.jpg').write_bytes(b'x')
            (root/'b.jpg').write_bytes(b'bad-size')
            db=sqlite3.connect(':memory:')
            db.execute('create table files(disk text,path text,size integer,sha text)')
            db.executemany('insert into files values (?,?,?,?)',[('HDD61','a.jpg',1,'a'*64),('HDD61','b.jpg',1,'b'*64)])
            hb=SimpleNamespace(connect=lambda:(db,{}),check_disk=lambda c,d:None,
                presence=lambda c,d,p:[('a.jpg',1,'a'*64,1,1,3),('b.jpg',1,'b'*64,0,0,1)],
                decisions_for=lambda d:[],decision_of=lambda p,d:None,ANSWERS=base/'answers')
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_recovery_plan(SimpleNamespace(disk='HDD61',root=root),hb)
            import json
            result=json.loads((hb.ANSWERS/'разбор восстановления - HDD61/summary.json').read_text(encoding='utf-8'))
            self.assertEqual(result['matching']['review'],1)
            self.assertEqual(db.execute('select count(*) from files').fetchone()[0],2)
            self.assertIn('not verified',result['scope'])
            db.close()

if __name__=='__main__':unittest.main()
