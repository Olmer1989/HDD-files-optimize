"""Build a reviewable hashing selection using saved metadata only."""
import json
import sqlite3
from pathlib import Path, PureWindowsPath
from collections import defaultdict
from datetime import datetime
from inventory import MEDIA, MIN_BYTES, EXCLUDED_DIRS, excluded_file

BASE = Path(__file__).resolve().parents[1]

# Selection rules. Version 1: every media file from 1 MiB. Version 2 (agreed
# 08.11.2026): camera photos (JPEG/HEIC) from 50 KB, which keeps old
# camera/phone photos; other images and RAW from 150 KB, which skips web
# graphics and thumbnails; video of any non-zero size (old 3GP clips are tiny).
CAMERA_IMAGES = frozenset('.jpg .jpeg .heic .heif'.split())
VIDEO = frozenset('.mov .mp4 .avi .mkv .m4v .mts .m2ts .m2t .dv .mpg .mpeg .wmv .3gp .vob .mod .tod .mxf .ts .m2v .webm .flv'.split())
THRESHOLDS_V1 = {'default': MIN_BYTES}
THRESHOLDS_V2 = {'camera_image': 50_000, 'video': 1, 'other_media': 150_000}

def threshold(extension, thresholds):
    if 'default' in thresholds:
        return thresholds['default']
    if extension in CAMERA_IMAGES:
        return thresholds['camera_image']
    if extension in VIDEO:
        return thresholds['video']
    return thresholds['other_media']

def select(path, size, thresholds=THRESHOLDS_V1):
    parts = PureWindowsPath(path).parts
    if any(p.lower() in EXCLUDED_DIRS or excluded_file(p) for p in parts):
        return False
    extension = PureWindowsPath(path).suffix.lower()
    return extension in MEDIA and size >= threshold(extension, thresholds)

def main():
    registry = json.loads(Path(__file__).with_name('disks.json').read_text(encoding='utf-8'))
    output = BASE / 'Каталог дисков' / ('Выборка_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    output.mkdir()
    report = ['# Выборка для полного SHA-256', '',
              'Построено по сохранённым метаданным; источники не открывались. Хешей пока нет.',
              'Все фото/видео от 1 МиБ, включая M2V, WebM, FLV. Служебные каталоги исключены.',
              'Документы и другие файлы остаются в исходных каталогах. Эта выборка ничего не переносит.', '']
    with sqlite3.connect(output / 'selection.sqlite') as target:
        target.execute('create table files(disk_id text,path text,size integer,mtime_ns text,file_id text,source_inventory text, primary key(disk_id,path))')
        target.execute('create table metadata(key text primary key,value text)')
        details = {}
        for disk_id in registry:
            candidates = sorted((BASE / 'Каталог дисков').glob(disk_id + '_*/summary.json'))
            valid = [(p, json.loads(p.read_text(encoding='utf-8'))) for p in candidates]
            valid = [(p, s) for p, s in valid if s['status'] in ('complete', 'complete_with_errors') and s['identity']['disk_id'] == disk_id]
            if not valid:
                raise RuntimeError('No completed inventory for ' + disk_id)
            summary_path, summary = valid[-1]
            db_path = summary_path.with_name('inventory.sqlite')
            folders = defaultdict(lambda: [0, 0])
            count = total = 0
            with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as source:
                for path, size, mtime, file_id in source.execute('select path,size,mtime_ns,file_id from files'):
                    if not select(path, size):
                        continue
                    target.execute('insert into files values (?,?,?,?,?,?)', (disk_id, path, size, mtime, file_id, str(db_path)))
                    count += 1
                    total += size
                    top = PureWindowsPath(path).parts[0] if len(PureWindowsPath(path).parts) > 1 else '[файлы в корне]'
                    folders[top][0] += 1
                    folders[top][1] += size
                errors = source.execute('select path,operation,message from errors').fetchall()
            details[disk_id] = dict(files=count, bytes=total, source=str(db_path), inventory_status=summary['status'], errors=errors)
            report += [f'## {disk_id} — Диск №{registry[disk_id]["number"]}', '',
                       f'Выбрано: {count:,} файлов; {total/1e9:.3f} ГБ. Исходная инвентаризация: {summary["status"]}.', '',
                       '| Верхняя папка | Файлов | ГБ |', '|---|---:|---:|']
            for name, (n, b) in sorted(folders.items(), key=lambda x: -x[1][1]):
                report.append(f'| {name.replace("|", " / ")} | {n} | {b/1e9:.3f} |')
            report += ['', 'Непросканированные пути:']
            for path, operation, message in errors:
                report.append(f'- `{path}`: {message}')
            report.append('')
        # Size is only a candidate filter. No name or size group is a proven duplicate.
        size_groups = target.execute('select count(*),sum(size*n) from (select size,count(*) n from files group by size having count(*)>1)').fetchone()
        details['total'] = dict(files=sum(v['files'] for v in details.values()), bytes=sum(v['bytes'] for v in details.values()))
        details['size_candidates'] = dict(groups=size_groups[0], bytes=size_groups[1] or 0, confirmed_duplicates=False)
        target.execute('insert into metadata values (?,?)', ('policy', json.dumps(dict(min_bytes=MIN_BYTES, media_extensions=sorted(MEDIA), excluded_dirs=sorted(EXCLUDED_DIRS)),ensure_ascii=False)))
        target.execute('insert into metadata values (?,?)', ('summary', json.dumps(details, ensure_ascii=False)))
    report += ['## Ограничения и следующий этап', '',
               'Папки с медиа не исключались по предполагаемому смыслу названий. Фильмы, копии сайтов и похожие категории нужно проверить по этому отчёту, если их требуется исключить из хеширования.',
               'Непросканированные found.000/found.001 могут содержать восстановленные данные; их нельзя считать пустыми или проверенными.',
               'Следующий этап: ограниченная проба хеширования с проверкой постоянной идентичности носителя, затем полные хеши с возобновлением. Удаление и перемещение не выполняются.']
    (output / 'Выборка.md').write_text('\n'.join(report), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output':str(output), **details}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
