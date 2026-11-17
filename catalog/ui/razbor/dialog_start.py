"""Окно «Начать копирование: HDD09 → H: Бэкап фото и видео (А1)» (18.11.2026, решение владельца; прежде окно
«Подготовить задания» и вопрос «Создать заданий…?»). Текст окна - texts_start.start_html; здесь только Qt.

Внизу «Отмена» и большая голубая кнопка: «Подтвердить и начать копирование» (mode 'start'; нажатие больше ничего не
спрашивает) или «Открыть «3. Копирование»» (mode 'running' - задания набора уже идут). Сверка оглавления не прошла -
главной кнопки нет, слева «Пересканировать эти папки (N)…» (extra). Окно возвращает Accepted только по главной кнопке."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

START_CSS = ('QPushButton { background:#e3f2fd; border:2px solid #1e88e5; border-radius:6px; color:#0d47a1; '
             'font-weight:bold; font-size:12pt; padding:10px 24px; min-height:36px; }'
             'QPushButton:hover { background:#bbdefb; }')
OK_TEXT = {'start': 'Подтвердить и начать копирование', 'running': 'Открыть «3. Копирование»'}


class StartDialog(QDialog):
    """Подтверждение копирования. Атрибуты для тестов: text (QTextBrowser), ok (главная кнопка или None), extra
    (кнопка пересканирования или None), mode."""

    def __init__(self, parent, title, body, mode, extra=None, width=980, height=680):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle(title)
        self.resize(width, height)
        lay = QVBoxLayout(self)
        self.text = QTextBrowser()
        self.text.setHtml(body)
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        self.extra = None
        if extra:
            self.extra = QPushButton(extra[0])
            self.extra.clicked.connect(lambda: (self.reject(), extra[1]()))
            row.addWidget(self.extra)
        row.addStretch()
        cancel = QPushButton('Отмена' if mode in OK_TEXT else 'Закрыть')
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.ok = None
        if mode in OK_TEXT:
            self.ok = QPushButton(OK_TEXT[mode])
            self.ok.setStyleSheet(START_CSS)
            self.ok.setDefault(True)
            self.ok.clicked.connect(self.accept)
            row.addWidget(self.ok)
        lay.addLayout(row)
