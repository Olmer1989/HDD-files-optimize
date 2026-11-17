"""Направления: выбор окна (галочки) и данные секции. Вынесено из directions_page.py без изменений кода."""
import json
import os
import shutil
import time

from hb_core import api as hb
import service as sv

CHOICE_NAME = 'окно - выбор направлений.json'


# ---------- выбор направлений (выбор окна, не таблица владельца) ----------

def choice_path():
    return hb.BASE_DIR / CHOICE_NAME


def load_choice():
    """Номера направлений, отмеченных галочкой (как записаны). Нет файла или он испорчен - пусто."""
    try:
        data = json.loads(choice_path().read_text(encoding='utf-8'))
        return [str(x) for x in data.get('направления', [])]
    except (OSError, ValueError, AttributeError):
        return []


def save_choice(nums):
    """Целиком и заменой файла (читатель видит старое или новое содержимое)."""
    p = choice_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps({'направления': list(nums), 'дата': time.strftime('%d.%m.%Y %H:%M')},
                              ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def chosen(dirs=None):
    """Для экрана «Разбор носителя»: отмеченные направления, которые есть сейчас и у которых есть диск, по номеру.
    -> [Direction]. Направления читаются заново: выбор хранит только номера."""
    dirs = sv.directions() if dirs is None else dirs
    want = set(load_choice())
    return [d for d in dirs.values() if d.num in want and d.disks]


# ---------- данные секции ----------

def section_data():
    """Направления, носители базы (подключённые - с буквой) и свободное место подключённых дисков направлений."""
    dirs = sv.directions()
    rows = sv.disks()
    by = {r['disk']: r for r in rows}
    free = {}
    for d in {x for v in dirs.values() for x in v.disks}:
        letter = (by.get(d) or {}).get('letter')
        if letter:
            try:
                free[d] = shutil.disk_usage(letter + '\\').free / hb.GIB
            except OSError:
                pass
    return dict(dirs=dirs, disks=rows, by=by, free=free, choice=load_choice())


