import hashlib
import tempfile
import unittest
import os
from pathlib import Path
from hash_files import hash_one, signature

class HashTests(unittest.TestCase):
    def test_same_name_same_size_different_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a'/'IMG_0001.JPG'; a.parent.mkdir()
            b=Path(tmp)/'b'/'IMG_0001.JPG'; b.parent.mkdir()
            a.write_bytes(b'abc'); b.write_bytes(b'xyz')
            self.assertNotEqual(hash_one(a,signature(a.stat())),hash_one(b,signature(b.stat())))

    def test_different_names_and_modification_dates_same_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'old.jpg'; b=Path(tmp)/'renamed.jpg'
            a.write_bytes(b'abc'); b.write_bytes(b'abc')
            os.utime(a,ns=(1000000000000000000,1000000000000000000))
            os.utime(b,ns=(1500000000000000000,1500000000000000000))
            self.assertNotEqual(a.stat().st_mtime_ns,b.stat().st_mtime_ns)
            self.assertEqual(hash_one(a,signature(a.stat())),hash_one(b,signature(b.stat())))

    def test_missing_inventory_file_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.jpg'; p.write_bytes(b'abc')
            s=signature(p.stat())
            self.assertEqual(hash_one(p,(s[0],s[1],'0')),hashlib.sha256(b'abc').hexdigest())

    def test_contents_not_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/n for n in ('a.jpg','renamed.jpg','different.jpg')]
            for p,b in zip(paths,(b'abc',b'abc',b'xyz')):
                p.write_bytes(b)
            hashes=[hash_one(p,signature(p.stat())) for p in paths]
            self.assertEqual(hashes[0],hashlib.sha256(b'abc').hexdigest())
            self.assertEqual(hashes[0],hashes[1])
            self.assertNotEqual(hashes[0],hashes[2])

    def test_changed_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.jpg'; p.write_bytes(b'abc'); expected=signature(p.stat())
            p.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):
                hash_one(p,expected)

if __name__ == '__main__':
    unittest.main()
