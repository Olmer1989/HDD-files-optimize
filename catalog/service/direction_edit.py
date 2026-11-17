"""Экран «Направления» и шаблон копирования 2.4 (логика v3, этап 4): использование, правка, версия шаблона.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections
import re
from pathlib import Path

from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import append_row, backup, Refused, ro, SEP, TableLock
from .directions_v3 import _ensure_directions, _norm_kind, _read_snapshot, direction_preview, directions
from .razbor_plan import _task_meta


# ---------- экран «Направления» и шаблон копирования 2.4 (логика v3, этап 4, 15.11.2026; directions_page.py) ----------
# Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 4». Описание направления («что собирается на этих дисках») -
# 7-я колонка направления.tsv (hb_core/directions.py). Смена дисков у направления с заданиями: предпросмотр показывает
# задания по журналам и отметки; убрать диск, на который у направления есть задания, - только с подтверждением (ack).

DESC_MAX = 200
GOOD_COPY = ('скопирован', 'уже есть')


def direction_usage(num, dirs=None, root=None):
    """Что уже сделано по направлению: задания (по разбор.json в папках заданий) с ходом по каждой цели ПО ЖУРНАЛАМ
    и число действующих отметок папок. -> dict(tasks=[dict(name, disks, targets, per={диск: (хорошо, всего)},
    state)], marks={носитель: n}). «хорошо» - строки журнала «скопирован…» или «уже есть» (это не доказательство
    копии: подтверждение даёт только база по SHA-256)."""
    dirs = directions() if dirs is None else dirs
    root = Path(root or hb.TASKS)
    tasks_ = []
    if root.exists():
        for t in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = _task_meta(t)
            if not meta or meta.get('направление') != num:
                continue
            total = collections.Counter(f[0] for f in hb.read_tsv(t / 'список.tsv') if len(f) >= 3) \
                if (t / 'список.tsv').exists() else collections.Counter()
            good = collections.defaultdict(set)
            logs = sorted(t.glob('Журнал копирования *.tsv'))
            for log in logs:
                for f in hb.read_tsv(log)[1:]:
                    if len(f) >= 7 and f[2].startswith(GOOD_COPY):
                        good[f[1]].add(f[5].lower())
            per = {d: (min(len(good[d]), total[d]), total[d]) for d in (meta.get('цели') or sorted(total))}
            if not logs:
                state = 'не запускалось'
            elif all(g >= n for g, n in per.values()):
                state = 'по журналам все строки пройдены'
            else:
                state = 'по журналам не всё'
            tasks_.append(dict(name=t.name, disks=meta.get('обязательные диски') or [], targets=meta.get('цели') or [],
                               per=per, state=state))
    marks = collections.Counter()
    data = hb.table_bytes(hb.DECISIONS)
    last = {}
    for i, f in enumerate(hb.tsv_rows(data[:data.rfind(b'\n') + 1]), start=1):
        f = hb.row_fields(f, paths=(1,), pad=3)          # путь - как в таблице (этап 16)
        if i == 1 and f[0].lower() == 'диск':
            continue
        if f[1].lower().startswith('класс:') or not f[2]:
            continue
        last[(f[0], f[1].strip(SEP).lower())] = f[2]
    for (disk, _p), verdict in last.items():
        kind, n, _, _ = hb.parse_verdict(verdict, dirs)
        if kind == hb.R_DIR and n == num:
            marks[disk] += 1
    return dict(tasks=tasks_, marks=dict(marks))


def copied_name(d):
    return d.folder() or f'Скопировано на {d.name} (диск не назначен)'


def _disk_has_data(disk, c=None):
    """Есть ли в базе файлы на диске (подтверждённые копии могли попасть туда и без папок заданий). Только чтение."""
    own = c is None
    try:
        c = c or ro()
        try:
            return c.execute('select 1 from files where disk=? limit 1', (disk,)).fetchone() is not None
        finally:
            if own:
                c.close()
    except Refused:                                      # базы ещё нет (ro): данных о диске нет
        return False
    except Exception:                                    # noqa: BLE001 - ошибка чтения базы: переспросить на всякий случай
        return True


def _usage_lines(cur, nd, dirs, root=None, c=None):
    """Строки предпросмотра смены дисков. -> (строки, убранные диски, на которые у направления есть задания,
    нужно ли переспросить владельца). Переспрос (этап 5, п. 2): убирается или заменяется диск, а у направления есть
    задания или на убираемом диске есть данные в базе (Дискуссия этапа 5, п. 9: копии могли лечь туда и без заданий).
    Только добавление диска - без переспроса."""
    use = direction_usage(cur.num, dirs, root)
    old, new = list(cur.disks), list(nd.disks)
    removed, added = [d for d in old if d not in new], [d for d in new if d not in old]
    lines = []
    if use['tasks']:
        lines.append(f'У направления уже подготовлено заданий: {len(use["tasks"])}. Ход по журналам копирования '
                     '(журнал - не подтверждение; подтверждает база по SHA-256):')
        for t in use['tasks'][:8]:
            per = ', '.join(f'{d}: {g} из {n}' for d, (g, n) in t['per'].items())
            lines.append(f'  «{t["name"]}» - {t["state"]} ({per})')
        if len(use['tasks']) > 8:
            lines.append(f'  … и ещё {len(use["tasks"]) - 8}')
        lines.append('Уже созданные задания и перемещения по ним по-прежнему требуют копий на своих прежних дисках '
                     f'({", ".join(sorted({d for t in use["tasks"] for d in t["disks"]}))}).')
    if use['marks']:
        lines.append('Отмечено папок этим направлением: ' + ', '.join(f'{d}: {n}' for d, n in sorted(use['marks'].items()))
                     + '. Новые задания по этим отметкам пойдут на новый набор дисков.')
    if old:
        lines.append('Прежние копии на новый диск сами не попадут: что не хватает на новом диске, покажет итог разбора '
                     'носителя (строка «копировать на …»).')
        lines.append(f'Папки «{copied_name(cur)}» на носителях не переименовываются; новые будут «{copied_name(nd)}».')
    risky, confirm = [], False
    for d in removed:
        n = sum(1 for t in use['tasks'] if d in t['targets'] or d in t['disks'])
        data = _disk_has_data(d, c)
        lines.append(f'Диск {d} перестаёт быть диском направления; всё, что на нём уже скопировано, остаётся на нём, '
                     'но направлению больше не засчитывается: «уже есть» для новых заданий считается только по новым '
                     'дискам. Для перемещения файлов, которые прежние задания ставили на этот диск, он остаётся '
                     'обязательным.' + (f' На этот диск у направления заданий: {n} - нужно подтверждение.' if n else ''))
        if n:
            risky.append(d)
        if n or use['tasks'] or data:
            confirm = True
    for d in added:
        busy = [f'{x.num} «{x.name}»' for x in dirs.values() if x.num != cur.num
                and any(d in t['targets'] for t in direction_usage(x.num, dirs, root)['tasks'])]
        if busy:
            lines.append(f'На диск {d} раньше шли задания направлений {", ".join(busy)}: их копии остаются там.')
    return lines, risky, confirm


def direction_save_preview(num=None, name=None, disks=None, kind=None, desc=None, dirs=None, c=None, root=None):
    """Окно «Направления»: новое направление (num=None) или полная новая версия: имя, диски (ПОЛНЫЙ список; None -
    оставить), что копировать, описание (None - оставить). Проверки - ядро direction_preview (имя, прежние имена,
    один диск - одному направлению, диск есть в базе). Одна строка таблицы.
    -> dict(fields, lines, direction, needs_ack=[убранные диски, на которые есть задания], confirm - окну переспросить
    владельца перед записью (этап 5: только смена/удаление диска у направления с заданиями или данными))."""
    import dataclasses
    dirs = directions() if dirs is None else dirs
    d_txt = None if desc is None else ' '.join(str(desc).split())
    if d_txt is not None and len(d_txt) > DESC_MAX:
        raise Refused(f'Описание длиннее {DESC_MAX} знаков.')
    cur = None
    if num:
        cur = dirs.get(hb.norm_num(num)) or hb.find_direction(dirs, num)
        if not cur:
            raise Refused(f'Нет направления «{num}».')
    want = None if disks is None else list(dict.fromkeys(x.strip() for x in disks if x and x.strip()))
    core_same = cur is not None and (name is None or name.strip() == cur.name) \
        and (want is None or want == list(cur.disks)) and (kind is None or _norm_kind(kind) == cur.kind)
    if core_same:
        if d_txt is None or d_txt == (cur.desc or ''):
            raise Refused('Ничего не меняется.')
        nd = dataclasses.replace(cur, desc=d_txt)
        lines = [f'Изменить {cur.num} «{cur.name}»: только описание.']
    else:
        pv = direction_preview(num=cur.num if cur else None, name=name, disks=want, kind=kind, dirs=dirs, c=c)
        nd = dataclasses.replace(pv['direction'], desc=d_txt if d_txt is not None else ((cur.desc or '') if cur else ''))
        lines = list(pv['lines'])
    if d_txt is not None and d_txt != ((cur.desc or '') if cur else ''):
        lines.append(f'Что собирается на дисках: «{d_txt}».' if d_txt else 'Описание будет стёрто.')
    risky, confirm = [], False
    if cur and list(cur.disks) != list(nd.disks):
        more, risky, confirm = _usage_lines(cur, nd, dirs, root, c)
        lines += more
    return dict(fields=hb.direction_row(nd), lines=lines, direction=nd, needs_ack=risky, confirm=confirm or bool(risky))


def direction_save(ack=False, **kw):
    """Запись из окна: под замком таблиц снова предпросмотр по свежей таблице, затем одна строка (копия - в архив)."""
    with TableLock():
        snap = _read_snapshot()
        pv = direction_save_preview(dirs=hb.parse_directions(snap['directions']), **kw)
        if pv['needs_ack'] and not ack:
            raise Refused('Диск ' + ', '.join(pv['needs_ack']) + ' убирается из направления, у которого есть задания на '
                          'него. Поставьте галочку «Понимаю…» и сохраните снова.')
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_row(hb.DIRECTIONS, pv['fields'])
    return pv


TEMPLATE_VER_RE = re.compile(r'версия (\d+)\.(\d+)')


def copy_template_version(task):
    """Версия шаблона копирования в папке задания: (2, 6) / (2, 5) / (2, 4) / (2, 3) / None. Для очереди: -Confirmed
    понимают только задания 2.4 и новее (2.5 и 2.6 - как 2.4: те же параметры, отпечаток и коды выхода; сравнивать
    кортежем `>= (2, 4)`); старые в автоматическую очередь не включаются (Дискуссия этапа 4, р2-7). Задание хранит свою
    копию шаблона: задания, подготовленные с 2.5, так и работают с 2.5."""
    try:
        with open(Path(task) / 'Копировать.ps1', encoding='utf-8-sig') as f:
            m = TEMPLATE_VER_RE.search(f.readline())
    except OSError:
        return None
    return (int(m.group(1)), int(m.group(2))) if m else None


def copy_task_fingerprint(task):
    """Отпечаток задания для подтверждения в окне (шаблон 2.4, параметр -Expect): SHA-256 байтов список.tsv + 0 +
    тома.tsv + 0 + разбор.json (нет файла - пусто), заглавными; и объём по целям из ТЕХ ЖЕ байтов: {цель: (файлов,
    байт)}. Окно показывает владельцу объём по целям, шаблону передаёт отпечаток: изменилось что-то - шаблон не начнёт."""
    import hashlib
    task = Path(task)
    lst = (task / 'список.tsv').read_bytes()
    vol = (task / 'тома.tsv').read_bytes()
    raz = (task / 'разбор.json').read_bytes() if (task / 'разбор.json').exists() else b''
    sha = hashlib.sha256(lst + b'\0' + vol + b'\0' + raz).hexdigest().upper()
    per = collections.defaultdict(lambda: [0, 0])
    for f in hb.tsv_rows(lst):
        if len(f) >= 3 and f[2].strip().isdigit():
            per[f[0]][0] += 1
            per[f[0]][1] += int(f[2])
    return dict(sha=sha, per={k: tuple(v) for k, v in per.items()})
