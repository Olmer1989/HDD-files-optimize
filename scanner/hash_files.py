"""Read-only SHA-256 pilot/full pass; results and checkpoints stay in project."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import stat
import time
from inventory import discover_disk, volume

def signature(st):
    return st.st_size, str(st.st_mtime_ns), str(st.st_ino)

class ReadFailure(OSError):
    """Reading an already opened file failed: almost always the medium itself.

    Python reports Windows read errors through the C runtime, which maps codes
    19-36 (CRC error, sector not found, read fault...) to EACCES, so a damaged
    sector looks like "Permission denied". The real Windows code is kept here.
    """
    def __init__(self, message, windows_code, offset):
        super().__init__(message)
        self.windows_code = windows_code
        self.offset = offset

WINDOWS_ERROR_TEXT = {21: 'устройство не готово', 23: 'ошибка в данных (CRC) — повреждённый сектор',
                      25: 'ошибка позиционирования головки', 27: 'сектор не найден', 30: 'сбой чтения',
                      31: 'устройство не работает', 33: 'часть файла заблокирована другой программой',
                      483: 'аппаратная ошибка устройства', 1117: 'ошибка ввода-вывода устройства',
                      1167: 'устройство отключено'}

def last_windows_error():
    """Windows code of the last failed C runtime call (_doserrno), or None."""
    try:
        import ctypes
        value = ctypes.c_ulong()
        if ctypes.CDLL('ucrtbase')._get_doserrno(ctypes.byref(value)) == 0 and value.value:
            return value.value
    except (OSError, AttributeError):
        pass
    return None

def hash_one(path, expected, progress=None):
    # Refuse symlinks/junctions at every component, including ancestor directories.
    for part in [*path.parents, path]:
        st = part.lstat()
        if getattr(st, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(st.st_mode):
            raise RuntimeError('Reparse point refused')
    observed = signature(path.stat())
    # Windows scandir may omit file IDs and report zero. Zero means unknown,
    # not a different file. Capture the actual ID now and enforce it throughout.
    if observed[:2] != expected[:2] or (expected[2] != '0' and observed[2] != expected[2]):
        raise RuntimeError('File changed since inventory')
    expected = observed
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as source:
        if signature(os.fstat(source.fileno())) != expected:
            raise RuntimeError('File changed before reading')
        while True:
            try:
                block = source.read(4 * 1024 * 1024)
            except OSError as exc:
                code = getattr(exc, 'winerror', None) or last_windows_error()
                text = WINDOWS_ERROR_TEXT.get(code, exc.strerror or str(exc))
                raise ReadFailure(f'ошибка чтения около байта {count:,}: {text} (код Windows {code or "неизвестен"})',
                                  code, count) from exc
            if not block:
                break
            count += len(block)
            digest.update(block)
            if progress:
                progress(count)
        if signature(os.fstat(source.fileno())) != expected or count != expected[0]:
            raise RuntimeError('File changed during reading')
    if signature(path.stat()) != expected:
        raise RuntimeError('Path changed after reading')
    return digest.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--disk', choices=['HDD01','HDD02'], required=True)
    parser.add_argument('--max-gb', type=float, default=1.0, help='Pilot budget; 0 for full selected disk')
    args = parser.parse_args()
    if args.max_gb < 0:
        parser.error('max-gb must be nonnegative')
    base = Path(__file__).resolve().parents[1]
    selection = args.selection.resolve()
    if selection.name != 'selection.sqlite' or not selection.is_relative_to(base / 'Каталог дисков'):
        parser.error('Selection must be a project selection.sqlite')
    record = json.loads(Path(__file__).with_name('disks.json').read_text(encoding='utf-8'))[args.disk]
    root, physical = discover_disk(record)  # fail closed if Windows identity query is denied
    def check():
        import shutil
        if volume(root)[0] != record['volume_serial'] or shutil.disk_usage(root).total != record['volume_bytes']:
            raise RuntimeError('Volume disconnected or replaced')
    started = time.monotonic()
    used = done = errors = cached = cached_bytes = completed_bytes = 0
    interrupted = False
    last_progress = started
    budget = int(args.max_gb * 1e9)
    with sqlite3.connect(selection.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(selection.with_name('hashes.sqlite')) as target:
        target.execute('create table if not exists hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,status text,error text,primary key(disk_id,path))')
        total_files, total_bytes = source.execute('select count(*),coalesce(sum(size),0) from files where disk_id=?', (args.disk,)).fetchone()
        print(f'{args.disk}: starting; selected {total_files:,} files, {total_bytes/1e9:.2f} GB; saved hashes will be reused.', flush=True)
        def show_progress(in_file=0, force=False):
            nonlocal last_progress
            now = time.monotonic()
            if not force and now-last_progress < 10:
                return
            elapsed = max(now-started, .001)
            read_bytes = used + in_file
            rate = read_bytes/elapsed
            position = cached_bytes + completed_bytes + in_file
            remaining = max(0, total_bytes-position)
            eta = f'{remaining/rate/3600:.1f} h' if rate > 0 else 'estimating'
            print(f'{args.disk}: hashed={done:,}, reused={cached:,}, errors={errors}; '
                  f'{position/1e9:.2f}/{total_bytes/1e9:.2f} GB ({position/max(total_bytes,1):.1%}); '
                  f'{rate/1e6:.1f} MB/s; elapsed={elapsed/3600:.2f} h; ETA={eta}', flush=True)
            last_progress = now
        for rel, size, mtime, file_id in source.execute('select path,size,mtime_ns,file_id from files where disk_id=? order by size,path', (args.disk,)):
            if budget and used + size > budget:
                continue
            parts = PureWindowsPath(rel).parts
            if PureWindowsPath(rel).is_absolute() or any(p in ('.','..') or ':' in p for p in parts):
                raise RuntimeError('Unsafe relative path in selection')
            path = Path(root).joinpath(*parts)
            expected = (size, str(mtime), str(file_id))
            old = target.execute('select size,mtime_ns,file_id,status from hashes where disk_id=? and path=?', (args.disk, rel)).fetchone()
            try:
                check()
                current = signature(path.stat())
                if old == (*expected, 'verified') and current[:2] == expected[:2] and (expected[2] == '0' or current[2] == expected[2]):
                    cached += 1
                    cached_bytes += size
                    show_progress()
                    continue
                digest = hash_one(path, expected, show_progress)
                check()
                status, message = 'verified', ''
                done += 1
                completed_bytes += size
            except KeyboardInterrupt:
                interrupted = True
                print('Stopped by user. Completed file hashes are saved; current file will be read again.', flush=True)
                break
            except (OSError, RuntimeError) as exc:
                digest, status, message = None, 'error', str(exc)
                errors += 1
            target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (args.disk, rel, *expected, digest, status, message))
            target.commit()
            used += size
            if errors:
                print(f'ERROR: {rel}: {message}', flush=True)
            show_progress()
            if errors:
                break  # inspect first read/change error before continuing heavy I/O
        show_progress(force=True)
    report = dict(disk_id=args.disk,physical=physical,mode='full' if not budget else 'pilot',
                  status='interrupted' if interrupted else ('error' if errors else 'complete'),
                  hashed_files=done,cached_files=cached,errors=errors,attempted_bytes=used,seconds=round(time.monotonic()-started,2))
    output = selection.with_name(f'{args.disk}_hash_run_{time.time_ns()}.json')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors or interrupted:
        raise SystemExit(130 if interrupted else 2)

if __name__ == '__main__':
    main()
