"""Раздел окна «Задания на копирование» - переходник (шаг А разбивки, 17.11.2026).

Код перенесён без правки тел в пакет ui/tasks (карта файлов и правила слоёв - docs/СТРУКТУРА_ПРОГРАММЫ.md):
постоянные - common, тексты - texts_words и texts_rows, журналы, правила, запуск, блок перемещения и строки
таблицы - model_*, мелкие части окна и TextDialog - widgets, части окна - view_* и flow_run, сборка TasksPage -
page. Здесь только прежние имена для тестов (tp.move_items, tp.state_text, tp.TasksPage, tp.RED …).
Новый код импортирует из ui.tasks напрямую (app.py - ui.tasks.page.TasksPage). Подменять в тестах имена этого
модуля (mock.patch.object(tp, 'X')) нельзя - код их отсюда не берёт: подменяйте там, где имя используется
(model_load.serial_names, model_load.disk_labels, flow_run.run_hb, view_table.load_all), или у экземпляра.
"""
from ui.tasks.common import *                           # noqa: F401,F403
from ui.tasks.texts_words import *                      # noqa: F401,F403
from ui.tasks.texts_rows import *                       # noqa: F401,F403
from ui.tasks.model_journal import *                    # noqa: F401,F403
from ui.tasks.model_rules import *                      # noqa: F401,F403
from ui.tasks.model_run import *                        # noqa: F401,F403
from ui.tasks.model_move import *                       # noqa: F401,F403
from ui.tasks.model_load import *                       # noqa: F401,F403
from ui.tasks.widgets import *                          # noqa: F401,F403
from ui.tasks.view_table import *                       # noqa: F401,F403
from ui.tasks.view_done import *                        # noqa: F401,F403
from ui.tasks.view_offers import *                      # noqa: F401,F403
from ui.tasks.view_ask import *                         # noqa: F401,F403
from ui.tasks.flow_run import *                         # noqa: F401,F403
from ui.tasks.page import *                             # noqa: F401,F403
from ui.tasks.common import _meta                       # noqa: F401 - звёздочка не отдаёт имена с «_»
from ui.tasks.texts_words import _date, _folder_word, _loc, _num, _on_disks, _where  # noqa: F401
from ui.tasks.texts_rows import _size_words, _target_words, _targets_of  # noqa: F401
from ui.tasks.model_journal import _CACHE, _DRIVE_RE, _TIME_RE, _file_key, _read_log  # noqa: F401
from ui.tasks.model_rules import _overlap               # noqa: F401 - звёздочка не отдаёт имена с «_»
from ui.tasks.model_run import _retry                   # noqa: F401 - звёздочка не отдаёт имена с «_»
from ui.tasks.model_load import _LABELS, _SERIALS, _letters  # noqa: F401
from ui.tasks.widgets import _cell, _chip_style, _small, _table  # noqa: F401
from ui.tasks.page import TasksPage                     # noqa: F401 - главное имя
