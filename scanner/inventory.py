"""Read-only metadata inventory. Never opens file contents or modifies sources."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import subprocess
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

EXCLUDED_DIRS = {'$recycle.bin', 'system volume information', 'node_modules',
                 '.git', '.svn', '__pycache__', '.venv', 'venv', '$windows.~bt',
                 'recycler', '.trashes', '.fseventsd'}
MEDIA = set('.jpg .jpeg .png .heic .heif .tif .tiff .webp .bmp .gif .avif '
            '.raw .cr2 .cr3 .nef .nrw .dng .arw .srf .sr2 .orf .rw2 .raf .pef '
            '.mov .mp4 .avi .mkv .m4v .mts .m2ts .mpg .mpeg .wmv .3gp .vob .mod .tod .mxf .ts .m2v .webm .flv'.split())
COMPANIONS = set('.xmp .aae .thm .lrv .srt .wav .mp3 .m4a .prproj .drp .psd .psb'.split())
MIN_BYTES = 1048576

def utc():
    return datetime.now(timezone.utc).isoformat()

def volume(root):
    serial = wintypes.DWORD()
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    fn = ctypes.WinDLL('kernel32', use_last_error=True).GetVolumeInformationW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                   ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                   ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if not fn(root, label, 261, ctypes.byref(serial), None, None, fs, 261):
        raise ctypes.WinError(ctypes.get_last_error())
    return f'{serial.value:08X}', label.value, fs.value

def classification(name, size):
    ext = Path(name).suffix.lower()
    if ext in MEDIA:
        return 'media_ge_1MiB' if size >= MIN_BYTES else 'media_small'
    return 'companion_or_project' if ext in COMPANIONS else 'other'

def excluded_file(name):
    n = name.lower()
    return n == '.env' or n.startswith('.env.') or n.endswith('.env')

def discover_disk(record):
    # Read-only Windows storage queries. Drive letters are addresses, not IDs.
    command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; @(Get-Partition | Where-Object DriveLetter | ForEach-Object { $p=$_; $d=Get-Disk -Number $p.DiskNumber; [pscustomobject]@{letter=[string]$p.DriveLetter; serial=[string]$d.SerialNumber; bytes=$d.Size; unique_id=[string]$d.UniqueId} }) | ConvertTo-Json -Compress"
    proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                          capture_output=True, encoding='utf-8-sig', check=True)
    items = json.loads(proc.stdout)
    if isinstance(items, dict):
        items = [items]
    matches = []
    for item in items:
        if item['serial'].strip() != record['hardware_serial'] or item['bytes'] != record['physical_bytes']:
            continue
        root = item['letter'] + ':\\'
        if volume(root)[0] == record['volume_serial'] and shutil.disk_usage(root).total == record['volume_bytes']:
            matches.append((root, item))
    if len(matches) != 1:
        raise RuntimeError('Registered disk absent, ambiguous, or changed. No scan started. Check registry manually.')
    return matches[0]

def inventory(root, db, check, progress=None):
    # progress(summary) is called after each directory; callers throttle it.
    summary = {'started_utc': utc(), 'source': root, 'status': 'running',
               'files': 0, 'bytes': 0, 'directories': 0,
               'excluded_directories': 0, 'excluded_secret_files': 0, 'reparse_skipped': 0,
               'errors': 0, 'content_bytes_read': 0,
               'scope': 'metadata only; no hashes; excludes service directories and reparse points'}
    groups = defaultdict(lambda: [0, 0])
    extensions = defaultdict(lambda: [0, 0])
    top = defaultdict(lambda: [0, 0])
    db.execute('create table files(path text primary key,size integer,mtime_ns text,ctime_ns text,file_id text,attributes integer,category text)')
    db.execute('create table errors(path text,operation text,message text)')
    db.execute('create table metadata(key text primary key,value text)')
    db.execute('insert into metadata values (?,?)', ('status', 'running'))
    db.commit()
    stack = [root]
    last = time.monotonic()
    def error(path, op, exc):
        summary['errors'] += 1
        db.execute('insert into errors values (?,?,?)', (path, op, str(exc)))
    try:
        check()
        while stack:
            directory = stack.pop()
            check()  # stop if volume disappeared or drive letter was reused
            try:
                with os.scandir(directory) as entries:
                    summary['directories'] += 1
                    for entry in entries:
                        if excluded_file(entry.name):
                            summary['excluded_secret_files'] += 1
                            continue
                        try:
                            st = entry.stat(follow_symlinks=False)
                            attrs = getattr(st, 'st_file_attributes', 0)
                            if attrs & 0x400 or stat.S_ISLNK(st.st_mode):
                                summary['reparse_skipped'] += 1
                                continue
                            if stat.S_ISDIR(st.st_mode):
                                if entry.name.lower() in EXCLUDED_DIRS:
                                    summary['excluded_directories'] += 1
                                else:
                                    stack.append(entry.path)
                                continue
                            if not stat.S_ISREG(st.st_mode):
                                continue
                            rel = os.path.relpath(entry.path, root)
                            cat = classification(entry.name, st.st_size)
                            db.execute('insert into files values (?,?,?,?,?,?,?)',
                                       (rel, st.st_size, str(st.st_mtime_ns), str(st.st_ctime_ns),
                                        str(st.st_ino or os.stat(entry.path, follow_symlinks=False).st_ino), attrs, cat))
                            summary['files'] += 1
                            summary['bytes'] += st.st_size
                            for group, key in ((groups, cat), (extensions, Path(entry.name).suffix.lower() or '[no extension]'),
                                               (top, rel.split(os.sep)[0] if os.sep in rel else '[root files]')):
                                group[key][0] += 1
                                group[key][1] += st.st_size
                            if summary['files'] % 2000 == 0:
                                db.commit()
                        except OSError as exc:
                            error(entry.path, 'stat', exc)
            except OSError as exc:
                error(directory, 'scandir', exc)
                if directory == root:
                    raise
            if progress:
                progress(summary)
            if time.monotonic() - last > 10:
                print(f"{root}: {summary['files']:,} files, {summary['bytes']/1e9:.1f} GB, {summary['errors']} errors", flush=True)
                last = time.monotonic()
        check()
        summary['status'] = 'complete_with_errors' if summary['errors'] else 'complete'
    except (Exception, KeyboardInterrupt) as exc:
        summary['status'] = 'interrupted'
        error(root, 'scan stopped', exc)
    finally:
        summary.update(finished_utc=utc(), categories=dict(groups),
                       extensions=dict(sorted(extensions.items(), key=lambda x: -x[1][1])),
                       top_level=dict(sorted(top.items(), key=lambda x: -x[1][1])))
        db.execute('update metadata set value=? where key=?', (summary['status'], 'status'))
        db.execute('insert into metadata values (?,?)', ('summary', json.dumps(summary, ensure_ascii=False)))
        db.commit()
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    registry = json.loads(Path(__file__).with_name('disks.json').read_text(encoding='utf-8'))
    parser.add_argument('--disk', choices=registry, required=True)
    args = parser.parse_args()
    record = registry[args.disk]
    root, physical = discover_disk(record)
    expected_serial = record['volume_serial']
    expected_size = record['volume_bytes']
    def check():
        current = volume(root)
        if current[0] != expected_serial or shutil.disk_usage(root).total != expected_size:
            raise RuntimeError(f'Unexpected volume at {root}; scan refused')
        return current
    identity = check()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output = Path(__file__).resolve().parents[1] / 'Каталог дисков' / f'{args.disk}_{expected_serial}_{stamp}'
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(output / 'inventory.sqlite') as db:
        result = inventory(root, db, check)
        result['identity'] = {'disk_id': args.disk, 'physical_at_scan': physical, 'volume_serial': identity[0], 'label': identity[1], 'filesystem': identity[2],
                              'expected_volume_bytes': expected_size}
        db.execute('insert into metadata values (?,?)', ('identity', json.dumps(result['identity'], ensure_ascii=False)))
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), **result}, ensure_ascii=False, indent=2), flush=True)
    return 0 if result['status'] == 'complete' else 2

if __name__ == '__main__':
    sys.exit(main())
