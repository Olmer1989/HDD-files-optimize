"""План и проверка семейного копирования. Содержимое архивных файлов не читает.

План вызывается из hashbase.py. Проверка работает автономно со своим планом.
"""
import argparse
import collections
import csv
import ctypes
import datetime as dt
import html
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import sys
import time

MAIN = ('HDD45', 'HDD77')
EXCLUDED = ('ВОССТАНОВЛЕНО_HDD61', 'HDD61_2026-11-12.img.dsk', 'HDD61_2026-11-12.rsm')
SYSTEM = {'$recycle.bin', 'system volume information', '.trashes', '.fseventsd', 'wd smartware',
          'wd smartware for mac', 'extras', 'user manuals'}
PHOTO = set('.jpg .jpeg .heic .heif .raw .cr2 .cr3 .nef .nrw .dng .arw .srf .sr2 .orf .rw2 .raf .pef .png .tif .tiff .webp .bmp .gif .avif'.split())
VIDEO = set('.mov .mp4 .avi .mkv .m4v .mts .m2ts .m2t .mpg .mpeg .wmv .3gp .vob .mod .tod .mxf .ts .m2v .webm .flv .lrv'.split())
DOC = set('.doc .docx .pdf .xls .xlsx .txt .rtf .odt .ods .ppt .pptx .xmp .aae .thm .prproj .aep .veg .pbook .ifo .bup'.split())

def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def secret(name):
    n = name.lower()
    return n == '.env' or n.startswith('.env.') or n.endswith('.env') or Path(n).suffix in ('.pem', '.key', '.pfx', '.p12')

def clean_rel(rel):
    p = PureWindowsPath(rel)
    if not rel or p.is_absolute() or p.drive or ':' in rel or any(x in ('.', '..') for x in p.parts):
        raise ValueError('Небезопасный относительный путь')
    if any(secret(x) for x in p.parts):
        raise ValueError('Путь секрета исключён')
    return p.parts

def safe_stat(root, rel):
    p = Path(root)
    for component in clean_rel(rel):
        p = p / component
        s = p.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Ссылка или reparse point')
    if not stat.S_ISREG(s.st_mode):
        raise ValueError('Ожидался обычный файл')
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns}

def volumes(serials):
    if sys.platform != 'win32':
        raise RuntimeError('Нужна Windows')
    found = collections.defaultdict(list)
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = chr(65+i) + ':\\'
        n = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, ctypes.byref(n), None, None, None, 0):
            found[f'{n.value:08X}'].append(root)
    answer = {}
    for disk, sn in serials.items():
        matches = found[str(sn).upper()]
        if len(matches) != 1:
            raise RuntimeError(f'{disk}: нужен ровно один подключённый том, найдено {len(matches)}')
        answer[disk] = matches[0]
    if len(set(answer.values())) != len(answer):
        raise RuntimeError('Источник и цели должны быть разными томами')
    return answer

def snapshot(root):
    """Только оглавление. Исключения отсеиваются до stat и входа в каталог."""
    rows, issues, excluded = [], [], []
    stack = [Path(root)]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for e in entries:
                    rel = str(Path(e.path).relative_to(root))
                    if secret(e.name) or (folder == Path(root) and (e.name in EXCLUDED or e.name.lower() in SYSTEM)):
                        excluded.append(rel)
                        continue
                    try:
                        s = e.stat(follow_symlinks=False)
                        if e.is_symlink() or getattr(s, 'st_file_attributes', 0) & 0x400:
                            issues.append([rel, 'ссылка/reparse point; не обходилась'])
                        elif stat.S_ISDIR(s.st_mode):
                            stack.append(Path(e.path))
                        elif stat.S_ISREG(s.st_mode):
                            rows.append({'path': rel, 'size': s.st_size, 'mtime_ns': s.st_mtime_ns})
                    except OSError as ex:
                        issues.append([rel, str(ex)])
        except OSError as ex:
            issues.append([str(folder), str(ex)])
    return sorted(rows, key=lambda x: x['path']), issues, excluded

def classify(row, media_parents):
    p = PureWindowsPath(row['path']); lower = str(p).lower(); ext = p.suffix.lower()
    top = p.parts[0]
    if p.name.lower() in ('thumbs.db', '.ds_store', 'desktop.ini', 'zbthumbnail.info', 'zb4meta.info') or p.name.startswith('._') or ext in ('.tmp', '.exe', '.dll'):
        return '5. Служебное', 'служебный файл; остаётся на месте'
    if top == 'Music' or any(x.lower() in ('french shanson (2011)', 'french shanson - избранное', 'музыка с контакта') for x in p.parts):
        return '4. Другие файлы', 'музыка и обложки; не на 45/77'
    if top == 'Фильмы' or top == 'Описание фильмов.doc':
        return '4. Другие файлы', 'раздел Фильмы; не на 45/77'
    if p.name.lower().startswith('dobrinya.nikitich.i.zmey.gorinich.'):
        return '4. Другие файлы', 'мультфильм Добрыня Никитич; не семейное видео'
    if ext in PHOTO:
        return '1. Фотографии', 'семейное'
    if ext in VIDEO:
        return '2. Видео', 'семейное по ранее согласованным папкам HDD51'
    # Проекты фотокниг сохраняются целиком: маленькие ресурсы тоже нужны.
    if 'фотокниги' in lower:
        return '3. Сопроводительные', 'проект фотокниги и его ресурсы'
    if str(p.parent) in media_parents and ext in DOC:
        return '3. Сопроводительные', 'документ/проект рядом с фото и видео'
    if ext in ('.ifo', '.bup') and top == 'Эстонское кино с Арнольдом Мери':
        return '3. Сопроводительные', 'структура семейного DVD'
    # Архив содержит сканы; его сохранение уже поручено в журнале 12.11.
    if p.name == 'Сканирование слайдов и плёнок.rar':
        return '3. Сопроводительные', 'ранее поручено сохранить архив сканов'
    return '4. Другие файлы', 'отдельный разбор; на 45/77 не включён'

def old_success(logpath, src, dest, size, cache):
    key=('log',str(logpath))
    if key not in cache:
        evidence=set()
        try:
            with logpath.open(encoding='utf-8-sig',newline='') as f:
                for r in csv.DictReader(f,delimiter='\t'):
                    try:
                        r={k.lower():v for k,v in r.items() if k}
                        result=r.get('результат') or ''
                        if result=='скопирован' or result.startswith('скопирован, размер'):
                            a=PureWindowsPath(r.get('источник') or r.get('откуда') or '');b=PureWindowsPath(r.get('куда') or '')
                            # Исторический адрес HDD51 в этих журналах — J:. Текущая буква
                            # определяется отдельно по серийному номеру и может быть другой.
                            if not a.drive or not b.drive:
                                raise ValueError('Оборванная строка журнала')
                            if a.drive.upper()!='J:':
                                continue
                            evidence.add((str(PureWindowsPath(*a.parts[1:])).casefold(),str(PureWindowsPath(*b.parts[1:])).casefold(),int(r['размер'])))
                    except (TypeError,ValueError,KeyError):
                        cache.setdefault(('warnings',),[]).append(f'Повреждённая строка старого журнала: {logpath.name}')
        except (OSError,ValueError,KeyError) as ex:
            cache.setdefault(('warnings',),[]).append(f'Старый журнал не дочитан: {logpath.name}: {type(ex).__name__}')
        cache[key]=evidence
    return (src.casefold(),dest.casefold(),size) in cache[key]

def known_copy(c, source, row, target, roots, cache, logroot):
    """Хеш из описи ИЛИ конкретная успешная операция для этого исходного пути."""
    sha = row.get('sha')
    candidates = []
    if sha:
        candidates += [(p, s, 'сохранённый хеш; ' + origin) for p, s, origin in c.execute(
            'select path,size,origin from files indexed by files_sha where sha=? and disk=?', (sha, target))]
    # Размер сам по себе не доказательство. Берём только адресную запись журнала.
    dest = 'ПЕРЕНОС с других дисков\\' + source + '\\' + row['path']
    weak=list(c.execute('select path,size,origin,ev,sha_exp from files where disk=? and path=?', (target,dest)))
    if sha:
        weak+=list(c.execute('select path,size,origin,ev,sha_exp from files indexed by files_exp where sha_exp=? and disk=?',(sha,target)))
    else:
        weak+=list(c.execute('select path,size,origin,ev,sha_exp from files indexed by files_name where name_lc=? and size=? and disk=?',(PureWindowsPath(row['path']).name.lower(),row['size'],target)))
    for p, size, origin, ev, expected in weak:
        if origin.startswith('журнал:') and ev in ('C', 'Z') and (not sha or expected == sha or ev == 'C'):
            logfile = origin[len('журнал: '):]
            if old_success(logroot/logfile,row['path'],p,size,cache):
                candidates.append((p, size, 'журнал копирования и метаданные; ' + logfile))
    for p, size, basis in candidates:
        if size != row['size'] or p.split('\\')[0] in EXCLUDED or p.startswith('ВОССТАНОВЛЕНО'):
            continue
        key = (target, p)
        if key not in cache:
            try:
                cache[key] = safe_stat(roots[target], p)
            except (OSError, ValueError):
                cache[key] = None
        m = cache[key]
        if m and m['size'] == size:
            return {'path': p, 'basis': basis, 'metadata': m, 'planned': False}
    return None

def prepare(hb, a):
    t0 = time.monotonic()
    c, jobs = hb.connect()
    disk = a.disk
    serials = {d: sn for sn, d in hb.serial_map(jobs).items() if d in (disk,) + MAIN}
    if set(serials) != {disk, *MAIN}:
        raise RuntimeError('Нет однозначных серийных номеров всех трёх томов')
    roots = volumes(serials)
    if disk != 'HDD51':
        raise ValueError('Текущие правила разметки подтверждены только для HDD51')
    task = Path(a.output).resolve()
    if task.exists() and any(task.iterdir()):
        raise ValueError('Нужна новая пустая папка задания')
    task.mkdir(parents=True, exist_ok=True)
    print('Собираю оглавление обычных папок HDD51; восстановление и образы исключены.', flush=True)
    cached=getattr(a,'snapshot',None)
    if cached:
        snap=json.loads(Path(cached).read_text(encoding='utf-8'))
        current,issues,excluded=snap['files'],snap['issues'],snap['excluded']
    else:
        current, issues, excluded = snapshot(roots[disk])
    write_json(task/'Оглавление источника.json', {'at': now(), 'files': current, 'issues': issues, 'excluded': excluded})
    original = {p: (s, sha, m) for p, s, sha, m in c.execute('select path,size,sha,mtime from files where disk=?', (disk,))}
    media_parents = {str(PureWindowsPath(x['path']).parent) for x in current if PureWindowsPath(x['path']).suffix.lower() in PHOTO | VIDEO}
    cache, pending, items, skipped = {}, {}, [], []
    manual_file=getattr(a,'manual_evidence',None)
    manual=json.loads(Path(manual_file).read_text(encoding='utf-8')) if manual_file else []
    totals = collections.defaultdict(lambda: [0, 0])
    copy_count = collections.Counter(); copy_bytes = collections.Counter()
    folder_summary = collections.defaultdict(lambda: collections.Counter())
    destination = {t:'ПЕРЕНОС с других дисков на диск '+t[3:] for t in MAIN}
    # Один новый комплект не смешивается со старым одноимённым файлом без журнала.
    for t in MAIN:
        if (Path(roots[t])/destination[t]/disk).exists():
            destination[t] += ' — задание ' + dt.datetime.now().strftime('%Y-%m-%d %H-%M-%S')
    last_ui=0
    for i, row in enumerate(current):
        if time.monotonic()-last_ui>2:
            print(f'Обработано {i} из {len(current)} записей оглавления',flush=True)
            last_ui=time.monotonic()
        group, reason = classify(row, media_parents)
        totals[group][0] += 1; totals[group][1] += row['size']
        if group[0] not in '123':
            skipped.append({**row, 'group': group, 'reason': reason})
            continue
        saved = original.get(row['path'])
        row = dict(row, group=group, reason=reason, sha=None)
        if saved:
            size, sha, mtime = saved
            # hashbase.files.mtime хранится в целых секундах Unix; оглавление — в нс.
            if size != row['size'] or int(mtime) != row['mtime_ns']//1_000_000_000:
                skipped.append({**row, 'reason': 'размер/дата источника изменились после описи; нужен разбор'})
                continue
            row['sha'] = sha
        elif PureWindowsPath(row['path']).suffix.lower() in PHOTO | VIDEO:
            skipped.append({**row, 'reason': 'новое медиа вне описи; нет сохранённого хеша'})
            continue
        row['targets'] = {}
        top = row['path'].split('\\')[0]
        fs = folder_summary[top]; fs['files'] += 1; fs['bytes'] += row['size']
        for target in MAIN:
            existing = known_copy(c, disk, row, target, roots, cache,hb.bp.OUT_DIR)
            if not existing:
                for e in manual:
                    if e['source']!=row['path'] or e['target']!=target or e['size']!=row['size']:
                        continue
                    try:
                        m=safe_stat(roots[target],e['path'])
                        if m['size']==row['size']:
                            existing={'path':e['path'],'basis':'сообщение владельца в журнале операций; '+e['evidence']+'; наличие и размер проверены','metadata':m,'planned':False}
                            break
                    except (OSError,ValueError):
                        pass
            if existing:
                row['targets'][target] = existing
                fs[target+'_have'] += row['size']
                continue
            # Внутренние дубли с одним сохранённым хешем копируются один раз на цель.
            key = (target, row['sha'] or ('path:' + row['path']))
            if key not in pending:
                dest = destination[target] + '\\' + disk + '\\' + row['path']
                clean_rel(dest)
                pending[key] = {'source': row['path'], 'target': target, 'path': dest,
                                'size': row['size'], 'sha': row['sha'], 'mtime_ns': row['mtime_ns']}
                copy_count[target] += 1; copy_bytes[target] += row['size']
            entry = pending[key]
            row['targets'][target] = {'path': entry['path'], 'planned': True, 'copy_source': entry['source'],
                                      'basis': 'новое копирование по этому заданию'}
            fs[target+'_need'] += row['size']
        items.append(row)
    for t in MAIN:
        if shutil.disk_usage(roots[t]).free < copy_bytes[t] + 1024**3:
            raise RuntimeError(f'На {t} не хватает места')
    plan = {'version': 1, 'created': now(), 'disk': disk, 'serials': serials,
            'database_built': dict(c.execute('select * from meta')).get('built'),
            'excluded': excluded, 'issues': issues, 'items': items, 'copy': list(pending.values()),
            'copy_counts': dict(copy_count), 'copy_bytes': dict(copy_bytes),
            'folders': dict(folder_summary), 'categories': dict(totals), 'skipped': skipped,
            'manual_evidence':manual,'warnings':cache.get(('warnings',),[]),
            'verification': 'журналы и фактическое наличие/размер; без повторного хеширования целей'}
    write_json(task/'План.json', plan)
    if manual:
        write_json(task/'Подтверждённые ручные копирования.json',manual)
    with (task/'список.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        for e in pending.values():
            f.write('\t'.join(map(str,(e['target'], e['source'], e['size'], 'семейный архив', e['sha'] or '')))+'\n')
    (task/'тома.tsv').write_text(''.join(f'{d}\t{serials[d]}' + (f'\t{destination[d]}' if d != disk else '') + '\n' for d in (disk,)+MAIN),encoding='utf-8-sig')
    from hb_core.paths import copy_template      # здесь, не наверху: этот файл копируется в задание как Проверить.py
    copy_template(hb.TEMPLATE, task, 'Копировать.ps1', extra=())      # главный и части (шаблон 2.8)
    write_launchers(task)
    report(task, plan)
    print('ПАПКА:',task)
    for t in MAIN:
        print(t, copy_count[t], 'файлов,',round(copy_bytes[t]/1024**3,3),'ГиБ')
    print('Семейных экземпляров:',len(items),'остальных/на разбор:',len(skipped),'ошибок доступа:',len(issues))
    print('Секунд:',round(time.monotonic()-t0,1))

def write_launchers(task):
    shutil.copy2(Path(__file__), task/'Проверить.py')
    # Только одна .ps1 в задании; стандартный запуск не цепляет вспомогательные сценарии.
    (task/'1 — Копировать.cmd').write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\npy -3 "%~dp0Проверить.py" --task "%~dp0." --preflight\r\nif errorlevel 1 goto finish\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Копировать.ps1"\r\npy -3 "%~dp0Проверить.py" --task "%~dp0."\r\n:finish\r\npause\r\n').encode('utf-8'))
    (task/'2 — Проверить.cmd').write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\npy -3 "%~dp0Проверить.py" --task "%~dp0."\r\npause\r\n').encode('utf-8'))
def report(task, plan):
    heads = ['Папка','Семейных файлов','Объём, ГиБ','Есть на 45, ГиБ','Есть на 77, ГиБ','Докопировать на 45, ГиБ','Докопировать на 77, ГиБ']
    rows = []
    for p,v in sorted(plan['folders'].items()):
        rows.append([p,str(v['files'])]+[f'{v.get(k,0)/1024**3:.3f}' for k in ('bytes','HDD45_have','HDD77_have','HDD45_need','HDD77_need')])
    def table(headers, data):
        return '<table><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in data)+'</table>'
    detailed=[]
    for x in plan['items']:
        detailed.append([x['path'],x['size'],x['group']]+['ДОКОПИРОВАТЬ: '+x['targets'][t]['path'] if x['targets'][t]['planned'] else 'ЕСТЬ: '+x['targets'][t]['path']+' ('+x['targets'][t]['basis']+')' for t in MAIN])
    doc='<!doctype html><html lang="ru"><meta charset="utf-8"><title>HDD51: план копирования</title><style>body{font:16px Segoe UI;margin:24px}table{border-collapse:collapse;margin:20px 0}td,th{border:1px solid #bbb;padding:6px;vertical-align:top}th{background:#eaf0f6}h1{font-size:26px}</style><h1>HDD51 — семейные файлы для 45 и 77</h1><p>План от '+html.escape(plan['created'])+'. Восстановление HDD61, образ и карта исключены. Источник: обычные папки My Book. Музыка, фильмы, служебное и отдельные документы в это задание не входят.</p><p>«Есть» означает сохранённый хеш из описи либо запись конкретного копирования, дополненную проверкой фактического пути и размера. Содержимое целей повторно не читалось. Объёмы «есть на 45» и «есть на 77» пересекаются, их нельзя складывать. Недостача по исходным экземплярам может превышать фактическое копирование: одинаковый сохранённый хеш копируется на каждую цель один раз.</p>'
    doc+=table(heads,rows)
    doc+='<h2>Баланс обычных файлов в оглавлении</h2>'+table(['Категория','Файлов','ГиБ'],[[k,v[0],f'{v[1]/1024**3:.3f}'] for k,v in sorted(plan['categories'].items())])
    need=[r for r,x in zip(detailed,plan['items']) if any(e['planned'] for e in x['targets'].values())]
    doc+='<h2>Что именно докопировать</h2>'+table(['Исходный путь','Байт','Тип','45','77'],need)
    doc+='<p>Полный пофайловый учёт всего семейного набора: <a href="Все файлы — назначения.tsv">Все файлы — назначения.tsv</a>.</p>'
    not_in=collections.defaultdict(lambda:[0,0])
    for x in plan['skipped']:
        not_in[x['reason']][0]+=1;not_in[x['reason']][1]+=x['size']
    doc+='<h2>Не включено / оставлено на месте</h2>'+table(['Причина','Файлов','ГиБ'],[[k,v[0],f'{v[1]/1024**3:.3f}'] for k,v in not_in.items()])
    doc+='<p>Полные пути: <a href="Не включено.tsv">Не включено.tsv</a>. Восстановление, образы и служебные каталоги, исключённые до обхода, в баланс обычных файлов не входят.</p>'
    if plan.get('warnings'):
        doc+='<h2>Замечания</h2><pre>'+html.escape('\n'.join(plan['warnings']))+'</pre>'
    doc+='</html>'
    (task/'Какие файлы копировать.html').write_text(doc,encoding='utf-8')
    with (task/'Все файлы — назначения.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t'); w.writerow(['источник','размер','тип','HDD45','HDD77']); w.writerows(detailed)
    with (task/'Не включено.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['источник','размер','причина']);w.writerows((x['path'],x['size'],x['reason']) for x in plan['skipped'])

def successful_logs(task):
    found={}
    for path in sorted(task.glob('Журнал копирования *.tsv')):
        with path.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f,delimiter='\t'):
                if not (r.get('результат') or '').startswith('скопирован, размер'):
                    continue
                try:
                    src=PureWindowsPath(r.get('источник') or '');dst=PureWindowsPath(r.get('куда') or '')
                    if not src.drive or not dst.drive:
                        continue
                    int(r['размер'])
                    key=(r.get('цель'),str(PureWindowsPath(*src.parts[1:])),str(PureWindowsPath(*dst.parts[1:])))
                    found.setdefault(key,[]).append(r)
                except (ValueError,TypeError,KeyError):
                    continue
    return found

def verify(task, roots_override=None, preflight=False):
    task=Path(task)
    plan=json.loads((task/'План.json').read_text(encoding='utf-8'))
    roots=roots_override or volumes(plan['serials'])
    if preflight and not (task/'Копировать.ps1').is_file():
        raise RuntimeError('В комплекте нет Копировать.ps1')
    # части шаблона 2.8 (*.psm1) проверяет сам Копировать.ps1: нет части или она изменена - не начнёт, код 5
    logs=successful_logs(task)
    results=[];errors=[];cache={}
    for i,item in enumerate(plan['items']):
        row={'path':item['path'],'targets':{},'ok':True}
        try:
            s=safe_stat(roots[plan['disk']],item['path'])
            if s!={'size':item['size'],'mtime_ns':item['mtime_ns']}:
                raise ValueError('Источник изменился после планирования')
            for t,entry in item['targets'].items():
                key=(t,entry['path'])
                if key not in cache:
                    try:
                        cache[key]=safe_stat(roots[t],entry['path'])
                    except FileNotFoundError:
                        if not (preflight and entry['planned']):
                            raise
                        cache[key]=None
                m=cache[key]
                if m is None and preflight and entry['planned']:
                    row['targets'][t]={'path':entry['path'],'basis':'будет скопирован'}
                    continue
                if m['size']!=item['size']:
                    raise ValueError(f'{t}: другой размер')
                if entry['planned']:
                    logkey=(t,entry['copy_source'],entry['path'])
                    good=[r for r in logs.get(logkey,[]) if int(r['размер'])==item['size'] and (not item['sha'] or r.get('SHA-256 прочитанного','').lower()==item['sha'].lower())]
                    if not good:
                        raise ValueError(f'{t}: нет успешной записи копирования для этого файла; одного «уже есть» недостаточно')
                elif m != entry['metadata']:
                    raise ValueError(f'{t}: метаданные существующей копии изменились после планирования')
                row['targets'][t]={'path':entry['path'],'metadata':m,'basis':entry['basis']}
        except (OSError,ValueError,KeyError) as ex:
            row['ok']=False;row['error']=str(ex);errors.append({'path':item['path'],'error':str(ex)})
        results.append(row)
        if i%1000==0:
            print(f'Проверено {i+1}/{len(plan["items"])}',flush=True)
    proof={'at':now(),'plan_created':plan['created'],'ok':not errors and bool(results),'checked':len(results),'errors':errors,'files':results,
           'method':'журнал + фактические пути, размеры и метаданные; содержимое целей не читалось'}
    write_json(task/('Проверка перед запуском.json' if preflight else 'Результат проверки.json'),proof)
    with (task/('Ошибки перед запуском.tsv' if preflight else 'Ошибки проверки.tsv')).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['источник','ошибка']);w.writerows((e['path'],e['error']) for e in errors)
    if preflight:
        print(f'ПЕРЕД ЗАПУСКОМ: проверено {len(results)} исходных файлов; ошибок {len(errors)}. Это ещё не результат копирования.')
    else:
        print(f'ПРОВЕРКА: {len(results)-len(errors)} из {len(results)} исходных файлов имеют учтённые копии на обоих дисках. Ошибок: {len(errors)}.')
    print('Целевые файлы повторно не хешировались. Перемещение исходников не выполнялось.')
    return proof

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser();ap.add_argument('--task',type=Path,default=Path(__file__).parent)
    ap.add_argument('--preflight',action='store_true')
    a=ap.parse_args()
    try:
        result=verify(a.task,preflight=a.preflight)
        raise SystemExit(0 if result['ok'] else 2)
    except (OSError,ValueError,RuntimeError) as e:
        print('ПРОВЕРКА НЕ ЗАВЕРШЕНА:',e)
        raise SystemExit(2)
