"""Страница окна «Разбор носителя» - переходник (шаг А разбивки, 17.11.2026).

Код перенесён без правки тел в пакет ui/razbor (карта файлов и правила слоёв - docs/СТРУКТУРА_ПРОГРАММЫ.md):
константы - common, тексты - texts_*, Model - model_* и model, окна - dialogs, блоки страницы - view_*, запись и фон -
flow_*, сборка RazborPage - page. Здесь только прежние имена для app.py, commands_page.py и тестов (rp.RazborPage,
rp.Model, rp.dest_cell_html, rp.QMessageBox, rp.Qt …). Новый код импортирует из ui.razbor напрямую.
Подменять в тестах имена этого модуля (mock.patch.object(rp, 'X')) нельзя - код их отсюда не берёт: подменяйте там,
где имя используется (flow_tasks.tasks_dry, flow_autosave.FLUSH_WAIT_MS), или у класса (QMessageBox.question).
"""
from PySide6.QtCore import QCoreApplication, QThreadPool    # noqa: F401 - прежние имена (в коде страницы не нужны)
from PySide6.QtWidgets import QGroupBox                   # noqa: F401
from hb_core.directions import R_NONE                     # noqa: F401

from ui.razbor.texts_cell import *                        # noqa: F401,F403
from ui.razbor.common import *                            # noqa: F401,F403
from ui.razbor.texts_head import *                        # noqa: F401,F403
from ui.razbor.texts_tasks import *                       # noqa: F401,F403
from ui.razbor.model_marks import *                       # noqa: F401,F403
from ui.razbor.model_checks import *                      # noqa: F401,F403
from ui.razbor.model_show import *                        # noqa: F401,F403
from ui.razbor.model import *                             # noqa: F401,F403
from ui.razbor.dialogs import *                           # noqa: F401,F403
from ui.razbor.view_carrier import *                      # noqa: F401,F403
from ui.razbor.view_tree import *                         # noqa: F401,F403
from ui.razbor.view_head import *                         # noqa: F401,F403
from ui.razbor.view_checks import *                       # noqa: F401,F403
from ui.razbor.view_cell import *                         # noqa: F401,F403
from ui.razbor.view_summary import *                      # noqa: F401,F403
from ui.razbor.view_list import *                         # noqa: F401,F403
from ui.razbor.flow_autosave import *                     # noqa: F401,F403
from ui.razbor.flow_tasks import *                        # noqa: F401,F403
from ui.razbor.flow_contested import *                    # noqa: F401,F403
from ui.razbor.page import *                              # noqa: F401,F403
from ui.razbor.page import RazborPage                     # noqa: F401 - главное имя (app.py)
