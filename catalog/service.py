"""Сервис над hashbase: единственный путь записи в таблицы владельца и данные для окна программы.

Записи владельца (ручные операции, решения, исключения) делают ТОЛЬКО эти функции - из окна, из командной
строки и из чата (через команды hashbase.py manual / decide / exclude). Каждая запись:
  1. проверяет формат и смысл (диск есть в базе, путь есть в базе, такой же строки ещё нет);
  2. показывает предпросмотр: сколько файлов базы затронет и примеры путей;
  3. под замком таблиц кладёт копию таблицы в «_БАЗА\\архив таблиц» и дописывает ОДНУ целую строку;
  4. сразу применяет её к базе (сборщик берёт только новые строки; если программа упадёт между шагами 3 и 4,
     следующая команда применит строку сама - строка уже является модулем).
Строку, записанную по ошибке, исправляет fix_manual: старая строка заменяется, причина пишется в комментарий,
база собирается заново целиком (изменённый модуль) - так ошибка не остаётся в учёте навсегда.
"""
import collections
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

SEP = '\\'
ACTIONS = ('удалено', 'скопировано', 'перемещено')
VERDICT_RE = re.compile(r'^(не нужно|раздел: .+|пока не трогаем)$')
DATE_RE = re.compile(r'^\d\d\.\d\d\.\d{4}$')
BACKUPS_KEEP = 200


class Refused(Exception):
    """Запись не сделана: причина понятна владельцу."""


# ---------- замок, копия, дописывание ----------

class TableLock:
    """Одна запись в таблицы владельца за раз (окно, командная строка, чат)."""

    def __enter__(self):
        hb.BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(hb.BASE_DIR / 'таблицы.lock', 'a+b')
        try:
            import msvcrt
        except ImportError:
            return self
        for _ in range(120):
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.locked = True
                return self
            except OSError:
                time.sleep(0.5)
        self.f.close()
        raise Refused('Таблицы сейчас записывает другая программа дольше минуты. Повторите позже.')

    def __exit__(self, *exc):
        try:
            if getattr(self, 'locked', False):
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def backup(path):
    """Копия таблицы перед записью: «_БАЗА\\архив таблиц\\<имя> <время>.tsv», хранятся последние 200."""
    path = Path(path)
    if not path.exists():
        return None
    arch = hb.BASE_DIR / 'архив таблиц'
    arch.mkdir(exist_ok=True)
    dst = arch / f'{path.stem} {time.strftime("%Y-%m-%d %H-%M-%S")}-{time.perf_counter_ns() % 1000000:06d}{path.suffix}'
    shutil.copy2(path, dst)
    old = sorted(arch.glob(f'{path.stem} *{path.suffix}'))
    for p in old[:-BACKUPS_KEEP]:
        p.unlink()
    return dst


def append_row(path, fields):
    """Дописать одну целую строку (одной записью на диск). Номер новой строки в файле - в ответе."""
    for x in fields:
        if '\t' in x or '\n' in x or '\r' in x:
            raise Refused('В тексте не должно быть табуляции и переводов строки.')
    data = Path(path).read_bytes() if Path(path).exists() else b''
    if data and not data.endswith(b'\n'):
        raise Refused(f'Последняя строка {Path(path).name} не закончена (её кто-то пишет или файл испорчен). '
                      'Запись остановлена, файл не тронут.')
    eol = '\r\n' if b'\r\n' in data[-400:] else '\n'
    line = ('\t'.join(fields) + eol).encode('utf-8')
    with open(path, 'ab') as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return len([x for x in data.decode('utf-8-sig', errors='replace').splitlines() if x.strip()]) + 1


# ---------- проверки ----------

def check_rel(path, what='путь'):
    p = (path or '').strip().strip(SEP)
    if not p or ':' in p or '/' in p or (SEP + p + SEP).find(SEP + '..' + SEP) >= 0:
        raise Refused(f'Недопустимый {what} «{path}»: нужен путь от корня диска без буквы, например «Фото\\2014».')
    return p


def db():
    return hb.connect()[0]


def check_disk(c, disk):
    if not c.execute('select 1 from disks where disk=?', (disk,)).fetchone():
        raise Refused(f'Носителя {disk} нет в базе.')


def files_under(c, disk, path, limit=3):
    """Сколько записей базы лежит по пути (сам файл или всё внутри папки - не соседние имена) и примеры."""
    cond, args = hb.prefix_cond('path', path)
    n, size = c.execute(f'select count(*), coalesce(sum(size), 0) from files where disk=? and {cond}', [disk] + args).fetchone()
    sample = [r[0] for r in c.execute(f'select path from files where disk=? and {cond} limit ?', [disk] + args + [limit])]
    return n, size, sample


# ---------- записи владельца ----------

def manual_preview(date, act, disk, path, disk2='', path2=''):
    """Что изменит ручная операция. Исключение Refused - если записывать нельзя."""
    act = (act or '').strip().lower()
    if act not in ACTIONS:
        raise Refused(f'Действие должно быть одним из: {", ".join(ACTIONS)}.')
    if not DATE_RE.match(date or ''):
        raise Refused('Дата - в виде ДД.ММ.ГГГГ, например 14.11.2026.')
    c = db()
    check_disk(c, disk)
    path = check_rel(path)
    if act != 'удалено':
        check_disk(c, disk2)
        path2 = check_rel(path2, 'путь назначения')
    else:
        disk2 = path2 = ''
    n, size, sample = files_under(c, disk, path)
    if not n:
        raise Refused(f'В базе нет файлов по пути {disk}\\{path}. Проверьте номер диска и путь (папку можно '
                      'выбрать и на отключённом диске - из каталога базы).')
    for ln, f in hb.manual_rows():
        if [x.strip() for x in f[:6]] == [date, act, disk, path, disk2, path2]:
            raise Refused(f'Такая операция уже записана (строка {ln}). Повторно не записываю.')
    lines = [f'{date} {act}: {disk}\\{path}' + (f' -> {disk2}\\{path2}' if disk2 else ''),
             f'Затронет записей базы: {n}, {hb.gb(size)} ГБ. Например: ' + '; '.join(sample)]
    if disk2:
        m, _, _ = files_under(c, disk2, path2)
        if m:
            lines.append(f'ВНИМАНИЕ: в {disk2}\\{path2} в базе уже есть {m} записей - одинаковые пути будут заменены.')
        lines.append('Копия «со слов» получает степень U (не подтверждена): удалять оригинал по ней нельзя.'
                     if act == 'скопировано' or disk2 != disk else 'Перемещение внутри диска: хеш и степень сохраняются.')
    return dict(fields=[date, act, disk, path, disk2, path2], lines=lines, files=n)


def add_manual(date, act, disk, path, disk2='', path2='', note='', apply=True):
    with TableLock():
        pv = manual_preview(date, act, disk, path, disk2, path2)
        hb.ensure_tables()
        backup(hb.MANUAL)
        ln = append_row(hb.MANUAL, pv['fields'] + [note or ''])
    pv['line'] = ln
    if apply:
        hb.close_last()
        hb.update(quiet=True)
    return pv


def fix_manual(line_no, fields, reason):
    """Исправить ошибочно записанную строку: заменить её, причину - в комментарий; база соберётся заново."""
    if not reason:
        raise Refused('Нужна причина исправления.')
    with TableLock():
        lines = hb.MANUAL.read_bytes().decode('utf-8-sig').split('\n')
        idx = [i for i, x in enumerate(lines) if x.strip()]
        if line_no < 2 or line_no > len(idx):
            raise Refused(f'Строки {line_no} нет.')
        backup(hb.MANUAL)
        i = idx[line_no - 1]
        eol = '\r' if lines[i].endswith('\r') else ''
        old = lines[i].rstrip('\r').split('\t')
        note = (fields[6] if len(fields) > 6 else '') + f' | исправлено {time.strftime("%d.%m.%Y")}: {reason}; было: {" / ".join(old[:6])}'
        lines[i] = '\t'.join(fields[:6] + [note]) + eol
        data = '\n'.join(lines).encode('utf-8-sig')
        hb.MANUAL.write_bytes(data)
    hb.close_last()
    hb.update(quiet=True)


def decision_preview(disk, path, verdict):
    verdict = (verdict or '').strip()
    if not VERDICT_RE.match(verdict):
        raise Refused('Решение: «не нужно», «раздел: <название>» или «пока не трогаем».')
    c = db()
    if disk != '*':
        check_disk(c, disk)
    if path.lower().startswith('класс:'):
        n, size, sample = 0, 0, []
    else:
        path = check_rel(path)
        n, size, sample = files_under(c, disk, path) if disk != '*' else (0, 0, [])
        if disk != '*' and not n:
            raise Refused(f'В базе нет файлов по пути {disk}\\{path}.')
    for f in hb.read_table(hb.DECISIONS)[1:]:
        f = [x.strip() for x in f] + ['', '', '']
        if f[:3] == [disk, path, verdict]:
            raise Refused('Такое решение уже записано.')
    return dict(fields=[disk, path, verdict],
                lines=[f'{disk}\\{path}: {verdict}', f'Под решение попадает записей базы: {n}, {hb.gb(size)} ГБ'])


def add_decision(disk, path, verdict, note=''):
    with TableLock():
        pv = decision_preview(disk, path, verdict)
        hb.ensure_tables()
        backup(hb.DECISIONS)
        pv['line'] = append_row(hb.DECISIONS, pv['fields'] + [note or ''])
    return pv                       # решения читаются при каждом ответе - применять к базе нечего


def exclusion_preview(disk, path):
    c = db()
    check_disk(c, disk)
    path = check_rel(path)
    for d, folders in hb.read_exclusions().items():
        if d == disk and path in folders:
            raise Refused('Эта папка уже в исключениях.')
    n, size, sample = files_under(c, disk, path)
    return dict(fields=[disk, path], lines=[f'Исключить {disk}\\{path}: база перестанет учитывать {n} записей, '
                                            f'{hb.gb(size)} ГБ (их список сохранится в таблице excluded).'])


def add_exclusion(disk, path, note=''):
    with TableLock():
        pv = exclusion_preview(disk, path)
        hb.ensure_tables()
        backup(hb.EXCLUSIONS)
        pv['line'] = append_row(hb.EXCLUSIONS, pv['fields'] + [note or ''])
    hb.close_last()
    hb.update(quiet=True)
    return pv


# ---------- чтение для окна: каждое обращение - своё соединение только для чтения ----------

def ro():
    """Соединение только для чтения на один запрос. Окно не держит базу открытой: пересборке ничто не мешает."""
    if not hb.DB.exists():
        raise Refused('База ещё собирается - подождите.')
    return sqlite3.connect(f'file:{hb.DB.as_posix()}?mode=ro', uri=True, timeout=30)


def generation():
    """Поколение базы - время её сборки; меняется после каждого применения модулей."""
    if not hb.DB.exists():
        return None
    c = ro()
    try:
        r = c.execute("select value from meta where key='built'").fetchone()
        return r[0] if r else None
    finally:
        c.close()


def volumes():
    """Подключённые сейчас тома: серийный номер -> буква. Сетевые диски пропускаются, диски не читаются."""
    import ctypes
    k32 = ctypes.windll.kernel32
    res = {}
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f'{chr(65 + i)}:\\'
        if k32.GetDriveTypeW(root) in (0, 1, 4):          # неизвестный, нет корня, сетевой
            continue
        ser = ctypes.c_ulong()
        if k32.GetVolumeInformationW(root, None, 0, ctypes.byref(ser), None, None, None, 0):
            res[f'{ser.value:08X}'] = root[:2]
    return res


def disks():
    """Таблица носителей: номер, метка, подключён ли (буква), файлов, ГБ, опись от, состояние, частичных сканов."""
    jobs = bp.find_jobs()
    serial_of = {v: k for k, v in hb.serial_map(jobs).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    c = ro()
    try:
        rows = []
        size = dict(c.execute("select disk, bytes from folders where folder=''"))
        parts = collections.Counter(r[0] for r in c.execute('select disk from scan_folders'))
        for d, label, total, status, scanned in c.execute('select disk, label, total, status, scanned from disks order by disk'):
            rows.append(dict(disk=d, label=label.split(' - ', 1)[-1] if label else '', letter=vols.get(serial_of.get(d, '?'), ''),
                             files=total, gib=(size.get(d) or 0) / hb.GIB, status=status,
                             scanned=time.strftime('%d.%m.%Y', time.localtime(scanned)) if scanned else '',
                             partial=parts.get(d, 0)))
        return rows
    finally:
        c.close()


def overview():
    """Сводка для экрана «Обзор»: поколение базы, 45 и 77, предупреждения, задания."""
    c = ro()
    try:
        rep = hb.load_report(c)
        res = dict(built=c.execute("select value from meta where key='built'").fetchone()[0],
                   files=c.execute("select sum(total) from disks").fetchone()[0], disks=c.execute('select count(*) from disks').fetchone()[0],
                   main={}, warn=sorted(rep['warn']) + [x for _, x in sorted(rep['unique'].items())],
                   skipped=list(rep['skipped']))
        for d in hb.MAIN:
            ev = dict(c.execute("select ev, count(*) from files where disk=? group by ev", (d,)).fetchall())
            res['main'][d] = dict(ev=ev, gib=(c.execute("select bytes from folders where disk=? and folder=''", (d,)).fetchone() or [0])[0] / hb.GIB)
    finally:
        c.close()
    jobs = bp.find_jobs()
    serial_of = {v: k for k, v in hb.serial_map(jobs).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    for d in hb.MAIN:
        letter = vols.get(serial_of.get(d, '?'))
        res['main'][d]['letter'] = letter or ''
        if letter:
            try:
                res['main'][d]['free_gib'] = shutil.disk_usage(letter + '\\').free / hb.GIB
            except OSError:
                pass
    res['checked'] = time.strftime('%H:%M:%S')
    return res


def folder_children(disk, folder=''):
    """Подпапки папки (по готовой таблице folders): имя, путь, файлов, ГБ, ГБ по типам, решение владельца."""
    folder = (folder or '').strip(SEP)
    depth = (folder.count(SEP) + 1 if folder else 0) + 1
    cond, args = hb.prefix_cond('folder', folder)
    decs = hb.decisions_for(disk)
    c = ro()
    try:
        q = (f'select folder, files, bytes, ' + ', '.join(f'b{i}' for i in range(5)) +
             f' from folders where disk=? and depth=? and {cond} order by bytes desc')
        res = []
        for r in c.execute(q, [disk, depth] + args):
            res.append(dict(path=r[0], name=r[0].rsplit(SEP, 1)[-1], files=r[1], gib=r[2] / hb.GIB,
                            types=[x / hb.GIB for x in r[3:8]], decision=hb.decision_of(r[0], decs) or ''))
        return res
    finally:
        c.close()


def folder_presence(disk, folder):
    """Чего из папки нет на 45 и 77 (фото и видео с SHA-256, по таблице presence; решения не учитываются)."""
    cond, args = hb.prefix_cond('f.path', (folder or '').strip(SEP))
    c = ro()
    try:
        q = f"""select count(*), coalesce(sum(f.size),0),
                       coalesce(sum(case when not coalesce(p.e45 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when not coalesce(p.e77 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when p.ndisks=1 then f.size end),0)
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        n, b, no45, no77, only = c.execute(q, [disk] + args).fetchone()
        nohash = c.execute(f"select count(*) from files f where f.disk=? and f.sha is null and {cond}", [disk] + args).fetchone()[0]
        return dict(files=n, gib=b / hb.GIB, no45=no45 / hb.GIB, no77=no77 / hb.GIB, only=only / hb.GIB, nohash=nohash)
    finally:
        c.close()


def find_folders(words, disk=None, limit=300):
    """Папки, в пути которых есть все слова (только верхние совпадения), по таблице folders."""
    words = [w.lower() for w in words if w.strip()]
    if not words:
        return []
    q = 'select disk, folder, files, bytes from folders where ' + ' and '.join(['instr(folder_lc, ?) > 0'] * len(words))
    args = list(words)
    if disk:
        q += ' and disk=?'
        args.append(disk)
    c = ro()
    try:
        rows = c.execute(q, args).fetchall()
    finally:
        c.close()
    hits = {(r[0], r[1]) for r in rows}
    top = [r for r in rows if r[1] and (r[0], hb.parent_of(r[1])) not in hits]
    top.sort(key=lambda r: -r[3])
    return [dict(disk=d, path=f, files=n, gib=b / hb.GIB) for d, f, n, b in top[:limit]]


def sources_signature():
    """Быстрая подпись первоисточников (размеры и время таблиц, журналов, описей) - чтобы окно знало,
    что пора применить новые модули. Диски не читаются."""
    sig = []
    for p in [hb.MANUAL, hb.DECISIONS, hb.EXCLUSIONS] + [Path(x) for x in hb.journal_paths()]:
        try:
            st = Path(p).stat()
            sig.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for j in bp.find_jobs().values():
        try:
            st = (j['dir'] / 'inventory.sqlite').stat()
            sig.append((str(j['dir']), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for pj in hb.find_partials():
        sig.append((str(pj['dir']), pj['time']))
    return hash(tuple(sorted(sig)))


# ---------- пересканирование выбранных папок (сканер 1.4.0) ----------

SCANNER = Path(__file__).resolve().parent.parent / 'scanner'


def _scanner():
    """Модули сканера (rescan - правило доверия прежнему хешу, inventory - сведения о томе)."""
    if str(SCANNER) not in sys.path:
        sys.path.insert(0, str(SCANNER))
    import rescan
    import inventory
    return rescan, inventory


def disk_letter(disk):
    """Буква подключённого носителя - по серийному номеру тома из его полной описи. Диск не читается."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    if disk not in serial_of:
        raise Refused(f'У {disk} нет полной описи - пересканировать папки нельзя.')
    try:
        letter = volumes().get(serial_of[disk])
    except (OSError, AttributeError):
        letter = None
    if not letter:
        raise Refused(f'{disk} не подключён: подключите диск (буква найдётся сама по серийному номеру тома).')
    return letter


def rescan_plan(disk, folders, rehash_all=False):
    """Предпросмотр пересканирования по оглавлению диска: сколько файлов прочитать, сколько хешей взять из
    прежней описи, сколько исчезло. Содержимое файлов не читается."""
    letter = disk_letter(disk)
    rescan, inventory = _scanner()
    try:
        fs = inventory.volume(letter + '\\')[2]
        plan = rescan.plan(letter + '\\', disk, list(folders), bp.SCAN_ROOTS, rehash_all, fs)
    except (ValueError, OSError) as e:
        raise Refused(str(e))
    plan.update(letter=letter, filesystem=fs, lines=rescan.plan_text(plan))
    if fs.upper() != 'NTFS':
        plan['lines'].insert(1, f'Файловая система {fs}: прежним хешам не доверяем, читается всё.')
    return plan


def rescan_files(disk):
    """Файлы хода и остановки сканирования - в «_БАЗА\\пересканирование»."""
    d = hb.BASE_DIR / 'пересканирование'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{disk} ход.json', d / f'{disk} стоп.txt', d / f'{disk} вывод.txt'


def scanner_python():
    exe = Path(sys.executable)
    return str(exe.with_name('python.exe')) if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists() else str(exe)


def rescan_argv(disk, letter, folders, rehash_all=False, job=None):
    """Командная строка сканера (то же можно запустить вручную в консоли). job - продолжить это задание."""
    progress, stop, _ = rescan_files(disk)
    argv = [scanner_python(), '-X', 'utf8', '-u', str(SCANNER / 'portable.py'), '--progress-file', str(progress),
            '--stop-file', str(stop)]
    if job:
        return argv + ['resume', str(job)]
    argv += ['start', '--disk', disk, '--letter', letter.rstrip(':\\')]
    for f in folders:
        argv += ['--folder', f]
    argv += ['--output', str(Path(bp.SCAN_ROOTS[0]) / hb.PARTIAL_DIR), '--yes']
    for r in bp.SCAN_ROOTS:
        argv += ['--prior-root', str(r)]
    return argv + (['--rehash-all'] if rehash_all else [])


def rescan_start(disk, letter, folders, rehash_all=False, job=None):
    """Запуск сканера отдельным процессом без консоли - ТОЛЬКО по кнопке владельца после подтверждения."""
    progress, stop, log = rescan_files(disk)
    for p in (progress, stop):
        if p.exists():
            p.unlink()
    out = open(log, 'a' if job else 'w', encoding='utf-8')
    env = os.environ.copy()
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    proc = subprocess.Popen(rescan_argv(disk, letter, folders, rehash_all, job), cwd=str(SCANNER), env=env,
                            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    out.close()
    return proc


def read_progress(disk):
    try:
        import json
        return json.loads(rescan_files(disk)[0].read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def partial_outcome(job_name):
    """Итог приёма частичного скана базой: по каждой папке - в скане, стало S, новые, исчезли, хеш не совпал."""
    c = ro()
    try:
        rep = hb.load_report(c)
    finally:
        c.close()
    stats = (rep.get('partial_stats') or {}).get(job_name)
    warn = sorted(w for w in rep['warn'] if job_name in w) + [x for x in rep['old'] if job_name in x]
    lines = []
    for f, k in (stats or {}).items():
        became = sum(v for key, v in k.items() if key.startswith('было ') and key != 'было S')
        lines.append(f'{f}: в скане {k.get("файлов", 0)} файлов ({hb.gb(k.get("байт", 0))} ГБ); стало S {became}'
                     f' (уже было S {k.get("было S", 0)}); '
                     f'новые {k.get("новые", 0)}; исчезли из базы {k.get("исчезли", 0)}; хеш не совпал {k.get("хеш не совпал", 0)}')
    return dict(accepted=stats is not None, lines=lines, warn=warn)


# ---------- задания: честное состояние ----------

def running_scripts():
    """Командные строки запущенных PowerShell (чтобы понять, идёт ли задание). None - узнать не удалось."""
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | ForEach-Object CommandLine"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return [x for x in r.stdout.decode('utf-8', errors='replace').splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        return None


def task_state(task, running='спросить'):
    """Состояние папки задания по её списку и журналам. Только то, что можно доказать:
    «не запускалось», «идёт», «прервано», «готово», «готово с ошибками», «состояние неизвестно»."""
    task = Path(task)
    kind = 'копирование' if (task / 'список.tsv').exists() else 'перемещение' if (task / 'перемещение.tsv').exists() else None
    if not kind:
        return None
    lst = task / ('список.tsv' if kind == 'копирование' else 'перемещение.tsv')
    total = len([x for x in hb.read_tsv(lst) if x])
    ok_words = ('скопирован', 'уже есть') if kind == 'копирование' else ('перемещён', 'уже перемещён')
    logs = sorted(task.glob(('Журнал копирования' if kind == 'копирование' else 'Журнал перемещения') + ' *.tsv'))
    done, errors, skipped, last = {}, 0, 0, None
    for log in logs:
        rows = hb.read_tsv(log)[1:]
        for f in rows:
            if kind == 'копирование' and len(f) >= 7:
                key, res = (f[1], f[5]), f[2]
            elif kind == 'перемещение' and len(f) >= 6:
                key, res = f[4], f[1]
            else:
                continue
            done[key] = res
        last = log
    good = sum(1 for r in done.values() if r.startswith(ok_words))
    errors = sum(1 for r in done.values() if r.startswith('ОШИБКА') or r.startswith('КОНФЛИКТ'))
    skipped = len(done) - good - errors
    if running == 'спросить':
        running = running_scripts()            # None - узнать не удалось
    is_running = None if running is None else any(str(task).lower() in x.lower() for x in running)
    if is_running:
        state = 'идёт'
    elif not logs:
        state = 'не запускалось'
    elif len(done) >= total:
        state = 'готово' if not errors and not skipped else 'готово с ошибками'
    elif is_running is None:
        state = 'состояние неизвестно'
    else:
        state = 'прервано'
    return dict(task=task.name, kind=kind, state=state, total=total, done=len(done), good=good, errors=errors,
                skipped=skipped, journal=str(last) if last else '')


def tasks(root=None):
    root = Path(root or hb.TASKS)
    running = running_scripts()
    res = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        st = task_state(d, running)
        if st:
            res.append(st)
    return res


MOVE_MARK = 'после копирования.json'


def mark_task_move(task, disk, folders=None):
    """Пометка в папке задания копирования (окно, «Подготовить копирование» с галочкой «разложить»): после
    копирования разложить файлы на источнике по «ПЕРЕНЕСЕНО → …» (команда mvlist). Сама ничего не перемещает.
    Файл «после копирования.json»: {"разложить_на_источнике": true, "диск": "HDDxx", "папки": [...] или null,
    "создано": "ДД.ММ.ГГГГ ЧЧ:ММ"}; null - весь диск."""
    import json
    task = Path(task)
    if not task.is_dir():
        raise Refused(f'Нет папки задания: {task}')
    data = {'разложить_на_источнике': True, 'диск': disk, 'папки': list(folders) if folders else None,
            'создано': time.strftime('%d.%m.%Y %H:%M')}
    path = task / MOVE_MARK
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path
