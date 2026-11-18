"""Окна «Разбора носителя»: окно с текстом (TextDialog) и «Пересчитать хеши спорных файлов» (ContestedDialog).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout

import service as sv

from .common import SEP, TITLE, safe
from .texts_cell import GREEN, ORANGE, RED, esc, num


class TextDialog(QDialog):
    """Окно с текстом (HTML) и кнопками: ok_text - главная кнопка (None - только «Закрыть»); extra - (текст, действие)
    дополнительной кнопки слева (окно при её нажатии закрывается)."""

    def __init__(self, parent, title, body, ok_text=None, cancel_text='Отмена', width=900, height=600, extra=None):
        super().__init__(parent)
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
        self.ok = None
        if ok_text:
            self.ok = QPushButton(ok_text)
            self.ok.setDefault(True)
            self.ok.clicked.connect(self.accept)
            row.addWidget(self.ok)
        b = QPushButton(cancel_text if ok_text else 'Закрыть')
        b.clicked.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)


class ContestedDialog(QDialog):
    """По service.contested: на каких дисках и в каких папках спорные файлы; подключённый диск - открыть «Пересканировать
    папки» с этими папками (хеш у всех файлов там всегда включён); неподключённый - какой диск подключить."""

    def __init__(self, win, disk, folder=''):
        super().__init__(win)
        self.win, self.disk, self.folder = win, disk, (folder or '').strip(SEP)
        self.rows = None
        self.setWindowTitle(f'Пересчитать хеши спорных файлов - {disk}')
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        where = f'{disk}\\{self.folder}' if self.folder else f'{disk} (весь носитель)'
        note = QLabel(f'<b>{esc(where)}</b>: где лежат файлы без хеша и '
                      'неподтверждённые копии, из-за которых ответ «можно ли удалить» - «НЕТ» или «НЕДОСТАТОЧНО».'
                      ' Пересканирование посчитает хеш у всех файлов этих папок.')
        note.setWordWrap(True)                  # иначе окно расползается по ширине текста (замечание владельца 18.11)
        note.setMaximumWidth(780)
        lay.addWidget(note)
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)
        self.buttons = QVBoxLayout()
        lay.addLayout(self.buttons)
        row = QHBoxLayout()
        again = QPushButton('Проверить заново')
        again.clicked.connect(self.load)
        row.addWidget(again)
        row.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.load()

    def load(self):
        self.text.setHtml('<p>Ищу спорные файлы по базе (диски не читаются)…</p>')
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.win.bg.run(safe, sv.contested, self.disk, self.folder, ok=self.show_rows, quiet=True)

    def show_rows(self, res):
        kind, val = res
        if kind != 'ok':
            self.text.setHtml(f'<p style="color:{RED}">Не получилось: {esc(val.strip().splitlines()[-1] if val.strip() else val)}</p>')
            return
        self.rows = val
        if not val:
            self.text.setHtml('<p>Спорных файлов нет: пересчитывать хеши незачем.</p>')
            return
        h = []
        for d, letter, folders in val:
            total = sum(n for _, n in folders)
            state = (f'<b style="color:{GREEN}">подключён ({esc(letter)})</b>' if letter else
                     f'<b style="color:{ORANGE}">не подключён — подключите его и нажмите «Проверить заново»</b>')
            h.append(f'<p><b>{esc(d)}</b>: {state}; папок {len(folders)}, спорных файлов {num(total)}</p><ul>')
            for f, n in folders[:30]:
                if f == '':
                    h.append(f'<li>весь носитель — {num(n)} спорных файлов, часть лежит прямо в корне, поэтому папками '
                             f'не обойтись: запустите полное сканирование {esc(d)} в программе «Сканер дисков»</li>')
                else:
                    h.append(f'<li>{esc(f)} — {num(n)}</li>')
            if len(folders) > 30:
                h.append(f'<li>… и ещё {len(folders) - 30} папок (все войдут в пересканирование)</li>')
            h.append('</ul>')
            sub = [f for f, _ in folders if f]
            if letter and sub:
                b = QPushButton(f'Пересканировать эти папки на {d} ({letter})…  — {len(sub)} папок')
                b.clicked.connect(lambda _=False, d=d, sub=sub: self.rescan(d, sub))
                self.buttons.addWidget(b)
        self.text.setHtml(''.join(h))

    def rescan(self, disk, folders):
        import rescan_dialog
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.show()
