"""Применение модуля «журнал скрипта» (копирование, перемещение, корзина)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from pathlib import Path
from hb_core.consts import EV_COPY, EV_SCAN, EV_SIZE, FOLDER_MOVES, OLD_LOGS, SEP
from hb_core.util import moved_rel, prefix_cond, rel_of
from hb_core.sources import log_time, read_tsv
from hb_core.apply_common import put_row


def apply_log(c, log, jobs, serials, report, seen, rows=None, start=0):
    """Журнал скрипта -> поправки. Строка действует на диск, только если запуск был ПОЗЖЕ описи этого диска:
    иначе опись уже отражает результат (или его отсутствие), и старый журнал вернул бы исчезнувший файл.
    rows - уже прочитанные строки журнала; start - сколько строк данных уже учтено (журнал дописывается)."""
    task = Path(log).parent
    rows = read_tsv(log) if rows is None else rows
    if len(rows) < 2 + start:
        return
    head = [h.strip().lower() for h in rows[0]]
    body = rows[1 + start:]
    name = f'{task.name}\\{Path(log).name}'
    when = log_time(log)
    newer = lambda disk, path=None: when > seen.at(disk, path)     # опись диска или частичный скан папки новее
    added = removed = moved = weak = old = 0
    origin = 'журнал: ' + name
    lookup = lambda disk, rel: c.execute('select sha, size, mtime, sha_exp, ev from files where disk=? and path=?',
                                         (disk, rel)).fetchone()

    if 'цель' in head and 'куда' in head:                      # единый шаблон и ночные скрипты 12.11
        names = {}
        tv = task / 'тома.tsv'
        if tv.exists():
            for f in read_tsv(tv):
                if len(f) >= 2:
                    names[f[0].strip()] = serials.get(f[1].strip().upper())
        src_disk = next(iter(names.values()), None) if names else None
        i_t, i_r, i_s, i_src, i_dst = (head.index(x) for x in ('цель', 'результат', 'размер', 'источник', 'куда'))
        i_h = next((i for i, h in enumerate(head) if h.startswith('sha-256')), None)
        for f in body:
            if len(f) <= i_dst or not (f[i_r].startswith('скопирован') or f[i_r] == 'уже есть'):
                continue
            disk = names.get(f[i_t]) or (f[i_t] if f[i_t] in jobs and f[i_t] not in names else None)
            if not disk:
                report['warn'].add(f'{name}: цель «{f[i_t]}» не опознана по тома.tsv - строки пропущены')
                continue
            if not newer(disk, rel_of(f[i_dst])[1]):
                old += 1
                continue
            log_sha = (f[i_h].strip().lower() if i_h is not None and len(f) > i_h else '') or None
            got = lookup(src_disk, rel_of(f[i_src])[1]) if src_disk else None
            src_sha = (got[0] or got[3]) if got else None
            if f[i_r].startswith('скопирован') and log_sha:
                # скрипт сам прочитал и записал эти байты и посчитал их хеш
                put_row(c, disk, rel_of(f[i_dst])[1], int(f[i_s]), log_sha, got[2] if got else None, EV_COPY, None, origin)
            else:
                # «уже есть» или копия, сверенная только по размеру: содержимое приёмника никто не читал.
                # Но если по этому пути цели уже есть ПОДТВЕРЖДЁННАЯ запись (S/C) того же содержимого (тот же хеш, а
                # если хеш неизвестен - тот же размер) - например, копирование остановили клавишей Q и запустили
                # снова, - «уже есть» её не понижает до Z (15.11.2026).
                dst = rel_of(f[i_dst])[1]
                want = log_sha or src_sha
                have = c.execute('select sha, size, ev from files where disk=? and path=?', (disk, dst)).fetchone()
                if have and have[2] in (EV_SCAN, EV_COPY) and have[0] and \
                        (have[0] == want if want else have[1] == int(f[i_s])):
                    added += 1
                    continue
                put_row(c, disk, dst, int(f[i_s]), None, got[2] if got else None, EV_SIZE, want, origin)
                weak += 1
            added += 1
    elif task.name in OLD_LOGS and 'откуда' in head and 'куда' in head:
        letters = OLD_LOGS[task.name]
        i_r, i_a, i_b, i_s = (head.index(x) for x in ('результат', 'откуда', 'куда', 'размер'))
        for f in body:
            if len(f) <= max(i_a, i_b, i_s):
                continue
            (la, ra), (lb, rb) = rel_of(f[i_a]), rel_of(f[i_b])
            da, db_ = letters.get(la), letters.get(lb)
            if not da or not db_:
                continue
            got = lookup(da, ra)
            if f[i_r].startswith('скопирован'):
                if not newer(db_, rb):
                    old += 1
                    continue
                put_row(c, db_, rb, int(f[i_s]), None, got[2] if got else None, EV_SIZE,
                        (got[0] or got[3]) if got else None, origin)      # File.Copy + сверка размера
                added += 1; weak += 1
            elif f[i_r].startswith('перемещ'):
                if not newer(da, ra) or not newer(db_, rb):
                    old += 1
                    continue
                if got:                                                   # тот же файл на том же диске
                    c.execute('delete from files where disk=? and path=?', (da, ra))
                    put_row(c, db_, rb, got[1], got[0] if da == db_ else None, got[2],
                            got[4] if da == db_ else EV_SIZE, got[3] if da == db_ else (got[0] or got[3]), origin)
                    moved += 1
    elif task.name in OLD_LOGS and 'в корзину' in head:
        letters = OLD_LOGS[task.name]
        i_r, i_a = head.index('результат'), head.index('в корзину')
        for f in body:
            if len(f) > i_a and f[i_r].startswith('в корзин'):
                l, r = rel_of(f[i_a])
                if l in letters:
                    if not newer(letters[l], r):
                        old += 1
                        continue
                    removed += c.execute('delete from files where disk=? and path=?', (letters[l], r)).rowcount
    elif head[:6] == ['время', 'результат', 'размер', 'sha-256', 'откуда', 'куда']:    # шаблон «Переместить на источнике»
        vols = read_tsv(task / 'тома.tsv') if (task / 'тома.tsv').exists() else []
        disk = serials.get(vols[0][1].strip().upper()) if vols and len(vols[0]) >= 2 else None
        if not disk:
            report['warn'].add(f'{name}: диск-источник не опознан по тома.tsv - журнал перемещения не учтён')
            return
        for f in body:
            if len(f) < 6 or f[1] not in ('перемещён', 'уже перемещён'):
                continue
            ra, rb = moved_rel(f[4], f[5])
            if ra is None:
                continue
            if not newer(disk, ra) or not newer(disk, rb):
                old += 1
                continue
            got = lookup(disk, ra)
            if not got:
                continue                                # уже учтено (повторный запуск) или файла нет в базе
            c.execute('delete from files where disk=? and path=?', (disk, ra))
            put_row(c, disk, rb, got[1], got[0], got[2], got[4], got[3], origin)     # тот же файл на том же диске
            moved += 1
    elif task.name in FOLDER_MOVES and head[:3] == ['время', 'результат', 'папка']:
        disk, src_base, dst_base = FOLDER_MOVES[task.name]
        for f in body:
            if len(f) < 3 or not f[1].startswith('перемещ'):
                continue
            old_path = src_base + SEP + f[2]
            if not newer(disk, old_path) or not newer(disk, dst_base + SEP + f[2]):
                old += 1
                continue
            cond, args = prefix_cond('path', old_path)
            moved += c.execute(f'update files set path = ? || substr(path, ?), origin = ? where disk=? and {cond}',
                               [dst_base + SEP + f[2], len(old_path) + 1, origin, disk] + args).rowcount
    else:
        if name not in report['skipped']:
            report['skipped'].append(name)
        return
    k = report['logs'].setdefault(name, [0, 0, 0, 0])
    for i, v in enumerate((added, moved, removed, weak)):
        k[i] += v
    if old:
        report['old_logs'][name] = report['old_logs'].get(name, 0) + old
