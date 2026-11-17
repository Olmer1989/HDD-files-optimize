"""Prepare non-photo/non-video files from HDD17 for F using approved executor.

Only source metadata and stored inventories are read. No archive content is read
and no copying/formatting is started. Existing-copy exclusion is path+size only.
"""
import csv
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scanner'))
from inventory import MEDIA, excluded_file, volume

MEDIA_EXT=MEDIA | set('.jpe .jfif .jxl .jp2 .j2k .jpf .jpx .jpm .mj2 .svg .ico .icns .dib .pcx .tga .ppm .pgm .pbm .pnm .pam .dds .3g2 .asf .divx .f4v .ogv .rm .rmvb .m2t .m2p .mpv .mpeg2 .dv .mpe .mjpg .mjpeg .lrv .insv .360 .r3d .braw'.split())
OUT=ROOT/'Каталог дисков/K - НЕ фото и НЕ видео на F'
TEMP=Path('F:/ВРЕМЕННЫЕ ФАЙЛЫ для ПЕРЕМЕЩЕНИЯ на диски')
DEST='ВРЕМЕННЫЕ файлы с других дисков НЕ фото и НЕ видео'
SERVICE={'$recycle.bin','system volume information','recycler'}
DENIED=[]

def files(root):
    stack=[root]; scanned=0; last=time.monotonic()
    while stack:
        folder=stack.pop()
        try:
            with os.scandir(folder) as entries:
                for e in entries:
                    if excluded_file(e.name): continue
                    try:s=e.stat(follow_symlinks=False)
                    except PermissionError:
                        DENIED.append(str(Path(e.path).relative_to(root)));continue
                    if getattr(s,'st_file_attributes',0)&0x400 or stat.S_ISLNK(s.st_mode):continue
                    if stat.S_ISDIR(s.st_mode):
                        if e.name.casefold() not in SERVICE:stack.append(Path(e.path))
                    elif stat.S_ISREG(s.st_mode):
                        scanned+=1
                        if time.monotonic()-last>10:
                            print('Metadata entries:',scanned,flush=True);last=time.monotonic()
                        if Path(e.name).suffix.lower() not in MEDIA_EXT:
                            yield str(Path(e.path).relative_to(root)),s.st_size
        except PermissionError:
            DENIED.append(str(folder.relative_to(root)))

def matching_file(path,size):
    try:
        s=path.lstat()
        return stat.S_ISREG(s.st_mode) and not getattr(s,'st_file_attributes',0)&0x400 and s.st_size==size
    except FileNotFoundError:return False

def main():
    assert volume('K:\\')[0]=='04116A7A','K is not registered HDD17'
    assert volume('F:\\')[0]=='4E5BE816','F is not registered staging disk'
    assert not OUT.exists(),'Task already exists; preserve its list and logs'
    source=list(files(Path('K:/')))
    print('Nonmedia candidates:',len(source),flush=True)
    candidates={(p.casefold(),n) for p,n in source}
    present=set()
    jobs={}
    for p in (ROOT/'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные').glob('*/*/result.json'):
        d=json.loads(p.read_text(encoding='utf-8-sig'));k=d.get('disk_id')
        if k in ('HDD17','HDD45','HDD77') and (k not in jobs or p.stat().st_mtime>jobs[k].stat().st_mtime):jobs[k]=p
    fallback=[]
    if DENIED:
        db=sqlite3.connect(jobs['HDD17'].with_name('inventory.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            known={p for p,n in source}
            for path,size in db.execute('select path,size from files'):
                if path in known or Path(path).suffix.lower() in MEDIA_EXT or any(excluded_file(x) for x in path.split('\\')):continue
                if any(path==prefix or path.startswith(prefix+'\\') for prefix in DENIED):
                    source.append((path,size));fallback.append(path)
        finally:db.close()
        candidates={(p.casefold(),n) for p,n in source}
    for disk,p in jobs.items():
        if disk=='HDD17':continue
        db=sqlite3.connect(p.with_name('inventory.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            for path,size in db.execute('select path,size from files'):
                key=(path.casefold(),size)
                if key in candidates:present.add(key)
        finally:db.close()
    # Actual copy journals, including later additions not in scan snapshots.
    for log in (ROOT/'Каталог дисков').glob('*/Журнал копирования *.tsv'):
        with log.open(encoding='utf-8-sig',newline='') as f:
            for raw in csv.DictReader(f,delimiter='\t'):
                r={k.lower():v for k,v in raw.items() if k}
                if not r.get('результат','').startswith(('скопирован','уже есть')):continue
                src=r.get('источник') or r.get('откуда','')
                if src.startswith('K:\\'):
                    key=(src[3:].casefold(),int(r['размер']))
                    if key in candidates:present.add(key)
    todo=[];skipped=[]
    for path,size in source:
        key=(path.casefold(),size)
        reason=None
        if key in present:reason='совпадение полного пути и размера в описи 45/77 или журнале копирования'
        else:
            locations=[TEMP/path,TEMP/'на диск 45/HDD17'/path,Path('F:/')/DEST/'HDD17'/path]
            for p in locations:
                if matching_file(p,size):reason='совпадение пути и размера на F: '+str(p);break
        if reason:skipped.append((path,size,reason))
        else:todo.append(('STAGING_F',path,size,'не фото/видео; исходного SHA-256 нет',''))
    assert volume('K:\\')[0]=='04116A7A' and volume('F:\\')[0]=='4E5BE816'
    total=sum(r[2] for r in todo)
    assert shutil.disk_usage('F:/').free>total+1024**3,'Not enough free space on F'
    OUT.mkdir()
    template=ROOT/'Каталог дисков/_ШАБЛОН копирования'
    from hb_core.paths import copy_template      # шаблон 2.8 - из частей: главный, Запустить.cmd и части
    copy_template(template, OUT, 'Копировать.ps1')      # байты сверяет сам
    (OUT/'тома.tsv').write_text(f'HDD17\t04116A7A\nSTAGING_F\t4E5BE816\t{DEST}\n',encoding='utf-8-sig')
    for name,rows in [('список.tsv',todo),('Уже есть - исключено.tsv',skipped)]:
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f,delimiter='\t',lineterminator='\n').writerows(rows)
    (OUT/'Недоступные папки - проверить.txt').write_text('\n'.join(DENIED),encoding='utf-8-sig')
    summary={'source_nonmedia':len(source),'copy_files':len(todo),'copy_bytes':total,'GiB':round(total/2**30,3),'skipped':len(skipped),'denied_folders':len(DENIED),'inventory_fallback_files':len(fallback),'exclusion':'path + size, not verified content','source':'HDD17','destination':'F:\\'+DEST+'\\HDD17'}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
