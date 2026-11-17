"""«Задания на копирование»: запуск без экрана - .cmd очереди заданий, hashbase.py отдельным процессом, число «Можно
перенести», повтор копирования (service.retry_copy_task). Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import re
import subprocess
from pathlib import Path

import commands_page as cpg
import service as sv


def queue_cmd(dirs, path):
    """Один .cmd, который запускает задания друг за другом в одном окне консоли (call ждёт конца каждого)."""
    lines = ['@echo off', 'chcp 65001 >nul', 'title Задания по очереди',
             f'echo Задания по очереди: {len(dirs)}. Каждое спросит «да» в начале и Enter в конце.', 'echo.']
    for i, d in enumerate(dirs, 1):
        lines += [f'echo [{i} из {len(dirs)}] {Path(d).name}', f'call "{Path(d) / "Запустить.cmd"}"', 'echo.']
    lines += ['echo Очередь закончена.', 'pause']
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-8'))
    return path


def run_hb(*args, timeout=3600):
    """hashbase.py отдельным процессом (как раздел «Команды»): (код выхода, весь вывод)."""
    p = subprocess.run([cpg.python_exe(), '-X', 'utf8', '-u', str(cpg.SCRIPT), *args], cwd=str(cpg.CAT.parent),
                       env=cpg.child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return p.returncode, p.stdout.decode('utf-8', errors='replace')


def can_move(text):
    m = re.search(r'Можно перенести: ([\d ]+) файлов', text)
    return int(m.group(1).replace(' ', '')) if m else 0


def _retry(task):
    try:
        return sv.retry_copy_task(task)
    except sv.Refused as e:
        return str(e)
