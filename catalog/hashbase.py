r"""Программа «Архив дисков»: общая база хешей и быстрые ответы. Запуск: py catalog\hashbase.py <команда> …

Этот файл - только обёртка, своего состояния у неё нет (15.11.2026, разбивка на модули):
  catalog\hb_core\  - ядро: пути (paths), сборка базы (builder, apply_*), запросы (query), вывод (short, report);
  catalog\hb_cmd\   - команды, по файлу на команду; новая команда = новый файл, новый режим = правка одного файла;
  catalog\hb_cli.py - разбор командной строки (команды находит сам).
Старые имена (hb.cmd_mklist, hb.connect, hb.DB, hb.set_root …) отдаются отсюда - для тестов и других программ.
Список команд и их описание: py catalog\hashbase.py --help
"""
from hb_core.api import *              # noqa: F401,F403
from hb_core import api as _api
import hb_cli

main = hb_cli.main
for _mod in hb_cli.command_modules():   # старые имена команд: cmd_mklist, owner_write …
    globals().update({k: v for k, v in vars(_mod).items() if k.startswith(('cmd_', 'owner_'))})


def __getattr__(name):                  # пути и соединение - всегда текущие (после set_root())
    return getattr(_api, name)


if __name__ == '__main__':
    main()
