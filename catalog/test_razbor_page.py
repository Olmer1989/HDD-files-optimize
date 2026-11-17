"""Переходник (шаг А разбивки, 17.11.2026): тесты «Разбора носителя» перенесены в catalog/tests/razbor/.

Прежняя команда  py -m unittest catalog.test_razbor_page  запускает те же тесты; в полном прогоне вместо неё -
модули catalog.tests.razbor.test_* (docs/ПРАВИЛА_ЗАПИСИ_И_СБОРКИ.md). Обе сразу не перечислять - тесты пройдут дважды.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.razbor.base import PageBase  # noqa: E402,F401 - прежнее имя для test_razbor_cell и др.
from tests.razbor.test_tree import TreeTest, ChoiceTest, LayoutTest  # noqa: E402,F401
from tests.razbor.test_modes import ModesTest, HaveNearTest, SummaryTest  # noqa: E402,F401
from tests.razbor.test_save_tasks import SaveTest, TasksTest, ContestedTest, CapacityTest, TocTest, Review6Test  # noqa: E402,F401
from tests.razbor.test_review import Review8Test, Round3Test  # noqa: E402,F401
from tests.razbor.test_stage12 import Stage12Test, MovedPartialTest, CopiedRootMarksTest  # noqa: E402,F401
from tests.razbor.test_filelist import FileModelTest, FileWindowTest  # noqa: E402,F401
from tests.razbor.test_stage17 import CodeReview16UiTest, Stage17AutosaveTest, Stage17TreeTest, Stage17WatchdogTest, Stage17ListTreeTest, Stage17CodeReviewTest  # noqa: E402,F401
from tests.razbor.test_stage18 import Stage18Test  # noqa: E402,F401

if __name__ == '__main__':
    unittest.main()
