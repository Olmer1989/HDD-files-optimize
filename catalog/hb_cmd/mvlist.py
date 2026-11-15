"""Команда mvlist."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import io
import shutil
import sys
import build_pilot as bp
from hb_core import paths
from hb_core.consts import MAIN, MOVED_FOLDER, SEP
from hb_core.util import gb, is_moved_dir, out, prefix_cond
from hb_core.sources import serial_map
from hb_core.db import connect
from hb_core.query import check_disk, copied_from, decision_of, decisions_for


def cmd_mvlist(a):
    """Задание «Переместить на источнике»: файлы, у которых журнал копирования подтвердил копии, перекладываются
    внутри своего диска в «ПЕРЕНЕСЕНО → 45 и 77 / только 45 / только 77» (логика v2, разделы 4-5)."""
    c, jobs = connect()
    check_disk(c, a.disk)
    copies = copied_from(a.disk, jobs)
    decs = decisions_for(a.disk)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    wait, stay, notyet, other = [0, 0], [0, 0], [0, 0], [0, 0]
    for prefix in (a.folder or ['']):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        q = f"""select f.path, f.size, f.sha, f.mtime, coalesce(p.e45 in ('S','C'), 0), coalesce(p.e77 in ('S','C'), 0)
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        for path, size, sha, mt, on45, on77 in c.execute(q, [a.disk] + args):
            if is_moved_dir(path.split(SEP, 1)[0]) or decision_of(path, decs):
                continue                                  # уже перемещён; раздел, отсрочка или «не нужно» - не здесь
            done = copies.get(path, {})
            to_main = {t for t in done if t in MAIN}
            if not done:
                k = stay if (on45 and on77) else notyet   # на 45 и 77 уже было - остаётся на месте; иначе ещё не копировали
            elif not to_main:
                k = other                                 # копировали только на другие диски - их проход позже
            else:
                ok = all(c.execute("select 1 from files where disk=? and path=? and sha=? and ev in ('S','C')",
                                   (t, done[t], sha)).fetchone() for t in to_main)
                if not (ok and on45 and on77):
                    k = wait                              # копия не подтверждена (размер, «уже есть») или нет второй
                else:
                    folder = MOVED_FOLDER[frozenset(to_main)]
                    lines.append((path, size, mt if mt is not None else '', folder, sha.upper(),
                                  'копия подтверждена: ' + ', '.join(sorted(to_main))))
                    stat[folder][0] += 1; stat[folder][1] += size
                    continue
            k[0] += 1; k[1] += size
    lines.sort()
    out(f'{a.disk}: что переложить внутри диска после копирования (только фото и видео с SHA-256)')
    for folder, (n, b) in sorted(stat.items()):
        out(f'  -> {folder}: {n} файлов, {gb(b)} ГБ')
    if not lines:
        out('  перемещать нечего: ни у одного файла копии на 45 и 77 ещё не подтверждены журналом копирования')
    if not copies:
        out(f'С диска {a.disk} ещё не копировали скриптом: журналов копирования с него нет. Сначала скопируйте '
            '(«Подготовить копирование» -> задание -> «Запустить.cmd»), потом раскладывайте.')
    out(f'Ждут: копия ещё не подтверждена - {wait[0]} файлов ({gb(wait[1])} ГБ); ещё не копировались - {notyet[0]} '
        f'({gb(notyet[1])} ГБ); копировались только на другие диски - {other[0]}.')
    out(f'Остаются на месте (на 45 и 77 уже были): {stay[0]} файлов, {gb(stay[1])} ГБ.')
    if not lines or a.dry:
        if a.dry and lines:
            out('Пробный расчёт (--dry): папка задания не создаётся; создать - «Создать задание» в окне или без --dry.')
        return
    task = (paths.TASKS if getattr(a, 'task_root', None) == 'scripts' else bp.OUT_DIR) / a.name
    if task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задания уже есть и не пуста: {task}. Выберите другое имя (--name).')
    task.mkdir(parents=True, exist_ok=True)
    serial = {v: k for k, v in serial_map(jobs).items()}.get(a.disk, 'НЕТ_СЕРИЙНОГО_НОМЕРА')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{a.disk}\t{serial}\n')
    with io.open(task / 'перемещение.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    for name in ('Переместить.ps1', 'Запустить.cmd'):
        shutil.copy2(paths.MOVE_TEMPLATE / name, task / name)
    (task / 'Как запустить.txt').write_text(
        f'Задание: переложить внутри диска {a.disk} файлы, копии которых подтверждены журналами копирования.\n'
        f'Файлов: {len(lines)}, {gb(sum(r[1] for r in lines))} ГБ. Куда: ' +
        '; '.join(f'{k} - {v[0]} файлов' for k, v in sorted(stat.items())) + '.\n'
        'Ничего не удаляется и не перезаписывается: это переименование внутри того же диска.\n\n'
        f'1. Подключите диск {a.disk} (букву скрипт найдёт сам по серийному номеру).\n'
        '2. Двойной щелчок по «Запустить.cmd», проверьте сводку, введите «да».\n'
        '3. Q - остановиться после текущего файла; повторный запуск продолжит.\n'
        '4. Журнал «Журнал перемещения <дата>.tsv» появится здесь; программа учтёт его сама.\n', encoding='utf-8-sig')
    out(f'Папка задания: {task}')
    out('Запускает владелец: «Запустить.cmd» в этой папке. Перед запуском список можно пересобрать - он всегда по свежей базе.')

NAMES = ('mvlist',)
HELP = 'задание «Переместить на источнике» по подтверждённым копиям на 45 и 77'
GUI = False      # в окне отдельного пункта нет: галочка «разложить после копирования» в «Подготовить копирование»


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('--name', required=True)
    p.add_argument('--folder', action='append')
    p.add_argument('--dry', action='store_true', help='только посчитать, папку задания не создавать')
    p.set_defaults(task_root='scripts')


def run(a):
    cmd_mvlist(a)
