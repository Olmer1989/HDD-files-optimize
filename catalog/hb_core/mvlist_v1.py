"""Команда mvlist (часть 1, разбивка 17.11.2026): прежняя логика «ПЕРЕНЕСЕНО → …» - история заданий копирования,
расчёт, отчёт, задание и его проверка. Правило - в начале hb_cmd/mvlist.py."""
import collections
import io
import shutil
import sys
from pathlib import Path
import build_pilot as bp
from hb_core import paths
from hb_core.consts import EV_COPY, EV_SCAN, EV_SIZE, FOLDER_MOVES, HAVE_SHA, MAIN, OLD_LOGS, SEP
from hb_core.util import gb, is_moved_dir, moved_folder, out, prefix_cond, rel_of
from hb_core.sources import log_time, read_tsv, serial_map
from hb_core.query import decision_of, decisions_for
from hb_core import razbor as rz

COPY_OK = ('скопирован', HAVE_SHA)                   # HAVE_SHA - шаблон 2.5: файл в цели прочитан, SHA-256 совпал


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
    sub = vols[0][2].strip(SEP) if len(vols[0]) >= 3 else ''   # пробелы - часть имени (этап 16)
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
        'Лучше запускать из окна программы (вкладка «Копирование» -> отметить -> «Запустить отмеченные»): окно перед запуском\n'
        'ещё раз проверит, что с тех пор не появилось новых заданий копирования этих файлов.\n'
        f'1. Подключите диск {disk} (букву скрипт найдёт сам по серийному номеру).\n'
        '2. Двойной щелчок по «Запустить.cmd», проверьте сводку, введите «да».\n'
        '3. Q - остановиться после текущего файла; повторный запуск продолжит.\n'
        '4. Журнал «Журнал перемещения <дата>.tsv» появится здесь; программа учтёт его сама.\n', encoding='utf-8-sig')
    out(f'Папка задания: {task}')
    out('Запускает владелец: «Запустить.cmd» в этой папке или вкладка «Копирование» в окне.')


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
        if (f[0], f[3]) in ok:
            continue
        if c.execute('select 1 from files where disk=? and path=?', (disk, f[3] + SEP + f[0])).fetchone():
            continue                                        # уже перенесён прежним запуском
        bad.append(f[0])
    if bad:
        out(f'Задание перемещения устарело: {len(bad)} из {len(rows)} файлов больше не проходят проверку '
            f'(например «{bad[0]}»): появилось задание копирования или изменились сведения базы.')
        sys.exit('Соберите задание заново: «Разложить на источнике…» на вкладке «Копирование».')
    out(f'Проверено: все {len(rows)} строк задания перемещения по-прежнему верны (диск {disk}).')
