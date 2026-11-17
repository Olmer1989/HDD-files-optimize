"""«Задания на копирование»: ход задания по журналам (файлов и байт, скорость, остаток, проверено по хешу). Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import re
import time
from pathlib import Path

from hb_core import api as hb

from .common import HASH_WORD, MIN_BYTES, MIN_SEC
from .texts_words import fmt_eta


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
