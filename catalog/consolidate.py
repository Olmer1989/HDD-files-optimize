"""Собрать результаты сканирования из разных папок (флешек, компьютеров) в одну сводную.

Правила — как у импорта сканера:
- задание кладётся в папку своего носителя под своим job_id, файлы копируются
  с проверкой SHA-256, источник не меняется;
- одинаковое задание уже есть — пропуск; в источнике меньше хешей — пропуск (старее);
  в источнике больше — прежняя версия уходит в «_Архив\\Заменённые задания»;
- у носителя в сводной уже есть ДРУГОЕ задание — конфликт, ничего не делается;
- незавершённые задания (running/error) пропускаются, если их номер не указан в --include.

Запуск:  py catalog\\consolidate.py <сводная> <источник> [<источник>...] [--include Flash05 HDD06]
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scanner'))
import portable  # noqa: E402  (disk_folder, refresh_index)

SKIP_FILES = {'worker.lock'}


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def verified(job):
    try:
        with closing(sqlite3.connect(f'file:{job / "hashes.sqlite"}?mode=ro', uri=True)) as db:
            return db.execute("select count(*) from hashes where status='verified'").fetchone()[0]
    except sqlite3.Error:
        return 0


def files_of(job):
    return sorted(p.name for p in job.iterdir() if p.is_file() and p.name not in SKIP_FILES)


def same(a, b):
    names = files_of(a)
    return names == files_of(b) and all(sha(a / n) == sha(b / n) for n in names)


def copy_job(src, dst):
    dst.mkdir(parents=True)
    for name in files_of(src):
        shutil.copy2(src / name, dst / name)
        if sha(src / name) != sha(dst / name):
            raise RuntimeError('Контрольная сумма копии не совпала: ' + name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('destination', type=Path)
    ap.add_argument('sources', type=Path, nargs='+')
    ap.add_argument('--include', nargs='*', default=[], help='номера незавершённых заданий, которые всё же взять')
    args = ap.parse_args()
    dest = args.destination.resolve()
    report = []
    for root in args.sources:
        for jobfile in sorted(root.glob('*/*/job.json')):
            job = jobfile.parent
            if '_Архив' in job.parts:
                continue
            manifest = json.loads(jobfile.read_text(encoding='utf-8'))
            disk_id, job_id = manifest['disk_id'], manifest['job_id']
            result_path = job / 'result.json'
            status = json.loads(result_path.read_text(encoding='utf-8')).get('status', '?') if result_path.exists() else 'нет result.json'
            where = f'{disk_id} ({root.name})'
            if job.name != job_id:
                report.append(f'КОНФЛИКТ  {where}: имя папки {job.name} не совпадает с job_id {job_id}')
                continue
            if not status.startswith('complete') and disk_id not in args.include:
                report.append(f'пропуск   {where}: не завершено ({status})')
                continue
            disk_dir = portable.disk_folder(dest, disk_id, manifest.get('record', {}))
            others = [p.name for p in disk_dir.iterdir() if p.is_dir() and p.name != job_id] if disk_dir.exists() else []
            if others:
                report.append(f'КОНФЛИКТ  {where}: у {disk_id} в сводной другое задание {others}')
                continue
            target = disk_dir / job_id
            if target.exists():
                if same(job, target):
                    report.append(f'уже есть  {where}: без изменений')
                    continue
                vs, vt = verified(job), verified(target)
                if vs < vt or (vs == vt and (job / 'log.txt').stat().st_mtime <= (target / 'log.txt').stat().st_mtime):
                    report.append(f'пропуск   {where}: в сводной версия новее ({vt} хешей против {vs})')
                    continue
                archived = dest / '_Архив' / 'Заменённые задания' / f'{job_id}_{datetime.now():%Y%m%d_%H%M%S}'
                archived.parent.mkdir(parents=True, exist_ok=True)
                target.rename(archived)
                copy_job(job, target)
                report.append(f'ОБНОВЛЕНО {where}: {vt} → {vs} хешей, прежняя версия в _Архив')
            else:
                copy_job(job, target)
                report.append(f'добавлено {where}: {status}, хешей {verified(job)}')
    portable.refresh_index(dest)
    print('\n'.join(report))


if __name__ == '__main__':
    main()
