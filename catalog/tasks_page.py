"""Раздел окна «Задания» (15.11.2026): что сейчас идёт, ход и оценка времени по журналам, запуск отмеченных
заданий (каждое в своём окне PowerShell или по очереди в одном), «Разложить на источнике…» после копирования.

Окно ничего не копирует и не перемещает само: оно открывает «Запустить.cmd» задания, а задание перемещения
создаёт командой mvlist (отдельным процессом, как раздел «Команды»). Состояние задания - service.task_state
(правила, раздел 6); здесь к нему добавляется ход: сколько файлов и ГБ, скорость, сколько осталось.
Спор с GPT - «Проверка Архитектуры сортировки файлов\\Перемещение_на_любые_диски_v1.md».

Логика v3, этап 3 (15.11.2026): заголовок «Идёт: …» - в столбик; в колонке «Диски» - номер, название и буква; под
таблицей - «Можно переместить на носителе» (по каждой скопированной папке разбора - вопрос и кнопка; при ошибках
копирования - «Переместить скопированное», затем «Повторить копирование») и «Готово» (статусы). Задание переноса
создаёт `mvlist --razbor`, повтор копирования - service.retry_copy_task. Документ - «Логика_v3_разбор_носителя.md».
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import build_pilot as bp
import commands_page as cpg
import service as sv
from hb_core import api as hb

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
STATE_COLOR = {'идёт': '#1565c0', 'готово': '#2e7d32', 'готово с ошибками': '#c62828', 'прервано': '#e65100',
               'состояние неизвестно': '#6d4c41', 'не запускалось': '#455a64', 'в очереди': '#6a1b9a'}
DONE = ('готово', 'готово с ошибками')
MOVE_SUFFIX = ' - разложить на источнике'       # имя задания перемещения по умолчанию (mvlist --task)
COPY_META, V3_META = 'разбор.json', 'перемещение.json'   # логика v3: задание копирования разбора / задание переноса
MIN_BYTES, MIN_SEC = 10 * 1024 ** 2, 30          # раньше оценка времени не показывается
EXPLAIN = ('После копирования и проверки копий файлы на исходном диске можно перенести в папку «ПЕРЕНЕСЕНО → …» '
           'с сохранением всех папок и подпапок — так видно, что уже сохранено. Например, F:\\Котуй 2026\\Валере\\1.jpg '
           '→ F:\\ПЕРЕНЕСЕНО → 78\\Котуй 2026\\Валере\\1.jpg (78 — номер диска, где лежит копия). Это отдельный шаг '
           'с вашим подтверждением: кнопка «Разложить на источнике…» у законченного копирования. Ничего не удаляется. '
           'Переносится только файл, копия которого проверена по SHA-256 на всех дисках, куда его копировали.')


V3_EXPLAIN = ('После копирования и проверки копий папку можно перенести на носителе в «Скопировано на …», все '
              'подпапки сохраняются. Ничего не удаляется.')


def gb(b):
    return f'{b / 1024 ** 3:,.1f}'.replace(',', ' ')


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
    res = dict(total_b=total_b, done_b=done_b, speed=None, eta=None, eta_text='', ago=None, examples=errs)
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
    src = serials.get(vols[0][1].strip().upper()) if vols else None
    return dict(disks=label, disks_long=long_, src_long=longs[0] if longs else '', dst_long=longs[1:], serials=sers,
                src_serial=vols[0][1].strip().upper() if vols else None, src=src)


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


def load(root=None, now=None):
    """Строки таблицы: состояние (service) + ход, диски, пометка «после копирования.json», есть ли уже задание раскладки."""
    root = Path(root or hb.TASKS)
    rows = sv.tasks(root)
    serials = serial_names()
    labels = disk_labels()
    try:
        letters = sv.volumes()
    except (OSError, AttributeError):
        letters = {}
    names = {r['task'] for r in rows}
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
        mark = d / sv.MOVE_MARK
        try:
            r['mark'] = json.loads(mark.read_text(encoding='utf-8')) if mark.exists() else None
        except (OSError, ValueError):
            r['mark'] = None
        r['move_task'] = (r['task'] + MOVE_SUFFIX) if (r['task'] + MOVE_SUFFIX) in names else None
    return rows


# ---------- решения без экрана (их проверяют тесты) ----------

def headline(rows, queue=()):
    run = [r for r in rows if r['state'] == 'идёт']
    if run:
        parts = []
        for r in run:
            s = (f'Идёт: {r["task"]} — {r["disks"]}: {n(r["done"])} из {n(r["total"])} файлов')
            if r['kind'] == 'копирование':
                s += f', {gb(r["done_b"])} из {gb(r["total_b"])} ГБ'
                if r.get('eta_text'):
                    s += (', осталось ' + r['eta_text']) if r.get('eta') is not None else f' ({r["eta_text"]})'
            parts.append(s)
        waiting = sum(1 for r in rows if r['state'] == 'не запускалось')
        if waiting:
            parts.append(f'Ещё подготовлено, не запускалось: {waiting}')
        return '\n'.join(parts)
    waiting = sum(1 for r in rows if r['state'] == 'не запускалось')
    s = f'Ничего не идёт. Подготовлено, не запускалось: {waiting}'
    stopped = sum(1 for r in rows if r['state'] == 'прервано')
    if stopped:
        s += f'; прервано: {stopped}'
    offers = sum(1 for r in rows if r['kind'] == 'копирование' and r['state'] in DONE and not r.get('move_task')
                 and not r.get('meta'))
    if offers:
        s += f'; можно разложить на источнике: {offers}'
    return s


def headline_rows(rows, queue=()):
    """Заголовок «Идёт: …» в столбик: [(заголовок, [(название, значение)])] по каждому идущему заданию."""
    res = []
    for r in (r for r in rows if r['state'] == 'идёт'):
        p = [('Задание', r['task'])]
        if r['kind'] == 'копирование':
            p += [('Откуда', r.get('src_long') or r.get('disks', '')),
                  ('Куда', ', '.join(r.get('dst_long') or []) or '—'),
                  ('Сделано', f'{n(r["done"])} из {n(r["total"])} файлов · {gb(r["done_b"])} из {gb(r["total_b"])} ГБ')]
            sp = r.get('speed')
            p.append(('Скорость', f'{sp / 1024 ** 2:,.0f} МБ/с'.replace(',', ' ') if sp else 'считается…'))
            left = r.get('eta_text') or ''
            left = ('около ' + left.lstrip('~')) if r.get('eta') is not None else left
            if r.get('ago') is not None and r['ago'] > 120:
                left += f' (последняя запись {fmt_ago(r["ago"])}: идёт большой файл или диск завис)'
            p.append(('Осталось', left or '—'))
        else:
            p += [('Где', r.get('src_long') or r.get('disks', '')),
                  ('Сделано', f'{n(r["done"])} из {n(r["total"])} файлов')]
        res.append(('Идёт ' + r['kind'], p))
    if res:
        waiting = [r for r in rows if r['state'] == 'не запускалось' and r['task'] in queue]
        if waiting:
            res[-1][1].append(('В очереди', f'ещё {len(waiting)} заданий, '
                                            f'{gb(sum(r.get("total_b", 0) for r in waiting))} ГБ'))
        rest = sum(1 for r in rows if r['state'] == 'не запускалось' and r['task'] not in queue)
        if rest:
            res[-1][1].append(('Подготовлено', f'не запускалось: {rest}'))
    return res


def headline_text(rows, queue=()):
    """То же простым текстом, строка на величину (для «Сводки для чата» и тестов)."""
    lines = []
    for title, pairs in headline_rows(rows, queue):
        lines.append(title)
        lines += [f'{k}: {v}' for k, v in pairs]
    return '\n'.join(lines)


def headline_html(rows, queue=()):
    import html
    parts = []
    for title, pairs in headline_rows(rows, queue):
        cells = ''.join(f'<tr><td style="color:#546e7a; padding-right:14px">{html.escape(k)}:</td>'
                        f'<td>{html.escape(v)}</td></tr>' for k, v in pairs)
        parts.append(f'<div style="font-size:14pt; font-weight:bold; color:#1565c0">{html.escape(title)}</div>'
                     f'<table style="font-size:11pt; font-weight:normal">{cells}</table>')
    return ''.join(parts)


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


def pending_offers(rows, offered):
    """Законченные копирования с пометкой «разложить после копирования», для которых окно ещё не предлагало раскладку."""
    return [r for r in rows if r.get('mark') and r['kind'] == 'копирование' and r['state'] in DONE
            and not r.get('move_task') and r['task'] not in offered]


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
    return '(файлы в корне)' if folder is None else folder


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


def move_items(rows, groups=()):
    """Блоки под таблицей: (можно переместить [dict], готово [dict]). Считается заново по файлам заданий."""
    offers, done = [], []
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

    def done_items(key, disks, labels, folder, src_disk):
        for mv in moves.get(key, []):
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

    for r in rows:
        m = r.get('meta')
        if r['kind'] != 'копирование' or not m or m.get('повтор'):
            continue
        labels = r.get('labels') or {}
        folder, disks, src = m.get('папка'), m.get('обязательные диски') or [], m.get('носитель', '')
        group = [r] + retries.get(r['task'], [])
        if any(g['state'] == 'идёт' for g in group) or r['state'] not in DONE:
            continue
        if not m.get('перемещать на носителе', True):
            done.append(dict(text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}; '
                                  f'источник {src} — диск направления, на нём ничего не перемещается.',
                             task=r['task'], left=0, reasons={}, ok=True))
            continue
        dest = hb.copied_folder(m.get('имя направления', ''), disks) if disks else '…'
        mv = moves.get(r['task'], [])
        last = mv[-1] if mv else None
        left = r.get('left', 0)
        retry_busy = any(g['state'] not in DONE for g in group[1:])
        base = dict(copy_task=r['task'], folder=folder, dest=dest, disk=src)
        if last and last['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            word = 'Запустить перемещение' if last['state'] == 'не запускалось' else 'Продолжить перемещение'
            offers.append(dict(base, kind='run', move_task=last['task'], buttons=[word],
                               text=f'Папка «{_folder_word(folder)}»: задание переноса в «{dest}» '
                                    + ('создано, но не запускалось.' if last['state'] == 'не запускалось' else
                                       'прервано — повторный запуск продолжит с места остановки.')))
        elif last and last['state'] == 'идёт':
            pass
        else:
            newer = any(g['state'] in DONE and g.get('log_ts', 0) > last['move_meta'].get('создано_ts', 0)
                        for g in group[1:]) if last else False
            if (not last or newer) and not retry_busy:
                if left:
                    offers.append(dict(base, kind='move', buttons=['Переместить скопированное', 'Повторить копирование'],
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)} '
                                            f'не полностью: не скопировано {n(left)} файлов. Сначала можно переместить '
                                            f'скопированное в «{dest}» (остальное останется на месте), затем повторить '
                                            'копирование остального.'))
                else:
                    offers.append(dict(base, kind='move', buttons=['Переместить'],
                                       text=f'Папка «{_folder_word(folder)}» скопирована на {disks_words(disks, labels)}. '
                                            f'Переместить её на носителе {src} в «{dest}»?'))
            elif left and not retry_busy:
                offers.append(dict(base, kind='retry', buttons=['Повторить копирование'],
                                   text=f'Папка «{_folder_word(folder)}»: скопированное перенесено, не скопировано '
                                        f'{n(left)} файлов. Повторить копирование остального?'))
        done_items(r['task'], disks, labels, folder, src)
    labels = next((r.get('labels') for r in rows if r.get('labels')), {}) or {}
    for g in groups:
        gr = g['group']
        if not g.get('allowed', True):
            continue
        key = ('манифест', g['manifest'], gr.get('folder'))
        mv = moves.get(key, [])
        dest = hb.copied_folder(gr.get('direction', ''), gr.get('disks') or []) if gr.get('disks') else '…'
        base = dict(manifest=g['manifest'], group=_folder_word(gr.get('folder')), folder=gr.get('folder'), dest=dest,
                    disk=g['disk'])
        if not mv:
            offers.append(dict(base, kind='move', buttons=['Переместить'],
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: все подходящие файлы уже есть на '
                                    f'{disks_words(gr.get("disks") or [], labels)}. Переместить её на носителе '
                                    f'{g["disk"]} в «{dest}»?'))
        elif mv[-1]['state'] in ('не запускалось', 'прервано', 'состояние неизвестно'):
            offers.append(dict(base, kind='run', move_task=mv[-1]['task'], buttons=['Продолжить перемещение'],
                               text=f'Папка «{_folder_word(gr.get("folder"))}»: задание переноса в «{dest}» не закончено.'))
        done_items(key, gr.get('disks') or [], labels, gr.get('folder'), g['disk'])
    return offers, done


def load_all(root=None, now=None):
    """Для окна: строки таблицы и группы манифестов «копировать нечего»."""
    rows = load(root, now)
    try:
        groups = latest_manifest_groups()
    except OSError:
        groups = []
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


class TasksPage(QWidget):
    HEAD = ['Задание (галочка - запустить)', 'Вид', 'Состояние', 'Ход', 'Скорость', 'Осталось', 'Ошибки', 'Диски']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.checked, self.offered, self.queue = win, [], set(), set(), []
        self.start_file = os.startfile                    # тесты подменяют: окно PowerShell не открывается
        lay = QVBoxLayout(self)
        self.head = QLabel('Задания: считаю…')
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.head.setFont(f)
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.sub = QLabel(V3_EXPLAIN)
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet('color:#37474f')
        lay.addWidget(self.sub)
        lay.addWidget(QLabel('Папки в «Запускаемые скрипты». Каждое задание идёт в своём окне PowerShell: там спросят '
                             '«да», остановка — клавиша Q, повторный запуск продолжит с места остановки.'))
        self.t = _table(self.HEAD)
        self.t.itemChanged.connect(self.on_check)
        lay.addWidget(self.t, 1)
        # логика v3: под таблицей - «Можно переместить на носителе» и «Готово»
        self.offers, self.done_items, self.groups = [], [], []
        self.blocks = QScrollArea()
        self.blocks.setWidgetResizable(True)
        self.blocks.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        bl = QVBoxLayout(inner)
        bl.setContentsMargins(0, 0, 0, 0)
        self.offer_box = QGroupBox('Можно переместить на носителе')
        self.offer_lay = QVBoxLayout(self.offer_box)
        self.done_box = QGroupBox('Готово')
        self.done_lay = QVBoxLayout(self.done_box)
        bl.addWidget(self.offer_box)
        bl.addWidget(self.done_box)
        bl.addStretch()
        self.blocks.setWidget(inner)
        self.blocks.setMaximumHeight(320)
        lay.addWidget(self.blocks)
        self.note = QLabel(EXPLAIN)
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color:#37474f; background:#eef3f7; padding:8px; border-radius:4px')
        lay.addWidget(self.note)
        bar = QHBoxLayout()
        for text, fn in (('Обновить', self.refresh), ('Запустить отмеченные', self.launch_checked),
                         ('По очереди', lambda: self.launch_checked(sequential=True)),
                         ('Разложить на источнике…', self.move_current), ('Открыть папку', self.open_dir),
                         ('Открыть журнал', self.open_log), ('Сводка для чата', self.to_chat)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
            if text == 'Разложить на источнике…':
                self.move_btn = b
        bar.addStretch()
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.t.itemSelectionChanged.connect(self.on_select)

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
        self.t.blockSignals(True)
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            state = r['state']
            if state == 'не запускалось' and r['task'] in self.queue:
                state = 'в очереди'
            box = _cell(r['task'])
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            box.setCheckState(Qt.Checked if r['task'] in self.checked else Qt.Unchecked)
            self.t.setItem(i, 0, box)
            self.t.setItem(i, 1, _cell(r['kind']))
            self.t.setItem(i, 2, _cell(state, color=STATE_COLOR.get(state)))
            hod = f'{n(r["done"])} из {n(r["total"])} файлов'
            if r['kind'] == 'копирование':
                hod += f' · {gb(r["done_b"])} из {gb(r["total_b"])} ГБ'
            self.t.setItem(i, 3, _cell(hod, right=True))
            sp = r.get('speed') if r['state'] == 'идёт' else None       # у законченного скорость не нужна
            self.t.setItem(i, 4, _cell((f'{sp / 1024 ** 2:,.0f} МБ/с' if sp >= 10 * 1024 ** 2 else
                                        f'{sp / 1024 ** 2:.1f} МБ/с').replace(',', ' ') if sp else '', right=True))
            left = r.get('eta_text', '')
            if r.get('ago') is not None and r['ago'] > 120:
                left += f' (последняя запись {fmt_ago(r["ago"])}: идёт большой файл или диск завис)'
            self.t.setItem(i, 5, _cell(left))
            bad = r['errors'] + r['skipped']
            self.t.setItem(i, 6, _cell(bad if bad else '', right=True, color='#c62828' if r['errors'] else None,
                                       tip='\n'.join(r.get('examples', []))))
            self.t.setItem(i, 7, _cell(r.get('disks_long') or r.get('disks', ''), tip=r.get('disks', '')))
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        self.t.blockSignals(False)
        if any(r['state'] == 'идёт' for r in rows):
            self.head.setTextFormat(Qt.RichText)
            self.head.setText(headline_html(rows, self.queue))
        else:
            self.head.setTextFormat(Qt.AutoText)
            self.head.setText(headline(rows, self.queue))
        self.render_blocks()
        self.note.setVisible(any(r['kind'] == 'копирование' and not r.get('meta') for r in rows) or not rows)
        self.on_select()
        busy = bool(running) or bool(self.queue)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()
        for r in pending_offers(rows, self.offered):
            self.offered.add(r['task'])
            QTimer.singleShot(0, lambda r=r: self.offer_move(r, auto=True))

    def on_check(self, it):
        if it.column() != 0 or not (0 <= it.row() < len(self.rows)):
            return
        name = self.rows[it.row()]['task']
        (self.checked.add if it.checkState() == Qt.Checked else self.checked.discard)(name)

    def on_select(self):
        r = self.current()
        self.move_btn.setEnabled(bool(r and r['kind'] == 'копирование' and r['state'] in DONE and not r.get('meta')))

    def current(self):
        i = self.t.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def need(self):
        r = self.current()
        if not r:
            self.say('Сначала выберите задание в таблице (щелчок по строке).')
        return r

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
    def launch_checked(self, sequential=False):
        sel = [r for r in self.rows if r['task'] in self.checked]
        if not sel:
            self.say('Отметьте галочками задания, которые нужно запустить.')
            return
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

    # --- раскладка на источнике ---
    def move_current(self):
        r = self.need()
        if r:
            self.offer_move(r)

    def offer_move(self, r, auto=False):
        if r['kind'] != 'копирование' or r['state'] not in DONE:
            self.say('Разложить на источнике можно только после законченного копирования '
                     '(«готово» или «готово с ошибками»). Сейчас: ' + r['state'] + '.')
            return
        if r.get('move_task'):
            self.say(f'Задание раскладки уже создано: «{r["move_task"]}». Его можно запустить из таблицы.')
            return
        if auto and not self.ask(f'Копирование «{r["task"]}» закончилось ({r["state"]}).\n\nПри подготовке вы отметили '
                                 '«разложить на источнике после копирования». Посмотреть, сколько файлов и куда можно '
                                 'перенести? Сейчас ничего не переносится.'):
            return
        self.win.statusBar().showMessage(f'Считаю, что можно перенести после «{r["task"]}»…')
        self.win.bg.run(run_hb, 'mvlist', '--task', r['task'], '--dry', ok=lambda res: self._preview(r, *res))

    def _preview(self, r, code, text):
        self.win.statusBar().clearMessage()
        cnt = can_move(text) if code == 0 else 0
        intro = ('Предпросмотр (ничего не перенесено). Перенос — внутри того же диска, все папки и подпапки '
                 'сохраняются, ничего не удаляется.\n\n')
        if not cnt:
            self.show_text('Разложить на источнике', intro + text)
            return
        if not self.show_text('Разложить на источнике', intro + text, ok=f'Создать задание перемещения ({n(cnt)} файлов)'):
            return
        args = ['mvlist', '--task', r['task']]
        if 'главный архивный диск' in text:
            if not self.ask('Источник — главный архивный диск (45 или 77). Перенос в «ПЕРЕНЕСЕНО → …» изменит '
                            'структуру архива на нём. Всё равно создать задание?'):
                return
            args.append('--allow-main')
        self.win.bg.run(run_hb, *args, ok=lambda res: self._created(r, *res))

    def _created(self, r, code, text):
        if code != 0 or 'Папка задания:' not in text:
            self.show_text('Задание не создано', text)
            return
        name = r['task'] + MOVE_SUFFIX
        self.refresh()
        if self.ask(f'Создано задание «{name}».\n\nЗапустить его сейчас? Откроется окно PowerShell: подключите диск, '
                    'проверьте сводку и введите «да».'):
            self.checked = {name}
            self.win.bg.run(lambda: run_hb('mvlist', '--recheck', str(hb.TASKS / name)),
                            ok=lambda res: self._after_recheck([({'task': name}, *res)], [{'task': name}], False))

    # --- логика v3: блоки под таблицей ---
    def render_blocks(self):
        self.offers, self.done_items = move_items(self.rows, self.groups)
        for lay in (self.offer_lay, self.done_lay):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
        for it in self.offers:
            row = QFrame()
            row.setStyleSheet('QFrame{background:#f3f8ee; border-radius:4px}')
            h = QHBoxLayout(row)
            lab = QLabel(it['text'])
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            for i, word in enumerate(it['buttons']):
                b = QPushButton(word)
                if i == 0:
                    b.setStyleSheet('font-weight:bold')
                b.clicked.connect(lambda _=False, it=it, word=word: self.on_offer(it, word))
                h.addWidget(b)
            self.offer_lay.addWidget(row)
        if not self.offers:
            self.offer_lay.addWidget(QLabel('Сейчас нечего: папка появится здесь, когда её копирование закончится.'))
        for it in self.done_items:
            row = QFrame()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 4, 2)
            lab = QLabel(('✓ ' if it.get('ok') else '• ') + it['text'])
            lab.setWordWrap(True)
            lab.setStyleSheet('color:#2e7d32' if it.get('ok') else 'color:#8d6e00')
            h.addWidget(lab, 1)
            if it.get('left'):
                b = QPushButton('Показать')
                b.clicked.connect(lambda _=False, it=it: self.show_left(it))
                h.addWidget(b)
            self.done_lay.addWidget(row)
        if not self.done_items:
            self.done_lay.addWidget(QLabel('Пока ничего не перенесено.'))
        self.done_box.setVisible(True)

    def on_offer(self, it, word):
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
        left = next((r.get('left', 0) for r in self.rows if r['task'] == it['copy_task']), 0)
        if not self.ask(f'Создать задание «{it["copy_task"]} — повтор» из {n(left)} не скопированных файлов и запустить '
                        'его? Старое задание не перезапускается: то, что уже скопировано (и, возможно, перенесено), '
                        'повторно не читается.'):
            return
        self.win.bg.run(_retry, it['copy_task'], ok=self._retried)

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

    def to_chat(self):
        r = self.need()
        if r:
            QGuiApplication.clipboard().setText(
                f'Задание «{r["task"]}» ({r["kind"]}, {r.get("disks", "")}): {r["state"]}; обработано {r["done"]} из '
                f'{r["total"]}, ошибок {r["errors"]}, пропусков {r["skipped"]}. Журнал: {r["journal"] or "нет"}')
            self.win.statusBar().showMessage('Сводка скопирована - вставьте её в чат.', 5000)
