"""Prepare staged HDD17 files on F for HDD45; no archive contents are read."""
import csv
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'Каталог дисков/F - подготовленное HDD17 на HDD45'
PREFIX='ВРЕМЕННЫЕ ФАЙЛЫ для ПЕРЕМЕЩЕНИЯ на диски\\на диск 45\\HDD17'

def main():
    report=ROOT/'Анализ/HDD17 против HDD45 - 2026-11-12/Нет на HDD45.tsv'
    with report.open(encoding='utf-8-sig',newline='') as f:
        selected={r['Путь на HDD17']:r for r in csv.DictReader(f,delimiter='\t')
                  if r['Подготовка на F:']=='на F: для HDD45'
                  and not r['Путь на HDD17'].startswith('Путешествия, Картография\\')}
    rows=[]
    log=ROOT/'Каталог дисков/K - на 45 и 77/Журнал копирования 2026-11-12 19-41-04.tsv'
    with log.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            if r['цель']!='HDD45' or not r['результат'].startswith('скопирован'):
                continue
            rel=r['источник'][3:]
            if rel not in selected:
                continue
            expected='F:\\'+PREFIX+'\\'+rel
            assert r['куда']==expected
            st=Path(expected).stat()  # metadata only
            assert st.st_size==int(r['размер'])==int(selected[rel]['Размер, байт'])
            sha=r['SHA-256 прочитанного']
            assert sha.lower()==selected[rel]['SHA-256'].lower()
            rows.append(('HDD45',rel,st.st_size,'подготовлено на F: для HDD45',sha))
    assert len(rows)==len(selected)==2698
    matches=[]
    for p in (ROOT/'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные').glob('*/*/job.json'):
        d=json.loads(p.read_text(encoding='utf-8-sig'))
        if d.get('disk_id')=='HDD45':matches.append(d['record']['volume_serial'])
    assert len(set(matches))==1
    # F identity from the existing approved staging task, not its current letter.
    volumes=(ROOT/'Каталог дисков/K - на 45 и 77/тома.tsv').read_text(encoding='utf-8-sig').splitlines()
    fserial=next(s.split('\t')[1] for s in volumes if s.startswith('HDD45\t'))
    OUT.mkdir(exist_ok=False)
    template=ROOT/'Каталог дисков/_ШАБЛОН копирования'
    for name in ('Копировать.ps1','Запустить.cmd'):
        shutil.copy2(template/name,OUT/name)
        assert (template/name).read_bytes()==(OUT/name).read_bytes()
    (OUT/'тома.tsv').write_text(f'HDD17\t{fserial}\t{PREFIX}\nHDD45\t{matches[0]}\n',encoding='utf-8-sig')
    with (OUT/'список.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        csv.writer(f,delimiter='\t',lineterminator='\n').writerows(rows)
    print(OUT)
    print(len(rows),'files;',round(sum(r[2] for r in rows)/2**30,2),'GiB')
    print('Destination: HDD45 / ПЕРЕНОС с других дисков / HDD17 / original path')
    print('Every row has expected SHA-256. No archive content read, no copying started.')

if __name__=='__main__':main()
