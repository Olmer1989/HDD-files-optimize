"""Задания: честное состояние, список заданий, отметка «переместить после копирования».

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import subprocess
import time
from pathlib import Path

from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import Refused


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
