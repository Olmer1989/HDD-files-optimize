"""Общее для «Я сделал в Проводнике»: константы, исключения описи, помощники путей и текста, диск."""
import ctypes
import os
import sys
import time
from pathlib import Path

from hb_core import api as hb
import service as sv


SEP = '\\'
BIG_FOLDER = 300000          # папка с таким числом файлов по базе по умолчанию не отмечена: обход долгий
CHILDREN_MAX = 2000          # папку-единицу с большим числом файлов нельзя раскрыть до файлов
UNITS_MAX = 5000             # больше единиц в окне не показываем (и не записываем): сузьте область

try:                         # те же правила пропуска, что у описи
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scanner'))
    from inventory import EXCLUDED_DIRS, excluded_file          # noqa: E402
except Exception:                                               # noqa: BLE001
    EXCLUDED_DIRS = {'$recycle.bin', 'system volume information', 'node_modules', '.git', '.svn', '__pycache__',
                     '.venv', 'venv', '$windows.~bt', 'recycler', '.trashes', '.fseventsd'}

    def excluded_file(name):
        n = name.lower()
        return n == '.env' or n.startswith('.env.') or n.endswith('.env')


class Stopped(Exception):
    """Владелец остановил проверку: результат не используется."""


def key(path):
    return path.lower()


def parent(path):
    return path.rsplit(SEP, 1)[0] if SEP in path else ''


def ancestors(path):
    """'a\\b\\c' -> ['a\\b', 'a'] (без корня)."""
    res = []
    p = parent(path)
    while p:
        res.append(p)
        p = parent(p)
    return res


def under(path_k, keys):
    """Лежит ли путь (ключ) внутри одного из мест (ключи) или совпадает с ним."""
    return any(path_k == k or path_k.startswith(k + SEP) for k in keys)


def plural(n, one, few, many):
    n10, n100 = n % 10, n % 100
    w = one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many
    return f'{n:,} {w}'.replace(',', ' ')


def gb_text(b):
    return f'{(b or 0) / hb.GIB:,.2f} ГБ'.replace(',', ' ').replace('.', ',')


def when_text(t):
    return time.strftime('%d.%m.%Y %H:%M', time.localtime(t)) if t else ''


# ---------- диск ----------

def volume_serial(root):
    ser = ctypes.c_ulong()
    if not ctypes.windll.kernel32.GetVolumeInformationW(str(root), None, 0, ctypes.byref(ser), None, None, None, 0):
        return None
    return f'{ser.value:08X}'


def disk_root(disk):
    """Корень подключённого носителя 'F:\\' и серийный номер его тома. sv.Refused - если не подключён."""
    root = sv.disk_letter(disk) + SEP
    return root, volume_serial(root)


def top_folders(disk, root=None):
    """Папки верхнего уровня для выбора: по базе (число файлов) и по диску (новые помечены).
    Первая строка - файлы в корне диска (path=''). checked - отмечать ли по умолчанию."""
    base = {r['path'].lower(): r for r in sv.folder_children(disk)}
    excl = {x.lower() for x in hb.read_exclusions().get(disk, [])}
    res, seen = [], set()
    on_disk = {}
    if root:
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False) and e.name.lower() not in EXCLUDED_DIRS \
                                and not e.stat(follow_symlinks=False).st_file_attributes & 0x400:
                            on_disk[e.name.lower()] = e.name
                    except OSError:
                        pass
        except OSError:
            pass
    for k, r in base.items():
        if k in excl:
            continue
        res.append(dict(path=r['path'], files=r['files'], gib=r['gib'], on_disk=k in on_disk if root else None,
                        new=False, checked=r['files'] < BIG_FOLDER))
        seen.add(k)
    for k, name in on_disk.items():
        if k not in seen and k not in excl:
            res.append(dict(path=name, files=0, gib=0, on_disk=True, new=True, checked=True))
    res.sort(key=lambda r: r['path'].lower())
    res.insert(0, dict(path='', files=None, gib=None, on_disk=True, new=False, checked=True))
    return res
