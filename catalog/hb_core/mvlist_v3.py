"""Команда mvlist (часть 2, разбивка 17.11.2026): логика v3 - источник переноса, записи переносов, расчёт plan_v3."""
import collections
import sys
from pathlib import Path
import build_pilot as bp
from hb_core import paths
from hb_core.consts import COPIED_PREFIX, EV_COPY, EV_SCAN, MAIN, SEP
from hb_core.sources import read_tsv
from hb_core.query import check_disk
from hb_core import razbor as rz
from hb_core.mvlist_v1 import COPY_OK, _task_dirs, task_info, history, resolve_task

# ---------- логика v3, этап 3: перенос папки разбора в «Скопировано на <направление> (<диски>)» ----------
# Документ - «Проверка Архитектуры сортировки файлов\\Логика_v3_разбор_носителя.md» (1.7, раздел «Этап 3»).
# Вход - задание копирования разбора (разбор.json) или группа манифеста, где копировать нечего. Переносится файл,
# подтверждённый (S или C с SHA-256 этой версии) на всех обязательных дисках: дисках задания и всех дисках, куда его
# ставило любое задание копирования с этого носителя. Мусор и пустые файлы едут вместе. Папка целиком (одним
# переименованием) - если в базе ВСЕ её файлы переносятся; шаблон ещё раз сверяет оглавление перед переименованием.

V3_SUFFIX = ' — перемещение'
V3_META = 'перемещение.json'
COPY_META = 'разбор.json'
ROOT_WORD = '(файлы в корне)'
R_OWN = 'своя отметка у подпапки или файла - у них своё задание'
R_NOHASH = 'без хеша в описи, хеш при копировании не записан'
R_NODATE = 'без хеша и без даты изменения в описи'
R_ERR = 'ошибка копирования'
R_WAIT = 'ждёт задания копирования'
R_WEAK = 'копия не подтверждена (в базе только сверка по размеру)'
R_NONE = 'копии на диске нет (не подходит направлению по типу или заблокирован)'
R_BUSY = 'в назначении уже есть файл'


def _json(path):
    import json
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    import json
    import os
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def v3_source(task=None, manifest=None, group=None):
    """Что переносим: задание копирования разбора или группа манифеста («все подходящие уже есть») -> dict."""
    if task:
        tdir = resolve_task(task)
        m = _json(tdir / COPY_META)
        if not m:
            sys.exit(f'«{tdir.name}» - не задание разбора (нет {COPY_META}). Для старых заданий: mvlist --task.')
        if m.get('повтор'):
            sys.exit(f'«{tdir.name}» - повтор копирования. Переносите по исходному заданию «{m["повтор"]}».')
        return dict(copy_task=tdir.name, copy_dir=tdir, manifest=m.get('манифест'), disk=m['носитель'],
                    folder=m.get('папка'), key=m.get('ключ'), num=m['направление'], direction=m['имя направления'],
                    disks=list(m['обязательные диски']), mark=m['отметка'], mark_row=m['строка отметки'],
                    allowed=m.get('перемещать на носителе', True), group=m.get('группа'))
    mp = Path(manifest)
    if not mp.is_absolute():
        mp = paths.RAZBORY / manifest
    man = _json(mp)
    if not man:
        sys.exit(f'Нет манифеста разбора: {mp}')
    want = None if group in (None, '', ROOT_WORD) else group.strip(SEP)
    g = next((x for x in man.get('группы', []) if x.get('folder') == want), None)
    if not g:
        sys.exit(f'В манифесте «{mp.name}» нет папки «{group}».')
    if g.get('state') != rz.G_HAVE:
        sys.exit(f'Папка «{group}»: {g.get("state")}. Без задания копирования переносится только папка, где все '
                 'подходящие файлы уже есть на всех дисках направления.')
    return dict(copy_task=None, copy_dir=None, manifest=mp.name, disk=man['носитель'], folder=want,
                key=[g['mark_row'], want], num=g['num'], direction=g['direction'], disks=list(g['disks']),
                mark=g['mark'], mark_row=g['mark_row'], allowed=man.get('перемещать на носителе', True))


def v3_title(src):
    return ROOT_WORD if src['folder'] is None else src['folder'].rsplit(SEP, 1)[-1]


def v3_task_name(src):
    base = src.get('group') or src['copy_task'] or rz.safe_name(f'{src["disk"]} — {v3_title(src)[:60]} — {src["direction"]}')
    return base + V3_SUFFIX


def _decisive(ms, path, roots=()):
    """Решающая отметка пути: самая глубокая из него самого и его папок (как маршрут разбора). Внутри «Скопировано на
    …» (roots) - только отметки, поставленные внутри неё; отметка всего носителя туда не проникает (этап 13)."""
    parts = path.split(SEP) if path else []
    low = 1 if parts and parts[0] in roots and parts[0].startswith(COPIED_PREFIX) else 0
    for i in range(len(parts), low - 1, -1):
        m = ms.get(SEP.join(parts[:i]))
        if m:
            return m
    return None


def _copy_tasks(src, serials, jobs):
    """Задание копирования, его «соседи» (этап 5: задания той же группы на другие диски направления - на 45 и на 77
    отдельно; тот же носитель, ключ, направление и поле «группа») и все их повторы -> [task_info]."""
    metas = []
    for d in _task_dirs():
        m = _json(d / COPY_META) if (d / COPY_META).exists() else None
        if m and m.get('носитель') == src['disk'] and m.get('ключ') == src['key']:
            metas.append((d, m))
    names = {src['copy_task']}
    if src.get('group'):
        names |= {d.name for d, m in metas if not m.get('повтор') and m.get('группа') == src['group']
                  and m.get('направление') == src['num']}
    res = []
    for d, m in metas:
        if d.name in names or m.get('повтор') in names:
            info = task_info(d, serials, jobs)
            if info:
                res.append(info)
    return res


def _moved_done(task):
    """Перенос задания перемещения выполнялся: в его журнале есть строка «перемещён» или «уже перемещён»."""
    for log in Path(task).glob('Журнал перемещения *.tsv'):
        if any(len(f) >= 2 and f[1] in ('перемещён', 'уже перемещён') for f in read_tsv(log)[1:]):
            return True
    return False


def move_metas(disk=None):
    """Записи ВЫПОЛНЕННЫХ заданий перемещения v3 (перемещение.json и журнал с «перемещён») этого носителя -> [dict]:
    части имени и обязательные диски служебных папок. Одно имя «Скопировано на …» на разных носителях - норма,
    поэтому - только свой носитель (проверка ядра этапа 13, п. 1)."""
    res = []
    for root in (paths.TASKS, bp.OUT_DIR):
        root = Path(root)
        if root.exists():
            for d in sorted(root.iterdir()):
                m = _json(d / V3_META) if (d / V3_META).exists() else None
                if m and m.get('версия') == 3 and (disk is None or m.get('носитель') == disk) and _moved_done(d):
                    res.append(m)
    return res


def second_dest(r1, src, metas=None):
    """Второй проход (этап 13): папка, в которую переименуется служебная r1 после копии на диски src. -> (r2, части,
    диски r1 по записям переносов). Части r1 - из записей заданий перемещения («части»; у первого прохода - хвост его
    направления). Отказ (sys.exit): нет записи выполненного переноса в r1 на этом носителе (история папки неизвестна -
    обязательный диск первого прохода не теряется молча; проверка ядра этапа 13, п. 2), диски src уже учтены в r1,
    имя длинное."""
    from hb_core.util import COPIED_NAME_MAX, copied_join, copied_tail
    metas = move_metas(src.get('disk')) if metas is None else metas
    parts, r1_disks = [], set()
    for m in metas:
        if m.get('куда') != r1 or (src.get('disk') and m.get('носитель') != src['disk']):
            continue
        r1_disks |= set(m.get('обязательные диски') or [])
        own = m.get('части') or ([copied_tail(m.get('имя направления', ''), m['обязательные диски'])]
                                 if m.get('обязательные диски') else [])
        for t in own:
            if t.casefold() not in {x.casefold() for x in parts}:
                parts.append(t)
    if not parts or not r1_disks:
        sys.exit(f'«{r1}»: не найдена история этой папки (задание перемещения, которое её создало на {src.get("disk")}, '
                 'и его журнал) - на какие диски копия уже подтверждена, неизвестно. Перемещение не предлагается: '
                 'верните папку задания перемещения в «Запускаемые скрипты» или решите вручную.')
    tail = copied_tail(src['direction'], src['disks'])
    r2 = copied_join(parts + [tail])
    if r2 == r1 or (r1_disks and set(src['disks']) <= r1_disks):
        sys.exit(f'«{r1}»: копия на {", ".join(src["disks"])} в имени этой папки уже учтена - переименовывать некуда.')
    if len(r2) > COPIED_NAME_MAX:
        sys.exit(f'Имя «{r2}» длиннее {COPIED_NAME_MAX} знаков: папка не переименовывается (путь на носителе станет '
                 'слишком длинным). Решите вручную.')
    return r2, parts + [tail], r1_disks


def plan_v3(c, jobs, src, only=None):
    """Расчёт переноса одной папки разбора без записи на диск. only - только эти пути (повторная проверка).
    Этап 13: папка внутри «Скопировано на A» (или сама она) - второй проход: файлы переезжают в «Скопировано на A и B»
    с тем же путём внутри (без вложенности); обязательны и диски, которых требовал перенос в A."""
    from hb_core.consts import C_EMPTY, C_JUNK
    from hb_core.directions import MarkSet, mark_rows, read_directions, table_bytes
    from hb_core.util import class_of, copied_folder
    disk, F = src['disk'], src['folder']
    check_disk(c, disk)
    dirs = read_directions()
    own = [d.name for d in dirs.values() if disk in d.disks]
    if disk in MAIN or own or disk in src['disks'] or not src['allowed']:
        sys.exit(f'{disk} - сам диск направления' + (f' «{", ".join(own)}»' if own else '') +
                 ': копировать с него можно, перемещать на нём ничего нельзя.')
    if not src['disks']:
        sys.exit(f'У направления «{src["direction"]}» в задании нет дисков - перемещать некуда.')
    roots = rz.moved_roots(c, disk)
    copied = {r for r in roots if r.startswith(COPIED_PREFIX)}
    r1 = F.split(SEP, 1)[0] if F else None
    if r1 not in copied:
        r1 = None
    if F and F.split(SEP, 1)[0] in roots and not r1:
        sys.exit(f'«{F}» уже лежит в старой служебной папке «ПЕРЕНЕСЕНО → …»: второй раз папка не перемещается.')
    ms = MarkSet.build(mark_rows(disk, table_bytes(paths.DECISIONS)), dirs)
    m = _decisive(ms, F or '', copied)
    if not m or m.row != src['mark_row'] or m.verdict != src['mark'] or m.num != src['num']:
        sys.exit(f'Отметка папки «{F or ROOT_WORD}» изменилась после подготовки задания (было «{src["mark"]}», строка '
                 f'{src["mark_row"]}; сейчас «{m.verdict if m else "нет отметки"}»). Разберите носитель заново.')
    r1_disks = set()
    if r1:
        dest, parts_, r1_disks = second_dest(r1, src)
    else:
        dest, parts_ = copied_folder(src['direction'], src['disks']), None

    def new_of(path):
        """Путь после переноса: «A\\x» -> «<dest>\\A\\x»; второй проход: «<r1>\\x» -> «<dest>\\x», «<r1>» -> «<dest>»."""
        if r1:
            rest = path[len(r1) + 1:] if path.startswith(r1 + SEP) else ''
            return dest + (SEP + rest if rest else '')
        return dest + SEP + path
    known = dest in copied
    dcond, dargs = rz.inside_cond('path', dest)
    if not known and c.execute(f'select 1 from files where disk=? and {dcond} limit 1', [disk] + dargs).fetchone():
        sys.exit(f'На {disk} уже есть папка «{dest}», но её создала не программа (журнала перемещения нет). '
                 'Переименуйте её на диске или пересканируйте - иначе файлы смешаются.')
    base = (set(src['disks']) | r1_disks) - {disk}
    planned, events, _tasks = history(disk, jobs)
    full = c.execute('select scanned from disks where disk=?', (disk,)).fetchone()
    rz_seen = (full[0] or 0) if full else 0
    parts = [(f, t) for f, t in c.execute('select folder, time from scan_folders where disk=?', (disk,))]

    def seen_at(path):
        t = rz_seen
        for f, pt in parts:
            if pt and pt > t and (path == f or path.startswith(f + SEP)):
                t = pt
        return t

    def confirmed(d, h):
        return c.execute(f"select 1 from files where sha=? and disk=? and ev in ('{EV_SCAN}', '{EV_COPY}') limit 1",
                         (h, d)).fetchone() is not None

    if F:
        cond, args = rz.inside_cond('path', F)
    else:
        cond, args = "instr(path, '\\') = 0", []
    lines, junk = [], []
    stays = collections.defaultdict(lambda: [0, 0])
    total = [0, 0]
    via = collections.Counter()

    def stay(why, size):
        stays[why][0] += 1
        stays[why][1] += size or 0

    q = f'select path, size, sha, mtime, name_lc from files where disk=? and {cond}'
    for path, size, sha, mt, nm in c.execute(q, [disk] + args).fetchall():
        size = size or 0
        total[0] += 1
        total[1] += size
        if only is not None and path not in only:
            continue
        mm = _decisive(ms, path, copied)
        if not mm or mm.row != src['mark_row']:
            stay(R_OWN, size)
            continue
        new = new_of(path)
        if c.execute('select 1 from files where disk=? and path=?', (disk, new)).fetchone():
            stay(R_BUSY, size)
            continue
        cls = class_of(path, nm or path.rsplit(SEP, 1)[-1].lower(), size)
        if cls in (C_JUNK, C_EMPTY):
            junk.append((path, size, mt if mt is not None else '', dest, (sha or '').upper(),
                         'мусор или пустой файл - едет вместе с папкой') + ((r1,) if r1 else ()))
            continue
        # история копирования - по ВСЕМ путям этого файла на этом носителе: при втором проходе это исходный путь и тот
        # же путь внутри каждой служебной «Скопировано на …» (они только верхнего уровня, путь внутри сохраняется)
        if r1:
            rest = path[len(r1) + 1:]
            evs, plan_t = collections.defaultdict(list), set()
            for p_ in [rest] + [x + SEP + rest for x in sorted(copied)]:
                for t, lst in events.get(p_, {}).items():
                    evs[t] = evs[t] + lst
                plan_t |= set(planned.get(p_, {}))
        else:
            evs, plan_t = events.get(path, {}), set(planned.get(path, {}))
        # прежнее правило «45 - значит и 77» в логике v3 не действует (этап 13: 45 и 77 - разные направления, вторая
        # копия - вторым проходом); обязательны все диски, куда файл ставили задания копирования с этого носителя
        req = (base | plan_t | set(evs)) - {disk}
        h = sha.lower() if sha else None
        if not h:
            if mt is None:
                stay(R_NODATE, size)
                continue
            reads = sorted((e for t in evs for e in evs[t] if e[3].startswith(COPY_OK) and e[4]
                            and e[6] == size and e[0] > seen_at(path)), key=lambda e: e[0])
            if not reads:
                stay(R_NOHASH, size)
                continue
            h = reads[-1][4]
            via['по хешу прочитанного при копировании'] += 1
        why = None
        for d in sorted(req):
            if confirmed(d, h):
                continue
            te = evs.get(d, [])
            okd = [e for e in te if e[3].startswith(COPY_OK) or e[3] == 'уже есть']
            if te and not okd:
                why = R_ERR
            elif okd:
                why = R_WEAK
            elif d in plan_t:
                why = R_WAIT
            else:
                why = R_NONE
            break
        if why:
            stay(why, size)
            continue
        lines.append((path, size, mt if mt is not None else '', dest, h.upper(), 'копия подтверждена: ' + ', '.join(sorted(req)))
                     + ((r1,) if r1 else ()))
    if lines:
        lines += junk
    else:
        for j in junk:
            stay('мусор или пустой файл - едет только вместе с папкой', j[1])
    lines.sort()
    whole = []
    if F and only is None and lines and len(lines) == total[0] and not stays:
        ic, ia = rz.inside_cond('path', F)
        issues = c.execute(f'select count(*) from issues where disk=? and {ic}', [disk] + ia).fetchone()[0]
        target = new_of(F)
        fc, fa = rz.inside_cond('path', target)
        busy = c.execute(f'select 1 from files where disk=? and (path = ? or {fc}) limit 1',
                         [disk, target] + fa).fetchone()
        if not issues and not busy:
            whole.append((F, dest, len(lines), sum(r[1] for r in lines)) + ((r1,) if r1 else ()))
    return dict(src=src, dest=dest, known=known, roots=sorted(copied), lines=lines, stays=dict(stays), total=total,
                whole=whole, via=dict(via), strip=r1, parts=parts_)
