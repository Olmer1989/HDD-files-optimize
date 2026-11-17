"""Записи владельца: ручные операции (manual), решения (decide), исключения (exclude) - предпросмотр и запись.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time

from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import (ACTIONS, append_row, append_rows, backup, check_disk, check_rel, DATE_RE, db, files_under,
    Refused, SEP, TableLock, VERDICT_RE)
from .marks import add_marks_batch, marks_preview


# ---------- записи владельца ----------

def manual_preview(date, act, disk, path, disk2='', path2='', c=None):
    """Что изменит ручная операция. Исключение Refused - если записывать нельзя. c - уже открытое соединение
    (пакетная запись проверяет все строки по одной базе)."""
    act = (act or '').strip().lower()
    if act not in ACTIONS:
        raise Refused(f'Действие должно быть одним из: {", ".join(ACTIONS)}.')
    if not DATE_RE.match(date or ''):
        raise Refused('Дата - в виде ДД.ММ.ГГГГ, например 14.11.2026.')
    c = c or db()
    check_disk(c, disk)
    path = check_rel(path)
    if act != 'удалено':
        check_disk(c, disk2)
        path2 = check_rel(path2, 'путь назначения')
    else:
        disk2 = path2 = ''
    n, size, sample = files_under(c, disk, path)
    if not n:
        raise Refused(f'В базе нет файлов по пути {disk}\\{path}. Проверьте номер диска и путь (папку можно '
                      'выбрать и на отключённом диске - из каталога базы).')
    for ln, f in hb.manual_rows():
        if hb.row_fields(f[:6], paths=(3, 5)) == [date, act, disk, path, disk2, path2]:
            raise Refused(f'Такая операция уже записана (строка {ln}). Повторно не записываю.')
    lines = [f'{date} {act}: {disk}\\{path}' + (f' -> {disk2}\\{path2}' if disk2 else ''),
             f'Затронет записей базы: {n}, {hb.gb(size)} ГБ. Например: ' + '; '.join(sample)]
    if disk2:
        m, _, _ = files_under(c, disk2, path2)
        if m:
            lines.append(f'ВНИМАНИЕ: в {disk2}\\{path2} в базе уже есть {m} записей - одинаковые пути будут заменены.')
        lines.append('Копия «со слов» получает степень U (не подтверждена): удалять оригинал по ней нельзя.'
                     if act == 'скопировано' or disk2 != disk else 'Перемещение внутри диска: хеш и степень сохраняются.')
    return dict(fields=[date, act, disk, path, disk2, path2], lines=lines, files=n)


def add_manual(date, act, disk, path, disk2='', path2='', note='', apply=True):
    with TableLock():
        pv = manual_preview(date, act, disk, path, disk2, path2)
        hb.ensure_tables()
        backup(hb.MANUAL)
        ln = append_row(hb.MANUAL, pv['fields'] + [note or ''])
    pv['line'] = ln
    if apply:
        hb.close_last()
        hb.update(quiet=True)
    return pv


def add_manual_batch(date, rows, note='', apply=True):
    """Пакетная запись ручных операций (окно «Я сделал в Проводнике»): rows - [(действие, диск, путь, диск2, путь2)].
    Всё или ничего: под одним замком таблиц все строки проверяются заранее (как manual_preview каждой, плюс нет
    повторов внутри пакета), затем одна копия таблицы в архив, все строки - одной записью на диск, одно применение к
    базе. При любой ошибке не пишется ничего. Ответ: [(поля, номер строки в файле)]."""
    rows = [tuple((list(r) + [''] * 5)[:5]) for r in rows]
    if not rows:
        raise Refused('Ничего не отмечено.')
    with TableLock():
        c = db()
        fields, seen = [], set()
        for r in rows:
            try:
                pv = manual_preview(date, *r, c=c)
            except Refused as e:
                raise Refused(f'{r[1]}{SEP}{r[2]}: {e} Ничего не записано.')
            key = tuple(pv['fields'])
            if key in seen:
                raise Refused(f'{r[1]}{SEP}{r[2]}: эта операция в пакете дважды. Ничего не записано.')
            seen.add(key)
            fields.append(pv['fields'] + [note or ''])
        hb.ensure_tables()
        hb.close_last()
        backup(hb.MANUAL)
        first = append_rows(hb.MANUAL, fields)
    if apply:
        hb.close_last()
        hb.update(quiet=True)
    return [(f, first + i) for i, f in enumerate(fields)]


def fix_manual(line_no, fields, reason):
    """Исправить ошибочно записанную строку: заменить её, причину - в комментарий; база соберётся заново."""
    if not reason:
        raise Refused('Нужна причина исправления.')
    with TableLock():
        lines = hb.MANUAL.read_bytes().decode('utf-8-sig').split('\n')
        idx = [i for i, x in enumerate(lines) if x.strip()]
        if line_no < 2 or line_no > len(idx):
            raise Refused(f'Строки {line_no} нет.')
        backup(hb.MANUAL)
        i = idx[line_no - 1]
        eol = '\r' if lines[i].endswith('\r') else ''
        old = lines[i].rstrip('\r').split('\t')
        note = (fields[6] if len(fields) > 6 else '') + f' | исправлено {time.strftime("%d.%m.%Y")}: {reason}; было: {" / ".join(old[:6])}'
        lines[i] = '\t'.join(fields[:6] + [note]) + eol
        data = '\n'.join(lines).encode('utf-8-sig')
        hb.MANUAL.write_bytes(data)
    hb.close_last()
    hb.update(quiet=True)


def decision_preview(disk, path, verdict):
    verdict = (verdict or '').strip()
    if hb.is_v3_mark(verdict):                    # отметки разбора v3 - та же проверка, что у пакета отметок
        pv = marks_preview(disk, [(path, verdict)])
        return dict(fields=pv['fields'][0], lines=pv['lines'])
    if not VERDICT_RE.match(verdict):
        raise Refused('Решение: «не нужно», «раздел: <название>», «пока не трогаем» или (разбор v3) '
                      '«направление: <номер или имя>», «не копировать», «как у родителя».')
    c = db()
    if disk != '*':
        check_disk(c, disk)
    if path.lower().startswith('класс:'):
        n, size, sample = 0, 0, []
    else:
        path = check_rel(path)
        n, size, sample = files_under(c, disk, path) if disk != '*' else (0, 0, [])
        if disk != '*' and not n:
            raise Refused(f'В базе нет файлов по пути {disk}\\{path}.')
    for f in hb.read_table(hb.DECISIONS)[1:]:
        f = hb.row_fields(f, paths=(1,), pad=3)          # путь - как в таблице (этап 16)
        if f[:3] == [disk, path, verdict]:
            raise Refused('Такое решение уже записано.')
    return dict(fields=[disk, path, verdict],
                lines=[f'{disk}\\{path}: {verdict}', f'Под решение попадает записей базы: {n}, {hb.gb(size)} ГБ'])


def add_decision(disk, path, verdict, note=''):
    if hb.is_v3_mark(verdict):
        pv = add_marks_batch(disk, [(path, verdict)], note)
        pv['fields'] = pv['fields'][0]
        return pv
    with TableLock():
        pv = decision_preview(disk, path, verdict)
        hb.ensure_tables()
        backup(hb.DECISIONS)
        pv['line'] = append_row(hb.DECISIONS, pv['fields'] + [note or ''])
    return pv                       # решения читаются при каждом ответе - применять к базе нечего


def exclusion_preview(disk, path):
    c = db()
    check_disk(c, disk)
    path = check_rel(path)
    for d, folders in hb.read_exclusions().items():
        if d == disk and path in folders:
            raise Refused('Эта папка уже в исключениях.')
    n, size, sample = files_under(c, disk, path)
    return dict(fields=[disk, path], lines=[f'Исключить {disk}\\{path}: база перестанет учитывать {n} записей, '
                                            f'{hb.gb(size)} ГБ (их список сохранится в таблице excluded).'])


def add_exclusion(disk, path, note=''):
    with TableLock():
        pv = exclusion_preview(disk, path)
        hb.ensure_tables()
        backup(hb.EXCLUSIONS)
        pv['line'] = append_row(hb.EXCLUSIONS, pv['fields'] + [note or ''])
    hb.close_last()
    hb.update(quiet=True)
    return pv
