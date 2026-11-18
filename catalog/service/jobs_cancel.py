"""Отмена заданий копирования (вкладка «Копирование», кнопка «Отменить задание…»; утверждено владельцем 18.11.2026).

Отменить - перенести папку задания в «Запускаемые скрипты\\_Отменённые» (в пределах того же диска) и дописать строку
в «отменённые задания.tsv». Ничего не удаляется; файлы на дисках не трогаются: уже скопированное остаётся на архивном
диске и учитывается базой (paths.journal_paths читает журналы и из «_Отменённые»). Без Qt."""
import os
import subprocess
import time
from pathlib import Path

from hb_core import api as hb

from .jobs import task_state

CANCEL_DIR = '_Отменённые'
CANCEL_LOG = 'отменённые задания.tsv'
CANCEL_HEAD = ('Дата', 'Задание', 'Новая папка', 'Состояние', 'Сделано из всего')
CANCEL_STATES = ('не запускалось', 'прервано', 'готово с ошибками')
QUEUE_FILE = 'очередь заданий.cmd'
BUSY_WHY = 'папка занята — закройте окно задания (PowerShell) и повторите'


def can_cancel(row):
    """Можно ли отменить задание (строку списка заданий): только копирование, не идущее и не готовое. -> причина или ''."""
    if row.get('kind') != 'копирование':
        return 'перемещение не отменяется'
    if row.get('state') == 'идёт':
        return 'идёт — сначала остановите (Q)'
    if row.get('state') not in CANCEL_STATES:
        return f'состояние «{row.get("state")}» — отменять нельзя'
    return ''


def running_lines():
    """Командные строки запущенных PowerShell и cmd (окно задания и очередь заданий .cmd). None - узнать не удалось."""
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe' or Name='cmd.exe'\" | "
                            "ForEach-Object CommandLine"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return [x for x in r.stdout.decode('utf-8', errors='replace').splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        return None


def in_running_queue(task, running, queue=None):
    """Задание стоит в очереди заданий (.cmd), которая сейчас работает?"""
    queue = Path(queue or hb.BASE_DIR / QUEUE_FILE)
    if not queue.exists() or not any(str(queue).lower() in x.lower() for x in running):
        return False
    try:
        text = queue.read_bytes().decode('utf-8', errors='replace').lower()
    except OSError:
        return True                          # очередь работает, а прочесть её нельзя - лучше не трогать
    return str(Path(task) / 'Запустить.cmd').lower() in text


def _move(src, dest_root):
    """os.rename в dest_root; имя занято - « (2)», « (3)»… -> новая папка. PermissionError/OSError - наружу."""
    dest_root.mkdir(parents=True, exist_ok=True)
    for i in range(1, 1000):
        dst = dest_root / (src.name if i == 1 else f'{src.name} ({i})')
        if dst.exists():
            continue
        try:
            os.rename(src, dst)
            return dst
        except FileExistsError:
            continue                         # появилась между проверкой и переносом - следующее имя
    raise OSError(f'нет свободного имени в «{dest_root}»')


def _log(dest_root, name, dst, st):
    """Строка в «отменённые задания.tsv» (UTF-8, заголовок при создании). -> '' или текст предупреждения."""
    path = dest_root / CANCEL_LOG
    row = (time.strftime('%d.%m.%Y %H:%M:%S'), name, str(dst), st['state'], f'{st["done"]} из {st["total"]}')
    try:
        new = not path.exists()
        with open(path, 'a', encoding='utf-8', newline='') as f:
            if new:
                f.write('\t'.join(CANCEL_HEAD) + '\r\n')
            f.write('\t'.join(row) + '\r\n')
        return ''
    except OSError as e:
        return f'папка перенесена, но строка в «{CANCEL_LOG}» не записана: {e}'


def cancel_tasks(names, root=None, running='спросить', queue=None):
    """Отменить задания по именам папок. Перед каждым переносом заново - идёт ли оно и не стоит ли в работающей
    очереди. -> [dict(task, ok, dest, reason, warn)] по каждому заданию."""
    root = Path(root or hb.TASKS)
    dest_root = root / CANCEL_DIR
    res = []
    for name in names:
        item = dict(task=name, ok=False, dest='', reason='', warn='')
        res.append(item)
        src = root / name
        now = running_lines() if running == 'спросить' else running
        st = task_state(src, now) if src.is_dir() and not name.startswith('_') else None
        if not st:
            item['reason'] = 'нет такой папки задания'
            continue
        if now is None:
            item['reason'] = 'не удалось узнать, идёт ли задание — нажмите «Обновить» и повторите'
            continue
        why = can_cancel(st)
        if not why and in_running_queue(src, now, queue):
            why = 'стоит в очереди, которая сейчас работает'
        if why:
            item['reason'] = why
            continue
        try:
            dst = _move(src, dest_root)
        except OSError as e:
            item['reason'] = f'{BUSY_WHY} ({e})'
            continue
        item.update(ok=True, dest=str(dst), warn=_log(dest_root, name, dst, st))
    return res
