"""«Задания на копирование»: вопросы и сообщения владельцу (тесты подменяют у экземпляра) (часть-«примесь» класса
TasksPage).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtWidgets import QDialog, QMessageBox

from .common import TITLE
from .widgets import TextDialog


class AskView:
    """Часть TasksPage: вопросы и сообщения владельцу (тесты подменяют у экземпляра)."""

    # --- вопросы (тесты подменяют) ---
    def say(self, text):
        QMessageBox.information(self, TITLE, text)

    def ask(self, text):
        return QMessageBox.question(self, TITLE, text) == QMessageBox.Yes

    def choose(self, text, buttons):
        """Вопрос с несколькими ответами -> текст нажатой кнопки или None."""
        box = QMessageBox(QMessageBox.Question, TITLE, text, parent=self)
        btns = {box.addButton(b, QMessageBox.AcceptRole): b for b in buttons}
        box.addButton('Отмена', QMessageBox.RejectRole)
        box.exec()
        return btns.get(box.clickedButton())

    def show_text(self, title, text, ok=None):
        return TextDialog(self, title, text, ok).exec() == QDialog.Accepted
