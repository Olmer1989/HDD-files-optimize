"""Команда mvlist: задание «Переместить на источнике» после копирования - для любых дисков-целей (15.11.2026).

Правило (обсуждено с GPT, «Проверка Архитектуры сортировки файлов\\Перемещение_на_любые_диски_v1.md»):
- обязательные цели файла - все диски, куда его ставили задания копирования с этого ФИЗИЧЕСКОГО носителя
  (список.tsv любого задания, по серийному номеру в тома.tsv), и все диски из строк журналов (и с ошибкой);
- на каждой цели в месте назначения из журнала база держит S или C с SHA-256 этой версии файла
  (у файла без хеша в описи - SHA-256 прочитанного при последнем копировании);
- если среди целей есть 45 или 77 - файл подтверждён и на 45, и на 77 (прежнее правило);
- файл не в «ПЕРЕНЕСЕНО → …», не под решением владельца; путь после переноса не длиннее 259 символов;
- папка переноса - по набору целей (moved_folder): «ПЕРЕНЕСЕНО → 78», «… → 45 и 77», «… → только 77».
Логика v3 (этап 3, --razbor / --razbor-manifest): перенос папки разбора в «Скопировано на <направление> (<диски>)» -
см. раздел «логика v3» ниже.
"""
import collections
import io
import shutil
import sys
from pathlib import Path
import build_pilot as bp
from hb_core import paths
from hb_core.consts import EV_COPY, EV_SCAN, EV_SIZE, FOLDER_MOVES, MAIN, OLD_LOGS, SEP
from hb_core.util import gb, is_moved_dir, moved_folder, out, prefix_cond, rel_of
from hb_core.sources import log_time, read_tsv, serial_map
from hb_core.db import connect
from hb_core.query import check_disk, decision_of, decisions_for
from hb_core import razbor as rz

MAX_PATH = 259          # политика совместимости: Проводник и большинство программ не открывают пути длиннее
COPY_OK = ('скопирован',)


def _task_dirs():
    seen, res = set(), []
    for root in (bp.OUT_DIR, paths.TASKS):
        root = Path(root)
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if d.name in OLD_LOGS or d.name in FOLDER_MOVES:
                continue                     # старые скрипты 11-12.11: журнал другого вида, учтён сборкой как Z
            if d.is_dir() and (d / 'тома.tsv').exists() and d.resolve() not in seen:
                seen.add(d.resolve())
                res.append(d)
    return res


def task_info(task, serials, jobs):
    """Папка задания копирования -> физический источник, подпапка, имя -> диск, строки списка (цель-диск, путь от корня)."""
    task = Path(task)
    vols = [f for f in read_tsv(task / 'тома.tsv') if len(f) >= 2]
    if not vols:
        return None
    names = {}
    for f in vols:
        n = f[0].strip()
        names[n] = serials.get(f[1].strip().upper()) or (n if n in jobs else None)
    sub = vols[0][2].strip().strip(SEP) if len(vols[0]) >= 3 else ''
    rows = []
    if (task / 'список.tsv').exists():
        for f in read_tsv(task / 'список.tsv'):
            if len(f) >= 3 and f[0].strip():
                rel = f[1]
                rows.append((names.get(f[0].strip()), f[0].strip(), (sub + SEP + rel) if sub else rel, f[2]))
    return dict(dir=task, name=task.name, src=names.get(vols[0][0].strip()), src_name=vols[0][0].strip(),
                sub=sub, names=names, rows=rows)


def _journals(task):
    res = []
    for log in Path(task).glob('Журнал*.tsv'):
        rows = read_tsv(log)
        head = [h.strip().lower() for h in rows[0]] if rows else []
        if 'цель' in head and 'куда' in head and 'результат' in head and 'источник' in head:
            res.append((log_time(log), log, head, rows[1:]))
    return sorted(res, key=lambda x: (x[0], x[1].name))


def history(disk, jobs):
    """Всё, что задания копирования знают о файлах физического носителя disk.
    -> planned {путь: {цель: {задания}}}, events {путь: {цель: [(время, задание, журнал, результат, хеш, путь назначения)]}},
       tasks {имя задания: task_info}."""
    serials = serial_map(jobs)
    planned = collections.defaultdict(lambda: collections.defaultdict(set))
    events = collections.defaultdict(lambda: collections.defaultdict(list))
    tasks = {}
    for d in _task_dirs():
        info = task_info(d, serials, jobs)
        if not info or info['src'] != disk:
            continue
        tasks[info['name']] = info
        for t, _n, path, _size in info['rows']:
            if t:
                planned[path][t].add(info['name'])
        for when, log, head, body in _journals(d):
            i_t, i_r, i_src, i_dst = (head.index(x) for x in ('цель', 'результат', 'источник', 'куда'))
            i_h = next((i for i, h in enumerate(head) if h.startswith('sha-256')), None)
            i_s = head.index('размер') if 'размер' in head else None
            for f in body:
                if len(f) <= i_dst:
                    continue
                t = info['names'].get(f[i_t].strip())
                if not t:
                    continue
                h = (f[i_h].strip().lower() if i_h is not None and len(f) > i_h else '') or None
                try:
                    size = int(f[i_s]) if i_s is not None else None
                except ValueError:
                    size = None
                events[rel_of(f[i_src])[1]][t].append((when, info['name'], log.name, f[i_r], h, rel_of(f[i_dst])[1], size))
    return planned, events, tasks


def task_progress(info):
    """Сколько строк списка задания уже обработано журналами (последний результат по каждой строке)."""
    last = {}
    for _w, _log, head, body in _journals(info['dir']):
        i_t, i_r, i_src = (head.index(x) for x in ('цель', 'результат', 'источник'))
        for f in body:
            if len(f) > i_src:
                last[(f[i_t].strip(), rel_of(f[i_src])[1])] = f[i_r]
    want = [(n, p) for _t, n, p, _s in info['rows']]
    done = sum(1 for k in want if k in last)
    bad = sum(1 for k in want if k in last and not (last[k].startswith(COPY_OK) or last[k] == 'уже есть'))
    return done, len(want), bad


def _confirmed(c, t, dst, h, size, evs):
    """Копия на диске t по пути dst подтверждена для версии h? -> (да/нет, «по журналу»)."""
    r = c.execute('select sha, ev, sha_exp, size, origin from files where disk=? and path=?', (t, dst)).fetchone()
    if not r or not h:
        return False, False
    sha, ev, sha_exp, rsize, origin = r
    if sha and sha.lower() == h and ev in (EV_SCAN, EV_COPY):
        return True, False
    # Обход известной ошибки сборки: повторный запуск того же задания после Q пишет «уже есть» поверх C (запись Z).
    # Засчитывается, только если Z появилась из журнала ЭТОГО ЖЕ задания и раньше в этом задании была строка
    # «скопирован…» ровно для этой цели и этого пути с тем же хешем прочитанного.
    if ev == EV_SIZE and (sha_exp or '').lower() == h and rsize == size and (origin or '').startswith('журнал: '):
        o_task, _, o_log = origin[len('журнал: '):].partition(SEP)
        try:
            o_when = log_time(o_log)
        except OSError:
            return False, False
        for when, task, _log, res, eh, edst, *_ in evs:
            if task == o_task and edst == dst and eh == h and res.startswith(COPY_OK) and when < o_when:
                return True, True
    return False, False


def plan(c, jobs, disk, folders=None, task=None, only=None):
    """Расчёт без записи на диск. task - task_info задания копирования (только его файлы); only - только эти пути."""
    planned, events, tasks = history(disk, jobs)
    decs = decisions_for(disk)
    roots = rz.moved_roots(c, disk)                       # «ПЕРЕНЕСЕНО → …» по имени, «Скопировано на …» - по журналу
    scope = None
    tinfo = None
    if task:
        tinfo = task
        scope = {p for _t, _n, p, _s in tinfo['rows']}
    if only is not None:
        scope = set(only) if scope is None else scope & set(only)
    # кандидаты: файлы с хешем (как раньше) + файлы без хеша, у которых есть история копирования
    files = {}
    for prefix in (folders or ['']):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        q = f"""select f.path, f.size, f.sha, f.mtime, coalesce(p.e45 in ('S','C'), 0), coalesce(p.e77 in ('S','C'), 0)
                from files f left join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        for path, size, sha, mt, a45, a77 in c.execute(q, [disk] + args):
            if scope is None or path in scope:
                files[path] = (size, sha.lower(), mt, (bool(a45), bool(a77)))
    pfx = [p.rstrip(SEP) for p in (folders or [''])]
    for path in set(planned) | set(events):
        if path in files or (scope is not None and path not in scope):
            continue
        if not any(not p or path == p or path.startswith(p + SEP) for p in pfx):
            continue
        r = c.execute('select size, sha, mtime from files where disk=? and path=?', (disk, path)).fetchone()
        if r:
            files[path] = (r[0], (r[1] or '').lower() or None, r[2], None)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    k = collections.defaultdict(lambda: [0, 0])
    wait_task = collections.Counter()
    via_log = 0
    stays_dirs, ready_dirs = set(), set()

    def stay(key, path, size):
        k[key][0] += 1
        k[key][1] += size
        stays_dirs.add(path.rpartition(SEP)[0])

    for path, (size, sha, mt, pres) in files.items():
        head = path.split(SEP, 1)[0]
        if is_moved_dir(head) or head in roots:
            continue                                       # уже перенесён: имя папки - набор целей на момент переноса
        if decision_of(path, decs):
            continue                                       # раздел, отсрочка или «не нужно» - не здесь
        evs = events.get(path, {})
        req = set(planned.get(path, {})) | set(evs)
        h = sha
        if not h:                                          # файл без хеша в описи: версия - хеш последнего чтения
            ok_reads = sorted((e for t in evs for e in evs[t] if e[3].startswith(COPY_OK) and e[4]), key=lambda e: e[0])
            h = ok_reads[-1][4] if ok_reads else None
        if pres is None and h:                             # у файла без хеша - по хешу прочитанного
            r = c.execute("select coalesce(e45 in ('S','C'), 0), coalesce(e77 in ('S','C'), 0) from presence where sha=?",
                          (h,)).fetchone()
            pres = (bool(r[0]), bool(r[1])) if r else (False, False)
        on45, on77 = pres or (False, False)
        if not req:
            stay('на месте: на 45 и 77 уже были' if (on45 and on77) else 'ещё не копировались', path, size)
            continue
        if not h:
            stay('без хеша: при копировании хеш не записан', path, size)
            continue
        if not sha and mt is None:
            stay('без хеша и без даты изменения в описи', path, size)
            continue
        missing, by_log = [], False
        for t in sorted(req):
            te = evs.get(t, [])
            okd = [e for e in te if e[3].startswith(COPY_OK) or e[3] == 'уже есть']
            if not okd:
                if te:
                    missing.append(('ошибка', t))
                else:
                    missing.append(('задание', t))
                continue
            dst = okd[-1][5]
            good, bl = _confirmed(c, t, dst, h, size, te)
            if not good:
                missing.append(('не подтверждена', t))
            by_log |= bl
        if missing:
            kinds = {m[0] for m in missing}
            if 'задание' in kinds:
                for kind, t in missing:
                    if kind == 'задание':
                        for name in planned[path][t]:
                            wait_task[name] += 1
                stay('ждут другого задания копирования', path, size)
            elif 'ошибка' in kinds:
                stay('копирование не удалось (ошибка, конфликт, нет источника)', path, size)
            else:
                stay('копия ещё не подтверждена', path, size)
            continue
        if req & set(MAIN) and not (on45 and on77):
            stay('нет подтверждённой копии на 45 или 77', path, size)
            continue
        folder = moved_folder(req)
        if len('X:' + SEP + folder + SEP + path) > MAX_PATH:
            stay(f'путь станет длиннее {MAX_PATH} символов', path, size)
            continue
        via_log += by_log
        lines.append((path, size, mt if mt is not None else '', folder, h.upper(),
                      'копия подтверждена: ' + ', '.join(sorted(req))))
        stat[folder][0] += 1
        stat[folder][1] += size
        ready_dirs.add(path.rpartition(SEP)[0])
    lines.sort()
    return dict(lines=lines, stat=dict(stat), k=dict(k), wait_task=wait_task, via_log=via_log,
                split=len(ready_dirs & stays_dirs), has_history=bool(tasks), task=tinfo)


def resolve_task(name):
    """Папка задания копирования по имени (в «Запускаемые скрипты» или «Каталог дисков») или по полному пути."""
    p = Path(name)
    for cand in ([p] if p.is_absolute() else [paths.TASKS / name, Path(bp.OUT_DIR) / name]):
        if (cand / 'тома.tsv').exists() and (cand / 'список.tsv').exists():
            return cand
    sys.exit(f'Нет такого задания копирования (папки с тома.tsv и список.tsv): {name}')


def _n(x):
    return f'{x:,}'.replace(',', ' ')


def report(disk, res, title):
    out(f'{disk}: {title} (по сведениям базы)')
    for folder, (n, b) in sorted(res['stat'].items()):
        out(f'  -> {folder}\\<тот же путь>: {_n(n)} файлов, {gb(b)} ГБ')
    if not res['lines']:
        out('  перемещать нечего: ни у одного файла копии ещё не подтверждены журналом копирования на всех целях')
    if not res['has_history']:
        out(f'С диска {disk} ещё не копировали скриптом: заданий копирования с него нет. Сначала скопируйте '
            '(«Подготовить копирование» -> задание -> «Запустить.cmd»), потом раскладывайте.')
    k = res['k']
    g = lambda key: k.get(key, [0, 0])
    w = g('копия ещё не подтверждена')
    out(f'Ждут: копия ещё не подтверждена - {_n(w[0])} файлов ({gb(w[1])} ГБ); ещё не копировались - '
        f'{_n(g("ещё не копировались")[0])} ({gb(g("ещё не копировались")[1])} ГБ).')
    for key, (n, b) in sorted(k.items()):
        if key not in ('копия ещё не подтверждена', 'ещё не копировались', 'на месте: на 45 и 77 уже были'):
            out(f'Остаются на месте - {key}: {_n(n)} файлов, {gb(b)} ГБ')
    for name, n in res['wait_task'].most_common(3):
        out(f'  ждут задания «{name}»: {_n(n)} файлов')
    s = g('на месте: на 45 и 77 уже были')
    out(f'Остаются на месте (на 45 и 77 уже были): {_n(s[0])} файлов, {gb(s[1])} ГБ.')
    if res['split']:
        out(f'Папок, где часть файлов переедет, а часть останется: {_n(res["split"])}.')
    if res['via_log']:
        out(f'Из них {_n(res["via_log"])} подтверждены по журналу повторного запуска (в базе «уже есть» - известная ошибка сборки).')
    total = sum(r[1] for r in res['lines'])
    out(f'Можно перенести: {_n(len(res["lines"]))} файлов, {gb(total)} ГБ. Ничего не удаляется, все папки и подпапки сохраняются.')


def _write_task(a, disk, jobs, res, title):
    lines, stat = res['lines'], res['stat']
    task = (paths.TASKS if getattr(a, 'task_root', None) == 'scripts' else bp.OUT_DIR) / a.name
    if task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задания уже есть и не пуста: {task}. Выберите другое имя (--name).')
    task.mkdir(parents=True, exist_ok=True)
    serial = {v: k for k, v in serial_map(jobs).items()}.get(disk, 'НЕТ_СЕРИЙНОГО_НОМЕРА')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{disk}\t{serial}\n')
    with io.open(task / 'перемещение.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    for name in ('Переместить.ps1', 'Запустить.cmd'):
        shutil.copy2(paths.MOVE_TEMPLATE / name, task / name)
    (task / 'Как запустить.txt').write_text(
        f'Задание: переложить внутри диска {disk} файлы, копии которых подтверждены журналами копирования ({title}).\n'
        f'Файлов: {len(lines)}, {gb(sum(r[1] for r in lines))} ГБ. Куда: ' +
        '; '.join(f'{k}\\<тот же путь> - {v[0]} файлов' for k, v in sorted(stat.items())) + '.\n'
        'Все папки и подпапки сохраняются: F:\\Котуй 2026\\Валере\\1.jpg -> F:\\<папка переноса>\\Котуй 2026\\Валере\\1.jpg.\n'
        'Ничего не удаляется и не перезаписывается: это переименование внутри того же диска.\n\n'
        'Лучше запускать из окна программы («Задания» -> отметить -> «Запустить отмеченные»): окно перед запуском\n'
        'ещё раз проверит, что с тех пор не появилось новых заданий копирования этих файлов.\n'
        f'1. Подключите диск {disk} (букву скрипт найдёт сам по серийному номеру).\n'
        '2. Двойной щелчок по «Запустить.cmd», проверьте сводку, введите «да».\n'
        '3. Q - остановиться после текущего файла; повторный запуск продолжит.\n'
        '4. Журнал «Журнал перемещения <дата>.tsv» появится здесь; программа учтёт его сама.\n', encoding='utf-8-sig')
    out(f'Папка задания: {task}')
    out('Запускает владелец: «Запустить.cmd» в этой папке или «Задания» в окне.')


def recheck(c, jobs, task):
    """Задание перемещения ещё верно? Каждая строка либо уже перенесена, либо по-прежнему проходит правило."""
    task = Path(task) if Path(task).is_absolute() else paths.TASKS / task
    if not (task / 'перемещение.tsv').exists():
        sys.exit(f'Нет задания перемещения: {task}')
    vols = [f for f in read_tsv(task / 'тома.tsv') if len(f) >= 2]
    disk = serial_map(jobs).get(vols[0][1].strip().upper()) if vols else None
    if not disk:
        sys.exit('Диск задания перемещения не опознан по тома.tsv.')
    rows = [f for f in read_tsv(task / 'перемещение.tsv') if len(f) >= 4]
    res = plan(c, jobs, disk, only={f[0] for f in rows})
    ok = {(r[0], r[3]) for r in res['lines']}
    bad = []
    for f in rows:
        if (f[0], f[3].strip()) in ok:
            continue
        if c.execute('select 1 from files where disk=? and path=?', (disk, f[3].strip() + SEP + f[0])).fetchone():
            continue                                        # уже перенесён прежним запуском
        bad.append(f[0])
    if bad:
        out(f'Задание перемещения устарело: {len(bad)} из {len(rows)} файлов больше не проходят проверку '
            f'(например «{bad[0]}»): появилось задание копирования или изменились сведения базы.')
        sys.exit('Соберите задание заново: «Разложить на источнике…» в разделе «Задания».')
    out(f'Проверено: все {len(rows)} строк задания перемещения по-прежнему верны (диск {disk}).')


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
R_LONG = f'путь станет длиннее {MAX_PATH} символов'
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
                    allowed=m.get('перемещать на носителе', True))
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
    base = src['copy_task'] or f'{src["disk"]} — {v3_title(src)[:60]} — {src["direction"]}'
    return base + V3_SUFFIX


def _decisive(ms, path):
    """Решающая отметка пути: самая глубокая из него самого и его папок (как маршрут разбора)."""
    parts = path.split(SEP) if path else []
    for i in range(len(parts), -1, -1):
        m = ms.get(SEP.join(parts[:i]))
        if m:
            return m
    return None


def _copy_tasks(src, serials, jobs):
    """Задание копирования и все его повторы (тот же носитель и ключ группы) -> [task_info]."""
    res = []
    for d in _task_dirs():
        m = _json(d / COPY_META) if (d / COPY_META).exists() else None
        if m and m.get('носитель') == src['disk'] and m.get('ключ') == src['key'] and \
                (d.name == src['copy_task'] or m.get('повтор') == src['copy_task']):
            info = task_info(d, serials, jobs)
            if info:
                res.append(info)
    return res


def plan_v3(c, jobs, src, only=None):
    """Расчёт переноса одной папки разбора без записи на диск. only - только эти пути (повторная проверка)."""
    from hb_core.consts import C_EMPTY, C_JUNK, COPIED_PREFIX
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
    if F and F.split(SEP, 1)[0] in roots:
        sys.exit(f'«{F}» уже лежит в служебной папке переноса: второй раз папка не перемещается.')
    ms = MarkSet.build(mark_rows(disk, table_bytes(paths.DECISIONS)), dirs)
    m = _decisive(ms, F or '')
    if not m or m.row != src['mark_row'] or m.verdict != src['mark'] or m.num != src['num']:
        sys.exit(f'Отметка папки «{F or ROOT_WORD}» изменилась после подготовки задания (было «{src["mark"]}», строка '
                 f'{src["mark_row"]}; сейчас «{m.verdict if m else "нет отметки"}»). Разберите носитель заново.')
    dest = copied_folder(src['direction'], src['disks'])
    copied = {r for r in roots if r.startswith(COPIED_PREFIX)}
    known = dest in copied
    dcond, dargs = rz.inside_cond('path', dest)
    if not known and c.execute(f'select 1 from files where disk=? and {dcond} limit 1', [disk] + dargs).fetchone():
        sys.exit(f'На {disk} уже есть папка «{dest}», но её создала не программа (журнала перемещения нет). '
                 'Переименуйте её на диске или пересканируйте - иначе файлы смешаются.')
    base = set(src['disks']) - {disk}
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
        mm = _decisive(ms, path)
        if not mm or mm.row != src['mark_row']:
            stay(R_OWN, size)
            continue
        new = dest + SEP + path
        if len('X:' + SEP + new) > MAX_PATH:
            stay(R_LONG, size)
            continue
        if c.execute('select 1 from files where disk=? and path=?', (disk, new)).fetchone():
            stay(R_BUSY, size)
            continue
        cls = class_of(path, nm or path.rsplit(SEP, 1)[-1].lower(), size)
        if cls in (C_JUNK, C_EMPTY):
            junk.append((path, size, mt if mt is not None else '', dest, (sha or '').upper(),
                         'мусор или пустой файл - едет вместе с папкой'))
            continue
        evs = events.get(path, {})
        req = (base | set(planned.get(path, {})) | set(evs)) - {disk}
        if req & set(MAIN):
            req |= set(MAIN)
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
            elif d in planned.get(path, {}):
                why = R_WAIT
            else:
                why = R_NONE
            break
        if why:
            stay(why, size)
            continue
        lines.append((path, size, mt if mt is not None else '', dest, h.upper(), 'копия подтверждена: ' + ', '.join(sorted(req))))
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
        fc, fa = rz.inside_cond('path', dest + SEP + F)
        busy = c.execute(f'select 1 from files where disk=? and (path = ? or {fc}) limit 1',
                         [disk, dest + SEP + F] + fa).fetchone()
        if not issues and not busy:
            whole.append((F, dest, len(lines), sum(r[1] for r in lines)))
    return dict(src=src, dest=dest, known=known, roots=sorted(copied), lines=lines, stays=dict(stays), total=total,
                whole=whole, via=dict(via))


def report_v3(res):
    src = res['src']
    where = src['folder'] or ROOT_WORD
    out(f'{src["disk"]}: перенести папку «{where}» в «{res["dest"]}» (по сведениям базы)')
    n_, b_ = len(res['lines']), sum(r[1] for r in res['lines'])
    if res['lines']:
        how = 'папкой целиком, одним переименованием' if res['whole'] else 'по файлам, все пути сохраняются'
        out(f'  -> {src["disk"]}:\\{res["dest"]}\\{src["folder"] or ""}{SEP if src["folder"] else ""}…: '
            f'{_n(n_)} файлов, {gb(b_)} ГБ - {how}')
    out(f'Всего в папке по описи: {_n(res["total"][0])} файлов, {gb(res["total"][1])} ГБ.')
    for why, (k, b) in sorted(res['stays'].items()):
        out(f'Остаются на месте - {why}: {_n(k)} файлов, {gb(b)} ГБ')
    for why, k in res['via'].items():
        out(f'  из них {_n(k)} файлов без хеша в описи подтверждены {why}')
    if res['lines'] and not res['whole'] and src['folder']:
        out('Папка уходит по файлам: на старом месте останутся перечисленные выше файлы и пустые папки.')
    out(f'Можно перенести: {_n(n_)} файлов, {gb(b_)} ГБ. Ничего не удаляется и не перезаписывается, все подпапки '
        'сохраняются. Содержимое источника перед перемещением не проверялось: шаблон сверяет размер и дату с описью.')


def _write_task_v3(name, res, serial):
    import time
    src = res['src']
    task = paths.TASKS / name
    task.mkdir(parents=True, exist_ok=False)
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{src["disk"]}\t{serial}\n')
    with io.open(task / 'перемещение.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in res['lines']:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(task / 'папки целиком.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in res['whole']:
            f.write('\t'.join(map(str, r)) + '\n')
    write_roots(task, res)
    for fn in ('Переместить.ps1', 'Запустить.cmd'):
        shutil.copy2(paths.MOVE_TEMPLATE / fn, task / fn)
    _write_json(task / V3_META, {
        'версия': 3, 'носитель': src['disk'], 'задание копирования': src['copy_task'], 'манифест': src['manifest'],
        'папка': src['folder'], 'ключ': src['key'], 'направление': src['num'], 'имя направления': src['direction'],
        'обязательные диски': src['disks'], 'отметка': src['mark'], 'строка отметки': src['mark_row'],
        'перемещать на носителе': src['allowed'], 'куда': res['dest'], 'целиком': bool(res['whole']),
        'файлов': len(res['lines']), 'байт': sum(r[1] for r in res['lines']), 'всего в папке': res['total'],
        'остаток': res['stays'], 'создано': time.strftime('%d.%m.%Y %H:%M'), 'создано_ts': time.time()})
    (task / 'Как запустить.txt').write_text(
        f'Задание: перенести на носителе {src["disk"]} папку «{src["folder"] or ROOT_WORD}» в «{res["dest"]}».\n'
        f'Файлов: {len(res["lines"])}, {gb(sum(r[1] for r in res["lines"]))} ГБ; '
        + ('папкой целиком (одно переименование).\n' if res['whole'] else 'по файлам.\n') +
        'Все папки и подпапки сохраняются: K:\\Поход 2010\\Фото\\1.jpg -> K:\\<папка переноса>\\Поход 2010\\Фото\\1.jpg.\n'
        'Ничего не удаляется и не перезаписывается: это переименование внутри того же диска.\n\n'
        'Запускайте из окна программы («Задания» -> «Можно переместить на носителе»): окно перед запуском ещё раз\n'
        'проверит задание по свежей базе. Двойной щелчок по «Запустить.cmd» этой проверки не делает.\n'
        f'Q - остановиться после текущей операции; повторный запуск продолжит и сам восстановит прерванный перенос\n'
        'по записи намерения («Намерение перемещения.tsv»).\n', encoding='utf-8-sig')
    return task


def write_roots(task, res):
    """корни.tsv для шаблона: служебные папки носителя (источник не может лежать в них) и папка назначения -
    «известен» (её создал журнал перемещения, она в базе) или «новый» (создаст этот шаблон)."""
    rows = [(r, 'известен') for r in res['roots'] if r != res['dest']]
    rows.append((res['dest'], 'известен' if res['known'] else 'новый'))
    tmp = Path(task) / 'корни.tsv.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write('\t'.join(r) + '\n')
    import os
    os.replace(tmp, Path(task) / 'корни.tsv')


def recheck_v3(c, jobs, task, meta):
    src = dict(copy_task=meta.get('задание копирования'), copy_dir=None, manifest=meta.get('манифест'),
               disk=meta['носитель'], folder=meta.get('папка'), key=meta.get('ключ'), num=meta['направление'],
               direction=meta['имя направления'], disks=list(meta['обязательные диски']), mark=meta['отметка'],
               mark_row=meta['строка отметки'], allowed=meta.get('перемещать на носителе', True))
    rows = [f for f in read_tsv(task / 'перемещение.tsv') if len(f) >= 4]
    res = plan_v3(c, jobs, src, only={f[0] for f in rows})
    ok = {r[0] for r in res['lines']}
    bad = [f[0] for f in rows if f[0] not in ok and not
           c.execute('select 1 from files where disk=? and path=?', (src['disk'], f[3].strip() + SEP + f[0])).fetchone()]
    if bad:
        out(f'Задание перемещения устарело: {len(bad)} из {len(rows)} файлов больше не проходят проверку '
            f'(например «{bad[0]}»).')
        sys.exit('Соберите задание заново: «Задания» -> «Можно переместить на носителе».')
    write_roots(task, res)
    out(f'Проверено: все {len(rows)} строк задания перемещения по-прежнему верны (диск {src["disk"]}).')


def cmd_v3(a, c, jobs):
    src = v3_source(task=a.razbor) if a.razbor else v3_source(manifest=a.razbor_manifest, group=a.group)
    serials = serial_map(jobs)
    res = plan_v3(c, jobs, src)                       # сначала отказы по носителю, отметке и служебной папке
    if src['copy_task']:
        for info in _copy_tasks(src, serials, jobs):
            done, total, _bad = task_progress(info)
            if done < total:
                sys.exit(f'Задание копирования «{info["name"]}» ещё не закончено: обработано {done} из {total} строк. '
                         'Сначала докопируйте (повторный запуск продолжит), потом переносите.')
    report_v3(res)
    if not res['lines'] or a.dry:
        if a.dry and res['lines']:
            out('Пробный расчёт (--dry): папка задания не создаётся.')
        return
    name = a.name or v3_task_name(src)
    base, i = name, 2
    while (paths.TASKS / name).exists():
        meta = _json(paths.TASKS / name / V3_META)
        if meta and meta.get('ключ') == src['key'] and meta.get('носитель') == src['disk'] and \
                not list((paths.TASKS / name).glob('Журнал перемещения *.tsv')):
            sys.exit(f'Задание перемещения уже создано и ещё не запускалось: «{name}». Запустите его из «Заданий».')
        name, i = f'{base} {i}', i + 1
    serial = {v: k for k, v in serials.items()}.get(src['disk'], 'НЕТ_СЕРИЙНОГО_НОМЕРА')
    task = _write_task_v3(name, res, serial)
    out(f'Папка задания: {task}')
    out('Запускает владелец: «Задания» в окне (с проверкой) или «Запустить.cmd» в этой папке.')


def cmd_mvlist(a):
    """Задание «Переместить на источнике» (правило - в начале файла)."""
    c, jobs = connect()
    if getattr(a, 'recheck', None):
        t = Path(a.recheck) if Path(a.recheck).is_absolute() else paths.TASKS / a.recheck
        meta = _json(t / V3_META) if (t / V3_META).exists() else None
        if meta and meta.get('версия') == 3:
            return recheck_v3(c, jobs, t, meta)
        return recheck(c, jobs, a.recheck)
    if getattr(a, 'razbor', None) or getattr(a, 'razbor_manifest', None):
        return cmd_v3(a, c, jobs)
    tinfo = None
    if getattr(a, 'task', None):
        tdir = resolve_task(a.task)
        tinfo = task_info(tdir, serial_map(jobs), jobs)
        if not tinfo or not tinfo['src']:
            sys.exit(f'Источник задания «{tdir.name}» не опознан по серийному номеру в тома.tsv.')
        if a.disk and a.disk != tinfo['src']:
            sys.exit(f'Задание «{tdir.name}» копирует с {tinfo["src"]}, а не с {a.disk}.')
        a.disk = tinfo['src']
        done, total, bad = task_progress(tinfo)
        if done < total:
            sys.exit(f'Задание копирования «{tdir.name}» ещё не закончено: обработано {done} из {total} строк. '
                     'Сначала докопируйте (повторный запуск продолжит), потом раскладывайте.')
    if not a.disk:
        sys.exit('Укажите диск или --task "<папка задания копирования>".')
    check_disk(c, a.disk)
    res = plan(c, jobs, a.disk, a.folder, tinfo)
    title = (f'разложить после задания «{tinfo["name"]}»' if tinfo else 'что переложить внутри диска после копирования')
    report(a.disk, res, title)
    if tinfo and tinfo['sub']:
        out(f'Источник - папка «{tinfo["sub"]}» на диске {a.disk}; папка переноса - в корне {a.disk}.')
    main_src = a.disk in MAIN
    if main_src:
        out(f'ВНИМАНИЕ: {a.disk} - главный архивный диск. Перенос там меняет структуру архива; '
            'создать задание можно только с явным согласием (--allow-main, в окне - отдельный вопрос).')
    if not res['lines'] or a.dry:
        if a.dry and res['lines']:
            out('Пробный расчёт (--dry): папка задания не создаётся.')
        return
    if main_src and not getattr(a, 'allow_main', False):
        sys.exit(f'Задание не создано: источник {a.disk} - главный архивный диск, нужен флаг --allow-main.')
    if not a.name:
        a.name = f'{tinfo["name"]} - разложить на источнике' if tinfo else None
    if not a.name:
        sys.exit('Укажите имя задания: --name "…".')
    _write_task(a, a.disk, jobs, res, title)


NAMES = ('mvlist',)
HELP = 'задание «Переместить на источнике» по подтверждённым копиям (любые диски-цели)'
GUI = False      # в окне - кнопка «Разложить на источнике…» в «Заданиях» и галочка в «Подготовить копирование»


def add_args(p, name):
    p.add_argument('disk', nargs='?')
    p.add_argument('--name', help='имя папки задания (с --task - по умолчанию «<задание> - разложить на источнике»)')
    p.add_argument('--folder', action='append')
    p.add_argument('--task', help='только файлы этого задания копирования (папка в «Запускаемые скрипты»)')
    p.add_argument('--allow-main', action='store_true', help='источник - HDD45 или HDD77: создать задание всё равно')
    p.add_argument('--recheck', help='проверить, что задание перемещения ещё верно (перед запуском)')
    p.add_argument('--dry', action='store_true', help='только посчитать, папку задания не создавать')
    p.add_argument('--razbor', help='логика v3: перенести папку этого задания копирования разбора в «Скопировано на …»')
    p.add_argument('--razbor-manifest', help='логика v3: манифест разбора (группа, где копировать нечего)')
    p.add_argument('--group', help='с --razbor-manifest: папка группы («(файлы в корне)» - файлы в корне)')
    p.set_defaults(task_root='scripts')


def run(a):
    cmd_mvlist(a)
