"""Замок таблиц, копия перед записью, дописывание строк, проверки путей и носителя, соединения с базой (db - запись, ro - только чтение).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

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


def append_rows(path, rows):
    """Дописать целые строки ОДНОЙ записью на диск (write + fsync). Номер первой новой строки в файле - в ответе.
    Проверки - до записи: при отказе файл не тронут."""
    for fields in rows:
        for x in fields:
            if '\t' in x or '\n' in x or '\r' in x:
                raise Refused('В тексте не должно быть табуляции и переводов строки.')
    data = Path(path).read_bytes() if Path(path).exists() else b''
    if data and not data.endswith(b'\n'):
        raise Refused(f'Последняя строка {Path(path).name} не закончена (её кто-то пишет или файл испорчен). '
                      'Запись остановлена, файл не тронут.')
    eol = '\r\n' if b'\r\n' in data[-400:] else '\n'
    block = ''.join('\t'.join(fields) + eol for fields in rows).encode('utf-8')
    with open(path, 'ab') as f:
        f.write(block)
        f.flush()
        os.fsync(f.fileno())
    return len([x for x in data.decode('utf-8-sig', errors='replace').splitlines() if x.strip()]) + 1


def append_row(path, fields):
    """Дописать одну целую строку (одной записью на диск). Номер новой строки в файле - в ответе."""
    return append_rows(path, [fields])


# ---------- проверки ----------

def check_rel(path, what='путь'):
    """Путь от корня диска: убираются только «\» по краям; пробелы - часть имени (этап 16: « Перемещение…»)."""
    p = hb.clean_path(path)
    if not p.strip() or ':' in p or '/' in p or (SEP + p + SEP).find(SEP + '..' + SEP) >= 0:
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


def ro():
    """Соединение только для чтения на один запрос. Окно не держит базу открытой: пересборке ничто не мешает."""
    if not hb.DB.exists():
        raise Refused('База ещё собирается - подождите.')
    return sqlite3.connect(f'file:{hb.DB.as_posix()}?mode=ro', uri=True, timeout=30)
