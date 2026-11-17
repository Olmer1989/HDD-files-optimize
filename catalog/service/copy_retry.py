"""Логика v3, этап 3: «Повторить копирование» остального (после «Переместить скопированное»).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import io
import os
import shutil
import time

from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import Refused, SEP
from .jobs import running_scripts, task_state
from .razbor_plan import _task_meta, _write_json


# ---------- логика v3, этап 3: «Повторить копирование» остального (после «Переместить скопированное») ----------
# Старое задание не перезапускается: после переноса скопированной части его строки дали бы «нет источника».
# Создаётся новое задание «<задание> — повтор N» только из пар (цель, путь), у которых последний результат по журналам
# исходного задания и всех прежних повторов - не «скопирован…» и не «уже есть». Ничего не копирует и не запускает.

RETRY_WORD = ' — повтор'


def _copy_group(name):
    """Исходное задание разбора и все его повторы -> (папка исходного, разбор.json исходного, [папки повторов])."""
    t = hb.TASKS / name
    meta = _task_meta(t)
    if not meta:
        raise Refused(f'«{name}» - не задание разбора (нет разбор.json).')
    if meta.get('повтор'):
        t = hb.TASKS / meta['повтор']
        meta = _task_meta(t)
        if not meta:
            raise Refused(f'Нет исходного задания «{t.name}».')
    retries = []
    if hb.TASKS.exists():
        for d in sorted(p for p in hb.TASKS.iterdir() if p.is_dir()):
            m = _task_meta(d) if (d / 'разбор.json').exists() else None
            if m and m.get('повтор') == t.name:
                retries.append(d)
    return t, meta, retries


def copy_left(name):
    """Что не скопировано: [(строка списка.tsv исходного задания)], по паре (цель, путь) и последнему результату."""
    t, _meta, retries = _copy_group(name)
    last = {}
    logs = []
    for d in [t] + retries:
        logs += [(hb.log_time(x), x) for x in d.glob('Журнал копирования *.tsv')]
    for _w, log in sorted(logs, key=lambda x: (x[0], x[1].name)):
        rows = hb.read_tsv(log)
        head = [h.strip().lower() for h in rows[0]] if rows else []
        if not all(x in head for x in ('цель', 'результат', 'источник')):
            continue
        i_t, i_r, i_s = head.index('цель'), head.index('результат'), head.index('источник')
        for f in rows[1:]:
            if len(f) > max(i_t, i_r, i_s):
                last[(f[i_t].strip(), hb.rel_of(f[i_s])[1])] = f[i_r]
    sub = ''
    vols = [f for f in hb.read_tsv(t / 'тома.tsv') if len(f) >= 2]
    if vols and len(vols[0]) >= 3:
        sub = vols[0][2].strip(SEP)                      # подпапка источника: пробелы - часть имени (этап 16)
    res = []
    for f in hb.read_tsv(t / 'список.tsv'):
        if len(f) < 3 or not f[0].strip():
            continue
        key = (f[0].strip(), (sub + SEP + f[1]) if sub else f[1])
        r = last.get(key, '')
        if not hb.copy_ok(r):
            res.append(f)
    return res


def retry_copy_task(name):
    """«Повторить копирование»: новое задание из того, что не скопировано. -> dict(task, files, bytes)."""
    t, meta, retries = _copy_group(name)
    running = running_scripts()
    for d in [t] + retries:
        st = task_state(d, running)
        if st and st['state'] == 'идёт':
            raise Refused(f'Задание «{d.name}» сейчас идёт - дождитесь конца.')
    rows = copy_left(t.name)
    if not rows:
        raise Refused(f'В задании «{t.name}» всё скопировано - повторять нечего.')
    n = len(retries) + 1
    while (hb.TASKS / f'{t.name}{RETRY_WORD} {n}').exists():
        n += 1
    new = f'{t.name}{RETRY_WORD} {n}'
    hb.RAZBORY.mkdir(parents=True, exist_ok=True)
    stage = hb.RAZBORY / (new + '.tmp')
    if stage.exists():
        raise Refused(f'Осталась папка прошлой попытки: {stage}. Уберите её и повторите.')
    stage.mkdir()
    with io.open(stage / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write('\t'.join(r) + '\n')
    shutil.copy2(t / 'тома.tsv', stage / 'тома.tsv')
    hb.copy_template(hb.TEMPLATE, stage, 'Копировать.ps1')      # главный, Запустить.cmd и части (шаблон 2.8)
    _write_json(stage / 'разбор.json', dict(meta, повтор=t.name, **{'дата повтора': time.strftime('%d.%m.%Y %H:%M')}))
    os.replace(stage, hb.TASKS / new)
    size = 0
    for r in rows:
        try:
            size += int(r[2])
        except (IndexError, ValueError):
            pass
    return dict(task=hb.TASKS / new, files=len(rows), bytes=size)
