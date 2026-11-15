"""Команды razbor, razbor-tasks, contested: разбор носителя по направлениям (логика v3, 15.11.2026).

razbor HDDxx        - итог разбора: что будет с каждым файлом (сумма = опись) и сколько писать на каждый диск.
                      Ничего не пишет, кроме файла ответа.
razbor-tasks HDDxx  - задания копирования по отметкам: одно задание - одна отмеченная папка и её направление
                      (--dry - только посчитать). Ничего не копирует и не запускает.
contested HDDxx п.  - после «НЕТ»/«НЕДОСТАТОЧНО» в candel: какие папки пересканировать с хешем всех файлов и на каких
                      дисках (подключён ли диск). Сама ничего не сканирует.
"""
from hb_core import paths
from hb_core.util import gb, out
from hb_core.report import save, table
from hb_core import razbor as rz


def _plan_or_exit(fn, *a, **kw):
    import service as sv
    try:
        return fn(*a, **kw)
    except sv.Refused as e:
        out('НЕ ВЫПОЛНЕНО: ' + str(e))
        raise SystemExit(1)


def _save_details(P, title):
    rows = [('А', t, n, b) for t, n, b in rz.part_a_rows(P)]
    rows += [('А', 'Итого = опись носителя', P.total[0], P.total[1])]
    rows += [('Б', f'на {d}', v[0], v[1]) for d, v in sorted(P.part_b.items())]
    rows += [('группа', f'{g[0]} | {g[1]} | {g[2]} | по дискам: {g[5]}', g[3], g[4]) for g in rz.group_rows(P)]
    rows += [('документы рядом', f'{f or "корень"} (основание: {b})', n, s) for f, n, s, b in P.docs_near]
    rows += [('заблокировано', f'{d}: {w}: {p}', 1, s) for p, d, w, s in sorted(P.blocked)]
    rows += [('внимание', x, '', '') for x in rz.attention_lines(P)]
    return save(title, ('часть', 'строка', 'файлов', 'байт'), rows)


def cmd_razbor(a):
    import service as sv
    P = _plan_or_exit(sv.razbor, a.disk)
    for x in rz.summary_lines(P):
        out(x)
    free = sv.free_space(list(P.part_b))
    if free:
        out('Свободно: ' + '; '.join(f'{d} ({l}) {v:.0f} ГиБ' for d, (l, v) in sorted(free.items())))
    for x in rz.attention_lines(P)[:4]:
        out(x)
    path = _save_details(P, f'разбор - {a.disk}')
    out(f'Подробно (группы заданий, документы рядом, заблокированные): {path}')


def cmd_razbor_tasks(a):
    import service as sv
    res = _plan_or_exit(sv.razbor_tasks, a.disk, dry=a.dry)
    P, specs = res['plan'], res['specs']
    new = [s for s in specs if not s.get('exists')]
    if not specs:
        out(f'{a.disk}: заданий копирования нет - копировать нечего (или у направлений нет дисков).')
    else:
        table(('задание', 'файлов', 'ГБ', 'на диски'),
              [(s['name'][:70] + (' (уже подготовлено)' if s.get('exists') else ''), s['files'], gb(s['bytes']),
                ', '.join(s['targets'])) for s in specs], limit=10)
    states = res['states']
    nod = [g for g in states if g['state'] == rz.G_NODISK]
    if nod:
        names = sorted({g['direction'] for g in nod})
        out(f'Без задания: {len(nod)} папок с направлением без диска ({", ".join(names)}) - назначьте диск: '
            'direction-edit <направление> --add-disk HDDxx.')
    have = [g for g in states if g['state'] == rz.G_HAVE]
    if have:
        out(f'Копировать нечего (всё уже есть на дисках направления): {len(have)} папок - это ещё не разрешение '
            'перемещать (его проверит перемещение по базе).')
    for x in rz.attention_lines(P)[:4]:
        out(x)
    if a.dry:
        out(f'Пробный расчёт (--dry): будет создано заданий {len(new)}; ничего не создано.')
    elif new:
        out(f'Создано заданий: {len(new)} в «{paths.TASKS.name}»; манифест разбора: {res["manifest"]}. '
            'Запускает владелец («Задания» в окне или «Запустить.cmd»).')
    elif specs:
        out('Все задания уже подготовлены раньше - новых нет.')


def cmd_contested(a):
    import service as sv
    rows = _plan_or_exit(sv.contested, a.disk, a.folder)
    if not rows:
        out('Спорных файлов нет: пересчитывать хеши незачем.')
        return
    body = []
    for d, letter, folders in rows:
        state = f'подключён ({letter})' if letter else 'не подключён - подключите диск'
        out(f'{d}: {state}; папок {len(folders)}, файлов {sum(n for _, n in folders)}')
        body += [(d, letter or '-', f or '(корень - полное сканирование носителя)', n) for f, n in folders]
    path = save(f'спорные - {a.disk} {a.folder}'.replace('\\', ' - ').strip(), ('диск', 'буква', 'папка', 'файлов'), body)
    out(f'Папки для «Пересканировать папку…» (хеш у всех файлов): {path}')


NAMES = ('razbor', 'razbor-tasks', 'contested')
HELP = {'razbor': 'итог разбора носителя по направлениям: что с каждым файлом и сколько писать на каждый диск',
        'razbor-tasks': 'задания копирования по отметкам разбора: одно задание на отмеченную папку',
        'contested': 'какие папки пересканировать с хешем, чтобы снять «НЕТ / НЕДОСТАТОЧНО» в candel'}
GUI_GROUP = 'Разбор носителя (v3)'
GUI_ORDER = {'razbor': 3, 'razbor-tasks': 4, 'contested': 8}
GUI_TITLE = {'razbor': 'Итог разбора носителя', 'razbor-tasks': 'Подготовить задания по отметкам',
             'contested': 'Пересчитать хеши спорных файлов: какие папки'}
GUI_HINT = {'razbor': 'Что будет с каждым файлом носителя (сумма равна описи) и сколько писать на каждый диск. Ничего не пишет.',
            'razbor-tasks': ('Одно задание на каждую отмеченную папку и её направление. «Посчитать» - ничего не создаёт; '
                             'запускаете задания вы, в «Заданиях».'),
            'contested': ('После ответа «НЕТ» или «НЕДОСТАТОЧНО» в «можно ли удалить»: папки со спорными файлами на этом '
                          'диске и на 45/77; подключённые - «Пересканировать папку…», остальные - подключить.')}
GUI_ARGS = {'razbor': {'disk': 'Носитель'}, 'razbor-tasks': {'disk': 'Носитель', 'dry': 'Только посчитать'},
            'contested': {'disk': 'Диск', 'folder': 'Папка'}}
GUI_MAKES_TASK = {'razbor-tasks': True}


def add_args(p, name):
    p.add_argument('disk')
    if name == 'razbor-tasks':
        p.add_argument('--dry', action='store_true', help='только посчитать, задания не создавать')
        p.set_defaults(task_root='scripts')
    elif name == 'contested':
        p.add_argument('folder', nargs='?', default='')


def run(a):
    {'razbor': cmd_razbor, 'razbor-tasks': cmd_razbor_tasks, 'contested': cmd_contested}[a.cmd](a)
