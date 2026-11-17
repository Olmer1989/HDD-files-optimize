"""Логика v3, ядро разбора носителя: маршрут файлов, итог (части А и Б), задания по отметкам, «спорные» файлы.

Документ - «Проверка Архитектуры сортировки файлов\\Логика_v3_разбор_носителя.md» (разделы 1.2-1.6 и «Ядро: устройство»).
Ничего не пишет: итог и план заданий - данные; записывает их пакет service (единый путь записи), печатает команда.

Как считается быстро (секунды на носителе с 4 млн файлов):
- маршрут - по ПАПКАМ таблицы folders (у самого большого носителя 16 тыс. папок), а не по файлам;
- файлы без хеша по одному не читаются: «прямо в папке» = суммы folders папки минус суммы её детей по 5 типам, минус
  файлы, прочитанные поштучно. Поштучно читаются: все файлы с хешем (нужен SHA-256 для «уже есть»), файлы с
  собственной отметкой, файлы с длинным путём назначения, файлы, чей путь назначения на диске D уже занят;
- «уже есть на 45/77» - по готовой таблице presence; на других дисках - множество SHA-256 диска (один запрос).
Сверки (спор с GPT, п. 20): сумма части А = строке корня folders = независимому счёту по files (число и байты);
отрицательный остаток в папке - ошибка. Ошибка сверки - итог «НЕВЕРЕН», задания не создаются.
"""
# Разбит 17.11.2026 на razbor_base, razbor_planner, razbor_report, razbor_contested (код дословно); этот файл -
# переходник: прежний набор имён (api.py делает from hb_core.razbor import *).
import collections
import time
from collections import namedtuple
import build_pilot as bp
from hb_core.consts import (C_DOC, C_JUNK, CAT_DOC, CAT_OF_TYPE, EV_COPY, EV_SCAN, EXT_CLASS, F_ARCH, F_JUNK, F_MUSIC,
                            F_NEVER, F_OTHER, F_PHOTO, F_PROJ, F_TEXT, F_VIDEO, JUNK_NAMES, MAIN, N_TYPES,
                            NEVER_COPY_EXT, SEP)
from hb_core.derived import sub_of_other
from hb_core.consts import COPIED_PREFIX
from hb_core.util import is_moved_dir, parent_of, prefix_cond
from hb_core.directions import R_DIR, R_NONE, R_SKIP, R_UNSET
from hb_core.query import _keys
from hb_core.razbor_scope import B_UNREAD, top_folders, unread_files
from hb_core.razbor_base import *                                    # noqa: F401,F403
from hb_core.razbor_base import _mark_route, _group, _collect_rest, _twins, _probe_all  # noqa: F401
from hb_core.razbor_planner import planner                           # noqa: F401
from hb_core.razbor_report import *                                  # noqa: F401,F403
from hb_core.razbor_report import _n, _gb, _cut                      # noqa: F401
from hb_core.razbor_contested import *                               # noqa: F401,F403
