"""Логика v3: направления (снимок отметок, таблица направлений, предпросмотр и запись).

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import append_row, append_rows, backup, check_disk, db, Refused, TableLock


# ---------- логика v3: направления, отметки разбора, задания по отметкам (15.11.2026) ----------
# Документ - «Проверка Архитектуры сортировки файлов\Логика_v3_разбор_носителя.md». Направления - «_БАЗА\направления.tsv»
# (только дописывание, действует последняя строка номера), отметки - строки «решения.tsv» новых видов. Расчёт - ядро
# (hb_core/razbor.py), здесь - снимок входов под замком, проверки, запись и публикация заданий.

KIND_WORDS = {'фото': hb.KIND_MEDIA, 'фото, видео и документы рядом': hb.KIND_MEDIA, 'медиа': hb.KIND_MEDIA,
              'все': hb.KIND_ALL, 'все файлы': hb.KIND_ALL}
DEFAULT_DIRECTIONS = [    # ответы владельца 15.11.2026 (В4, В5): у «Семейного архива» 45 и 77, у остальных - свой диск
    dict(name='Семейный архив', disks=['HDD45', 'HDD77'], kind=hb.KIND_MEDIA, former=[],
         note='две копии; фото, видео и документы рядом'),
    dict(name='Работа и Сафари', disks=['HDD78'], kind=hb.KIND_ALL, former=['Сафари', 'Работа'],
         note='диск 78 «Работа Сафари 6ТБ»; одно направление (В4)'),
    dict(name='Фильмы', disks=['HDD55'], kind=hb.KIND_ALL, former=[], note='диск 55 My Book 2 ТБ (В5)'),
    dict(name='Оцифрованные источники', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
    dict(name='Саша, Таня, Наташа', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
    dict(name='Разные', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
]


def _read_snapshot():
    """Обе таблицы целиком в память; подпись - по тем же байтам (спор с GPT, раунд 2, п. 4). Без замка."""
    dec, dirs = hb.table_bytes(hb.DECISIONS), hb.table_bytes(hb.DIRECTIONS)
    return dict(decisions=dec, directions=dirs, sig=hb.signature(dec, dirs))


def snapshot():
    """Согласованный снимок таблиц владельца: читается под замком таблиц (никто не пишет в это время)."""
    with TableLock():
        return _read_snapshot()


def directions(snap=None):
    return hb.parse_directions((snap or _read_snapshot())['directions'])


def _ensure_directions():
    hb.BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not hb.DIRECTIONS.exists():
        hb.DIRECTIONS.write_text(hb.DIRECTION_HEAD + '\n', encoding='utf-8-sig')


def _norm_kind(kind):
    """«Что копировать» -> текст колонки. Принимает старые слова («фото», «все» …), текст набора категорий («фото,
    видео, документы рядом, архивы») или (набор, рядом). Пустой набор и неизвестное слово - отказ (этап 5)."""
    if isinstance(kind, (tuple, list)) and len(kind) == 2 and not isinstance(kind[0], str):
        cats, near = kind
        if not cats:
            raise Refused('Что копировать: отметьте хотя бы одну категорию файлов.')
        bad = set(cats) - set(hb.COPY_CATS)
        if bad:
            raise Refused('Что копировать: неизвестная категория ' + ', '.join(sorted(bad)) + '.')
        return hb.kind_text(cats, near)
    k = ' '.join((kind or '').split()).lower()
    if k in KIND_WORDS:
        return KIND_WORDS[k]
    cats, near, ok = hb.parse_kind(k)
    if not k or not ok:
        raise Refused('Что копировать: «фото» (фото, видео и документы рядом), «все» (все файлы, кроме программ, '
                      'системных и временных) или категории через запятую: ' + ', '.join(hb.COPY_CATS) +
                      f' («{hb.DOCS_NEAR_WORD}» - документы только рядом с фото и видео).')
    return hb.kind_text(cats, near)


def direction_preview(num=None, name=None, disks=None, add_disks=(), kind=None, former=(), note=None, dirs=None, c=None):
    """Новое направление (num=None) или новая версия направления num. Проверки - логика v3, 1.1 и 2.1.
    disks - заменить список дисков (None - оставить); add_disks - добавить. -> dict(fields, lines, direction)."""
    dirs = directions() if dirs is None else dirs
    cur = None
    if num:
        n = hb.norm_num(num)
        cur = dirs.get(n) or hb.find_direction(dirs, num)
        if not cur:
            raise Refused(f'Нет направления «{num}». Есть: ' + (', '.join(f'{d.num} {d.name}' for d in dirs.values()) or 'никаких'))
        num = cur.num
    else:
        if not (name or '').strip():
            raise Refused('Нужно имя нового направления.')
        num = f'Н{max([hb.num_key(x) for x in dirs] + [0]) + 1}'
    new_name = (name or (cur.name if cur else '')).strip()
    err = hb.check_name(new_name)
    if err:
        raise Refused(err)
    for d in dirs.values():
        if d.num != num and new_name.casefold() in {x.casefold() for x in (d.name,) + d.former}:
            raise Refused(f'Имя «{new_name}» уже занято направлением {d.num} «{d.name}» (как имя или прежнее имя).')
    fm = list(cur.former) if cur else []
    for x in list(former) + ([cur.name] if cur and cur.name != new_name else []):
        x = x.strip()
        if x and x.casefold() != new_name.casefold() and x.casefold() not in {y.casefold() for y in fm}:
            for d in dirs.values():
                if d.num != num and x.casefold() in {y.casefold() for y in (d.name,) + d.former}:
                    raise Refused(f'Прежнее имя «{x}» уже у направления {d.num} «{d.name}».')
            fm.append(x)
    dl = list(cur.disks) if (cur and disks is None) else list(disks or [])
    for x in add_disks or ():
        if x not in dl:
            dl.append(x)
    dl = list(dict.fromkeys(x.strip() for x in dl if x.strip()))
    c = c or db()
    for x in dl:
        check_disk(c, x)
        other = hb.direction_of_disk({k: v for k, v in dirs.items() if k != num}, x)
        if other:
            raise Refused(f'Диск {x} уже у направления {other.num} «{other.name}»: один диск - одному направлению.')
    k = _norm_kind(kind) if kind else (cur.kind if cur else hb.KIND_ALL)
    nd = hb.Direction(num, new_name, tuple(fm), tuple(dl), k, (note if note is not None else (cur.note if cur else '')).strip())
    if cur and nd == cur:
        raise Refused('Ничего не меняется.')
    lines = [f'{"Изменить" if cur else "Новое направление"} {num} «{nd.name}»: диски {", ".join(nd.disks) or "не назначены"}; '
             f'что копировать: {nd.kind}.',
             f'Папка на носителе после переноса: «{nd.folder()}».' if nd.disks else
             'Без диска: отмечать папки можно, задания не создаются, пока не назначен диск.']
    if nd.former:
        lines.append('Прежние имена (старые «раздел: …» с ними сразу относятся к этому направлению): ' + ', '.join(nd.former))
    if cur and set(cur.disks) != set(nd.disks):
        lines.append('Смена дисков касается только НОВЫХ заданий; уже созданные требуют свои прежние диски.')
    return dict(fields=hb.direction_row(nd), lines=lines, direction=nd)


def add_direction(note=None, **kw):
    with TableLock():
        snap = _read_snapshot()
        pv = direction_preview(note=note, dirs=hb.parse_directions(snap['directions']), **kw)
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_row(hb.DIRECTIONS, pv['fields'])
    return pv


def directions_batch_preview(items, dirs=None):
    """Несколько направлений одним пакетом: всё или ничего (directions-default)."""
    dirs = dict(directions() if dirs is None else dirs)
    c = db()
    res, lines = [], []
    for it in items:
        cur = hb.find_direction(dirs, it['name'], by_num=False)
        if cur and cur.name == it['name'] and set(cur.disks) >= set(it['disks']):
            lines.append(f'{cur.num} «{cur.name}» уже есть - пропускаю.')
            continue
        pv = direction_preview(num=cur.num if cur else None, name=it['name'], disks=it['disks'] if not cur else None,
                               add_disks=it['disks'] if cur else (), kind=it['kind'], former=it.get('former', ()),
                               note=it.get('note', ''), dirs=dirs, c=c)
        dirs[pv['direction'].num] = pv['direction']
        res.append(pv['fields'])
        lines += pv['lines']
    if not res:
        raise Refused('Все направления по умолчанию уже заведены - записывать нечего.')
    return dict(fields=res, lines=lines)


def add_directions_batch(items):
    with TableLock():
        snap = _read_snapshot()
        pv = directions_batch_preview(items, hb.parse_directions(snap['directions']))
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_rows(hb.DIRECTIONS, pv['fields'])
    return pv
