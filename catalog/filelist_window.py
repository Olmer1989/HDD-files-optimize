"""Окно «Список файлов» - переходник (шаг А разбивки, 17.11.2026).

Код перенесён без правки тел в пакет ui/filelist (карта файлов и правила слоёв - docs/СТРУКТУРА_ПРОГРАММЫ.md):
тексты - texts_list, постоянные - common, строки и FileModel - model_rows и model_table, части окна - view_*,
сборка FileListWindow и open_list - page. Здесь только прежние имена для тестов (fw.prepare, fw.FileModel, fw.C_SIZE …).
Новый код импортирует из ui.filelist напрямую (ui/razbor/view_list.py и disks_page.py - from ui.filelist import page).
Подменять в тестах имена этого модуля (mock.patch.object(fw, 'X')) нельзя - код их отсюда не берёт: подменяйте там,
где имя используется (model_rows.XLSX_MAX, view_buttons.XLSX_MAX, page.open_list), или у класса (QMessageBox.question).
"""
from ui.filelist.texts_list import *                      # noqa: F401,F403
from ui.filelist.common import *                          # noqa: F401,F403
from ui.filelist.common import _esc, _last_line, _safe    # noqa: F401 - звёздочка не отдаёт имена с «_»
from ui.filelist.model_rows import *                      # noqa: F401,F403
from ui.filelist.model_table import *                     # noqa: F401,F403
from ui.filelist.view_table import *                      # noqa: F401,F403
from ui.filelist.view_tree import *                       # noqa: F401,F403
from ui.filelist.view_file import *                       # noqa: F401,F403
from ui.filelist.view_buttons import *                    # noqa: F401,F403
from ui.filelist.view_sync import *                       # noqa: F401,F403
from ui.filelist.page import *                            # noqa: F401,F403
from ui.filelist.page import FileListWindow, open_list    # noqa: F401 - главные имена
