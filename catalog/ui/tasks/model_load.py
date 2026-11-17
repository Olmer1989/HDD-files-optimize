"""«Задания на копирование»: строки таблицы - состояние (service) + ход по журналам, диски задания (тома.tsv), названия
и буквы дисков; load_all - для окна. Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time
from pathlib import Path

import build_pilot as bp
import service as sv
from hb_core import api as hb

from .common import COPY_META, DONE, _meta, V3_META
from .texts_words import disk_long
from .model_journal import progress
from .model_move import latest_manifest_groups


def task_disks(task, serials, letters, labels=None):
    """Диски задания по тома.tsv: (подпись «HDD45 → HDD78 (L:)», серийные номера всех дисков, номер источника);
    disks_long / src_long / dst_long - то же с названиями дисков («HDD45 «Бэкап фото и видео» (G:)»)."""
    p = Path(task) / 'тома.tsv'
    vols = [f for f in hb.read_tsv(p) if len(f) >= 2] if p.exists() else []
    names, longs, sers = [], [], set()
    for f in vols:
        ser = f[1].strip().upper()
        sers.add(ser)
        name = serials.get(ser) or f[0].strip()          # физический носитель по серийному номеру
        names.append(name + (f' ({letters[ser]})' if letters.get(ser) else ''))
        longs.append(disk_long(name, letters.get(ser), labels))
    label = names[0] + (' → ' + ', '.join(names[1:]) if len(names) > 1 else ' (внутри диска)') if names else ''
    long_ = longs[0] + (' → ' + ', '.join(longs[1:]) if len(longs) > 1 else ' (внутри диска)') if longs else ''
    src = (serials.get(vols[0][1].strip().upper()) or vols[0][0].strip()) if vols else None
    src_ser = vols[0][1].strip().upper() if vols else None
    return dict(disks=label, disks_long=long_, src_long=longs[0] if longs else '', dst_long=longs[1:], serials=sers,
                src_serial=src_ser, src=src, src_letter=letters.get(src_ser, '') if src_ser else '',
                targets=[serials.get(f[1].strip().upper()) or f[0].strip() for f in vols[1:]])


_SERIALS = {'at': 0, 'map': {}}


def serial_names():
    if time.time() - _SERIALS['at'] > 300:
        try:
            _SERIALS['map'] = hb.serial_map(bp.find_jobs())
        except Exception:                                   # noqa: BLE001  - без имён дисков окно всё равно работает
            _SERIALS['map'] = {}
        _SERIALS['at'] = time.time()
    return _SERIALS['map']


_LABELS = {'at': 0, 'map': {}}


def disk_labels():
    """Названия носителей для подписей (как в «Дисках и папках»: метка, марка, объём); раз в 5 минут."""
    if time.time() - _LABELS['at'] > 300:
        try:
            from disk_ui import disk_title
            _LABELS['map'] = {r['disk']: disk_title(r) for r in sv.disks()}
        except Exception:                                   # noqa: BLE001  - без названий окно всё равно работает
            _LABELS['map'] = {}
        _LABELS['at'] = time.time()
    return _LABELS['map']


def _letters():
    try:
        return sv.volumes()
    except (OSError, AttributeError):
        return {}


def disk_letters(serials=None, letters=None):
    """Носитель -> буква подключённого тома («HDD09» -> «F:») по серийным номерам."""
    serials = serial_names() if serials is None else serials
    letters = _letters() if letters is None else letters
    return {serials[s]: l for s, l in letters.items() if s in serials and l}


def load(root=None, now=None):
    """Строки таблицы: состояние (service) + ход по журналам, диски, разбор.json / перемещение.json."""
    root = Path(root or hb.TASKS)
    rows = sv.tasks(root)
    serials = serial_names()
    labels = disk_labels()
    letters = _letters()
    for r in rows:
        d = root / r['task']
        r.update(progress(d, r['kind'], r['state'] == 'идёт', now))
        r.update(task_disks(d, serials, letters, labels))
        r['meta'] = _meta(d / COPY_META) if r['kind'] == 'копирование' else None          # задание разбора v3
        r['move_meta'] = _meta(d / V3_META) if r['kind'] == 'перемещение' else None
        r['labels'] = labels
        r['log_ts'] = Path(r['journal']).stat().st_mtime if r.get('journal') and Path(r['journal']).exists() else 0
        if r['meta'] and not r['meta'].get('повтор') and r['state'] in DONE:
            try:
                r['left'] = len(sv.copy_left(r['task']))
            except Exception:                               # noqa: BLE001
                r['left'] = r['errors'] + r['skipped']
    return rows


def load_all(root=None, now=None):
    """Для окна: строки таблицы и группы манифестов «копировать нечего»."""
    rows = load(root, now)
    try:
        groups = latest_manifest_groups()
    except OSError:
        groups = []
    if groups:
        lt = disk_letters()
        for g in groups:
            g['letter'] = lt.get(g['disk'], '')
    return rows, groups
