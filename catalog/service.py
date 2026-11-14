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
import hashbase as hb

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
