"""Логика v3: отметки разбора - предпросмотр и запись (add_marks_batch).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import append_rows, backup, check_disk, check_rel, db, files_under, Refused, SEP, TableLock
from .directions_v3 import _read_snapshot


def mark_verdict(text, dirs):
    """Текст отметки владельца -> (решение для решения.tsv, направление или None)."""
    t = (text or '').strip()
    low = t.lower()
    if low == hb.MARK_SKIP:
        return hb.MARK_SKIP, None
    if low == hb.MARK_INHERIT:
        return hb.MARK_INHERIT, None
    if low.startswith(hb.MARK_DIR):
        t = t.split(':', 1)[1].strip()
    d = hb.find_direction(dirs, t)
    if not d:
        raise Refused(f'Нет направления «{t}». Есть: ' + (', '.join(f'{x.num} {x.name}' for x in dirs.values()) or
                                                          'никаких (заведите: directions-default или direction-add)')
                      + '; или «не копировать», «как у родителя».')
    return d.verdict(), d


def _real_path(c, disk, path, roots=()):
    """Путь как в базе: точный, иначе - папка без учёта регистра (folders.folder_lc), иначе - тот же исходный путь
    внутри служебной папки переноса (папка уже перенесена, владелец назвал её исходный путь)."""
    for cand in [path] + [r + SEP + path for r in sorted(roots)]:
        if files_under(c, disk, cand, 1)[0]:
            return cand
        r = c.execute('select folder from folders where disk=? and folder_lc=?', (disk, cand.lower())).fetchone()
        if r:
            return r[0]
    raise Refused(f'В базе нет файлов по пути {disk}\\{path}. Проверьте путь (папку можно выбрать по дереву базы).')


def marks_preview(disk, rows, c=None, snap=None):
    """Отметки разбора одним пакетом: rows - [(путь, отметка)], путь '' - весь носитель (режим разбора).
    Отметка: направление (номер или имя), «не копировать», «как у родителя». Путь проверяется физически (есть в базе),
    затем пишется ИСХОДНЫМ (без «ПЕРЕНЕСЕНО → …» / «Скопировано на …»). Совпадает с действующей - пропускается."""
    c = c or db()
    check_disk(c, disk)
    snap = snap or _read_snapshot()
    dirs = hb.parse_directions(snap['directions'])
    ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs)
    roots = hb.moved_roots(c, disk)
    fields, lines, skipped, seen = [], [], [], set()
    for path, text in rows:
        path = hb.clean_path(path)                       # этап 16: пробелы по краям имени не обрезаются
        if path:
            real = _real_path(c, disk, check_rel(path), roots)
            orig = hb.mark_path(real, roots)              # этап 13: внутри «Скопировано на …» - нынешний путь
            inside = real.split(SEP, 1)[0] in roots
            if not orig:
                raise Refused(f'«{real}» - служебная папка переноса; отметьте папки внутри неё.')
        else:
            real, orig, inside = '', '', False
        verdict, d = mark_verdict(text, dirs)
        if orig.lower() in seen:
            raise Refused(f'{disk}\\{orig or "(весь носитель)"}: отмечено в пакете дважды. Ничего не записано.')
        seen.add(orig.lower())
        cur = ms.get(orig)
        where = f'{disk}\\{orig}' if orig else f'{disk} (весь носитель)'
        if verdict == hb.MARK_INHERIT:
            if cur is None:
                skipped.append(f'{where}: своей отметки нет - уже «как у родителя»')
                continue
        elif cur is not None and hb.parse_verdict(verdict, dirs)[:2] == (cur.kind, cur.num):
            skipped.append(f'{where}: уже отмечено так ({hb.mark_text(cur, dirs)})')
            continue
        n, size, _ = files_under(c, disk, real)
        what = hb.mark_text(None if verdict == hb.MARK_INHERIT else hb.Mark(*hb.parse_verdict(verdict, dirs)[:3]), dirs)
        line = f'{where} → {what}: {n} файлов, {hb.gb(size)} ГБ' + (
            '' if not inside else ' (папка в «Скопировано на …»: отметка действует только там)' if orig == real else
            ' (папка уже перенесена; отметка - по исходному пути)')
        if d and disk in d.disks:
            line += f' - {disk} сам диск этого направления: копируется на остальные его диски, перемещать нельзя'
        if verdict == hb.MARK_INHERIT and cur and cur.legacy:
            line += f' (старое решение «{cur.verdict}» для старых команд остаётся в силе)'
        lines.append(line)
        fields.append([disk, orig, verdict])
    if not fields:
        raise Refused('Записывать нечего: ' + '; '.join(skipped))
    lines.insert(0, f'Будет записано отметок: {len(fields)}.')
    if skipped:
        lines.append('Пропущено (уже так): ' + '; '.join(skipped))
    return dict(fields=fields, lines=lines, skipped=skipped)


def add_marks_batch(disk, rows, note=''):
    """Запись отметок пакетом, всё или ничего (как add_manual_batch): под замком - снова все проверки, копия таблицы,
    одна запись на диск. Решения в базу не применяются (читаются при каждом ответе)."""
    with TableLock():
        pv = marks_preview(disk, rows, snap=_read_snapshot())
        hb.ensure_tables()
        backup(hb.DECISIONS)
        first = append_rows(hb.DECISIONS, [f + [note or ''] for f in pv['fields']])
    pv['line'] = first
    return pv
