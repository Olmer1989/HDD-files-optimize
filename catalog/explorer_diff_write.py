"""«Я сделал в Проводнике»: проверки и запись, папки без диска, записанные действия и их исправление."""
import os
import time

from hb_core import api as hb
import service as sv
from explorer_diff_base import SEP, EXCLUDED_DIRS, excluded_file, key, under, volume_serial
from explorer_diff_group import _sig


# ---------- запись ----------

def check_date(c, date, disk, path):
    """Дата операции не раньше описи диска и пересканирования этого места (иначе база её не применит)."""
    when = hb.manual_time(date)
    r = c.execute('select scanned from disks where disk=?', (disk,)).fetchone()
    latest = r[0] if r and r[0] else 0
    pk = key(path)
    for f, t in c.execute('select folder, time from scan_folders where disk=?', (disk,)):
        fk = key(f)
        if under(pk, [fk]) or fk.startswith(pk + SEP):
            latest = max(latest, t or 0)
    if when < latest:
        raise sv.Refused(f'Дата {date} раньше описи или пересканирования {disk}\\{path} '
                         f'({time.strftime("%d.%m.%Y", time.localtime(latest))}): база такую операцию не применит. '
                         'Укажите дату, когда вы сделали это в Проводнике (не раньше этой).')


def verify_disk(diff, rows):
    """Перед записью: тот же том, та же база, и на диске всё ещё так, как показано."""
    if diff.root and diff.serial and volume_serial(diff.root) != diff.serial:
        raise sv.Refused(f'Под буквой {diff.root} сейчас другой диск. Проверьте заново.')
    if sv.generation() != diff.generation:
        raise sv.Refused('База обновилась после проверки (пришли новые журналы или записи). Нажмите «Проверить» ещё раз.')
    for act, d, p, d2, p2, *_ in rows:
        if act in ('удалено', 'перемещено') and d == diff.disk and os.path.lexists(os.path.join(diff.root, p)):
            raise sv.Refused(f'{d}\\{p} снова есть на диске. Нажмите «Проверить» ещё раз.')
        if act in ('перемещено', 'скопировано') and not os.path.lexists(os.path.join(diff.root, p2)):
            raise sv.Refused(f'{d2}\\{p2} уже нет на диске. Нажмите «Проверить» ещё раз.')
    exp = expected(diff)
    for act, d, p, d2, p2, *_ in rows:          # то ли это, что сопоставили при проверке (размер, дата, состав папки)
        e = exp.get(key(p2)) if act in ('перемещено', 'скопировано') else None
        if not e:
            continue
        try:
            if e[0] == 'dir':
                same = disk_sig(diff.root, p2) == e[1]
            else:
                st = os.stat(os.path.join(diff.root, p2), follow_symlinks=False)
                same = (st.st_size, st.st_mtime_ns // 10 ** 9) == (e[1], e[2])
        except OSError:
            same = False
        if not same:
            raise sv.Refused(f'{d2}\\{p2} изменился после проверки. Нажмите «Проверить» ещё раз.')


def disk_sig(root, folder):
    """Подпись папки на диске сейчас (как _sig): только оглавление."""
    rows = []
    for dp, dn, fn in os.walk(os.path.join(root, folder)):
        dn[:] = [x for x in dn if x.lower() not in EXCLUDED_DIRS]
        for f in fn:
            if excluded_file(f):
                continue
            full = os.path.join(dp, f)
            st = os.stat(full, follow_symlinks=False)
            rows.append((os.path.relpath(full, root), st.st_size, st.st_mtime_ns // 10 ** 9))
    return _sig(folder, rows)


def expected(diff):
    """Назначение перемещения/копии -> что нашла проверка: ('dir', подпись) или ('file', размер, дата)."""
    res = {}
    for u in diff.units:
        if u['kind'] not in ('move', 'copy'):
            continue
        if u['is_dir']:
            res[key(u['path'])] = ('dir', u['sig'])
            for ch in u['children'] or []:
                res[key(ch.get('dst') or ch['path'])] = ('file', ch['bytes'], ch['mtime'])
        else:
            res[key(u['path'])] = ('file', u['bytes'], u['mtime'])
    return res


def check_overlap(rows):
    srcs = sorted((r[1], key(r[2])) for r in rows)
    for (d1, a), (d2, b) in zip(srcs, srcs[1:]):
        if d1 == d2 and (a == b or b.startswith(a + SEP)):
            raise sv.Refused(f'Одно место выбрано дважды: {d1}\\{a}. Проверьте заново.')


def write(date, rows, note='окно «Я сделал в Проводнике»', diff=None, add=None, progress=None):
    """Записать строки одним пакетом через service.add_manual_batch: все проверки заранее, все строки - одной записью
    на диск, одно применение к базе; при любой ошибке не пишется ничего. Строки, уже записанные раньше, пропускаются.
    Ответ: dict(written=[(строка, номер)], skipped=[строка уже записана], failed=None | (строка, причина),
    remaining=[не записанные]). add - замена add_manual_batch (тесты)."""
    add = add or sv.add_manual_batch
    if not rows:
        raise sv.Refused('Ничего не отмечено.')
    if not sv.DATE_RE.match(date or ''):
        raise sv.Refused('Дата - в виде ДД.ММ.ГГГГ.')
    rows = [tuple(r[:5]) for r in rows]
    check_overlap(rows)
    if diff is not None:
        verify_disk(diff, rows)
    todo, skipped = [], []
    c = sv.ro()
    try:
        for r in rows:
            if r[0] != 'скопировано':                  # копия не меняет источник: важна только дата назначения
                check_date(c, date, r[1], r[2])
            if r[3]:
                check_date(c, date, r[3], r[4])
    finally:
        c.close()
    already = {tuple(f[:6]) for _, f in hb.manual_rows()}
    for r in rows:
        if (date,) + r in already:                     # записано прошлой попыткой
            skipped.append(r)
            continue
        try:
            sv.manual_preview(date, *r)
            todo.append(r)
        except sv.Refused as e:
            if 'уже записана' in str(e):
                skipped.append(r)
            else:
                raise sv.Refused(f'{r[1]}{SEP}{r[2]}: {e} Ничего не записано.')
    written, failed = [], None
    if todo:
        try:
            res = add(date, todo, note=note)
            written = [(r, ln) for r, (_, ln) in zip(todo, res)]
        except Exception as e:                                   # noqa: BLE001
            failed = (todo[0], str(e))
        if progress:
            progress(len(written), len(todo))
    remaining = todo[1:] if failed else []
    return dict(written=written, skipped=skipped, failed=failed, remaining=remaining)


def result_text(res):
    lines = [f'Записано строк: {len(res["written"])}.']
    if res['skipped']:
        lines.append(f'Уже были записаны раньше (пропущены): {len(res["skipped"])}.')
    if res['failed']:
        r, msg = res['failed']
        lines.append(f'ОСТАНОВЛЕНО: {msg}')
        lines.append(f'Не записано ничего (строк: {len(res["remaining"]) + 1}): запись идёт одним пакетом - всё или '
                     'ничего. Нажмите «Проверить» и «Записать» ещё раз.')
    return '\n'.join(lines)


# ---------- диск не подключён: папки из базы ----------

def offline_rows(disk, act, folders, disk2='', dest=''):
    """Строки для отключённого диска: отмеченные папки (вложенные в отмеченные отбрасываются)."""
    folders = sorted({f.strip(SEP) for f in folders if f.strip(SEP)}, key=str.lower)
    top = [f for f in folders if not any(key(f).startswith(key(g) + SEP) for g in folders if g != f)]
    res = []
    for f in top:
        if act == 'удалено':
            res.append(('удалено', disk, f, '', ''))
        else:
            if not disk2:
                raise sv.Refused('Выберите диск, куда скопировали или переместили.')
            d = (dest or '').strip(SEP)                   # пробелы - часть имени (этап 16)
            res.append((act, disk, f, disk2, (d + SEP if d else '') + f.rsplit(SEP, 1)[-1]))
    return res


# ---------- записанные действия ----------

def recorded(disk=None):
    """Строки «ручные операции.tsv», новые сверху: dict(line, fields, date, act, src, dst, note, text)."""
    res = []
    for ln, f in hb.manual_rows():
        date, act, d, p, d2, p2, note = f[:7]
        if disk and disk not in (d, d2):
            continue
        res.append(dict(line=ln, fields=f[:7], date=date, act=act, src=f'{d}\\{p}', dst=f'{d2}\\{p2}' if d2 else '',
                        note=note, text=describe(f[:7])))
    res.sort(key=lambda r: -r['line'])
    return res


def describe(f):
    date, act, d, p, d2, p2 = (list(f) + [''] * 7)[:6]
    if act == 'удалено':
        return f'{date}: удалено {d}\\{p}'
    if act == 'перемещено' and d == d2:
        return f'{date}: перемещено внутри {d}: {p} → {p2}'
    return f'{date}: {act} {d}\\{p} → {d2}\\{p2}'


def fix_check(fields, disks):
    """Проверка исправленной строки (fix_manual сам поля не проверяет)."""
    date, act, d, p, d2, p2, note = (list(fields) + [''] * 7)[:7]
    if act not in sv.ACTIONS:
        raise sv.Refused('Выберите действие.')
    if not sv.DATE_RE.match(date):
        raise sv.Refused('Дата - в виде ДД.ММ.ГГГГ.')
    if d not in disks:
        raise sv.Refused(f'Носителя «{d}» нет в базе.')
    if p.startswith(SEP) or p2.startswith(SEP):
        raise sv.Refused('Путь пишется от корня диска без буквы и без «\\» в начале, например «Фото\\2014».')
    p = sv.check_rel(p)
    if act == 'удалено':
        d2 = p2 = ''
    else:
        if d2 not in disks:
            raise sv.Refused('Выберите диск, куда скопировали или переместили.')
        p2 = sv.check_rel(p2, 'путь назначения')
    return [date, act, d, p, d2, p2, note]


def fix(line_no, old_fields, fields, reason, fixer=None):
    """Исправить строку: под рукой сервиса; сначала проверяется, что строка не изменилась с момента показа."""
    if not (reason or '').strip():
        raise sv.Refused('Напишите, почему исправляете: это сохранится в комментарии строки.')
    now = dict(hb.manual_rows()).get(line_no)
    if now is None or hb.row_fields(now[:7], (3, 5)) != hb.row_fields(old_fields[:7], (3, 5)):
        raise sv.Refused('Эту строку за это время изменили. Обновите список и выберите её снова.')
    if hb.row_fields(fields[:7], (3, 5)) == hb.row_fields(old_fields[:7], (3, 5)):
        raise sv.Refused('Вы ничего не изменили.')
    (fixer or sv.fix_manual)(line_no, list(fields), reason.strip())
