"""Логика v3: расчёт разбора, свободное место, задания по отметкам (razbor_tasks), спорные файлы.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import io
import os
import shutil
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import check_disk, db, Refused, ro, TableLock
from .directions_v3 import _read_snapshot, snapshot
from .read_disks import volumes


def _plan(disk, drafts=(), detail=False, snap=None):
    """Снимок таблиц + одно соединение с одним поколением базы (транзакция чтения) -> ядро planner."""
    snap = snap or snapshot()
    c = db()
    check_disk(c, disk)
    c.execute('begin')                                  # всё дальнейшее чтение - одно состояние базы
    try:
        dirs = hb.parse_directions(snap['directions'])
        ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs, drafts)
        P = hb.planner(c, disk, dirs, ms, detail)
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.rollback()
    P.info['signature'] = hb.signature(snap['sig'].encode(), str(gen).encode())
    P.info['built'] = gen
    return P


def razbor(disk, drafts=()):
    """Итог разбора носителя (без записи). drafts - несохранённые отметки окна [(путь, отметка)]: только для показа."""
    return _plan(disk, drafts)


def free_space(disks_):
    """Свободное место подключённых дисков: {диск: (буква, ГиБ)}. Диски не читаются (только размер тома)."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    res = {}
    for d in disks_:
        letter = vols.get(serial_of.get(d, '?'))
        if letter:
            try:
                res[d] = (letter, shutil.disk_usage(letter + '\\').free / hb.GIB)
            except OSError:
                pass
    return res


def _task_meta(task):
    import json
    try:
        return json.loads((Path(task) / 'разбор.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    """Целиком и заменой файла: читатель видит либо старое, либо новое содержимое."""
    import json
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def same_task(meta, disk, s):
    """Задание разбора meta уже покрывает spec s: тот же носитель, ключ группы, направление и набор «что копировать»
    (смена набора - новое задание, Дискуссия этапа 5, п. 11), и диск s среди его целей (старое общее задание на 45 и
    77 покрывает оба). Этап 14: и та же подпапка источника - задание второго прохода, составленное до этапа 14 (путь на
    диске назначения со «Скопировано на …»), подготовленным не считается."""
    return (meta.get('носитель') == disk and meta.get('ключ') == s['key'] and meta.get('направление') == s['num']
            and meta.get('что копировать') == s['kind'] and set(s['targets']) <= set(meta.get('цели') or [])
            and (meta.get('подпапка источника') or '') == (s.get('sub') or ''))


def _new_have_groups(disk, states):
    """Группы «все подходящие уже есть», которых ещё нет в готовых манифестах этого носителя (та же папка, строка
    отметки и направление). Без манифеста перенос такой папки не предлагается (этап 13: вторая копия, когда на втором
    диске всё уже есть по хешу). -> [группа]."""
    import json
    have = [g for g in states if g['state'] == hb.G_HAVE]
    if not have:
        return []
    known = set()
    for p in sorted(hb.RAZBORY.glob(f'{disk} *.json')) if hb.RAZBORY.exists() else []:
        try:
            m = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if m.get('статус') == 'готово':
            known |= {(g.get('folder'), g.get('mark_row'), g.get('num')) for g in m.get('группы', [])
                      if g.get('state') == hb.G_HAVE}
    return [g for g in have if (g['folder'], g['mark_row'], g['num']) not in known]


def razbor_tasks(disk, dry=True, only=None):
    """Задания копирования по отметкам: одно задание - одна группа (решающая отметка + папка), её направление и ОДИН
    диск назначения (этап 5: на 45 и на 77 - отдельные задания одной группы, поле «группа» в разбор.json). Всё под замком таблиц: снимок, расчёт, проверка имён, публикация (два генератора одновременно не работают).
    Публикация: манифест «создаётся» -> папки собираются в «_БАЗА\\разборы\\<…>.tmp» и переносятся в «Запускаемые
    скрипты» -> манифест «готово». Повтор после сбоя: задание с тем же ключом уже есть - «уже подготовлено»,
    создаются только недостающие. Ничего не копирует и не запускает. only - номера направлений (этап 6: кнопка
    ячейки направления; None - все). -> dict."""
    with TableLock():
        P = _plan(disk, detail=True, snap=_read_snapshot())
        if P.errors:
            raise Refused('Итог разбора не сходится (' + '; '.join(P.errors) + ') - задания не создаются.')
        serials = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
        specs = hb.task_specs(P, serials)
        states = hb.group_states(P)
        if only is not None:                                     # этап 6: задания только этих направлений
            only = set(only)
            specs = [s for s in specs if s['num'] in only]
            states = [g for g in states if g['num'] in only]
        made = [(t.name, _task_meta(t)) for t in (sorted(hb.TASKS.iterdir()) if hb.TASKS.exists() else ())
                if t.is_dir() and (t / 'разбор.json').exists()]
        made = [(n_, m) for n_, m in made if m and not m.get('повтор')]
        for s in specs:
            old = next((n_ for n_, m in made if same_task(m, disk, s)), None)
            if old:                                              # уже подготовлено (в том числе общим заданием на
                s['exists'], s['name'] = True, old               # 45 и 77 прежнего вида - под своим именем)
                continue
            base, i = s['name'], 2
            while True:
                meta = _task_meta(hb.TASKS / s['name']) if (hb.TASKS / s['name']).exists() else None
                if not (hb.TASKS / s['name']).exists():
                    break
                if meta and same_task(meta, disk, s):
                    s['exists'] = True
                    break
                s['name'], i = f'{base} ({i})', i + 1
        res = dict(plan=P, specs=specs, states=states, dry=dry, manifest=None)
        if dry or not ([s for s in specs if not s.get('exists')] or _new_have_groups(disk, states)):
            return res                                   # этап 13: «всё уже есть» - манифест и без новых заданий
        stamp = time.strftime('%Y-%m-%d %H-%M-%S')
        hb.RAZBORY.mkdir(parents=True, exist_ok=True)
        manifest = hb.RAZBORY / f'{disk} {stamp}.json'
        man = {'носитель': disk, 'дата': time.strftime('%d.%m.%Y %H:%M'), 'статус': 'создаётся',
               'подпись входов': P.info['signature'], 'поколение базы': P.info.get('built'),
               'носитель - диск направления': P.info.get('is_target') or [],
               'перемещать на носителе': not P.info.get('is_target'),
               'отметки': [dict(путь=m.path, решение=m.verdict, строка=m.row) for m in P.marks.by_key.values()],
               'задания': [dict(имя=s['name'], группа=s['group'], папка=s['folder'], направление=s['num'], диски=s['disks'],
                                цели=s['targets'],
                                файлов=s['files'], байт=s['bytes'], уже_было=bool(s.get('exists'))) for s in specs],
               'группы': states}
        _write_json(manifest, man)
        stage = hb.RAZBORY / f'{disk} {stamp}.tmp'
        stage.mkdir()
        hb.TASKS.mkdir(parents=True, exist_ok=True)
        for s in specs:
            if s.get('exists'):
                continue
            t = stage / s['name']
            t.mkdir()
            with io.open(t / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
                for r in s['rows']:
                    f.write('\t'.join(map(str, r)) + '\n')
            with io.open(t / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
                # этап 14: группа в «Скопировано на …» - третья колонка источника (подпапка, шаблон 2.2+): на диске
                # назначения файл ляжет без служебной папки, как при первом проходе
                f.write(f'{disk}\t{s["serials"][disk]}' + (f'\t{s["sub"]}' if s.get('sub') else '') + '\n')
                for d in s['targets']:
                    f.write(f'{d}\t{s["serials"][d]}\n')
            for name in ('Копировать.ps1', 'Запустить.cmd'):
                shutil.copy2(hb.TEMPLATE / name, t / name)
            _write_json(t / 'разбор.json', {
                'носитель': disk, 'ключ': s['key'], 'папка': s['folder'], 'направление': s['num'],
                'имя направления': s['direction'], 'обязательные диски': s['disks'], 'цели': s['targets'],
                'группа': s['group'], 'подпапка источника': s.get('sub') or '',
                'что копировать': s['kind'], 'отметка': s['mark'], 'строка отметки': s['mark_row'],
                'подпись входов': P.info['signature'], 'дата': man['дата'], 'манифест': manifest.name,
                'перемещать на носителе': not P.info.get('is_target'),
                'зависимые': {d: [list(x) for x in v] for d, v in s['deps'].items() if v}})
            os.replace(t, hb.TASKS / s['name'])
        try:
            stage.rmdir()
        except OSError:
            pass
        man['статус'] = 'готово'
        _write_json(manifest, man)
        res['manifest'] = manifest
    return res


def contested(disk, folder):
    """«Пересчитать хеши спорных файлов»: папки по дискам и подключён ли диск. -> [(диск, буква или '', [(папка, n)])]."""
    c = ro()                       # своё соединение только для чтения (этап 16: окно спрашивает и в фоне)
    try:
        check_disk(c, disk)
        got = hb.contested(c, disk, folder)
    finally:
        c.close()
    free = free_space(list(got))
    return [(d, free.get(d, ('', 0))[0], got[d]) for d in sorted(got)]


def contested_count(disk, folder=''):
    """Сколько спорных файлов (contested_rows: файл один раз) у папки носителя или у всего носителя - число на кнопке
    «Пересчитать хеши спорных файлов (N)» (этап 16). -> dict(total, carrier, copies)."""
    c = ro()
    try:
        check_disk(c, disk)
        rows = hb.contested_rows(c, disk, folder)
    finally:
        c.close()
    own = sum(1 for r in rows if r[0] == disk)
    return dict(total=len(rows), carrier=own, copies=len(rows) - own)
