"""Команда stats, build."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
from hb_core import paths
from hb_core.consts import MAIN
from hb_core.util import gb, out
from hb_core.sources import read_exclusions, read_table
from hb_core.builder import build, load_report
from hb_core.db import connect
from hb_core.query import report_lines


def cmd_stats(a):
    c, jobs = connect()
    n, h = c.execute('select count(*), count(sha) from files').fetchone()
    rep = load_report(c)
    out(f'База собрана {c.execute("select value from meta where key=?", ("built",)).fetchone()[0]}: файлов {n}, '
        f'с подтверждённым SHA-256 {h}; носителей {len(jobs)}')
    for disk in MAIN:
        parts = [f'{ev} {k} ({gb(b)} ГБ)' for ev, k, b in
                 c.execute('select ev, count(*), sum(size) from files where disk=? group by ev order by 2 desc', (disk,))]
        out(f'  {disk}: ' + ', '.join(parts))
    out(f'  степени: S - хеш измерен сканером, C - скопировано скриптом с хешем; Z, U, X - НЕ подтверждено; N - без хеша')
    kinds = collections.Counter(r[0] for r in c.execute('select kind from applied'))
    out('Учтено модулей: ' + ', '.join(f'{k} - {v}' for k, v in sorted(kinds.items())))
    bad = c.execute("select count(*) from disks where status not like 'complete'").fetchone()[0]
    out(f'Описей с замечаниями (не «complete»): {bad}; непрочитанных мест: {c.execute("select count(*) from issues").fetchone()[0]}')
    out('Все найденные журналы учтены.' if not rep['skipped'] else
        f'НЕ УЧТЕНЫ журналы, которые программа не умеет читать: {len(rep["skipped"])}')
    if rep['old_logs'] or rep['old']:
        out(f'Не применено, потому что опись новее операции: строк журналов {sum(rep["old_logs"].values())}, '
            f'других операций {len(rep["old"])} (подробно - в файле ниже)')
    if rep['partial']:
        tot = collections.Counter()
        for folders in rep.get('partial_stats', {}).values():
            for k in folders.values():
                tot.update(k)
        conf = sum(v for k, v in tot.items() if k.startswith('было ') and k != 'было S')
        out(f'Частичные сканы папок: {len(rep["partial"])} папок, файлов {tot["файлов"]}; стало S {conf}, новые {tot["новые"]}, '
            f'исчезли {tot["исчезли"]}, хеш не совпал {tot["хеш не совпал"]}, пропущено по исключениям {tot["исключено"]}')
    out(f'Исключённых папок: {sum(len(v) for v in read_exclusions().values())}; ручных операций: {len(rep["manual"])}; '
        f'решений: {len(read_table(paths.DECISIONS)) - 1}')
    warn = sorted(rep['warn'])
    for x in warn[:3]:
        out('ВНИМАНИЕ: ' + x)
    if len(warn) > 3:
        out(f'... и ещё предупреждений: {len(warn) - 3}')
    for _, x in sorted(rep['unique'].items()):
        out('ВНИМАНИЕ: ' + x)
    path = paths.ANSWERS / 'сборка - подробно.txt'
    path.write_text('\n'.join(report_lines(c, rep)) + '\n', encoding='utf-8-sig')
    out(f'Подробно (журналы, сканы, модули): {path}')

NAMES = ('stats', 'build')
HELP = {'stats': 'что в базе и какие модули учтены', 'build': 'применить новые модули (журналы, сканы, ручные операции) и показать сводку'}
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP = 'Обслуживание'
GUI_ORDER = {'stats': 1, 'build': 2}
GUI_TITLE = {'stats': 'Сводка по базе', 'build': 'Обновить базу (новые журналы и записи)'}
GUI_HINT = {'stats': 'Что в базе: носители, 45 и 77, учтённые журналы и записи, замечания.',
            'build': 'Учитывает новые журналы скриптов, сканы и ваши записи, затем показывает сводку.'}


def add_args(p, name):
    pass


def run(a):
    if a.cmd == 'build':
        build()
    cmd_stats(a)
