"""Применение модуля «опись носителя»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import os
import sqlite3
import build_pilot as bp
from hb_core.consts import EV_SCAN, EV_STALE, SEP
from hb_core.util import name_key, rel_of
from hb_core.apply_common import scan_row


def load_disk(c, d, j):
    """Полная опись одного носителя -> строки files, issues и disks. Возвращает (файлов, с хешем, с устаревшим хешем)."""
    hp, ip = j['dir'] / 'hashes.sqlite', j['dir'] / 'inventory.sqlite'
    hashes = {}
    if hp.exists():
        with bp.ro(hp) as h:
            for p, s, m, x, st in h.execute('select path, size, mtime_ns, lower(sha256), status from hashes'):
                if st == 'verified' and x:
                    hashes[p] = (s, '' if m is None else str(m), x)
                else:
                    c.execute('insert into issues values (?,?,?,?)', (d, p, 'файл не прочитан при подсчёте хеша', st or ''))
    have_inv = ip.exists()
    cnt = collections.Counter()

    def rows():
        if not have_inv:                              # описи нет вовсе: есть только таблица хешей
            for p, (size, m, x) in hashes.items():
                cnt[EV_SCAN] += 1
                yield d, p, size or 0, x, 'опись', name_key(p), None, EV_SCAN, None
            return
        with bp.ro(ip) as inv:
            for p, size, mt in inv.execute('select path, size, mtime_ns from files order by path'):
                r = scan_row(d, p, size, mt, hashes.get(p), 'опись', keep_empty=True)
                cnt[r[7]] += 1
                yield r
        # хеш, для которого в описи нет файла, не переносится: по описи такого файла на диске нет

    c.executemany('insert or replace into files values (?,?,?,?,?,?,?,?,?)', rows())
    total = sum(cnt.values())                       # не total_changes: при сборке по шагам его увеличивают триггеры
    if have_inv:
        try:
            with bp.ro(ip) as inv:
                for p, op, msg in inv.execute('select path, operation, message from errors'):
                    c.execute('insert into issues values (?,?,?,?)',
                              (d, rel_of(p or '')[1].rstrip(SEP), 'папка или файл не прочитаны при описи', f'{op}: {msg}'[:300]))
        except sqlite3.Error:
            pass
    scanned = os.path.getmtime(ip) if have_inv else j.get('mtime', 0)
    c.execute('insert or replace into disks values (?,?,?,?,?,?)',
              (d, j['label'], cnt[EV_SCAN], total, j.get('status') or '?', scanned))
    return total, cnt[EV_SCAN], cnt[EV_STALE]
