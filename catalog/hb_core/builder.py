"""Сборщик базы: какие модули новые, применение, полная пересборка, самопроверка, замок."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import hashlib
import json
import os
import sqlite3
import sys
import time
import build_pilot as bp
from hb_core import paths
from hb_core.consts import BUILD_VERSION, KIND_ORDER, STATE_KINDS
from hb_core.schema import DERIVED_SCHEMA, DIGEST_TABLES, INDEXES, SCHEMA, TRIGGERS
from hb_core.util import Seen, out
from hb_core.sources import discover, ensure_tables, read_exclusions, read_log, serial_map
from hb_core.apply_common import replace_file
from hb_core.apply_excl import apply_exclusions, excluded_unique
from hb_core.apply_log import apply_log
from hb_core.apply_manual import apply_manual_row
from hb_core.apply_partial import apply_partial
from hb_core.apply_disk import load_disk
from hb_core.derived import derived_finish, derived_start, folders_full, presence_full


def apply_event(c, ev, jobs, serials, report, seen, excl):
    kind, data = ev[3], ev[4]
    if kind == 'log':
        apply_log(c, data, jobs, serials, report, seen)
    elif kind == 'partial':
        apply_partial(c, data, seen, excl, report)
    else:
        apply_manual_row(c, data[0], data[1], report, seen)


def plan(c, mods):
    """Что применить: (список новых модулей, None) или (None, причина полной пересборки)."""
    applied = {r[0]: r for r in c.execute('select module, kind, time, size, mtime_ns, checksum, rows from applied')}
    gone = [k for k in applied if k not in mods]
    if gone:
        return None, f'пропал уже учтённый модуль «{gone[0]}»'
    last = c.execute(f"select max(time) from applied where kind in ({','.join('?' * len(STATE_KINDS))})",
                     STATE_KINDS).fetchone()[0] or 0
    todo = []
    for key, m in mods.items():
        a = applied.get(key)
        k = m['kind']
        if k == 'журнал':
            if a and (a[3], a[4]) == (m['size'], m['mtime_ns']):
                continue
            start = read_log(m, (a[3], a[5], a[6]) if a else None)
            if start is None:
                return None, f'изменился уже учтённый журнал «{key}» (не дописан, а исправлен)'
            m['start'] = start
            todo.append((key, m))
        elif a:
            if a[5] != m['checksum']:
                if k == 'опись' and m['time'] >= last:
                    todo.append((key, m))                # новая опись носителя: заменить только его строки
                    continue
                return None, f'изменился уже учтённый модуль «{key}»'
        elif k in ('опись', 'частичный скан') and m['time'] < last:
            return None, f'новый модуль «{key}» старше уже учтённых поправок'
        else:
            todo.append((key, m))
    return sorted(todo, key=lambda km: (km[1]['time'], KIND_ORDER[km[1]['kind']], km[0])), None


def load_report(c):
    row = c.execute("select value from meta where key='report'").fetchone()
    rep = json.loads(row[0]) if row else {}
    for k, v in (('logs', {}), ('old_logs', {}), ('skipped', []), ('manual', []), ('old', []), ('warn', []),
                 ('partial', []), ('excluded', []), ('unique', {})):
        rep.setdefault(k, v)
    rep['warn'] = set(rep['warn'])
    return rep


def save_report(c, rep):
    rep = dict(rep, warn=sorted(rep['warn']))
    c.execute('insert or replace into meta values (?,?)', ('report', json.dumps(rep, ensure_ascii=False)))
    c.execute('insert or replace into meta values (?,?)', ('built', time.strftime('%d.%m.%Y %H:%M')))


def load_seen(c):
    seen = Seen(c.execute('select disk, scanned from disks'))
    for d, f, t in c.execute('select disk, folder, time from scan_folders'):
        seen.add(d, f, t)
    return seen


def replace_disk(c, d, j, seen):
    """Новая полная опись носителя: строки только этого носителя удаляются и вставляются заново.
    Триггеры на сотни тысяч строк медленны, поэтому здесь они выключаются: суммы по папкам этого носителя
    считаются заново целиком, а в presence пересчитываются только его хеши (старые и новые)."""
    fast = bool(c.execute("select 1 from sqlite_temp_master where type='trigger' and name='t_files_ins'").fetchone())
    mark = ('insert or ignore into temp.touched select sha from files where disk=? and sha is not null',
            'insert or ignore into temp.touched select sha_exp from files where disk=? and sha_exp is not null')
    if fast:
        for name in ('t_files_ins', 't_files_del', 't_files_upd'):
            c.execute(f'drop trigger if exists temp.{name}')
        for q in mark:
            c.execute(q, (d,))
        c.execute('delete from temp.delta where disk=?', (d,))
    for t in ('files', 'issues', 'disks', 'scan_folders', 'excluded'):
        c.execute(f'delete from {t} where disk=?', (d,))
    load_disk(c, d, j)
    if fast:
        for q in mark:
            c.execute(q, (d,))
        folders_full(c, [d])
        for q in TRIGGERS:
            c.execute(q)
    seen.full[d] = c.execute('select scanned from disks where disk=?', (d,)).fetchone()[0]
    seen.parts.pop(d, None)


def apply_modules(c, todo, jobs, rep, seen, incremental):
    """Применить модули по порядку и записать их в applied. Исключения действуют всегда: после каждого модуля
    строки в исключённых папках убираются, откуда бы они ни пришли."""
    serials = serial_map(jobs)
    excl = read_exclusions()
    stamp = time.strftime('%d.%m.%Y %H:%M')
    count = ((lambda: c.execute('select count(*) from temp.delta').fetchone()[0]) if incremental   # без строк триггеров
             else (lambda: c.total_changes))
    for key, m in todo:
        before = count()
        k = m['kind']
        if k == 'опись':
            if incremental:
                replace_disk(c, *m['data'], seen)
            else:
                load_disk(c, *m['data'])
                seen.full[m['data'][0]] = c.execute('select scanned from disks where disk=?', (m['data'][0],)).fetchone()[0]
        elif k == 'частичный скан':
            apply_partial(c, m['data'], seen, excl, rep)
        elif k == 'журнал':
            if 'rows' not in m:
                read_log(m)
                m['start'] = 0
            apply_log(c, m['data'], jobs, serials, rep, seen, rows=m['rows'], start=m['start'])
        elif k == 'ручная операция':
            apply_manual_row(c, m['data'][0], m['data'][1], rep, seen)
        if k != 'опись' or incremental:
            apply_exclusions(c, excl, rep)
        changed = max(0, count() - before)
        c.execute('insert or replace into applied values (?,?,?,?,?,?,?,?,?)',
                  (key, k, m['time'], m['size'], m['mtime_ns'], m['checksum'],
                   max(0, len(m['rows']) - 1) if k == 'журнал' else 0, stamp, changed))


def rebuild(jobs=None, quiet=False, check=False):
    """Полная пересборка из всех модулей во временный файл; затем он заменяет рабочую базу.
    check=True - самопроверка: сравнить с базой, собранной по шагам."""
    jobs = jobs or bp.find_jobs()
    ensure_tables()
    t0 = time.time()
    tmp = paths.DB.with_name(f'хеши.{os.getpid()}.tmp')
    if tmp.exists():
        tmp.unlink()
    c = sqlite3.connect(tmp)
    c.executescript('pragma journal_mode=off; pragma synchronous=off; pragma cache_size=-400000;')
    for q in SCHEMA:
        c.execute(q)
    mods = discover(jobs)
    rep = load_report(c)
    seen = Seen({})
    todo = sorted(mods.items(), key=lambda km: (KIND_ORDER[km[1]['kind']] if km[1]['kind'] == 'опись' else 1,
                                                km[1]['time'], KIND_ORDER[km[1]['kind']], km[0]))
    disks_first = [km for km in todo if km[1]['kind'] == 'опись']
    apply_modules(c, disks_first, jobs, rep, seen, incremental=False)
    c.commit()
    t_disks = time.time() - t0
    apply_exclusions(c, read_exclusions(), rep)
    rest = sorted((km for km in todo if km[1]['kind'] != 'опись'),
                  key=lambda km: (km[1]['time'], KIND_ORDER[km[1]['kind']], km[0]))
    apply_modules(c, rest, jobs, rep, seen, incremental=False)
    for q in INDEXES + DERIVED_SCHEMA:
        c.execute(q)
    t1 = time.time()
    presence_full(c)
    folders_full(c)
    t_derived = time.time() - t1
    finish(c, rep)
    c.execute('insert or replace into meta values (?,?)', ('version', str(BUILD_VERSION)))
    c.commit()
    result = None
    if check:
        result = compare_with_current(c)
    c.close()
    replace_file(tmp, paths.DB)          # прежняя рабочая база остаётся на месте до этой строки
    if not quiet:
        out(f'База собрана целиком за {time.time() - t0:.0f} с (описи носителей {t_disks:.0f} с, '
            f'таблицы presence и folders {t_derived:.0f} с): '
            f'{len(jobs)} носителей, модулей {len(mods)}.')
    return result


def finish(c, rep):
    """Общий хвост сборки: список единственных экземпляров в исключённых папках."""
    excluded_unique(c, rep)
    save_report(c, rep)


def digest(c, prefix=''):
    """Контрольные суммы отсортированного содержимого таблиц: таблица -> (строк, сумма)."""
    res = {}
    for t, cols in DIGEST_TABLES.items():
        h, n = hashlib.sha256(), 0
        for r in c.execute(f'select {cols} from {prefix}{t} order by {cols}'):
            h.update(repr(r).encode('utf-8', 'surrogatepass'))
            n += 1
        res[t] = (n, h.hexdigest())
    return res


def compare_with_current(c):
    """Самопроверка: та же ли база получилась с нуля, что и собранная по шагам. (совпало, строки отчёта)."""
    if not paths.DB.exists():
        return None, ['прежней базы нет - сравнивать не с чем']
    c.execute('attach ? as cur', (str(paths.DB),))
    try:
        ver = c.execute("select value from cur.meta where key='version'").fetchone()
    except sqlite3.Error:
        ver = None
    if not ver or ver[0] != str(BUILD_VERSION):
        c.execute('detach cur')
        return None, ['прежняя база собрана по другим правилам - сравнивать не с чем']
    new, old = digest(c), digest(c, 'cur.')
    c.execute('detach cur')
    lines = [f'{t}: {"совпала" if new[t] == old[t] else "НЕ СОВПАЛА"} (строк {new[t][0]}'
             + (f', по шагам было {old[t][0]})' if new[t] != old[t] else ')') for t in DIGEST_TABLES]
    return all(new[t] == old[t] for t in DIGEST_TABLES), lines


def db_version():
    if not paths.DB.exists():
        return None
    c = sqlite3.connect(f'file:{paths.DB.as_posix()}?mode=ro', uri=True)
    try:
        row = c.execute("select value from meta where key='version'").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        c.close()


def update(jobs=None, quiet=False):
    """Применить к рабочей базе только новые модули. Нужна полная пересборка - сообщить и собрать целиком."""
    jobs = jobs or bp.find_jobs()
    ensure_tables()
    with BuildLock():
        if db_version() != str(BUILD_VERSION):
            out('(рабочей базы ещё нет или изменились правила сборки - собираю её целиком из модулей, это несколько минут)')
            rebuild(jobs, quiet=quiet)
            return 'rebuild'
        t0 = time.time()
        c = sqlite3.connect(paths.DB)
        try:
            mods = discover(jobs)
            todo, why = plan(c, mods)
            if why:
                c.close()
                out(f'({why} - пересобираю рабочую базу целиком, это несколько минут)')
                rebuild(jobs, quiet=quiet)
                return 'rebuild'
            if not todo:
                return None
            kinds = collections.Counter(m['kind'] for _, m in todo)
            out('(есть новые модули: ' + ', '.join(f'{k} - {n}' for k, n in kinds.items())
                + ' - пересобираю рабочую базу частично: применяю только их)')
            c.execute('pragma cache_size=-200000')
            rep = load_report(c)
            seen = load_seen(c)
            derived_start(c)
            apply_modules(c, todo, jobs, rep, seen, incremental=True)
            derived_finish(c)
            finish(c, rep)
            c.commit()
        finally:
            c.close()
    if not quiet:
        out(f'Новые модули применены за {time.time() - t0:.1f} с.')
    return 'update'


class BuildLock:
    """Одна сборка базы за раз: вторая копия программы ждёт, а не портит временные файлы первой."""

    def __enter__(self):
        paths.BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(paths.BASE_DIR / 'сборка.lock', 'a+b')
        try:
            import msvcrt
        except ImportError:
            return self
        for _ in range(900):
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.locked = True
                return self
            except OSError:
                time.sleep(1)
        self.f.close()
        sys.exit('Другая копия программы уже 15 минут пересобирает базу. Дождитесь её и повторите команду.')

    def __exit__(self, *exc):
        try:
            if getattr(self, 'locked', False):
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def build(jobs=None, quiet=False):
    """Привести рабочую базу в порядок (только новые модули) и вернуть отчёт сборки."""
    update(jobs, quiet)
    c = sqlite3.connect(f'file:{paths.DB.as_posix()}?mode=ro', uri=True)
    try:
        return load_report(c)
    finally:
        c.close()
