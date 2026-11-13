"""Read-only comparison of HDD17 with HDD45; explicit journal adjustments, 12 Nov.

Writes reports inside the project only. Does not open archive files. This is not
an automatic operation ledger: exclusions below are decisions in the dated journal.
"""
import csv
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'Анализ' / 'HDD17 против HDD45 - 2026-11-12'

def ro(p):
    return sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)

def main():
    jobs = {}
    for p in (ROOT / 'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные').glob('*/*/result.json'):
        d = json.loads(p.read_text(encoding='utf-8-sig'))
        key = d['disk_id']
        if '_Архив' not in str(p) and (key not in jobs or p.stat().st_mtime > jobs[key].stat().st_mtime):
            jobs[key] = p
    hashes = {}
    for disk in ('HDD17','HDD45','HDD51','HDD55'):
        db = ro(jobs[disk].with_name('hashes.sqlite'))
        try:
            hashes[disk] = dict(db.execute("select path,sha256 from hashes where status='verified'"))
        finally:
            db.close()
    on45 = set(hashes['HDD45'].values())
    additions = set()
    # Successful logged copies physically to G: (HDD45 at these dated runs).
    for log in (ROOT / 'Каталог дисков').glob('*/Журнал копирования *.tsv'):
        with log.open(encoding='utf-8-sig', newline='') as f:
            for raw in csv.DictReader(f, delimiter='\t'):
                r = {k.lower(): v for k,v in raw.items() if k}
                if not r.get('результат','').startswith('скопирован') or not r.get('куда','').startswith('G:\\'):
                    continue
                source = r.get('источник') or r.get('откуда','')
                disk = {'I:':'HDD55','J:':'HDD51'}.get(source[:2])
                sha = r.get('sha-256 прочитанного') or (hashes[disk].get(source[3:]) if disk else None)
                if sha:
                    additions.add(sha)
    on45.update(additions)
    staged = set(); retired = set()
    log = ROOT / 'Каталог дисков' / 'K - на 45 и 77' / 'Журнал копирования 2026-11-12 19-41-04.tsv'
    with log.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if r['цель'] != 'HDD45':
                continue
            if r['результат'].startswith('скопирован') and r['куда'].startswith('F:\\'):
                staged.add(r['источник'][3:])
            elif r['результат'] == 'нет источника' or r['результат'].startswith('ОШИБКА: SHA-256'):
                retired.add(r['источник'][3:])  # Seven explicitly waived by user.
    deleted_roots = [
        'Лёшке', '8 апреля - Гугл MV', 'Топозеро 2010', 'CPUKILLER', 'Володькина свадьба',
        'Перемещение G\\GoogleMV',
        'Монтаж Эквадора копия винчестера\\' + 'Рабочие материалы ( слегка подмонтированные исхоники )',
    ] + ['Монтаж Эквадора копия винчестера\\' + x for x in
         ['Проекты Encore DVD','Проекты Adobe','Adobe Premiere Pro Auto-Save','Encoded Files',
          '66e25584712a44c4cb204766686e49','e4095fead73aedc0b13d794dd4']]
    deleted_files = {
        'Проба HDTV кодирования\\1440-качество 5 - битрейт 18мб.mpg',
        *['Монтаж Эквадора копия винчестера\\'+x for x in
          ['CD-ROM_640x480_PAL.avi','MPEG2_DVD_PAL.mpg','Монтаж ФИЛЬМА.prproj']],
        *['Готовые таблицы\\'+x for x in ['Вес крепежа по Bossard 2.xls','Московские цены на DIN933 A2.xls','Сравнение Московских цен на DIN 933 8,8 - 2.xls']]
    } | retired
    def deleted(path):
        return path in deleted_files or any(path == x or path.startswith(x+'\\') for x in deleted_roots)
    db = ro(jobs['HDD17'].with_name('inventory.sqlite'))
    try:
        inventory = db.execute('select path,size from files').fetchall()
    finally:
        db.close()
    groups = defaultdict(lambda:[0,0,0,0]); rows=[]; unknown=[0,0]; ignored=[0,0]
    for path, size in inventory:
        if deleted(path):
            ignored[0]+=1; ignored[1]+=size; continue
        sha = hashes['HDD17'].get(path)
        if not sha:
            unknown[0]+=1; unknown[1]+=size; continue
        if sha in on45:
            continue
        top = path.split('\\')[0] if '\\' in path else '(корень)'
        g = groups[top]; g[0]+=1; g[1]+=size
        if path in staged:
            g[2]+=1; g[3]+=size
        rows.append((top,path,size,sha,'на F: для HDD45' if path in staged else 'не в подготовленной копии на F:'))
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'Нет на HDD45.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t'); w.writerow(['Папка','Путь на HDD17','Размер, байт','SHA-256','Подготовка на F:'])
        w.writerows(sorted(rows))
    result={'scope':'Hashed files only; snapshots + dated journal; no live content checks',
            'missing_files':len(rows),'missing_bytes':sum(r[2] for r in rows),
            'unhashed_files_bytes':unknown,'excluded_by_user_files_bytes':ignored,
            'staged_missing_files':sum(g[2] for g in groups.values()),
            'staged_missing_bytes':sum(g[3] for g in groups.values()),
            'groups':dict(sorted(groups.items(),key=lambda kv:-kv[1][1]))}
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
