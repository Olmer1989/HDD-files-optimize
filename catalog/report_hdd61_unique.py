"""HDD61 content without known copies: stored hashes + successful copy/recovery logs.

Never opens H:. HDD17's old snapshot is not counted as a surviving backup after
the failed erase; its successfully copied/restored hashes are counted separately.
User-waived Ecuador material is excluded by the explicit dated journal decision.
"""
import csv
import collections
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'Анализ/HDD61 - файлы без известных копий - 2026-11-12'
PREFIX='Монтаж Эквадора копия винчестера\\'

def read_hashes(job):
    db=sqlite3.connect(job.with_name('hashes.sqlite').as_uri()+'?mode=ro',uri=True)
    try:return [(p,n,s.lower()) for p,n,s in db.execute("select path,size,sha256 from hashes where status='verified'")]
    finally:db.close()

def waived(path):
    if not path.startswith(PREFIX):return False
    parts=path[len(PREFIX):].split('\\')
    if parts[0].startswith('Рабочие материалы'):return True
    if parts[0] in {'Проекты Encore DVD','Проекты Adobe','Adobe Premiere Pro Auto-Save','Encoded Files',
                    '66e25584712a44c4cb204766686e49','e4095fead73aedc0b13d794dd4'}:return True
    if parts[-1]=='Спринт.avi':return True
    return len(parts)==1 and parts[0] in {
        'Елеть - смонтированная.avi','Проба кодирования Елети.avi','CD-ROM_640x480_PAL.avi',
        'MPEG2_DVD_PAL.mpg','Верхнее поле - 8000.mpg','Нижнее поле - 8000.mpg',
        'Деинтерл - 8000.mpg','Адапт Деинтерл - 8000.m2p','Адапт нот-доминант Деинтерл - 8000.m2p'}

def main():
    jobs={}
    for p in (ROOT/'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные').glob('*/*/result.json'):
        d=json.loads(p.read_text(encoding='utf-8-sig'));k=d.get('disk_id')
        if '_Архив' not in str(p) and (k not in jobs or p.stat().st_mtime>jobs[k].stat().st_mtime):jobs[k]=p
    source=read_hashes(jobs['HDD61']);source_sha={s for p,n,s in source}
    pending=set(source_sha); alternatives=collections.defaultdict(set)
    source_names={p.rsplit('\\',1)[-1].casefold() for p,n,s in source}
    for disk,job in jobs.items():
        if disk in ('HDD61','HDD17'):continue
        for path,size,sha in read_hashes(job):
            pending.discard(sha)
            name=path.rsplit('\\',1)[-1].casefold()
            if name in source_names:alternatives[name].add((disk,sha))
    for log in (ROOT/'Каталог дисков').glob('*/Журнал копирования *.tsv'):
        with log.open(encoding='utf-8-sig',newline='') as f:
            for raw in csv.DictReader(f,delimiter='\t'):
                r={k.lower():v for k,v in raw.items() if k}
                sha=r.get('sha-256 прочитанного','')
                if sha and r.get('результат','').startswith('скопирован'):pending.discard(sha.lower())
    restore=ROOT/'Каталог дисков/Сверка восстановленного HDD17/Эквадор - сверка SHA-256.tsv'
    with restore.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            if r['итог']=='совпал':pending.discard(r['SHA-256 восстановленного'].lower())
    remaining=[r for r in source if r[2] in pending and not waived(r[0])]
    # Preserve all paths but distinguish instance bytes from distinct content bytes.
    distinct={sha:size for path,size,sha in remaining}
    groups=collections.defaultdict(lambda:[0,0])
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'Файлы без известных копий.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['Папка','Путь HDD61','Размер, байт','ГиБ','SHA-256','Одноимённые другие версии на дисках'])
        for path,size,sha in sorted(remaining):
            top=path.split('\\')[0];groups[top][0]+=1;groups[top][1]+=size
            others=sorted({disk for disk,h in alternatives[path.rsplit('\\',1)[-1].casefold()] if h!=sha})
            w.writerow([top,path,size,round(size/2**30,6),sha,', '.join(others)])
    summary={'source_disk':'HDD61','comparison':'Other scan snapshots + successful hash-bearing copy/recovery logs; no live H access',
             'excluded_as_backup':'HDD17 old snapshot after attempted erase',
             'files':len(remaining),'bytes':sum(n for p,n,s in remaining),
             'GiB':round(sum(n for p,n,s in remaining)/2**30,3),
             'distinct_contents':len(distinct),'distinct_content_GiB':round(sum(distinct.values())/2**30,3),
             'user_waived_candidate_files':sum(s in pending and waived(p) for p,n,s in source),
             'groups':{k:{'files':v[0],'GiB':round(v[1]/2**30,3)} for k,v in sorted(groups.items(),key=lambda kv:-kv[1][1])}}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('LARGEST')
    for p,n,s in sorted(remaining,key=lambda r:-r[1])[:16]:print(round(n/2**30,3),p)

if __name__=='__main__':main()
