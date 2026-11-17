"""Команда mvlist: задание «Переместить на источнике» после копирования - для любых дисков-целей (15.11.2026).

Правило (обсуждено с GPT, «Проверка Архитектуры сортировки файлов\\Перемещение_на_любые_диски_v1.md»):
- обязательные цели файла - все диски, куда его ставили задания копирования с этого ФИЗИЧЕСКОГО носителя
  (список.tsv любого задания, по серийному номеру в тома.tsv), и все диски из строк журналов (и с ошибкой);
- на каждой цели в месте назначения из журнала база держит S или C с SHA-256 этой версии файла
  (у файла без хеша в описи - SHA-256 прочитанного при последнем копировании);
- если среди целей есть 45 или 77 - файл подтверждён и на 45, и на 77 (прежнее правило);
- файл не в «ПЕРЕНЕСЕНО → …», не под решением владельца (длина пути не ограничена - шаблоны работают с длинными путями, 17.11.2026);
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
from hb_core.consts import COPIED_PREFIX, EV_COPY, EV_SCAN, EV_SIZE, FOLDER_MOVES, HAVE_SHA, MAIN, OLD_LOGS, SEP
from hb_core.util import copied_tail, gb, is_moved_dir, moved_folder, out, prefix_cond, rel_of
from hb_core.sources import log_time, read_tsv, serial_map
from hb_core.db import connect
from hb_core.query import check_disk, decision_of, decisions_for
from hb_core import razbor as rz
from hb_core.mvlist_v1 import (COPY_OK, _task_dirs, task_info, _journals, history, task_progress, _confirmed, plan,
    resolve_task, _n, report, _write_task, recheck)
from hb_core.mvlist_v3 import (V3_SUFFIX, V3_META, COPY_META, ROOT_WORD, R_OWN, R_NOHASH, R_NODATE, R_ERR, R_WAIT,
    R_WEAK, R_NONE, R_BUSY, _json, _write_json, v3_source, v3_title, v3_task_name, _decisive, _copy_tasks,
    _moved_done, move_metas, second_dest, plan_v3)
from hb_core.mvlist_v3_out import (dest_path, report_v3, _write_task_v3, write_roots, recheck_v3)  # noqa: F401


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
