"""Команда recovery-plan, recovery-staging."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
from pathlib import Path
from hb_core import api


def cmd_recovery_plan(a):
    import recovery_plan
    recovery_plan.cmd_recovery_plan(a, api)


def cmd_recovery_staging(a):
    import recovery_staging_audit as audit
    if not a.cached:
        audit.main()
    audit.refine_unhashed()

NAMES = ('recovery-plan', 'recovery-staging')
HELP = {'recovery-plan': 'разбор оглавления восстановленной папки, без чтения содержимого', 'recovery-staging': 'остаток восстановлений К/Н вне F, 45 и 77; только метаданные'}


def add_args(p, name):
    if name == 'recovery-plan':
        p.add_argument('disk'); p.add_argument('--root', type=Path, required=True)
        p.add_argument('--cached', action='store_true', help='обновить разметку сохранённого оглавления, без обращения к диску')
    else:
        p.add_argument('--cached', action='store_true', help='работать только с сохранёнными оглавлениями')


def run(a):
    (cmd_recovery_plan if a.cmd == 'recovery-plan' else cmd_recovery_staging)(a)
