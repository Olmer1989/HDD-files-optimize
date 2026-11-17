"""Пересканирование выбранных папок (сканер 1.4.0+): план, запуск, ход, итог.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os
import subprocess
import sys
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import Refused, ro
from .read_disks import volumes


# ---------- пересканирование выбранных папок (сканер 1.4.0) ----------

SCANNER = Path(__file__).resolve().parent.parent.parent / 'scanner'   # service/rescan_run.py: на уровень глубже


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


def rescan_confirmed(disk, folders):
    """{путь: степень} файлов носителя в этих папках с подтверждённым хешем в базе (S или C) - для предупреждения
    окна: у невыбранного типа без годного прежнего хеша сканера подтверждение после приёма скана пропадёт."""
    c = ro()
    try:
        res = {}
        for f in folders:
            cond, args = hb.prefix_cond('path', f)
            res.update(c.execute(f"select path, ev from files where disk=? and ev in (?, ?) and {cond}",
                                 [disk, hb.EV_SCAN, hb.EV_COPY] + args).fetchall())
        return res
    finally:
        c.close()


def rescan_files(disk):
    """Файлы хода и остановки сканирования - в «_БАЗА\\пересканирование»."""
    d = hb.BASE_DIR / 'пересканирование'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{disk} ход.json', d / f'{disk} стоп.txt', d / f'{disk} вывод.txt'


def scanner_python():
    exe = Path(sys.executable)
    return str(exe.with_name('python.exe')) if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists() else str(exe)


def rescan_argv(disk, letter, folders, rehash_all=False, job=None, cats=None):
    """Командная строка сканера (то же можно запустить вручную в консоли). job - продолжить это задание (выбор типов
    берётся из задания). cats - типы файлов для хеша (hb.COPY_CATS); None или все - хеш у всех файлов, как раньше."""
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
    import hash_types
    types = hash_types.scanner_args(hash_types.ALL if cats is None else cats)   # одно правило с «что копировать»
    return argv + (types or ['--hash-all-types']) + (['--rehash-all'] if rehash_all else [])   # все типы - явно


def rescan_start(disk, letter, folders, rehash_all=False, job=None, cats=None):
    """Запуск сканера отдельным процессом без консоли - ТОЛЬКО по кнопке владельца после подтверждения."""
    progress, stop, log = rescan_files(disk)
    for p in (progress, stop):
        if p.exists():
            p.unlink()
    out = open(log, 'a' if job else 'w', encoding='utf-8')
    env = os.environ.copy()
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    proc = subprocess.Popen(rescan_argv(disk, letter, folders, rehash_all, job, cats), cwd=str(SCANNER), env=env,
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
    pj = next((x for x in hb.find_partials() if x['name'] == job_name), None)
    if pj:                                    # итог сканера: прочитано заново / взято из прежнего скана (с даты)
        lines.append(_scanner()[0].summary_text(pj['info']))
    for f, k in (stats or {}).items():
        became = sum(v for key, v in k.items() if key.startswith('было ') and key != 'было S')
        lines.append(f'{f}: в скане {k.get("файлов", 0)} файлов ({hb.gb(k.get("байт", 0))} ГБ); стало S {became}'
                     f' (уже было S {k.get("было S", 0)}); '
                     f'новые {k.get("новые", 0)}; исчезли из базы {k.get("исчезли", 0)}; хеш не совпал {k.get("хеш не совпал", 0)}')
    return dict(accepted=stats is not None, lines=lines, warn=warn)
