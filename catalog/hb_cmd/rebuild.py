"""Команда rebuild."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import time
from hb_core.util import out
from hb_core.builder import BuildLock, rebuild
from hb_core.db import close_last


def cmd_rebuild(a):
    """Полная пересборка с нуля и сверка с базой, собранной по шагам."""
    close_last()
    t0 = time.time()
    with BuildLock():
        ok, lines = rebuild(check=True)
    out(f'Пересборка с нуля: {time.time() - t0:.0f} с. Сверка с базой, собранной по шагам:')
    for x in lines:
        out('  ' + x)
    if ok is True:
        out('ИТОГ: совпала - сборка по шагам работает правильно.')
    elif ok is False:
        out('ИТОГ: НЕ СОВПАЛА - сборка по шагам дала другую базу; теперь действует собранная с нуля. Сообщите разработчику.')

NAMES = ('rebuild',)
HELP = 'самопроверка: собрать базу с нуля и сверить с собранной по шагам (минуты)'
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP, GUI_ORDER = 'Обслуживание', 4
GUI_TITLE = 'Пересобрать базу с нуля и проверить (несколько минут)'
GUI_HINT = 'Собирает базу заново и сверяет с базой, собранной по шагам. Данные владельца не меняет.'


def add_args(p, name):
    pass


def run(a):
    cmd_rebuild(a)
