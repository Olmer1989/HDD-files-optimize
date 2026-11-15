"""Команда family-plan, family-check."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from pathlib import Path
from hb_core import api


def cmd_family_plan(a):
    import copy_workflow
    copy_workflow.prepare(api, a)


def cmd_family_check(a):
    import copy_workflow
    result = copy_workflow.verify(a.task, preflight=a.preflight)
    if not result['ok']:
        raise SystemExit(2)

NAMES = ('family-plan', 'family-check')
HELP = {'family-plan': 'план семейного копирования и проверки HDD51', 'family-check': 'журнал и фактические пути/размеры двух копий; без хеширования целей'}

GUI = False      # в окне не показывается (ручной режим владельца / разовые команды), в командной строке есть


def add_args(p, name):
    if name == 'family-plan':
        p.add_argument('disk')
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--snapshot', type=Path, help='сохранённое оглавление; повторного обхода не будет')
        p.add_argument('--manual-evidence', type=Path, help='конкретные ручные копирования из журнала операций')
    else:
        p.add_argument('--task', type=Path, required=True)
        p.add_argument('--preflight', action='store_true')


def run(a):
    (cmd_family_plan if a.cmd == 'family-plan' else cmd_family_check)(a)
