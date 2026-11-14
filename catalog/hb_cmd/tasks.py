"""Команда tasks."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from hb_core import paths
from hb_core.util import out
from hb_core.report import table


def cmd_tasks(a):
    import service as sv
    rows = sv.tasks()
    if not rows:
        out(f'Заданий нет в {paths.TASKS}')
        return
    table(('задание', 'вид', 'состояние', 'строк', 'обработано', 'ошибок'),
          [(r['task'][:50], r['kind'], r['state'], r['total'], r['done'], r['errors']) for r in rows], limit=15)

NAMES = ('tasks',)
HELP = 'задания в «Запускаемые скрипты» и их состояние'


def add_args(p, name):
    pass


def run(a):
    cmd_tasks(a)
