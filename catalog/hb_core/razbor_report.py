"""Логика v3, ядро разбора носителя: текст итога, группы, задания по отметкам (план без записи).
Часть бывшего hb_core/razbor.py (разбит 17.11.2026, код дословно)."""
import collections
import time
from hb_core.consts import SEP
from hb_core.razbor_scope import B_UNREAD
from hb_core.razbor_base import (B_CHECK, B_CONFLICT, B_TWIN, O_COPY, O_HAVE, O_JUNK, O_MOVED, O_NODISK, O_NONE, O_SKIP,
                                 O_TYPE, O_UNSET, ROOT_GROUP, ROOT_TITLE, copied_sub)

# ---------- текст итога ----------

def _n(x):
    return f'{x:,}'.replace(',', ' ')


def _gb(b):
    return f'{(b or 0) / 1024 ** 3:.2f}'.replace('.', ',')


def part_a_rows(P):
    """Строки части А в порядке показа: (подпись, файлов, байт)."""
    rows = []
    for num, d in P.dirs.items():
        for o, text in ((O_COPY, 'будет скопирован хотя бы на один его диск'), (O_HAVE, 'уже есть на всех его дисках'),
                        (O_TYPE, 'не подходит по типу, останется на месте'), (O_NODISK, 'диск не назначен, ждёт')):
            v = P.part_a.get((o, num))
            if v and v[0]:
                rows.append((f'{d.name}: {text}', v[0], v[1]))
    for o, text in ((O_SKIP, 'Не копировать'), (O_UNSET, 'Направление не задано (старый «раздел: …» без направления)'),
                    (O_NONE, 'Не отмечено (режим разбора не выбран)'),
                    (O_MOVED, 'Уже перенесено раньше («ПЕРЕНЕСЕНО → …», «Скопировано на …»)'),
                    (O_JUNK, 'Мусор (не копируется, едет вместе с папкой)')):
        v = P.part_a.get((o, None))
        if v and v[0]:
            rows.append((text, v[0], v[1]))
    return rows


def group_title(g):
    return ROOT_TITLE if g['folder'] is ROOT_GROUP else g['folder'].rsplit(SEP, 1)[-1]


WIN_BAD = set('\\/:*?"<>|') | {chr(i) for i in range(32)}


def safe_name(text):
    """Имя папки задания для Windows: запрещённые знаки -> «_», без точек и пробелов в конце (имя папки носителя
    могло прийти с другой файловой системы)."""
    t = ''.join('_' if ch in WIN_BAD else ch for ch in text).rstrip(' .')
    return t or '_'


def summary_lines(P):
    """Короткий итог для экрана (≤ 20 строк) и полный - для файла."""
    L = []
    lab = (P.info.get('label') or '').split(' - ', 1)[-1]
    L.append(f'Разбор {P.disk} {lab}: {_n(P.total[0])} файлов, {_gb(P.total[1])} ГБ; отметок {len(P.marks)}.')
    if P.errors:
        L.append('ИТОГ НЕВЕРЕН: ' + '; '.join(P.errors) + '. Задания не создаются.')
    L.append('А. Что будет с каждым файлом (файлов · ГБ):')
    for text, n, b in part_a_rows(P):
        L.append(f'  {text}: {_n(n)} · {_gb(b)}')
    if P.moved_copy[0]:
        L.append(f'  (из «будет скопирован» {_n(P.moved_copy[0])} лежат в уже перенесённых папках - копируются '
                 'дополнительно, второй раз не перемещаются)')
    L.append(f'  Итого = опись носителя: {_n(P.total[0])} · {_gb(P.total[1])}')
    if P.part_b:
        L.append('Б. Сколько писать: ' + '; '.join(f'на {d[3:] if d.startswith("HDD") else d}: {_n(v[0])} файлов, '
                                                  f'{_gb(v[1])} ГБ' for d, v in sorted(P.part_b.items())))
    else:
        L.append('Б. Писать на диски нечего.')
    return L


def attention_lines(P):
    L = []
    if P.info.get('is_target'):
        L.append(f'{P.disk} - диск направления «' + ', '.join(P.dirs[n].name for n in P.info['is_target']) +
                 '»: копировать с него можно, перемещать на нём ничего нельзя.')
    for d, (n, b) in sorted(P.unhashed_copy.items()):
        if n:
            extra = f'; на {d} есть тёзки (то же имя и размер) у {_n(P.namesakes[d])}' if d in P.namesakes else ''
            L.append(f'Без хеша к копированию на {d}: {_n(n)} файлов (сравнение только по имени и размеру{extra}).')
    why = collections.Counter((d, w) for _p, d, w, _s in P.blocked) + P.blocked_agg
    for (d, w), n in sorted(why.items()):
        hint = {B_CONFLICT: 'на месте назначения другое подтверждённое содержимое (или файл вместо папки) - не '
                            'копируются; решите вручную на диске',
                B_CHECK: 'путь назначения занят неподтверждённой записью - пересканируйте эту папку на диске',
                B_TWIN: 'у двух файлов носителя один путь назначения (тот же путь в «Скопировано на …» и вне её, '
                        'содержимое разное или без хеша) - не копируются; решите вручную на носителе',
                B_UNREAD: 'снова не прочитаны при пересканировании - не копируются (остальные копируются)'}[w]
        L.append(f'{d}: {_n(n)} файлов - {hint}.')
    st = P.info.get('status') or '?'
    if st != 'complete' or P.info.get('issues'):
        L.append(f'Опись: состояние «{st}», непрочитанных мест {_n(P.info.get("issues", 0))} - итог по тому, что описано.')
    sc = P.info.get('scanned')
    if sc:
        L.append('Дата описи: ' + time.strftime('%d.%m.%Y', time.localtime(sc)) + '.')
    return L


def group_rows(P):
    """Группы заданий для показа: (направление, папка, состояние, копировать файлов, ГБ, по дискам)."""
    res = []
    for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder']))):
        per = ', '.join(f'{d}: {_n(v[0])}' for d, v in sorted(g['per_disk'].items()))
        res.append((g['direction'], group_title(g) if g['folder'] is ROOT_GROUP else g['folder'], P.group_state(gk),
                    g['copy'][0], _gb(g['copy'][1]), per))
    return res


# ---------- задания (план без записи; записывает service.publish_tasks) ----------

def disk_word(d):
    return d[3:] if d.startswith('HDD') and d[3:].isdigit() else d


def task_specs(P, serials):
    """Задания по группам: одна группа (решающая отметка + папка) и её направление, и ОДИН диск назначения (этап 5:
    у «Семейного архива» - отдельное задание на 45 и на 77; что недостающее - своё для каждого диска). Имя у
    направления с несколькими дисками - «… — на 45». Обязательные диски задания - все диски направления (перемещение
    требует копий на всех). Этап 14: группа внутри служебной «Скопировано на …» (только из журнала перемещения) -
    sub = эта папка (подпапка источника в тома.tsv), пути строк и дублей - от неё: на диске назначения файл ляжет
    без «Скопировано на …», как при первом проходе. -> [dict], по группе, затем по диску."""
    specs, used = [], set()
    copied = set(P.info.get('copied') or ())
    for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder']))):
        targets = [d for d in g['disks'] if d != P.disk and P.rows.get((gk, d))]
        if not targets:
            continue
        group = safe_name(f'{P.disk} — {group_title(g)[:60]} — {g["direction"]}')
        sub = copied_sub(g['folder'], copied)
        for d in targets:
            base = group + (f' — на {disk_word(d)}' if len(g['disks']) > 1 else '')
            name, i = base, 2
            while name.lower() in used:
                name, i = f'{base} ({i})', i + 1
            used.add(name.lower())
            rows = sorted(set(P.rows[(gk, d)]), key=lambda r: (r[0], r[1]))
            deps = P.deps.get((gk, d), [])
            if sub:                                      # этап 14: пути - от подпапки источника (служебной папки)
                rows = [(r[0], _cut(r[1], sub)) + tuple(r[2:]) for r in rows]
                deps = [(_cut(x[0], sub), x[1], _cut(x[2], sub)) for x in deps]
            specs.append(dict(name=name, group=group, key=[g['row'], g['folder']], folder=g['folder'], num=g['num'],
                              direction=g['direction'], disks=list(g['disks']), targets=[d], kind=g['kind'],
                              mark=g['mark'], mark_row=g['row'], rows=rows, deps={d: deps}, sub=sub,
                              files=len(rows), bytes=sum(r[2] for r in rows),
                              serials={x: serials.get(x, 'НЕТ_СЕРИЙНОГО_НОМЕРА') for x in (P.disk, d)}))
    return specs


def _cut(path, sub):
    """Путь носителя внутри подпапки источника sub -> путь от неё. Группа второго прохода целиком лежит в своей
    служебной папке (отметки внутри неё действуют только там); иначе задание составлять нельзя."""
    if not path.startswith(sub + SEP):
        raise ValueError(f'«{path}» не внутри «{sub}»: задание второго прохода не составляется')
    return path[len(sub) + 1:]


def group_states(P):
    """Группы для манифеста: состояние каждой (в том числе «копировать нечего» - но это НЕ разрешение перемещать)."""
    return [dict(folder=g['folder'], title=group_title(g), num=g['num'], direction=g['direction'], disks=list(g['disks']),
                 kind=g['kind'], mark=g['mark'], mark_row=g['row'], state=P.group_state(gk), files_copy=g['copy'][0],
                 files_have=g['have'][0], files_type=g['type'][0], blocked=g['blocked'])
            for gk, g in sorted(P.groups.items(), key=lambda kv: (kv[1]['num'] or '', str(kv[1]['folder'])))]
