"""Команда mklist."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import io
import shutil
import sys
import build_pilot as bp
from hb_core import paths
from hb_core.consts import MAIN, SEP
from hb_core.util import gb, is_drop, out, prefix_cond
from hb_core.sources import serial_map
from hb_core.db import connect
from hb_core.query import check_disk, decision_of, decisions_for


def cmd_mklist(a):
    c, jobs = connect()
    check_disk(c, a.disk)
    for t in a.to:
        check_disk(c, t)
    task = (paths.TASKS if getattr(a, 'task_root', None) == 'scripts' else bp.OUT_DIR) / a.name
    if not a.dry and task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задачи уже есть и не пуста: {task}. Выберите другое имя (--name).')
    decs = decisions_for(a.disk)
    want = (getattr(a, 'section', None) or '').strip().lower()
    take_all = getattr(a, 'all', False)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    waiting = collections.defaultdict(lambda: [0, 0])      # раздел/отсрочка: файлов, байт - не идут в этот список
    dropped, weak_there = [0, 0], collections.Counter()
    waiting_seen = set()
    src_folder = (getattr(a, 'source_folder', None) or '').strip(SEP)
    src_name = getattr(a, 'as_name', None) or a.disk
    cut = len(src_folder) + 1 if src_folder else 0
    whole = getattr(a, 'whole', False)
    if whole and not (a.folder or src_folder):
        sys.exit('--whole копирует папки целиком: укажите их через --folder "папка" (можно несколько раз).')
    decided = [0, 0]                                       # --whole: файлов под решениями владельца (всё равно идут)
    for prefix in ([src_folder] if src_folder else (a.folder or [''])):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        if whole:
            # Папка целиком: все файлы из описи, с хешем и без. Решения не применяются - владелец сам назвал папки.
            # Пропускается только фото/видео, у которого на цели уже есть подтверждённая копия (S/C) по SHA-256.
            if not c.execute(f'select 1 from files f where f.disk=? and {cond} limit 1', [a.disk] + args).fetchone():
                sys.exit(f'В базе нет файлов в {a.disk}\\{prefix} (проверьте написание пути).')
            for t in a.to:
                q = f"""select f.path, f.size, f.sha from files f where f.disk=? and {cond}
                        and (f.sha is null or not exists(select 1 from files g where g.sha=f.sha and g.disk=?))"""
                for path, size, sha in c.execute(q, [a.disk] + args + [t]):
                    if t == a.to[0] and decision_of(path, decs):
                        decided[0] += 1; decided[1] += size
                    lines.append((t, path[cut:], size, 'фото/видео' if sha else 'без хеша', (sha or '').upper()))
                    stat[t][0] += 1; stat[t][1] += size
            continue
        for t in a.to:
            q = f"""select f.path, f.size, f.sha,
                           exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)
                    from files f where f.disk=? and f.sha is not null and {cond}
                    and not exists(select 1 from files g where g.sha=f.sha and g.disk=?)"""
            for path, size, sha, weak in c.execute(q, [t, a.disk] + args + [t]):
                v = decision_of(path, decs)
                if is_drop(v):
                    dropped[0] += 1; dropped[1] += size
                    continue
                if want:
                    if not v or v.strip().lower() != want:
                        continue
                elif v and not take_all:                   # раздел или отсрочка: НЕ на эти диски, но и не «не нужно»
                    if path not in waiting_seen:           # один файл считается один раз, а не по разу на каждую цель
                        waiting_seen.add(path)
                        w = waiting[v]
                        w[0] += 1; w[1] += size
                    continue
                if weak:
                    weak_there[t] += 1                     # файл там уже лежит, но не подтверждён: копирование его пропустит
                    continue
                lines.append((t, path[cut:], size, 'фото/видео', sha.upper()))
                stat[t][0] += 1; stat[t][1] += size
    lines = sorted(set(lines))

    def notes():
        for v, w in sorted(waiting.items(), key=lambda kv: -kv[1][1]):
            out(f'  ЖДУТ СВОЕГО ДИСКА, решение «{v}»: {w[0]} файлов, {gb(w[1])} ГБ - в этот список не вошли. '
                f'Собрать их: --section "{v}" --to <диск раздела>')
        for t, n in weak_there.items():
            out(f'  на {t} уже лежит неподтверждённая копия у {n} файлов (сверен только размер или со слов) - '
                f'в список не включены: скрипт их пропустит как «уже есть». Подтвердить можно только чтением.')
        if dropped[0]:
            out(f'  по решению «не нужно» пропущено: {dropped[0]} файлов, {gb(dropped[1])} ГБ')
        if decided[0]:
            out(f'  папки целиком (--whole): {decided[0]} файлов, {gb(decided[1])} ГБ под решениями владельца - '
                f'включены, решения при этом режиме не применяются')
        if whole:
            out('  файлы, появившиеся на диске после описи, в список не попали; изменённые после описи скрипт '
                'отметит ошибкой и не скопирует. Ключи (*.pem, secret.key) сканер не описывает - их в списке нет.')

    if not lines:
        if waiting or weak_there:
            out('В список для указанных дисков ничего не вошло, но это НЕ значит, что всё сохранено:')
        else:
            out('Копировать нечего: у всех файлов с хешем есть подтверждённая копия на указанных дисках.')
        notes()
        return
    if a.dry:
        out('Пробный расчёт (--dry): папка задачи не создаётся.')
        for t in a.to:
            out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ')
        notes()
        return
    serials = {v: k for k, v in serial_map(jobs).items()}
    task.mkdir(parents=True, exist_ok=True)
    with io.open(task / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{src_name}\t{serials.get(a.disk, "НЕТ_СЕРИЙНОГО_НОМЕРА")}' + (f'\t{src_folder}' if src_folder else '') + '\n')
        for d in a.to:
            f.write(f'{d}\t{serials.get(d, "НЕТ_СЕРИЙНОГО_НОМЕРА")}\n')
    for name in ('Копировать.ps1', 'Запустить.cmd'):
        shutil.copy2(paths.TEMPLATE / name, task / name)
    out(f'Папка задачи: {task}')
    for t in a.to:
        out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ -> ПЕРЕНОС с других дисков\\{src_name}\\<тот же путь>'
            + (f' (источник - папка {a.disk}\\{src_folder})' if src_folder else ''))
    notes()
    out('Запуск - пользователем: двойной щелчок по «Запустить.cmd». Свою папку на цели можно задать третьей колонкой в тома.tsv.')

NAMES = ('mklist',)
HELP = 'папка задачи для единого шаблона копирования'


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('--to', nargs='+', default=list(MAIN)); p.add_argument('--name', required=True)
    p.add_argument('--folder', action='append')
    p.add_argument('--dry', action='store_true', help='только посчитать, папку задачи не создавать')
    p.add_argument('--section', help='собрать только файлы с этим решением, например "раздел: Оцифрованные источники"')
    p.add_argument('--all', action='store_true', help='не учитывать разделы и отсрочки (решение «не нужно» учитывается всегда)')
    p.add_argument('--source-folder', help='копировать из этой папки диска; путь в списке - от неё (шаблон 2.2)')
    p.add_argument('--as', dest='as_name', help='имя источника в тома.tsv и в папке на цели (по умолчанию - номер диска)')
    p.add_argument('--whole', action='store_true',
                   help='папки (--folder) целиком: все файлы из описи, с хешем и без; решения не применяются')
    p.set_defaults(task_root='scripts')


def run(a):
    cmd_mklist(a)
