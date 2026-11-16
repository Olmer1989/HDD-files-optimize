"""Раздел окна «Задания на копирование» (15.11.2026): что сейчас идёт, ход и оценка времени по журналам, запуск отмеченных
заданий (каждое в своём окне PowerShell или по очереди в одном); перемещение папки на носителе после копирования.

Окно ничего не копирует и не перемещает само: оно открывает «Запустить.cmd» задания, а задание перемещения
создаёт командой mvlist (отдельным процессом, как раздел «Команды»). Состояние задания - service.task_state
(правила, раздел 6); здесь к нему добавляется ход: сколько файлов и ГБ, скорость, сколько осталось.
Спор с GPT - «Проверка Архитектуры сортировки файлов\\Перемещение_на_любые_диски_v1.md».

Логика v3, этап 3 (15.11.2026): заголовок «Идёт: …» - в столбик; в колонке «Диски» - номер, название и буква; под
таблицей - «Можно переместить на носителе» (по каждой скопированной папке разбора - вопрос и кнопка; при ошибках
копирования - «Переместить скопированное», затем «Повторить копирование») и «Готово» (статусы). Задание переноса
создаёт `mvlist --razbor`, повтор копирования - service.retry_copy_task. Документ - «Логика_v3_разбор_носителя.md».

Этап 9 (16.11.2026, макет владельца): плашки-сводка; таблица без готовых - галочка · «Что и куда» в две строки ·
Состояние (скорость и остаток - внутри) · Сделано · Ошибки; «Запустить отмеченные (N)», «Запустить все по очереди»;
блок «Скопировано — можно переместить папку на носителе»; «Готово (N)» свёрнутым списком. Из окна убраны старая
«Разложить на источнике…» («ПЕРЕНЕСЕНО → …», mvlist --task - остаётся в командах) и «Сводка для чата».
"""
import html
import json
import os
import re
import subprocess
import time
from pathlib import Path

import build_pilot as bp
import commands_page as cpg
from ui_common import StepsBar
import service as sv
from hb_core import api as hb

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
STATE_COLOR = {'идёт': '#1565c0', 'готово': '#2e7d32', 'готово с ошибками': '#c62828', 'прервано': '#e65100',
               'состояние неизвестно': '#6d4c41', 'не запускалось': '#455a64', 'в очереди': '#6a1b9a'}
DONE = ('готово', 'готово с ошибками')
COPY_META, V3_META = 'разбор.json', 'перемещение.json'   # логика v3: задание копирования разбора / задание переноса
MIN_BYTES, MIN_SEC = 10 * 1024 ** 2, 30          # раньше оценка времени не показывается
RED, GREY, AMBER = '#c62828', '#607d8b', '#8d6e00'
INTRO = 'Одно задание копирует одну папку носителя на диск направления. Ничего не удаляется и не перезаписывается.'
RUN_NOTE = ('Каждое задание открывается в своём окне. Остановить — клавиша Q; повторный запуск продолжит с места '
            'остановки.')
MOVE_NOTE = 'Перемещается внутри носителя, все подпапки сохраняются. Так видно, что папка уже сохранена.'
MOVE_EMPTY = 'Пока нечего: папка появится здесь, когда её копирование закончится и копии проверятся.'
BAD_STATES = ('прервано', 'готово с ошибками')        # плашка «Прервано, с ошибками»
HASH_WORD = 'SHA-256'                                 # «скопирован, размер и SHA-256 совпали» - копия проверена по хешу


def gb(b):
    return f'{b / 1024 ** 3:,.1f}'.replace(',', ' ').replace('.', ',')


def n(x):
    return f'{x:,}'.replace(',', ' ')


def fmt_eta(sec):
    """Секунды -> «~1 ч 10 мин» / «~25 мин» / «меньше минуты»."""
    if sec is None:
        return ''
    sec = max(0, int(sec))
    if sec < 60:
        return 'меньше минуты'
    h, m = divmod((sec + 59) // 60, 60)
    if h >= 48:
        return f'~{h // 24} дн {h % 24} ч'
    return f'~{h} ч {m} мин' if h else f'~{m} мин'


def fmt_ago(sec):
    sec = int(sec)
    if sec < 90:
        return f'{sec} с назад'
    return f'{sec // 60} мин назад' if sec < 7200 else f'{sec // 3600} ч назад'


# ---------- ход задания по журналам ----------

_CACHE = {}
_TIME_RE = re.compile(r'^(\d\d):(\d\d):(\d\d)$')


def _read_log(log, kind):
    """Строки журнала -> [(ключ, результат, байты, секунды от полуночи дня запуска)]; кэш по размеру и времени файла."""
    st = log.stat()
    key = (str(log), st.st_size, st.st_mtime_ns, kind)
    if key in _CACHE:
        return _CACHE[key]
    rows, prev, day = [], None, 0
    for f in hb.read_tsv(log)[1:]:
        if kind == 'копирование' and len(f) >= 7:
            k, res, size = (f[1], f[5]), f[2], f[3]
        elif kind == 'перемещение' and len(f) >= 6:
            k, res, size = f[4], f[1], f[2]
        else:
            continue
        m = _TIME_RE.match(f[0].strip())
        t = None
        if m:
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if prev is not None and t < prev:
                day += 1                                  # время в журнале - только ЧЧ:ММ:СС: переход через полночь
            prev = t
            t += day * 86400
        try:
            size = int(size)
        except ValueError:
            size = 0
        rows.append((k, res, size, t))
    _CACHE.clear() if len(_CACHE) > 200 else None
    _CACHE[key] = rows
    return rows


_DRIVE_RE = re.compile(r'^[A-Za-z]:')


def _file_key(k):
    """(диск-цель, путь источника) без буквы тома и без регистра: у повтора буква носителя могла смениться."""
    target, path = k
    return target.strip().upper(), _DRIVE_RE.sub('', path).lower()      # путь - без обрезки пробелов (этап 16)


def progress(task, kind, running=False, now=None):
    """Ход задания: обработано файлов и байт (по уникальной строке списка, последний результат), скорость
    текущего запуска, оценка оставшегося времени, примеры ошибок."""
    task, now = Path(task), now or time.time()
    lst = task / ('список.tsv' if kind == 'копирование' else 'перемещение.tsv')
    total_b = 0
    for f in hb.read_tsv(lst):
        try:
            total_b += int(f[2] if kind == 'копирование' else f[1])
        except (IndexError, ValueError):
            pass
    logs = sorted(task.glob(('Журнал копирования' if kind == 'копирование' else 'Журнал перемещения') + ' *.tsv'))
    last, cur, start = {}, [], None
    for log in logs:
        cur = _read_log(log, kind)
        for k, res, size, _t in cur:
            last[k] = (res, size)
        start = hb.log_time(log)
    ok_words = ('скопирован', 'уже есть') if kind == 'копирование' else ('перемещён', 'уже перемещён')
    done_b = sum(s for _r, s in last.values())
    errs = [f'{k[1] if isinstance(k, tuple) else k}: {r}' for k, (r, _s) in last.items()
            if not r.startswith(ok_words)][:5]
    # этап 9: сколько строк проверено по хешу (последний результат «… SHA-256 совпали» или, шаблон 2.5, «уже есть,
    # SHA-256 совпал»; простое «уже есть» - только размер)
    # и последний результат журнала (у прерванного - что было перед остановкой: причину шаблон пишет только в консоль)
    hashed_keys = frozenset(_file_key(k) for k, (r, _s) in last.items()
                            if isinstance(k, tuple) and r.startswith(('скопирован', hb.HAVE_SHA)) and HASH_WORD in r)
    last_res = cur[-1][1] if cur else ''
    res = dict(total_b=total_b, done_b=done_b, speed=None, eta=None, eta_text='', ago=None, examples=errs,
               hashed=len(hashed_keys), hashed_keys=hashed_keys, last_res=last_res)
    if not logs or start is None:
        return res
    times = [t for _k, _r, _s, t in cur if t is not None]
    t0 = time.localtime(start)
    start_sod = t0.tm_hour * 3600 + t0.tm_min * 60 + t0.tm_sec
    last_ts = start + (times[-1] - start_sod) if times else start
    if times and last_ts < start:                          # первая строка «до» старта: старт в имени - с точностью до минуты
        last_ts = start
    moved_b = sum(s for _k, r, s, _t in cur if r.startswith('скопирован' if kind == 'копирование' else 'перемещён'))
    elapsed = (now if running else last_ts) - start
    if running:
        res['ago'] = max(0, now - last_ts)
    if kind == 'копирование':
        if elapsed > 0 and moved_b > 0:
            res['speed'] = moved_b / elapsed
        if running:
            if moved_b >= MIN_BYTES and elapsed >= MIN_SEC and res['speed']:
                res['eta'] = max(0, total_b - done_b) / res['speed']
                res['eta_text'] = fmt_eta(res['eta'])
            else:
                res['eta_text'] = 'оценка появится позже'
    return res


def disk_long(disk, letter, labels):
    """«HDD17 «Samsung 750» (K:)»: номер, название диска (метка или модель, как в «Дисках и папках») и буква."""
    title = (labels or {}).get(disk, '')
    return disk + (f' «{title}»' if title else '') + (f' ({letter})' if letter else '')


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


def _meta(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else None
    except (OSError, ValueError):
        return None


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


# ---------- решения без экрана (их проверяют тесты) ----------

def summary(rows, queue=()):
    """Плашки над таблицей: [(текст, цвет или None)]. «Неизвестно» - отдельно и только если есть (не ошибка)."""
    st = [r['state'] for r in rows]
    wait = st.count('не запускалось')
    queued = sum(1 for r in rows if r['state'] == 'не запускалось' and r['task'] in queue)
    bad = sum(1 for s in st if s in BAD_STATES)
    res = [(f'Идёт: {st.count("идёт")}', '#1565c0' if 'идёт' in st else None),
           (f'Ждут запуска: {wait}' + (f' (в очереди {queued})' if queued else ''), None),
           (f'Прервано, с ошибками: {bad}', RED if bad else None),
           (f'Готово: {st.count("готово")}', '#2e7d32' if 'готово' in st else None)]
    unknown = st.count('состояние неизвестно')
    if unknown:
        res.append((f'Неизвестно: {unknown}', GREY))
    return res


def _loc(letter, disk, rel):
    """«F:\\Котуй 2026»; носитель не подключён - «HDD09\\Котуй 2026»; файлы в корне - «F:\\»."""
    base = letter or disk or '?'
    return base + '\\' + (rel or '')


def _where(letter, folder):
    """Папка носителя для «Что и куда»: «F:\\Котуй 2026», «Котуй 2026», «F:\\ (файлы в корне)», «(файлы в корне)»."""
    if not folder:                                           # None и '' - файлы в корне носителя
        return (letter + '\\ ' if letter else '') + '(файлы в корне)'
    return _loc(letter, '', folder) if letter else folder


def _target_words(meta, targets):
    """«Работа и Сафари — HDD78»; у направления на двух дисках задание на один - «Семейный архив — на 45 (HDD45)»."""
    name = meta.get('имя направления') or ''
    tg = list(meta.get('цели') or targets or [])
    req = meta.get('обязательные диски') or []
    if len(req) > 1 and len(tg) == 1:
        return f'{name} — на {_num(tg[0])} ({tg[0]})'
    return f'{name} — {", ".join(tg)}' if name else ', '.join(tg)


def what_where(r):
    """«Что и куда» в две строки: («HDD09 · F:\\Котуй 2026», «→ Работа и Сафари — HDD78»)."""
    m, mm = r.get('meta'), r.get('move_meta')
    src = r.get('src') or (m or {}).get('носитель') or ''
    letter = r.get('src_letter') or ''
    if m:
        where = _where(letter, m.get('папка'))
        tail = ' (повтор не скопированного)' if m.get('повтор') else ''
        return f'{src} · {where}', f'→ {_target_words(m, r.get("targets"))}{tail}'
    if mm:
        where = _where(letter, mm.get('папка'))
        return f'{src} · {where}', f'→ перемещение внутри носителя в «{mm.get("куда", "Скопировано на …")}»'
    return r['task'], '→ ' + (r.get('disks') or 'диски не указаны')


def state_text(r, queue=()):
    """Столбец «Состояние»: (текст, цвет). У идущего - скорость и остаток; у прерванного - последняя запись журнала."""
    s = r['state']
    if s == 'идёт':
        parts = ['Идёт']
        sp = r.get('speed')
        if sp:
            parts.append((f'{sp / 1024 ** 2:,.0f} МБ/с' if sp >= 10 * 1024 ** 2 else
                          f'{sp / 1024 ** 2:.1f} МБ/с').replace(',', ' ').replace('.', ','))
        eta = r.get('eta_text') or ''
        if eta:
            parts.append(('осталось ' + eta.lstrip('~')) if r.get('eta') is not None else eta)
        text = ' · '.join(parts)
        if r.get('ago') is not None and r['ago'] > 120:
            text += f' · последняя запись {fmt_ago(r["ago"])}: идёт большой файл или диск завис'
        return text, STATE_COLOR['идёт']
    if s == 'не запускалось':
        return ('В очереди', STATE_COLOR['в очереди']) if r['task'] in queue else ('Ждёт запуска', STATE_COLOR[s])
    if s == 'прервано':
        last = r.get('last_res') or ''
        ok = last.startswith(('скопирован', 'уже есть', 'перемещён', 'уже перемещён'))
        return ('Прервано' + (f' · последняя запись: {last[:80]}' if last and not ok else
                              ' · повторный запуск продолжит'), STATE_COLOR[s])
    if s == 'состояние неизвестно':
        return 'Неизвестно, идёт ли (не удалось узнать) — нажмите «Обновить»', STATE_COLOR[s]
    if s == 'готово с ошибками':
        return f'Готово с ошибками: не сделано {n(r["errors"] + r["skipped"])}', STATE_COLOR[s]
    return s.capitalize(), STATE_COLOR.get(s)


def errors_tip(r):
    lines = [f'ошибок (ОШИБКА, КОНФЛИКТ): {n(r["errors"])}', f'не сделано по другим причинам: {n(r["skipped"])}']
    return '\n'.join(lines + (r.get('examples') or []))


def checkable(r):
    """Галочку можно ставить всем, кроме идущего, неизвестного (может уже идти) и «готово с ошибками» задания разбора,
    которое можно перемещать на носителе (для него в блоке ниже - «Повторить копирование»: старое задание после переноса
    дало бы «нет источника»). Если источник - диск направления, блока нет: повтор - самим заданием (галочка)."""
    if r['state'] in ('идёт', 'состояние неизвестно'):
        return False
    m = r.get('meta')
    if r['state'] == 'готово с ошибками' and m and m.get('перемещать на носителе', True):
        return False
    return True                      # на диске направления ничего не перемещается - задание можно просто запустить снова


def run_all_set(rows):
    """«Запустить все по очереди»: ждущие и прерванные (не идущие, не готовые, не неизвестные)."""
    return [r for r in rows if r['state'] in ('не запускалось', 'прервано')]


def _date(ts):
    return time.strftime('%d.%m.%Y', time.localtime(ts)) if ts else ''


def done_rows(rows, done_items=()):
    """«Готово (N)»: [dict(task, files, gb, errors, date, left, tip, item)] по заданиям «готово»."""
    info = {it['task']: it for it in done_items}
    res = []
    for r in rows:
        if r['state'] != 'готово':
            continue
        it = info.get(r['task'])
        left = (it or {}).get('left', 0) if r['kind'] == 'перемещение' else 0
        res.append(dict(task=r['task'], files=r['total'], gb=gb(r.get('total_b', 0)) if r['kind'] == 'копирование' else '',
                        errors=r['errors'] + r['skipped'], date=_date(r.get('log_ts')), left=left,
                        tip=(it or {}).get('text', ''), item=it))
    return res


def _overlap(a, b):
    """Папки групп пересекаются? None - «файлы в корне» (пересекается только с такой же группой)."""
    if a is None or b is None:
        return a is None and b is None
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b + '\\') or b.startswith(a + '\\')


def conflicts(rows):
    """Пары заданий, которые одновременно работают с одним физическим диском (в любой роли)."""
    res = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            common = a.get('serials', set()) & b.get('serials', set())
            if common:
                res.append(f'«{a["task"]}» и «{b["task"]}» — общий диск')
    return res


def move_blocks(sel, rows):
    """Перемещение нельзя запускать, пока идёт или запускается копирование с того же носителя, и наоборот."""
    act = [r for r in rows if r['state'] == 'идёт'] + list(sel)
    res = []
    for m in (r for r in act if r['kind'] == 'перемещение'):
        for c in (r for r in act if r['kind'] == 'копирование'):
            if m.get('src_serial') and m['src_serial'] == c.get('src_serial'):
                mm, cm = m.get('move_meta'), c.get('meta')
                if mm and cm and not _overlap(mm.get('папка'), cm.get('папка')):
                    continue                  # логика v3: другая папка того же носителя - пути не пересекаются
                res.append(f'«{m["task"]}» (перемещение) и «{c["task"]}» (копирование) — один и тот же источник')
    return res


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


# ---------- логика v3: «Можно переместить на носителе» и «Готово» ----------

def _num(disk):
    return disk[3:] if disk.upper().startswith('HDD') and disk[3:].isdigit() else disk


def disks_words(disks, labels):
    """«диски 45 «Бэкап фото и видео» и 77 «Путешествия»» / «диск 78 «Работа Сафари»»."""
    items = [_num(d) + (f' «{labels[d]}»' if labels.get(d) else '') for d in disks]
    if not items:
        return 'диски направления'
    if len(items) == 1:
        return 'диск ' + items[0]
    return 'диски ' + ', '.join(items[:-1]) + ' и ' + items[-1]


def _folder_word(folder):
    return folder if folder else '(файлы в корне)'


def move_line(letter, disk, folder, dest):
    """«F:\\Котуй 2026 → F:\\Скопировано на Работа и Сафари (78)\\Котуй 2026» (тот же путь, что считает mvlist).
    Второй проход (этап 13): «F:\\Скопировано на A\\Поход → F:\\Скопировано на A и B\\Поход» - без вложенности."""
    src = _loc(letter, disk, folder) + ('' if folder else ' (файлы в корне)')
    r1, rest = hb.copied_inside(folder or '')
    dst = _loc(letter, disk, dest + ('\\' + rest if rest else '') if r1 else dest + '\\' + (folder or ''))
    return f'{src} → {dst}'


def _on_disks(disks):
    return ('диске ' if len(set(disks)) == 1 else 'дисках ') + hb.disk_nums(disks)


def _targets_of(x):
    return list((x.get('meta') or {}).get('цели') or x.get('targets') or [])


def hash_words(members, extra=()):
    """«Копии проверены по хешу на диске 78», если у каждой строки списка последний результат журнала - с SHA-256;
    иначе честно «по хешу проверено K из N». Окончательно разрешает перенос пофайловая проверка базы (mvlist)."""
    disks = sorted({t for x in members for t in _targets_of(x)})
    total = sum(x.get('total', 0) for x in members)
    group = list(members) + list(extra)
    if all('hashed_keys' in x for x in group):              # повтор тех же файлов не засчитывается дважды
        hashed = min(total, len(frozenset().union(*(x['hashed_keys'] for x in group))))
    else:                                                    # строки без ключей (тесты окна): по каждому заданию
        hashed = min(total, sum(x.get('hashed', 0) for x in members))
    if total and hashed >= total:
        return f'Копии проверены по хешу на {_on_disks(disks)}'
    return (f'Скопировано на {_on_disks(disks)}; по журналу копирования SHA-256 сверен у {n(hashed)} из {n(total)} — '
            'остальное перемещение проверит по базе')


def _size_words(r):
    return f'{n(r.get("total", 0))} файлов, {gb(r.get("total_b", 0))} ГБ'


def member_word(x):
    """Состояние одного задания группы 45/77: «на 45 скопировано и проверено», «на 77 ждёт запуска»."""
    s = x['state']
    if s == 'готово':
        w = ('скопировано и проверено' if x.get('hashed', 0) >= x.get('total', 0) else
             f'скопировано (по хешу проверено {n(x.get("hashed", 0))} из {n(x.get("total", 0))})')
    else:
        w = {'идёт': 'идёт копирование', 'готово с ошибками': 'скопировано с ошибками', 'не запускалось': 'ждёт запуска',
             'прервано': 'прервано, ждёт продолжения', 'состояние неизвестно': 'неизвестно, идёт ли'}.get(s, s)
    return f'на {", ".join(_num(t) for t in _targets_of(x)) or "?"} {w}'


def latest_manifest_groups(root=None):
    """Группы манифестов разбора, где копировать нечего («все подходящие уже есть»): их тоже можно переместить.
    По носителю и папке - из самого нового готового манифеста. -> [dict(manifest, disk, group, move_allowed)]."""
    root = Path(root or hb.RAZBORY)
    best = {}
    for p in sorted(root.glob('*.json')) if root.exists() else []:
        m = _meta(p)
        if not m or m.get('статус') != 'готово':
            continue
        for g in m.get('группы', []):
            best[(m.get('носитель'), g.get('folder'))] = dict(manifest=p.name, disk=m.get('носитель'), group=g,
                                                              allowed=m.get('перемещать на носителе', True))
    return [v for v in best.values() if v['group'].get('state') == hb.G_HAVE]


def r1_of(folder):
    return hb.copied_inside(folder or '')[0]


def move_items(rows, groups=()):
    """Блоки под таблицей: (можно переместить [dict], готово [dict]). Считается заново по файлам заданий."""
    offers, done, waiting = [], [], []
    retries = {}
    moves = {}
    for r in rows:
        m = r.get('meta')
        if m and m.get('повтор'):
            retries.setdefault(m['повтор'], []).append(r)
        mm = r.get('move_meta')
        if mm:
            key = mm.get('задание копирования') or ('манифест', mm.get('манифест'), mm.get('папка'))
            moves.setdefault(key, []).append(r)
    for v in moves.values():
        v.sort(key=lambda x: x['move_meta'].get('создано_ts', 0))
    parts_of = {}                                        # этап 13: части имени «Скопировано на …» по записям переносов
    for r in rows:
        mm = r.get('move_meta') or {}
        if mm.get('куда') and mm.get('части'):
            parts_of.setdefault(mm['куда'], [])
            parts_of[mm['куда']] += [t for t in mm['части'] if t not in parts_of[mm['куда']]]

    def done_items(key, disks, labels, folder, src_disk):
        keys = key if isinstance(key, list) else [key]
        for mv in [m for k in keys for m in moves.get(k, [])]:
            mm = mv['move_meta']
            if mv['state'] not in DONE:
                continue
            text = (f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)} и перенесена в '
                    f'«{mm["куда"]}» на {src_disk}. Содержимое источника перед перемещением не проверялось.')
            total = (mm.get('всего в папке') or [0])[0]
            left = max(0, total - mv.get('good', 0))
            if left:
                text += f' На старом месте осталось {n(left)} файлов.'
            if mv['state'] == 'готово с ошибками':
                text += f' Не перенесено по ошибке или конфликту: {n(mv["errors"] + mv["skipped"])}.'
            done.append(dict(text=text, task=mv['task'], left=left, reasons=mm.get('остаток') or {}, ok=not left))

    # этап 5: у направления с несколькими дисками (45 и 77) - отдельное задание на каждый диск одной группы («группа» в
    # разбор.json). Перемещение группы предлагается, только когда закончены ВСЕ её задания; пока нет - строка «на 45
    # скопировано, на 77 - ждёт». Окончательно решает пофайловая проверка SHA-256 на всех дисках (mvlist).
    sibs = {}
    for r in rows:
        m = r.get('meta')
        if r['kind'] != 'копирование' or not m or m.get('повтор'):
            continue
        key = (m.get('носитель', ''), m.get('группа')) if m.get('группа') else ('', r['task'])
        sibs.setdefault(key, []).append(r)

    for members in sibs.values():
        members.sort(key=lambda x: x['task'])
        r = members[0]                                       # «ведущее» задание группы: им вызывается mvlist
        m = r['meta']
        labels = r.get('labels') or {}
        folder, disks, src = m.get('папка'), m.get('обязательные диски') or [], m.get('носитель', '')
        letter = r.get('src_letter') or ''
        group = [g for x in members for g in [x] + retries.get(x['task'], [])]
        if any(g['state'] == 'идёт' for g in group) and len(members) == 1:
            continue
        if any(x['state'] not in DONE for x in members) or any(g['state'] == 'идёт' for g in group):
            if len(members) > 1:                             # не все диски группы скопированы - перемещать рано
                parts = [member_word(x) for x in members]
                dest = hb.move_dest(folder, m.get('имя направления', ''), disks, parts_of.get(r1_of(folder))) if disks else '…'
                small = ' · '.join(parts)
                waiting.append(dict(text=f'Папка «{_folder_word(folder)}»: ' + '; '.join(parts) + '. Переместить на '
                                         f'носителе можно, когда копии будут на {disks_words(disks, labels)}.',
                                    task=r['task'], left=0, reasons={}, ok=False, copy_task=r['task'], folder=folder,
                                    line=move_line(letter, src, folder, dest), small=small[:1].upper() + small[1:]))
            continue
        if not m.get('перемещать на носителе', True):
            done.append(dict(text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}; '
                                  f'источник {src} — диск направления, на нём ничего не перемещается.',
                             task=r['task'], left=0, reasons={}, ok=True))
            continue
        dest = hb.move_dest(folder, m.get('имя направления', ''), disks, parts_of.get(r1_of(folder))) if disks else '…'
        # задание переноса могло быть создано по ЛЮБОМУ заданию группы (mvlist --razbor «… — на 77» из командной строки)
        mv = sorted((x for t in members for x in moves.get(t['task'], [])),
                    key=lambda x: x['move_meta'].get('создано_ts', 0))
        last = mv[-1] if mv else None
        left = sum(x.get('left', 0) for x in members)
        with_left = [x['task'] for x in members if x.get('left', 0)]
        retry_busy = any(g['state'] not in DONE for x in members for g in retries.get(x['task'], []))
        hw = hash_words(members, [g for x in members for g in retries.get(x['task'], [])])
        base = dict(copy_task=r['task'], folder=folder, dest=dest, disk=src, retry_tasks=with_left or [r['task']],
                    line=move_line(letter, src, folder, dest), small=f'{hw} · {_size_words(r)}')
        if last and last['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            word = 'Запустить перемещение' if last['state'] == 'не запускалось' else 'Продолжить перемещение'
            offers.append(dict(base, kind='run', move_task=last['task'], buttons=[word],
                               small=('Задание перемещения создано, но не запускалось' if last['state'] == 'не запускалось'
                                      else 'Перемещение прервано — повторный запуск продолжит с места остановки'),
                               text=f'Папка «{_folder_word(folder)}»: задание переноса в «{dest}» '
                                    + ('создано, но не запускалось.' if last['state'] == 'не запускалось' else
                                       'прервано — повторный запуск продолжит с места остановки.')))
        elif last and last['state'] == 'идёт':
            pass
        else:
            newer = any(g['state'] in DONE and g.get('log_ts', 0) > last['move_meta'].get('создано_ts', 0)
                        for x in members for g in retries.get(x['task'], [])) if last else False
            if (not last or newer) and not retry_busy:
                if left:
                    offers.append(dict(base, kind='move', buttons=['Переместить скопированное', 'Повторить копирование'],
                                       small=f'Не скопировано {n(left)} файлов: можно переместить скопированное '
                                             f'(остальное останется на месте), затем повторить копирование · {hw}',
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)} '
                                            f'не полностью: не скопировано {n(left)} файлов. Сначала можно переместить '
                                            f'скопированное в «{dest}» (остальное останется на месте), затем повторить '
                                            'копирование остального.'))
                else:
                    offers.append(dict(base, kind='move', buttons=['Переместить'],
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}. '
                                            f'Переместить её на носителе {src} в «{dest}»? Проверка по хешу — по журналу '
                                            'копирования (SHA-256 прочитанного и записанного); перед перемещением '
                                            'каждый файл ещё раз сверяется с базой.'))
            elif left and not retry_busy:
                offers.append(dict(base, kind='retry', buttons=['Повторить копирование'],
                                   small=f'Скопированное уже перенесено; не скопировано {n(left)} файлов',
                                   text=f'Папка «{_folder_word(folder)}»: скопированное перенесено, не скопировано '
                                        f'{n(left)} файлов. Повторить копирование остального?'))
        done_items([x['task'] for x in members], disks, labels, folder, src)
    labels = next((r.get('labels') for r in rows if r.get('labels')), {}) or {}
    for g in groups:
        gr = g['group']
        if not g.get('allowed', True):
            continue
        key = ('манифест', g['manifest'], gr.get('folder'))
        mv = moves.get(key, [])
        dest = (hb.move_dest(gr.get('folder'), gr.get('direction', ''), gr.get('disks') or [],
                                parts_of.get(hb.copied_inside(gr.get('folder') or '')[0])) if gr.get('disks') else '…')
        gdisks = gr.get('disks') or []
        base = dict(manifest=g['manifest'], group=_folder_word(gr.get('folder')), folder=gr.get('folder'), dest=dest,
                    disk=g['disk'], line=move_line(g.get('letter') or '', g['disk'], gr.get('folder'), dest),
                    small=f'Все подходящие файлы уже есть на {_on_disks(gdisks)}' if gdisks else 'Копировать нечего')
        if not mv:
            offers.append(dict(base, kind='move', buttons=['Переместить'],
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: все подходящие файлы уже есть на '
                                    f'{disks_words(gr.get("disks") or [], labels)}. Переместить её на носителе '
                                    f'{g["disk"]} в «{dest}»?'))
        elif mv[-1]['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            offers.append(dict(base, kind='run', move_task=mv[-1]['task'], buttons=['Продолжить перемещение'],
                               small='Перемещение не закончено — повторный запуск продолжит с места остановки',
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: задание переноса в «{dest}» не закончено.'))
        done_items(key, gr.get('disks') or [], labels, gr.get('folder'), g['disk'])
    return offers + [dict(w, kind='wait', buttons=['Переместить'], disabled=True) for w in waiting], done


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


def _retry(task):
    try:
        return sv.retry_copy_task(task)
    except sv.Refused as e:
        return str(e)


# ---------- экран ----------

def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


def _cell(text, right=False, color=None, tip=''):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    if tip:
        it.setToolTip(tip)
    return it


class TextDialog(QDialog):
    """Весь ответ команды и кнопки: «ok» - согласие (например, «Создать задание перемещения»)."""

    def __init__(self, parent, title, text, ok=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        f = QFont('Consolas')
        f.setPointSize(10)
        view.setFont(f)
        lay.addWidget(view)
        box = QDialogButtonBox()
        if ok:
            box.addButton(ok, QDialogButtonBox.AcceptRole)
        box.addButton('Закрыть', QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)


def _small(text, color=GREY):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f'color:{color}; font-size:9pt')
    return lab


def _chip_style(color):
    if color == RED:
        return f'QLabel{{color:{RED}; background:#ffebee; border:1px solid #ef9a9a; border-radius:10px; ' \
               'padding:3px 12px; font-weight:bold}'
    return (f'QLabel{{color:{color or "#37474f"}; background:#f5f7f8; border:1px solid #cfd8dc; border-radius:10px; '
            'padding:3px 12px}')


class TasksPage(QWidget):
    HEAD = ['', 'Что и куда', 'Состояние', 'Сделано', 'Ошибки']
    DONE_HEAD = ['Задание', 'Файлов', 'ГБ', 'Ошибок и пропусков', 'Дата']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.trows, self.checked, self.queue = win, [], [], set(), []
        self.dlist = []
        self.start_file = os.startfile                    # тесты подменяют: окно PowerShell не открывается
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.head = QLabel('Задания на копирование')
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.head.setFont(f)
        top.addWidget(self.head)
        top.addStretch()
        self.refresh_btn = QPushButton('Обновить')
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        lay.addLayout(top)
        self.steps = StepsBar(win, 2)                     # шаги работы: «3. Копирование» (этап 11)
        lay.addWidget(self.steps)
        self.chips_lay = QHBoxLayout()
        self.chips = []
        lay.addLayout(self.chips_lay)
        self.sub = QLabel(INTRO)
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet('color:#37474f')
        lay.addWidget(self.sub)
        cap = QLabel('Задания')
        cap.setStyleSheet('font-weight:bold; margin-top:6px')
        lay.addWidget(cap)
        self.t = QTableWidget(0, len(self.HEAD))
        self.t.setHorizontalHeaderLabels(self.HEAD)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.verticalHeader().setVisible(False)
        hh = self.t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)      # ширина - по самой длинной строке «Что и куда»
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.setWordWrap(False)
        self.t.itemChanged.connect(self.on_check)
        lay.addWidget(self.t)
        bar = QHBoxLayout()
        self.run_btn = QPushButton('Запустить отмеченные (0)')
        self.run_btn.setStyleSheet('font-weight:bold')
        self.run_btn.clicked.connect(lambda: self.launch_checked())
        self.all_btn = QPushButton('Запустить все по очереди')
        self.all_btn.setToolTip('Все задания, которые ждут запуска или прерваны, — друг за другом в одном окне.')
        self.all_btn.clicked.connect(self.launch_all)
        self.log_btn = QPushButton('Открыть журнал')
        self.log_btn.clicked.connect(self.open_log)
        self.dir_btn = QPushButton('Открыть папку задания')
        self.dir_btn.clicked.connect(self.open_dir)
        for b in (self.run_btn, self.all_btn):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.log_btn, self.dir_btn):
            bar.addWidget(b)
        lay.addLayout(bar)
        lay.addWidget(_small(RUN_NOTE, '#37474f'))
        # ниже - блок перемещения и «Готово» (в прокрутке: список «Готово» может быть длинным)
        self.offers, self.done_items, self.groups = [], [], []
        self.blocks = QScrollArea()
        self.blocks.setWidgetResizable(True)
        self.blocks.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        bl = QVBoxLayout(inner)
        bl.setContentsMargins(0, 0, 0, 0)
        self.offer_box = QGroupBox('Скопировано — можно переместить папку на носителе')
        self.offer_lay = QVBoxLayout(self.offer_box)
        bl.addWidget(self.offer_box)
        self.move_note = _small(MOVE_NOTE)
        bl.addWidget(self.move_note)
        self.done_btn = QToolButton()
        self.done_btn.setCheckable(True)
        self.done_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.done_btn.setStyleSheet('QToolButton{border:none; font-weight:bold; padding:4px 0}')
        self.done_btn.toggled.connect(self.on_done_toggle)
        bl.addWidget(self.done_btn)
        self.done_t = QTableWidget(0, len(self.DONE_HEAD))
        self.done_t.setHorizontalHeaderLabels(self.DONE_HEAD)
        self.done_t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.done_t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.done_t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.done_t.verticalHeader().setVisible(False)
        self.done_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.done_t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.done_t.setMinimumHeight(170)
        self.done_t.setVisible(False)
        self.done_t.cellDoubleClicked.connect(self.on_done_double)
        bl.addWidget(self.done_t)
        bl.addStretch()
        self.blocks.setWidget(inner)
        lay.addWidget(self.blocks, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.t.itemSelectionChanged.connect(lambda: self._only_one(self.t, self.done_t))
        self.done_t.itemSelectionChanged.connect(lambda: self._only_one(self.done_t, self.t))
        self._done_title(0)

    # --- данные ---
    def refresh(self):
        self.win.bg.run(load_all, ok=lambda res: self.render(*res), quiet=True)

    def render(self, rows, groups=None):
        sel = self.current()
        self.rows = rows
        if groups is not None:
            self.groups = groups
        running = {r['task'] for r in rows if r['state'] == 'идёт'}
        if self.queue and not running and all(r['state'] != 'не запускалось' for r in rows if r['task'] in self.queue):
            self.queue = []
        self.render_chips()
        self.trows = [r for r in rows if r['state'] != 'готово']
        self.checked = {r['task'] for r in self.trows if r['task'] in self.checked and checkable(r)}
        self.t.blockSignals(True)
        self.t.clearSelection()
        self.t.setRowCount(len(self.trows))
        for i, r in enumerate(self.trows):
            box = QTableWidgetItem('')
            if checkable(r):
                box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                box.setCheckState(Qt.Checked if r['task'] in self.checked else Qt.Unchecked)
            else:
                box.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                box.setToolTip('Идёт — запускать нечего' if r['state'] == 'идёт' else
                               'Не удалось узнать, идёт ли задание: нажмите «Обновить»'
                               if r['state'] == 'состояние неизвестно' else
                               'Не скопированное — кнопкой «Повторить копирование» ниже')
            self.t.setItem(i, 0, box)
            l1, l2 = what_where(r)
            it = QTableWidgetItem('')
            it.setData(Qt.UserRole, f'{l1}\n{l2}')
            it.setToolTip(f'Задание: {r["task"]}\n{r.get("disks_long") or r.get("disks", "")}')
            self.t.setItem(i, 1, it)
            lab = QLabel(f'{html.escape(l1)}<br><span style="color:{GREY}; font-size:9pt">{html.escape(l2)}</span>')
            lab.setTextFormat(Qt.RichText)
            lab.setContentsMargins(4, 2, 4, 2)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.t.setCellWidget(i, 1, lab)
            text, color = state_text(r, self.queue)
            self.t.setItem(i, 2, _cell(text, color=color))
            done = _cell(f'{n(r["done"])} из {n(r["total"])}', right=True,
                         tip=f'{gb(r.get("done_b", 0))} из {gb(r.get("total_b", 0))} ГБ' if r['kind'] == 'копирование'
                         else '')
            self.t.setItem(i, 3, done)
            bad = r['errors'] + r['skipped']
            self.t.setItem(i, 4, _cell(n(bad) if bad else '', right=True, color=RED if bad else None, tip=errors_tip(r)))
            self.t.setRowHeight(i, 46)
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        self.t.blockSignals(False)
        widths = [self.t.cellWidget(i, 1).sizeHint().width() for i in range(len(self.trows))]
        self.t.setColumnWidth(1, min(700, max([260] + widths) + 16))
        # таблица - по числу строк (до 8 видно сразу, дальше прокрутка): место ниже - блоку перемещения и «Готово»
        self.t.setFixedHeight(self.t.horizontalHeader().sizeHint().height() + 46 * max(2, min(8, len(self.trows))) + 6)
        self.update_run_btn()
        self.render_blocks()
        self.render_done(sel)
        busy = bool(running) or bool(self.queue)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()

    def render_chips(self):
        while self.chips_lay.count():                       # плашки и растяжка - убираются из ряда сразу
            item = self.chips_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chips = []
        for text, color in summary(self.rows, self.queue):
            lab = QLabel(text)
            lab.setStyleSheet(_chip_style(color))
            self.chips_lay.addWidget(lab)
            self.chips.append(lab)
        self.chips_lay.addStretch(1)

    def update_run_btn(self):
        self.run_btn.setText(f'Запустить отмеченные ({len(self.checked)})')

    def on_check(self, it):
        if it.column() != 0 or not (0 <= it.row() < len(self.trows)):
            return
        r = self.trows[it.row()]
        if not checkable(r):
            return
        (self.checked.add if it.checkState() == Qt.Checked else self.checked.discard)(r['task'])
        self.update_run_btn()

    def _only_one(self, a, b):
        if a.selectionModel().selectedRows():
            b.blockSignals(True)
            b.clearSelection()
            b.blockSignals(False)

    def current(self):
        for t, lst in ((self.t, self.trows), (self.done_t, self.dlist)):
            rows = t.selectionModel().selectedRows() if not t.isHidden() else []
            if rows and 0 <= rows[0].row() < len(lst):
                name = lst[rows[0].row()]['task']
                return next((r for r in self.rows if r['task'] == name), None)
        return None

    def need(self):
        r = self.current()
        if not r:
            self.say('Сначала выберите задание в таблице (щелчок по строке).')
        return r

    # --- «Готово (N)» ---
    def _done_title(self, k):
        self.done_btn.setText(('▾ ' if self.done_btn.isChecked() else '▸ ') + f'Готово ({k})')

    def render_done(self, sel=None):
        self.dlist = done_rows(self.rows, self.done_items)
        t = self.done_t
        t.blockSignals(True)
        t.clearSelection()
        t.setRowCount(len(self.dlist))
        for i, d in enumerate(self.dlist):
            t.setItem(i, 0, _cell(d['task'], tip=d['tip']))
            t.setItem(i, 1, _cell(n(d['files']), right=True))
            t.setItem(i, 2, _cell(d['gb'], right=True))
            if d['left']:
                t.setItem(i, 3, _cell(f'осталось на месте: {n(d["left"])}', color=AMBER,
                                      tip='Двойной щелчок — почему файлы остались на старом месте'))
            else:
                t.setItem(i, 3, _cell(n(d['errors']) if d['errors'] else '0', right=True,
                                      color=RED if d['errors'] else None))
            t.setItem(i, 4, _cell(d['date']))
            if sel and d['task'] == sel['task'] and not t.isHidden():
                t.selectRow(i)
        t.blockSignals(False)
        self._done_title(len(self.dlist))

    def on_done_toggle(self, on):
        self.done_t.setVisible(on)
        if not on:
            self.done_t.clearSelection()
        self._done_title(len(self.dlist))

    def on_done_double(self, row, _col):
        if not (0 <= row < len(self.dlist)):
            return
        d = self.dlist[row]
        if d['left'] and d['item']:
            self.show_left(d['item'])
        else:
            self.start_file(str(hb.TASKS / d['task']))

    # --- вопросы (тесты подменяют) ---
    def say(self, text):
        QMessageBox.information(self, TITLE, text)

    def ask(self, text):
        return QMessageBox.question(self, TITLE, text) == QMessageBox.Yes

    def choose(self, text, buttons):
        """Вопрос с несколькими ответами -> текст нажатой кнопки или None."""
        box = QMessageBox(QMessageBox.Question, TITLE, text, parent=self)
        btns = {box.addButton(b, QMessageBox.AcceptRole): b for b in buttons}
        box.addButton('Отмена', QMessageBox.RejectRole)
        box.exec()
        return btns.get(box.clickedButton())

    def show_text(self, title, text, ok=None):
        return TextDialog(self, title, text, ok).exec() == QDialog.Accepted

    # --- запуск ---
    def launch_all(self):
        """«Запустить все по очереди»: ждущие и прерванные - тем же путём, что «По очереди» для отмеченных."""
        sel = run_all_set(self.rows)
        if not sel:
            self.say('Нет заданий, которые ждут запуска или прерваны.')
            return
        self.launch(sel, sequential=True)

    def launch_checked(self, sequential=False):
        sel = [r for r in self.rows if r['task'] in self.checked]
        if not sel:
            self.say('Отметьте галочками задания, которые нужно запустить.')
            return
        self.launch(sel, sequential)

    def launch(self, sel, sequential=False):
        busy = [r for r in sel if r['state'] == 'идёт']
        if busy:
            self.say('Уже идут: ' + ', '.join(f'«{r["task"]}»' for r in busy) + '. Их повторно не запускаю.')
            sel = [r for r in sel if r['state'] != 'идёт']
            if not sel:
                return
        block = move_blocks(sel, self.rows)
        if block:
            self.say('Так нельзя: перемещение и копирование с одного носителя одновременно ломают друг друга.\n\n'
                     + '\n'.join(block) + '\n\nДождитесь конца копирования, затем запускайте перемещение.')
            return
        running = [r for r in self.rows if r['state'] == 'идёт']
        clash = conflicts(sel + running)
        names = '\n'.join(f'  • {r["task"]} ({r["kind"]}, {r.get("disks", "")})' for r in sel)
        if len(sel) > 1 and not sequential:
            text = f'Запустить {len(sel)} задания(й) сразу, каждое в своём окне?\n\n{names}'
            if clash:
                text += ('\n\nВнимание: одни и те же диски у нескольких заданий —\n' + '\n'.join(clash) +
                         '\nОдновременно диск делит скорость между заданиями; лучше по очереди.')
            how = self.choose(text, ['По очереди', 'Все сразу'] if clash else ['Все сразу', 'По очереди'])
            if not how:
                return
            sequential = how == 'По очереди'
        elif not self.ask(('Запустить по очереди в одном окне?\n\n' if sequential and len(sel) > 1 else 'Запустить?\n\n')
                          + names + '\n\nВ начале каждого задания проверьте сводку и введите «да»; в конце — Enter. '
                          'Остановить — клавиша Q, повторный запуск продолжит.' +
                          ('\n\nВнимание: ' + '; '.join(clash) + '.' if clash else '')):
            return
        moves = [r for r in sel if r['kind'] == 'перемещение']
        if moves:
            self.win.statusBar().showMessage('Проверяю задания перемещения по свежей базе…')
            self.win.bg.run(lambda: [(r, *run_hb('mvlist', '--recheck', str(hb.TASKS / r['task']))) for r in moves],
                            ok=lambda res: self._after_recheck(res, sel, sequential))
            return
        self._start(sel, sequential)

    def _after_recheck(self, res, sel, sequential):
        bad = [(r, text) for r, code, text in res if code != 0]
        if bad:
            self.show_text('Задание перемещения устарело', '\n\n'.join(f'«{r["task"]}»:\n{t}' for r, t in bad))
            sel = [r for r in sel if r not in [b[0] for b in bad]]
            if not sel:
                return
        self._start(sel, sequential)

    def _start(self, sel, sequential):
        dirs = [hb.TASKS / r['task'] for r in sel]
        if sequential and len(dirs) > 1:
            path = queue_cmd(dirs, hb.BASE_DIR / 'очередь заданий.cmd')
            self.queue = [r['task'] for r in sel]
            self.start_file(str(path))
        else:
            for d in dirs:
                self.start_file(str(d / 'Запустить.cmd'))
        self.win.statusBar().showMessage(f'Запущено заданий: {len(dirs)}. Окна PowerShell ждут вашего «да».', 8000)
        QTimer.singleShot(3000, self.refresh)
        self.timer.start(5000)

    # --- логика v3: блок «Скопировано — можно переместить папку на носителе» ---
    def render_blocks(self):
        self.offers, self.done_items = move_items(self.rows, self.groups)
        lay = self.offer_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.offer_buttons = []
        for it in self.offers:
            row = QFrame()
            row.setStyleSheet('QFrame{background:#f3f8ee; border-radius:4px}' if not it.get('disabled') else
                              'QFrame{background:#f5f5f5; border-radius:4px}')
            h = QHBoxLayout(row)
            col = QVBoxLayout()
            lab = QLabel(it.get('line') or it['text'])
            lab.setWordWrap(True)
            lab.setToolTip(it['text'])
            col.addWidget(lab)
            if it.get('small'):
                col.addWidget(_small(it['small']))
            h.addLayout(col, 1)
            for i, word in enumerate(it['buttons']):
                b = QPushButton(word)
                if i == 0:
                    b.setStyleSheet('font-weight:bold')
                if it.get('disabled'):
                    b.setEnabled(False)
                    b.setToolTip('Станет доступна, когда копии будут на всех дисках направления.')
                b.clicked.connect(lambda _=False, it=it, word=word: self.on_offer(it, word))
                h.addWidget(b)
                self.offer_buttons.append((it, b))
            row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            lay.addWidget(row)
        if not self.offers:
            lay.addWidget(_small(MOVE_EMPTY, '#37474f'))

    def on_offer(self, it, word):
        if it.get('disabled'):
            return
        if word.startswith('Переместить'):
            self.move_v3(it)
        elif word == 'Повторить копирование':
            self.retry_copy(it)
        else:
            self.run_move(it['move_task'])

    def _v3_args(self, it):
        if it.get('copy_task'):
            return ['mvlist', '--razbor', it['copy_task']]
        return ['mvlist', '--razbor-manifest', it['manifest'], '--group', it['group']]

    def move_v3(self, it):
        args = self._v3_args(it)
        self.win.statusBar().showMessage(f'Считаю, что можно перенести из «{_folder_word(it.get("folder"))}»…')
        self.win.bg.run(run_hb, *args, '--dry', ok=lambda res: self._v3_preview(it, args, *res))

    def _v3_preview(self, it, args, code, text):
        self.win.statusBar().clearMessage()
        cnt = can_move(text) if code == 0 else 0
        intro = (f'Предпросмотр (ничего не перенесено). Папка уйдёт в «{it["dest"]}» на том же диске, все подпапки '
                 'сохраняются, ничего не удаляется и не перезаписывается.\n\n')
        if not cnt:
            self.show_text('Переместить на носителе', intro + text)
            return
        if not self.show_text('Переместить на носителе', intro + text, ok=f'Создать и запустить ({n(cnt)} файлов)'):
            return
        self.win.bg.run(run_hb, *args, ok=lambda res: self._v3_created(*res))

    def _v3_created(self, code, text):
        m = re.search(r'Папка задания: (.+)', text)
        if code != 0 or not m:
            self.show_text('Задание не создано', text)
            return
        self.refresh()
        self.run_move(Path(m.group(1).strip()).name)

    def run_move(self, name):
        row = next((r for r in self.rows if r['task'] == name), {'task': name, 'kind': 'перемещение'})
        block = move_blocks([row], self.rows)
        if block:
            self.say('Так нельзя: перенос и копирование одной и той же папки одновременно ломают друг друга.\n\n'
                     + '\n'.join(block) + '\n\nДождитесь конца копирования.')
            return
        self.checked = {name}
        self.win.statusBar().showMessage('Проверяю задание перемещения по свежей базе…')
        self.win.bg.run(lambda: run_hb('mvlist', '--recheck', str(hb.TASKS / name)),
                        ok=lambda res: self._after_recheck([({'task': name}, *res)], [{'task': name}], False))

    def retry_copy(self, it):
        tasks = it.get('retry_tasks') or [it['copy_task']]
        left = sum(r.get('left', 0) for r in self.rows if r['task'] in tasks)
        names = ', '.join(f'«{t} — повтор»' for t in tasks)
        if not self.ask(f'Создать {"задание" if len(tasks) == 1 else "задания"} {names} из {n(left)} не скопированных '
                        'файлов и запустить? Старое задание не перезапускается: то, что уже скопировано (и, возможно, '
                        'перенесено), повторно не читается.'):
            return
        for t in tasks:
            self.win.bg.run(_retry, t, ok=self._retried)

    def _retried(self, res):
        if isinstance(res, str):
            self.say(res)
            return
        self.refresh()
        self.start_file(str(Path(res['task']) / 'Запустить.cmd'))
        self.win.statusBar().showMessage(f'Запущен повтор: {Path(res["task"]).name} ({n(res["files"])} файлов). '
                                         'Окно PowerShell ждёт вашего «да».', 8000)

    def show_left(self, it):
        lines = [f'{why}: {n(v[0])} файлов, {gb(v[1])} ГБ' for why, v in sorted(it.get('reasons', {}).items())]
        self.show_text('Что осталось на старом месте', f'{it["text"]}\n\nПо расчёту перед переносом:\n'
                       + ('\n'.join(lines) or '—') + '\n\nСтроки журнала, кроме «перемещён», — в папке задания '
                       f'«{it["task"]}» («Открыть журнал»).')

    # --- прочее ---
    def open_dir(self):
        r = self.need()
        if r:
            self.start_file(str(hb.TASKS / r['task']))

    def open_log(self):
        r = self.need()
        if r and r['journal']:
            self.start_file(r['journal'])
        elif r:
            self.say('Журнала ещё нет: задание не запускалось.')
