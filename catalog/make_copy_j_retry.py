"""Prepare the four failed >2 GB copies from HDD51; never accesses archive disks.

Copies the approved executor unchanged. Selection comes from the recorded failed
run and is cross-checked against its original input list. No copying is started.
"""
import csv
import hashlib
import json
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'Каталог дисков' / 'J - недостающее на 45 и 77'
OUT = ROOT / 'Каталог дисков' / 'HDD51 - докопировать 4 задания больше 2 ГБ'
LOG = OLD / 'Журнал копирования 2026-11-12 01-28-36.tsv'

def main():
    failed = []
    with LOG.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if 'ОШИБКА' not in row['результат']:
                continue
            path = row['источник']
            if not path.startswith('J:\\'):
                raise ValueError('Unexpected source in historical log')
            failed.append((row['цель'], path[3:], int(row['размер'])))
    assert len(failed) == 4 and len(set(failed)) == 4
    assert all(size > 2**31-1 for _, _, size in failed)
    assert {target for target, _, _ in failed} == {'HDD45', 'HDD77'}
    assert len({path for _, path, _ in failed}) == 3
    with (OLD / 'список.tsv').open(encoding='utf-8-sig', newline='') as f:
        original = {(r[0], r[1], int(r[2])) for r in csv.reader(f, delimiter='\t')}
    assert set(failed) <= original
    candidates = []
    for result in (ROOT / 'РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ - сводные').glob('*/*/result.json'):
        info = json.loads(result.read_text(encoding='utf-8-sig'))
        if info.get('disk_id') == 'HDD51' and '_Архив' not in str(result):
            candidates.append(result)
    source = max(candidates, key=lambda p: p.stat().st_mtime).parent
    hashes = {}
    with sqlite3.connect((source / 'hashes.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        for target, path, size in failed:
            row = db.execute("select sha256 from hashes where path=? and size=? and status='verified'", (path, size)).fetchone()
            if row:
                hashes[path] = row[0]
    OUT.mkdir(exist_ok=False)
    template = ROOT / 'Каталог дисков' / '_ШАБЛОН копирования'
    from hb_core.paths import copy_template      # шаблон 2.8 - из частей: главный, Запустить.cmd и части
    copy_template(template, OUT, 'Копировать.ps1')      # байты сверяет сам
    shutil.copy2(OLD / 'тома.tsv', OUT / 'тома.tsv')
    with (OUT / 'список.tsv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        for target, path, size in failed:
            writer.writerow((target, path, size, 'повтор после ошибки Int32 (>2 ГБ)', hashes.get(path, '')))
    print(OUT)
    for target in ('HDD45', 'HDD77'):
        rows = [r for r in failed if r[0] == target]
        print(target, len(rows), 'files;', round(sum(r[2] for r in rows)/1e9, 3), 'GB')
    print('Rows with expected SHA-256:', sum(path in hashes for _, path, _ in failed))
    print('Archive disks were not accessed. Executor matches template byte for byte.')

if __name__ == '__main__':
    main()
