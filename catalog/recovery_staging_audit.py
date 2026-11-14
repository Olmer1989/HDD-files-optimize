"""Metadata-only audit of recovered K/H against the two staging directories on F.

No file-content reads on archive drives. H uses the saved recovery listing;
K and F are enumerated using scandir/stat. Matches on name/size are candidates,
never proof of content integrity. This utility never copies or deletes files.
"""
import collections
import csv
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import stat
import sys
import re

from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки
from recovery_plan import SYSTEM, CACHE

PROJECT = Path(__file__).resolve().parent.parent
CATALOG = PROJECT / 'Каталог дисков'
OUTPUT = CATALOG / '_БАЗА' / 'ответы' / 'остаток восстановлений перед удалением'
F_ROOTS = [Path('F:/ВРЕМЕННЫЕ ФАЙЛЫ для ПЕРЕМЕЩЕНИЯ на диски'),
           Path('F:/ВРЕМЕННЫЕ файлы с других дисков НЕ фото и НЕ видео')]


def listing(root):
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    rows, errors, stack = [], [], [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for e in entries:
                    if e.name.lower() == '.env' or e.name.lower().startswith('.env.') or e.name.lower().endswith('.env'):
                        continue
                    try:
                        s = e.stat(follow_symlinks=False)
                        if getattr(s, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(s.st_mode):
                            continue
                        if stat.S_ISDIR(s.st_mode):
                            stack.append(Path(e.path))
                        elif stat.S_ISREG(s.st_mode):
                            rows.append((str(Path(e.path).relative_to(root)), s.st_size, e.path))
                    except OSError as ex:
                        errors.append([e.path, str(ex)])
        except OSError as ex:
            errors.append([str(directory), str(ex)])
    return rows, errors


def canonical(path):
    return re.sub(r'\.Id_[0-9a-f]+(?=\.)', '', path, flags=re.I)


def waived(path):
    path = canonical(path)
    if not path.startswith('Монтаж Эквадора копия винчестера\\'):
        return False
    rel = path.split('\\', 1)[1]
    return (rel.split('\\')[0].startswith('Рабочие материалы') or
            rel.split('\\')[0] in {'Проекты Encore DVD', 'Проекты Adobe', 'Adobe Premiere Pro Auto-Save',
                                  'Encoded Files', '66e25584712a44c4cb204766686e49', 'e4095fead73aedc0b13d794dd4'} or
            PureWindowsPath(rel).name in {'Спринт.avi', 'Дорога Кито - Борха.avi',
                                        'Верхнее поле - 8000.mpg', 'Деинтерл - 8000.mpg',
                                        'Нижнее поле - 8000.mpg', 'Адапт Деинтерл - 8000.m2p',
                                        'Адапт нот-доминант Деинтерл - 8000.m2p',
                                        'Елеть - смонтированная.avi', 'Проба кодирования Елети.avi',
                                        'CD-ROM_640x480_PAL.avi', 'MPEG2_DVD_PAL.mpg', 'Монтаж ФИЛЬМА.prproj'} or
            rel == 'Фотографии\\Вадим\\Заявление\\Resize of Проектная документация с объекта.JPG')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fi, f_names, f_records, errors = collections.defaultdict(list), collections.defaultdict(list), [], []
    for root in F_ROOTS:
        rows, err = listing(root)
        errors += err
        for rel, size, full in rows:
            name = PureWindowsPath(rel).name.casefold()
            fi[(name, size)].append(full)
            f_names[name].append((size, full))
            f_records.append({'path': full, 'size': size})
    (OUTPUT / 'оглавление F.json').write_text(json.dumps(f_records, ensure_ascii=False), encoding='utf-8')
    print('F directory listing:', len(f_records), 'files', flush=True)

    db = sqlite3.connect((CATALOG / '_БАЗА' / 'хеши.sqlite').as_uri() + '?mode=ro', uri=True)
    saved = list(csv.DictReader((CATALOG / '_БАЗА' / 'ответы' / 'разбор восстановления - HDD61' / 'Файлы.tsv').open(encoding='utf-8-sig'), delimiter='\t'))
    records = []
    for r in saved:
        records.append({'disk': 'HDD61', 'rel': r['Исходный путь'],
                        'source': str(Path('J:/ВОССТАНОВЛЕНО_HDD61/Root') / r['Путь восстановления']),
                        'size': int(r['Размер, байт']),
                        'sha': r['Ожидаемый SHA-256, не проверен'] if 'размер совпал' in r['Статус описи'] else '',
                        'section': r['Раздел (предварительно)'], 'match': r['Статус описи']})
    prefix = 'Монтаж Эквадора копия винчестера\\'
    expected = {p.casefold(): (size, sha) for p, size, sha in db.execute('select path,size,sha from files where disk=?', ('HDD17',))}
    rows, err = listing(Path('S:/ВОССТАНОВЛЕНО с К_HDD17'))
    errors += err
    for rel, size, full in rows:
        original = prefix + rel
        oldsize, sha = expected.get(original.casefold(), (None, None))
        records.append({'disk': 'HDD17', 'rel': original, 'source': full, 'size': size,
                        'sha': (sha or '') if oldsize == size else '', 'section': 'Эквадор с К',
                        'match': 'размер совпал' if oldsize == size else 'нет сопоставления/размер отличается'})

    # Only project SQLite data is read here, not any archive file contents.
    db.execute('create temp table wanted(sha text primary key)')
    db.executemany('insert or ignore into wanted values (?)',
                   ((key,) for r in records if r['sha'] for key in (r['sha'].lower(), r['sha'].upper())))
    copies = collections.defaultdict(set)
    for sha, disk in db.execute('select distinct f.sha,f.disk from files f join wanted w on f.sha=w.sha where f.disk not in (?,?)', ('HDD17', 'HDD61')):
        copies[sha.upper()].add(disk)

    summary, groups = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    details = []
    for r in records:
        p, n = r['rel'], r['size']
        name = PureWindowsPath(p).name.casefold()
        top = PureWindowsPath(p).parts[0]
        fmatch = fi.get((name, n), [])
        known = sorted(copies.get(r['sha'].upper(), set()))
        if waived(p):
            action = 'ранее признано ненужным'
        elif fmatch:
            action = 'есть на F по имени и размеру — содержимое не проверено'
        elif p.startswith(prefix + 'Исходники\\') and any(abs(n - s) <= 10000 for s, full in f_names.get(name, []) if '\\Исходники\\' in full):
            action = 'Эквадор: версия близкого размера уже на F (до 10 КБ), не доказанный дубль'
        elif n == 0:
            action = 'пустой файл: не считать сохранением данных'
        elif top.casefold() in SYSTEM or CACHE.search('\\' + p):
            action = 'системное/кеш/корзина: отдельно решить, не удалять автоматически'
        elif 'HDD45' in known or 'HDD77' in known:
            action = 'исходный хеш есть на 45/77 по базе'
        elif known:
            action = 'исходный хеш есть только на других носителях по базе'
        else:
            action = 'сохранить или решить вручную: совпадений на F и известных копий по хешу нет'
        r.update(action=action, on_f=fmatch[:3], copies=known)
        summary[(r['disk'], action)].update(files=1, bytes=n)
        groups[(r['disk'], action, top)].update(files=1, bytes=n)
        details.append(r)
    (OUTPUT / 'файлы.json').write_text(json.dumps(details, ensure_ascii=False), encoding='utf-8')
    output = {'scope': 'metadata only; F matches are name and size, not content verification; H listing is saved snapshot',
              'errors': errors,
              'summary': [dict(disk=k[0], action=k[1], **v) for k, v in summary.items()],
              'folders': [dict(disk=k[0], action=k[1], folder=k[2], **v) for k, v in groups.items()]}
    (OUTPUT / 'summary.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in output['summary']:
        print(row['disk'], row['action'], row['files'], round(row['bytes']/2**30, 3), 'GiB')
    print('Errors:', len(errors), 'Report:', OUTPUT)


def refine_unhashed():
    """Compare unhashed names/sizes against 45/77 using only project SQLite."""
    path = OUTPUT / 'файлы.json'
    records = json.loads(path.read_text(encoding='utf-8'))
    f_aliases = collections.defaultdict(list)
    for r in json.loads((OUTPUT / 'оглавление F.json').read_text(encoding='utf-8')):
        f_aliases[(hb.name_key(canonical(r['path'])), r['size'])].append(r['path'])
    for r in records:
        if waived(r['rel']):
            r['action'] = 'ранее признано ненужным'
        elif r['action'].startswith(('сохранить', 'исходный хеш есть только')):
            matches = f_aliases.get((hb.name_key(canonical(r['rel'])), r['size']), [])
            if matches:
                r['action'] = 'есть на F по имени и размеру — содержимое не проверено'
                r['on_f'] = matches[:3]
    db = sqlite3.connect((CATALOG / '_БАЗА' / 'хеши.sqlite').as_uri() + '?mode=ro', uri=True)
    candidates = [r for r in records if not r['sha'] and r['size'] and r['action'].startswith('сохранить')]
    db.execute('create temp table wanted_names(name_lc text,size integer,primary key(name_lc,size))')
    db.executemany('insert or ignore into wanted_names values (?,?)',
                   ((hb.name_key(canonical(r['rel'])), r['size']) for r in candidates))
    hits = collections.defaultdict(set)
    for name, size, disk in db.execute('''select distinct w.name_lc,w.size,f.disk from wanted_names w
            join files f on f.name_lc=w.name_lc and f.size=w.size where f.disk in ('HDD45','HDD77')'''):
        hits[(name, size)].add(disk)
    for r in candidates:
        disks = sorted(hits.get((hb.name_key(canonical(r['rel'])), r['size']), set()))
        if disks:
            r['action'] = 'вероятная копия на 45/77 по имени и размеру — хеш не известен'
            r['probable_copies'] = disks
    path.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
    old = json.loads((OUTPUT / 'summary.json').read_text(encoding='utf-8'))
    totals, groups = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for r in records:
        top = PureWindowsPath(r['rel']).parts[0]
        totals[(r['disk'], r['action'])].update(files=1, bytes=r['size'])
        groups[(r['disk'], r['action'], top)].update(files=1, bytes=r['size'])
    old['summary'] = [dict(disk=k[0], action=k[1], **v) for k, v in totals.items()]
    old['folders'] = [dict(disk=k[0], action=k[1], folder=k[2], **v) for k, v in groups.items()]
    (OUTPUT / 'summary.json').write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf-8')
    md = ['# Остаток восстановлений К и Н: 13.11.2026', '',
          'Проверено только оглавление F и К, сохранённое оглавление Н и база описей/журналов.',
          'Совпадение имени и размера не доказывает целостность. Наличие хеша на 45/77 — по рабочей базе.',
          'Другие носители не исключают файл из остатка. Системное и ранее ненужное выделено отдельно.', '',
          '| Источник | Группа | Файлов | ГиБ |', '|---|---|---:|---:|']
    for r in old['summary']:
        md.append(f"| {r['disk']} | {r['action']} | {r['files']} | {r['bytes']/2**30:.3f} |")
    remaining = [r for r in records if r['action'].startswith(('сохранить', 'исходный хеш есть только'))]
    byfolder = collections.defaultdict(collections.Counter)
    for r in remaining:
        byfolder[(r['disk'], PureWindowsPath(r['rel']).parts[0])].update(files=1, bytes=r['size'])
    md += ['', '## На F, 45 и 77 копия не установлена', '', '| Источник | Папка | Файлов | ГиБ |', '|---|---|---:|---:|']
    for (disk, folder), v in sorted(byfolder.items(), key=lambda item: -item[1]['bytes']):
        md.append(f"| {disk} | {folder} | {v['files']} | {v['bytes']/2**30:.3f} |")
    (OUTPUT / 'Файлы остатка.json').write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding='utf-8')
    md += ['', '## Крупнейшие 40 файлов остатка', '', 'Полный список: `Файлы остатка.json`.', '',
           '| Источник файла | Байт | Основание |', '|---|---:|---|']
    for r in sorted(remaining, key=lambda r: -r['size'])[:40]:
        reason = 'старый SHA-256; нет на 45/77' if r['sha'] else 'нет хеша; по имени/размеру копия не найдена'
        md.append(f"| `{r['source']}` | {r['size']} | {reason} |")
    (OUTPUT / 'ИТОГ.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('Probable additional matches on 45/77:', sum(bool(r.get('probable_copies')) for r in candidates))
    for (disk, folder), v in sorted(byfolder.items(), key=lambda item: -item[1]['bytes'])[:25]:
        print(disk, folder, v['files'], round(v['bytes']/2**30, 3), 'GiB')
    print('Remaining:', len(remaining), round(sum(r['size'] for r in remaining)/2**30, 3), 'GiB')


if __name__ == '__main__':
    if '--cached' not in sys.argv:
        main()
    refine_unhashed()
