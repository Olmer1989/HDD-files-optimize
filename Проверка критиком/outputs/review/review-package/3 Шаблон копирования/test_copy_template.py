"""Exercise the approved executor in Windows PowerShell 5.1 on synthetic files."""
import hashlib
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    template=ROOT/'Каталог дисков/_ШАБЛОН копирования/Копировать.ps1'
    with tempfile.TemporaryDirectory(prefix='HDD test ') as tmp:
        base=Path(tmp); src=base/'источник'; dst=base/'цель'; task=base/'задача'
        prefix=' Временные файлы/на диск 45/HDD17'
        actual=src/prefix; actual.mkdir(parents=True); dst.mkdir();task.mkdir()
        files=[(' папка/кириллица.bin',7_000_001),('больше 2 ГБ.bin',2**31+17)]
        expected={}
        for rel,size in files:
            p=actual/rel;p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('wb') as f:
                f.write(b'begin');f.seek(size-3);f.write(b'end')
            expected[rel]=digest(p)
        (task/'Копировать.ps1').write_bytes(template.read_bytes())
        pfx=prefix.replace('/','\\')
        (task/'тома.tsv').write_text(f'HDD17\tTESTSRC\t{pfx}\nHDD45\tTESTDST\n',encoding='utf-8-sig')
        (task/'список.tsv').write_text(''.join('HDD45\t'+rel.replace('/','\\')+f'\t{size}\ttest\t{expected[rel]}\n' for rel,size in files),encoding='utf-8-sig')
        args=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(task/'Копировать.ps1'),'-TestRoots',f'HDD17={src};HDD45={dst}']
        for run in range(2):
            proc=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150)
            if proc.returncode:
                raise RuntimeError(proc.stdout.decode('utf-8',errors='replace'))
            for rel,size in files:
                out=dst/'ПЕРЕНОС с других дисков/HDD17'/rel
                assert out.stat().st_size==size
                assert digest(out)==expected[rel]
            print('PASS',run+1,'copy >2 GiB / Cyrillic / source prefix / preserved destination paths / repeat',flush=True)
        # Wrong expected digest must leave neither a final file nor a .part.
        (actual/'wrong.bin').write_bytes(b'wrong')
        (task/'список.tsv').write_text('HDD45\twrong.bin\t5\ttest\t'+'0'*64+'\n',encoding='utf-8-sig')
        proc=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        assert proc.returncode!=0
        assert not (dst/'ПЕРЕНОС с других дисков/HDD17/wrong.bin').exists()
        print('PASS wrong SHA-256 refused',flush=True)

if __name__=='__main__': main()
