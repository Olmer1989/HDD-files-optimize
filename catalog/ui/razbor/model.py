"""Model - данные одного носителя без Qt: папки, отметки, маршрут, черновик (собрана из частей model_*).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from .model_checks import ChecksPart
from .model_marks import MarksPart
from .model_show import ShowPart


class Model(MarksPart, ChecksPart, ShowPart):
    """Данные одного носителя: папки (folders), служебные папки, направления, сохранённые отметки и черновик."""

    def __init__(self, tree, drafts=None):
        self.disk = tree['disk']
        self.drafts = {}                 # исходный путь (нижний регистр) -> dict(path, phys, verdict, base)
        self.undo_stack = []             # этап 16: шаг отмены - [(физический путь, прежняя своя отметка)]
        self.inflight = {}               # этап 16: пакет, который сейчас пишется (ключ -> отметка) - «уже сохранён»
        self.have = self.have_disks = None
        self.load(tree)
        if drafts:
            self.drafts = drafts
            self.prune()
