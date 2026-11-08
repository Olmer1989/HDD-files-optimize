"""Сменить номер носителя у готового задания сканера (например, HDD07 → HDD37).

Нужно, когда один номер по ошибке выдан двум разным дискам. Меняется всё, по чему
сканер узнаёт задание: имя папки диска и задания, job.json, result.json, runs.jsonl,
столбец disk_id в hashes.sqlite. В log.txt дописывается строка о переименовании.
Задание не должно выполняться (проверяется блокировкой worker.lock).

Запуск:  py catalog\\rename_disk.py <папка задания HDD07_...> HDD37
"""
import json
import msvcrt
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ID = re.compile(r'(HDD|Flash)\d{2,}')


def retry_rename(src, dst, attempts=10):
    # Индексаторы и антивирус ненадолго держат свежие папки — повторяем.
    for i in range(attempts):
        try:
            return src.rename(dst)
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(1)


def main(job, new_id):
    job = Path(job)
    if not ID.fullmatch(new_id):
        raise SystemExit('Неверный номер: ' + new_id)
    manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
    old_id = manifest['disk_id']
    if not job.name.startswith(old_id + '_'):
        raise SystemExit('Имя папки задания не совпадает с номером в job.json')
    disk_dir = job.parent
    if not disk_dir.name.startswith(old_id + ' - '):
        raise SystemExit('Папка диска не начинается с ' + old_id)
    for other in disk_dir.parent.iterdir():
        if other.is_dir() and other.name.startswith(new_id + ' - '):
            raise SystemExit(f'Номер {new_id} уже занят: {other}')

    with open(job / 'worker.lock', 'a+b') as handle:   # занято — значит, задание выполняется
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    manifest['disk_id'] = new_id
    manifest['job_id'] = new_id + job.name[len(old_id):]
    (job / 'job.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
    result['disk_id'] = new_id
    (job / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    runs = []
    for line in (job / 'runs.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get('disk_id') == old_id:
                rec['disk_id'] = new_id
            runs.append(json.dumps(rec, ensure_ascii=False))
    (job / 'runs.jsonl').write_text('\n'.join(runs) + '\n', encoding='utf-8')
    with sqlite3.connect(job / 'hashes.sqlite') as db:
        n = db.execute('update hashes set disk_id=? where disk_id=?', (new_id, old_id)).rowcount
    with open(job / 'log.txt', 'a', encoding='utf-8') as log:
        log.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} === Номер носителя изменён: {old_id} → {new_id} '
                  f'(номер {old_id} уже принадлежит другому диску)\n')

    new_job = retry_rename(job, job.with_name(manifest['job_id']))
    new_disk = retry_rename(disk_dir, disk_dir.with_name(new_id + disk_dir.name[len(old_id):]))
    print(f'Готово: {old_id} → {new_id}, строк хешей {n}: {new_disk / new_job.name}')


if __name__ == '__main__':
    main(*sys.argv[1:3])
