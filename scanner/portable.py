"""Offline Windows worker. Only reads archive disks; writes local results."""
import argparse
from contextlib import contextmanager, closing
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from inventory import inventory, volume, discover_disk, MEDIA, MIN_BYTES, EXCLUDED_DIRS
from build_selection import select
from hash_files import hash_one, signature

VERSION = '1.0.0'
POLICY = {'algorithm': 'sha256', 'min_bytes': MIN_BYTES,
          'media_extensions': sorted(MEDIA), 'excluded_dirs': sorted(EXCLUDED_DIRS)}

def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

@contextmanager
def awake():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    if not kernel.SetThreadExecutionState(0x80000001):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(0x80000000)

@contextmanager
def lock(path):
    # Windows byte lock is released by the OS even after a crash.
    import msvcrt
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('This job is already running')
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

def inspect(letter):
    letter = letter.rstrip(':\\').upper()
    if not re.fullmatch('[A-Z]', letter):
        raise ValueError('Expected one drive letter')
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               f"$p=Get-Partition -DriveLetter '{letter}'; $d=Get-Disk -Number $p.DiskNumber; "
               "[pscustomobject]@{hardware_serial=([string]$d.SerialNumber).Trim(); "
               "physical_bytes=$d.Size; model=[string]$d.FriendlyName} | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            check=True, capture_output=True, encoding='utf-8-sig')
    record = json.loads(result.stdout)
    root = letter + ':\\'
    serial, label, filesystem = volume(root)
    record.update(volume_serial=serial, volume_bytes=shutil.disk_usage(root).total,
                  label_at_registration=label, filesystem=filesystem)
    if not record['hardware_serial']:
        raise RuntimeError('No hardware serial: manual identification required')
    return record

def safe_relative(rel):
    p = PureWindowsPath(rel)
    if not p.parts or p.is_absolute() or p.drive or any(x in ('.', '..') or ':' in x for x in p.parts):
        raise ValueError('Unsafe relative path')
    return p.parts

def process(job):
    manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION or manifest['policy'] != POLICY:
        raise RuntimeError('Different scan policy; use the original worker version')
    disk_id, record = manifest['disk_id'], manifest['record']
    root, physical = discover_disk(record)
    require_separate_output(job, root)
    def check():
        if volume(root)[0] != record['volume_serial'] or shutil.disk_usage(root).total != record['volume_bytes']:
            raise RuntimeError('Source disconnected or replaced')
    with lock(job / 'worker.lock'), awake():
        check()
        inv = job / 'inventory.sqlite'
        if not inv.exists() or not manifest.get('inventory_finished'):
            # An interrupted metadata pass is rebuilt; hashes are never discarded.
            if inv.exists():
                inv.rename(job / ('inventory_interrupted_' + uuid.uuid4().hex + '.sqlite'))
            with closing(sqlite3.connect(inv)) as db:
                summary = inventory(root, db, check)
            write_json(job / 'inventory_summary.json', summary)
            if summary['status'] not in ('complete', 'complete_with_errors'):
                raise RuntimeError('Inventory interrupted; resume this job')
            manifest['inventory_finished'] = True
            write_json(job / 'job.json', manifest)
        else:
            summary = json.loads((job / 'inventory_summary.json').read_text(encoding='utf-8'))
        with closing(sqlite3.connect(inv.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(job / 'hashes.sqlite')) as target:
            target.execute('create table if not exists hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,status text,error text,primary key(disk_id,path))')
            # Selection uses precisely the same function as the main project.
            rows = [(p, s, m, i) for p, s, m, i in source.execute('select path,size,mtime_ns,file_id from files order by size,path') if select(p, s)]
            total = sum(r[1] for r in rows)
            cached = hashed = finished = read = 0
            started = last = time.monotonic()
            report = {'disk_id': disk_id, 'status': 'running', 'selected_files': len(rows),
                      'selected_bytes': total, 'inventory_errors': summary['errors'], 'physical': physical}
            write_json(job / 'result.json', report)
            def progress(count=0, force=False):
                nonlocal last
                now = time.monotonic()
                if force or now - last >= 10:
                    print(f'{disk_id}: reused={cached:,}; new={hashed:,}; processed={(finished+count)/1e9:.2f}/{total/1e9:.2f} GB; newly read={(read+count)/1e9:.2f} GB', flush=True)
                    last = now
            try:
                for rel, size, mtime, file_id in rows:
                    path = Path(root).joinpath(*safe_relative(rel))
                    expected = size, str(mtime), str(file_id)
                    check()
                    old = target.execute('select size,mtime_ns,file_id,status from hashes where disk_id=? and path=?', (disk_id, rel)).fetchone()
                    current = signature(path.stat())
                    if old == (*expected, 'verified') and current[:2] == expected[:2] and (expected[2] == '0' or current[2] == expected[2]):
                        cached += 1
                        finished += size
                        progress()
                        continue
                    try:
                        digest = hash_one(path, expected, progress)
                        check()
                    except (OSError, RuntimeError) as exc:
                        target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, None, 'error', str(exc)))
                        target.commit()
                        raise
                    target.execute('insert or replace into hashes values (?,?,?,?,?,?,?,?)', (disk_id, rel, *expected, digest, 'verified', ''))
                    target.commit()
                    hashed += 1; finished += size; read += size
                    progress()
                report['status'] = 'complete_with_inventory_errors' if summary['errors'] else 'complete'
            except KeyboardInterrupt:
                report.update(status='interrupted', error='Stopped by user')
            except (OSError, RuntimeError) as exc:
                report.update(status='error', error=str(exc))
            finally:
                report.update(hashed_files=hashed, cached_files=cached, newly_read_bytes=read,
                              seconds=round(time.monotonic()-started, 2))
                write_json(job / 'result.json', report)
                progress(force=True)
                print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['status'].startswith('complete') else 2

def require_separate_output(job, root):
    if job.resolve().drive.upper() == Path(root).drive.upper():
        raise RuntimeError('Results must not be stored on the source volume')

def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def export(job, destination):
    with lock(job / 'worker.lock'):
        result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        if not result['status'].startswith('complete'):
            raise RuntimeError('Only completed jobs can be exported')
        names = ['job.json', 'result.json', 'inventory_summary.json', 'inventory.sqlite', 'hashes.sqlite']
        folder = destination / job.name
        folder.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for name in names:
            original = checksum(job / name)
            shutil.copy2(job / name, folder / name)
            hashes[name] = checksum(folder / name)
            if hashes[name] != original:
                raise RuntimeError('Export copy checksum mismatch: ' + name)
        write_json(folder / 'checksums.json', hashes)
        print('Exported:', folder)

def import_result(folder, destination):
    allowed = {'job.json', 'result.json', 'inventory_summary.json', 'inventory.sqlite', 'hashes.sqlite'}
    hashes = json.loads((folder / 'checksums.json').read_text(encoding='utf-8'))
    if set(hashes) != allowed:
        raise ValueError('Unexpected export file list')
    for name, digest in hashes.items():
        if checksum(folder / name) != digest:
            raise ValueError('Transfer checksum mismatch: ' + name)
    manifest = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    if not re.fullmatch('HDD[0-9]{2,}', manifest['disk_id']):
        raise ValueError('Invalid disk ID')
    # Keep imports separate; never overwrite a local registry or existing scan.
    output = destination / (manifest['disk_id'] + '_' + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    for name in [*allowed, 'checksums.json']:
        shutil.copy2(folder / name, output / name)
    for name, digest in hashes.items():
        if checksum(output / name) != digest:
            raise ValueError('Imported copy checksum mismatch: ' + name)
    print('Imported for review (registry unchanged):', output)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start')
    start.add_argument('--disk', required=True)
    start.add_argument('--letter', required=True)
    start.add_argument('--output', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.')) / 'HDDScanner' / 'results')
    resume = sub.add_parser('resume'); resume.add_argument('job', type=Path)
    exp = sub.add_parser('export'); exp.add_argument('job', type=Path); exp.add_argument('destination', type=Path)
    imp = sub.add_parser('import'); imp.add_argument('folder', type=Path); imp.add_argument('destination', type=Path)
    if len(sys.argv) == 1:
        print('HDD Scanner ' + VERSION)
        print('1 - New disk scan\n2 - Resume\n3 - Export to USB\n4 - Import on main PC')
        choice = input('Choose 1-4: ').strip()
        def ask(prompt):
            return input(prompt).strip().strip('"')
        if choice == '1':
            values = ['start', '--disk', ask('Central disk ID (HDD03 etc): '), '--letter', ask('Source drive letter: ')]
        elif choice == '2':
            values = ['resume', ask('Local JOB folder path: ')]
        elif choice == '3':
            values = ['export', ask('Local JOB folder path: '), ask('USB destination folder: ')]
        elif choice == '4':
            values = ['import', ask('Exported JOB folder on USB: '), ask('Local import destination folder: ')]
        else:
            return 1
        args = parser.parse_args(values)
    else:
        args = parser.parse_args()
    if args.command == 'start':
        if not re.fullmatch('HDD[0-9]{2,}', args.disk) or int(args.disk[3:]) < 3:
            parser.error('Assign a new central disk ID, HDD03 or higher; HDD01/02 already exist')
        record = inspect(args.letter)
        output = args.output.resolve()
        if output.drive.upper() == args.letter.rstrip(':\\').upper() + ':':
            parser.error('Output must not be on source volume')
        print(json.dumps({'disk_id': args.disk, **record}, ensure_ascii=False, indent=2))
        if input('Check central disk ID and device. Type YES to scan: ').strip() != 'YES':
            return 1
        job = output / (args.disk + '_' + uuid.uuid4().hex)
        job.mkdir(parents=True, exist_ok=False)
        write_json(job / 'job.json', {'version': VERSION, 'job_id': job.name, 'disk_id': args.disk,
                    'record': record, 'policy': POLICY, 'created_utc': datetime.now(timezone.utc).isoformat()})
        print('JOB (save this path for resume/export):', job, flush=True)
        return process(job)
    if args.command == 'resume':
        return process(args.job.resolve())
    if args.command == 'export':
        export(args.job.resolve(), args.destination.resolve())
    else:
        import_result(args.folder.resolve(), args.destination.resolve())
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('STOP:', exc, file=sys.stderr)
        sys.exit(2)
