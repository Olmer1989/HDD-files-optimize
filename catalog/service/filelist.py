"""Окно «Список файлов» (этап 16, 16.11.2026; ui/filelist): file_list и помощники.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import check_disk, Refused, ro, SEP
from .directions_v3 import snapshot
from .read_disks import volumes
from .read_hash import NOHASH_SQL


# ---------- окно «Список файлов» (этап 16, 16.11.2026; filelist_window.py) ----------
# Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 16». Ничего не пишет. Строка списка:
# (диск, путь, размер, дата, ev, тип 0..8, почему, где копия). Списки «к копированию», «уже есть», «не подходит по
# типу» - тот же расчёт, что числа ячейки «Разбора» (planner с collect); «без хеша» - то же условие, что столбец «Без
# хеша» (NOHASH_SQL); «спорные» - contested_rows; «уникальные» - presence.ndisks = 1.

LIST_KINDS = ('copy', 'have', 'type', 'nohash', 'contested', 'unique')
LIST_MAX = 1_500_000                  # строк в окне не больше (память); больше - откройте список для папки поменьше
EV_TEXT = {hb.EV_SCAN: 'посчитан сканером', hb.EV_COPY: 'проверен при копировании', hb.EV_SIZE: 'сверен только размер',
           hb.EV_USER: 'со слов владельца', hb.EV_STALE: 'файл изменился'}
NO_HASH_TEXT = 'не считался'
TYPE_WORD = {hb.F_PHOTO: 'фото', hb.F_VIDEO: 'видео', hb.F_TEXT: 'документ', hb.F_ARCH: 'архив', hb.F_OTHER: 'другие',
             hb.F_PROJ: 'другие · проект', hb.F_MUSIC: 'другие · музыка', hb.F_NEVER: 'другие · программа',
             hb.F_JUNK: 'другие · служебный'}
WHY_HEAD = {'copy': 'Почему', 'type': 'Почему', 'nohash': 'Почему', 'contested': 'Почему спорный', 'unique': 'Почему'}


def hash_text(ev):
    """Столбец «Хеш» окна по степени подтверждения записи."""
    return EV_TEXT.get(ev or '', NO_HASH_TEXT)


def _too_many(n):
    if n > LIST_MAX:
        raise Refused(f'В списке {n:,} файлов - больше {LIST_MAX:,}: окно столько не покажет. Откройте список для '
                      'папки поменьше.'.replace(',', ' '))


def _meta(c, disk, paths_):
    """Дата и степень подтверждения файлов носителя по путям: {путь: (mtime, ev)} (одна временная таблица)."""
    c.execute('create temp table if not exists fl_p(path text primary key)')
    c.execute('delete from fl_p')
    c.executemany('insert or ignore into fl_p values (?)', ((x,) for x in paths_))
    return {r[0]: r[1:] for r in c.execute('select f.path, f.mtime, f.ev from fl_p q cross join files f '
                                           'on f.disk=? and f.path=q.path', (disk,))}


def disk_letters(disks_):
    """Буквы подключённых сейчас носителей по серийному номеру тома из описи (диски не читаются): {диск: 'H:'}.
    Не подключён или узнать нельзя - диска в ответе нет."""
    try:
        serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
        vols = volumes()
    except (OSError, AttributeError):
        return {}
    return {d: vols[serial_of[d]] for d in disks_ if serial_of.get(d) in vols}


def full_path(disk, path, letters):
    """Полный путь файла или папки (этап 18): «H:\\путь» у подключённого носителя, иначе «HDD45\\путь». Пробелы не
    трогаются."""
    head = letters.get(disk) or disk
    return f'{head}{SEP}{path}' if path else head + SEP


def _copies(c, shas, disks_, skip, letters=None):
    """«Где копия»: все записи с тем же SHA-256 на дисках disks_ - подтверждённые (S/C) и с ожидаемым хешем (Z/U/X, с
    пометкой «не проверена»). skip - (диск, путь) самих файлов списка. Этап 18: полный путь копии с именем файла и
    буквой подключённого диска («H:\\…»), иначе «HDD45\\…». -> {sha: ['H:\\путь', …]}."""
    letters = letters or {}
    if not shas or not disks_:
        return {}
    c.execute('create temp table if not exists fl_s(sha text primary key)')
    c.execute('delete from fl_s')
    c.executemany('insert or ignore into fl_s values (?)', ((x,) for x in shas))
    q = ','.join('?' * len(disks_))
    res = collections.defaultdict(list)
    for sha, d, p, ev in c.execute(f'select s.sha, f.disk, f.path, f.ev from fl_s s cross join files f on f.sha=s.sha '
                                   f"where f.disk in ({q}) and f.ev in ('S', 'C') order by f.disk, f.path", list(disks_)):
        if (d, p) not in skip:
            res[sha].append(full_path(d, p, letters))
    for sha, d, p, ev in c.execute(f'select s.sha, f.disk, f.path, f.ev from fl_s s cross join files f '
                                   f"on f.sha_exp=s.sha where f.disk in ({q}) and coalesce(f.ev, '') not in ('S', 'C') "
                                   'order by f.disk, f.path', list(disks_)):
        res[sha].append(f'{full_path(d, p, letters)} (не проверена: {hash_text(ev)})')
    return res


def _takes(d):
    """«фото, видео» - что берёт направление (его «что копировать»), словами окна."""
    words = [x for x in hb.COPY_CATS if x in d.cats]
    if d.docs_near and hb.CAT_DOC in words:
        words[words.index(hb.CAT_DOC)] = 'документы (только рядом с фото и видео)'
    return ', '.join(words) if len(words) < len(hb.COPY_CATS) else 'все файлы'


def _type_why(d, k):
    """«Почему» в списке «не подходит по типу»: правило направления словами."""
    cat = hb.CAT_OF_TYPE.get(k)
    if cat is None:
        return 'программы, системные и служебные файлы не копируются никогда'
    if cat == hb.CAT_DOC and d.docs_near and hb.CAT_DOC in d.cats:
        return 'документ не рядом с фото и видео: направление берёт документы только рядом с ними'
    return f'направление берёт только {_takes(d)}; это — {TYPE_WORD.get(k, "другие")}'


def _plan_list(kind, disk, num, target, drafts):
    """Списки «Разбора» (к копированию на target / уже есть / не подходит по типу) по направлению num - planner с collect
    (тот же расчёт, что ячейка): каждый файл один раз (исход файла единственный)."""
    outs = {'copy': hb.O_COPY, 'have': hb.O_HAVE, 'type': hb.O_TYPE}[kind]
    snap = snapshot()
    c = ro()                       # окно: своё соединение только для чтения, одно состояние базы (транзакция чтения)
    try:
        check_disk(c, disk)
    except Refused:
        c.close()
        raise
    c.execute('begin')
    try:
        dirs = hb.parse_directions(snap['directions'])
        d = dirs.get(num)
        if d is None:
            raise Refused(f'Нет направления {num}.')
        ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs, drafts)
        P = hb.planner(c, disk, dirs, ms, collect=(num, {outs}))
        if kind == 'copy':
            target = target or next((x for x in d.disks if x != disk), None)
            if not target or target not in d.disks or target == disk:      # не «на None» и не чужой диск
                raise Refused(f'Нет диска «{target}» среди дисков направления «{d.num} {d.name}» '
                              f'({", ".join(d.disks) or "диска нет"}) - список «к копированию» не построить.')
            items = [it for it in P.items if target in it[5]]
        else:
            items = list(P.items)
        _too_many(len(items))
        meta = _meta(c, disk, [it[0] for it in items])
        rows, notes, counts = [], [], collections.Counter()
        where = {}
        if kind == 'have':
            cd = sorted(set(d.disks) | set(hb.MAIN))
            where = _copies(c, {it[2] for it in items if it[2]}, cd, {(disk, it[0]) for it in items}, disk_letters(cd))
        for it in items:
            path, size, sha, k = it[0], it[1], it[2], it[3]
            mt, ev = meta.get(path, (None, None))
            why, wh = '', ''
            if kind == 'copy':
                st = it[6].get(target, ('nohash', ''))
                counts[st[0]] += 1
                if st[0] == 'rep':
                    why = f'нет на {target} (по SHA-256)'
                elif st[0] == 'nohash':
                    why = 'без хеша — сравнить нельзя, копируется'
                elif st[0] == 'dup':
                    why = f'повтор: то же содержимое, что «{st[1]}» — пишется один раз'
                else:
                    why = f'не будет скопирован: {st[1]}' + (f'; то же содержимое пишется из «{st[2]}»' if st[2] else '')
            elif kind == 'have':
                wh = '; '.join(where.get(sha, ()))
            else:
                why = _type_why(d, k)
            rows.append((disk, path, size, mt, ev, k, why, wh))
        if kind == 'copy':
            write = counts['rep'] + counts['nohash']
            pb = P.part_b.get(target, [0, 0])[0]
            notes.append(f'В задание войдёт {write} файлов — как в ячейке «Разбора»; повторы того же содержимого '
                         f'(пишутся один раз): {counts["dup"]}; не будут скопированы (заблокированы): {counts["blocked"]}.')
            if write != pb:
                notes.append(f'ВНИМАНИЕ: список не сходится с частью Б ({pb} файлов) - сообщите о расхождении.')
        if P.errors:
            notes.append('ИТОГ НЕВЕРЕН: ' + '; '.join(P.errors))
        why_text = {'copy': f'отмечены для «{d.num} {d.name}», а на {target} их нет по SHA-256 (или у файла нет хеша — '
                            'сравнить нельзя)',
                    'have': f'отмечены для «{d.num} {d.name}», и такой же файл (тот же SHA-256) уже есть на '
                            f'{" и ".join(d.disks)}',
                    'type': f'отмечены для «{d.num} {d.name}», но их тип не входит в «что копировать» направления '
                            f'({_takes(d)})'}[kind]
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.rollback()
        c.close()
    return dict(kind=kind, disk=disk, folder='', num=num, direction=f'{d.num} {d.name}', target=target,
                targets=list(d.disks), scope='весь носитель — отмеченные папки', why=why_text, notes=notes, rows=rows,
                built=gen)


def file_list(kind, disk, folder='', num=None, target=None, drafts=()):
    """Данные окна «Список файлов» (этап 16). kind - LIST_KINDS; folder - папка носителя (и вложенные; '' - весь
    носитель); num, target, drafts - для списков «Разбора». Ничего не пишет.
    -> dict(kind, disk, folder, scope, why, notes, rows, built, …)."""
    if kind not in LIST_KINDS:
        raise Refused(f'Неизвестный список «{kind}».')
    if kind in ('copy', 'have', 'type'):
        return _plan_list(kind, disk, num, target, list(drafts))
    folder = hb.clean_path(folder)
    c = ro()
    try:
        check_disk(c, disk)
        cond, args = hb.prefix_cond('path', folder)
        ft = hb.fast_folder_type(fine=True)
        rows, notes = [], []
        if kind == 'nohash':
            n = c.execute(f'select count(*) from files where disk=? and {NOHASH_SQL} and {cond}',
                          [disk] + args).fetchone()[0]
            _too_many(n)
            media = 0
            for path, size, mt, ev, nm in c.execute(f'select path, size, mtime, ev, name_lc from files where disk=? and '
                                                    f'{NOHASH_SQL} and {cond}', [disk] + args):
                k = ft(path, nm, size)
                if k in (hb.F_PHOTO, hb.F_VIDEO):
                    media += 1
                    why = '⚠ фото/видео без хеша — пересканируйте с типами «Фото» и «Видео»'
                elif ev in (hb.EV_SIZE, hb.EV_USER, hb.EV_STALE):
                    why = f'хеш не измерен: {hash_text(ev)}'
                else:
                    why = 'хеш не считался: тип не выбирался при сканировании'
                rows.append((disk, path, size, mt, ev, k, why, ''))
            if media:
                notes.append(f'Из них фото и видео: {media} — у них хеш должен быть: пересканируйте их папки.')
            why_text = 'у файла нет SHA-256 (размер больше нуля): копию нельзя проверить по содержимому'
        elif kind == 'contested':
            got = hb.contested_rows(c, disk, folder)
            _too_many(len(got))
            for d, path, size, mt, ev, why in got:
                rows.append((d, path, size, mt, ev, ft(path, hb.name_key(path), size or 0), why, ''))
            why_text = ('копию нельзя проверить по SHA-256: без хеша на этом носителе, тёзки без хеша и непроверенные '
                        'копии (Z/U/X) на 45 и 77')
        else:                                                   # unique
            fcond, fargs = hb.prefix_cond('f.path', folder)
            n = c.execute(f'select count(*) from files f join presence p on p.sha=f.sha where f.disk=? and '
                          f'f.sha is not null and p.ndisks=1 and {fcond}', [disk] + fargs).fetchone()[0]
            _too_many(n)                                         # предел - до того, как строки собраны в память
            q = (f'select f.path, f.size, f.mtime, f.ev, f.name_lc from files f join presence p on p.sha=f.sha '
                 f'where f.disk=? and f.sha is not null and p.ndisks=1 and {fcond}')
            for path, size, mt, ev, nm in c.execute(q, [disk] + fargs):
                rows.append((disk, path, size, mt, ev, ft(path, nm, size or 0),
                             'тот же SHA-256 подтверждён только на этом носителе', ''))
            n = c.execute(f'select count(*) from files where disk=? and {NOHASH_SQL} and {cond}',
                          [disk] + args).fetchone()[0]
            if n:
                notes.append(f'Ещё {n} файлов без хеша — есть ли они где-то ещё, по базе неизвестно (в список не вошли).')
            why_text = 'файл с хешем, подтверждённая копия (S/C) с тем же SHA-256 есть только на этом носителе'
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.close()
    return dict(kind=kind, disk=disk, folder=folder, scope=(folder or 'весь носитель'), why=why_text, notes=notes,
                rows=rows, built=gen)


def folders_files(disk, folders):
    """Сколько файлов в папках носителя (по таблице folders, вместе с подпапками) - для вопроса перед
    пересканированием из окна «Список файлов». -> {папка: файлов}."""
    c = ro()
    try:
        return {f: (c.execute('select files from folders where disk=? and folder=?', (disk, f)).fetchone() or [0])[0]
                for f in folders}
    finally:
        c.close()
