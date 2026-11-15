"""Окно «Пересканировать папки…» (раздел «Диски и папки», 15.11.2026).

Предпросмотр по оглавлению диска (файлы не читаются) → подтверждение владельца → сканер отдельным процессом без
консоли (scanner\\portable.py start --folder …) → ход по файлу хода, «Остановить» - файл остановки → по окончании
окно применяет новые модули базы и показывает итог приёма. Сканирование начинается ТОЛЬКО по кнопке с подтверждением.
"""
import html
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QTextBrowser, QVBoxLayout)

import service as sv

TITLE = 'Архив дисков'


def gb(x):
    return f'{(x or 0) / 1e9:,.1f}'.replace(',', ' ').replace('.', ',')


class RescanDialog(QDialog):
    def __init__(self, win, disk, folders):
        super().__init__(win)
        self.win, self.disk, self.folders = win, disk, list(folders)
        self.plan = self.proc = self.job = None
        self.running = False
        self.setWindowTitle(f'Пересканировать папки - {disk}')
        self.resize(860, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>{disk}</b>: ' + html.escape('; '.join(self.folders))))
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)
        self.rehash = QCheckBox('Перечитать всё (прежние хеши не брать; дольше - для проверки сохранности)')
        self.rehash.toggled.connect(self.preview)
        lay.addWidget(self.rehash)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.state = QLabel('')
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.go = QPushButton('Начать сканирование…')
        self.go.setEnabled(False)
        self.go.clicked.connect(self.start)
        self.halt = QPushButton('Остановить')
        self.halt.setEnabled(False)
        self.halt.clicked.connect(self.stop)
        self.close_btn = QPushButton('Закрыть')
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.go)
        row.addWidget(self.halt)
        row.addStretch()
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.preview()

    # --- предпросмотр ---
    def preview(self):
        if self.running:
            return
        self.go.setEnabled(False)
        self.text.setHtml('<p>Читаю оглавление диска (только имена, размеры и даты)…</p>')

        def plan(disk, folders, rehash):
            try:
                return 'ok', sv.rescan_plan(disk, folders, rehash)
            except sv.Refused as e:
                return 'no', str(e)
        self.win.bg.run(plan, self.disk, self.folders, self.rehash.isChecked(), ok=self.show_plan)

    def show_plan(self, res):
        kind, val = res
        if kind == 'no':
            self.plan = None
            self.text.setHtml(f'<p style="color:#c62828">{html.escape(val)}</p>')
            return
        self.plan = val
        self.plan_html = '<p><b>Предпросмотр</b></p>' + ''.join(f'<p>{html.escape(x)}</p>' for x in val['lines'])
        self.text.setHtml(self.plan_html)
        self.go.setEnabled(not val['errors'])

    # --- запуск, ход, остановка ---
    def start(self, resume=False):
        p = self.plan
        if not resume and not p:
            return
        if resume:
            q = f'Продолжить сканирование {self.disk}? Готовые хеши сохранены, дочитаются остальные файлы.'
        else:
            q = (f'Начать сканирование {self.disk} ({p["letter"]})?\n\nПрочитать с диска: {p["read"][0]} файлов, '
                 f'{gb(p["read"][1])} ГБ. Хеш из прежней описи: {p["reuse"][0]} файлов.\n\nСканер только читает диск. '
                 'Остановить можно в любой момент - готовые хеши сохранятся.')
        if QMessageBox.question(self, TITLE, q) != QMessageBox.Yes:
            return
        letter = p['letter'] if p else ''
        folders = p['folders'] if p else self.folders
        self.proc = sv.rescan_start(self.disk, letter, folders, self.rehash.isChecked(), job=self.job if resume else None)
        self.running = True
        for b in (self.go, self.rehash, self.close_btn):
            b.setEnabled(False)
        self.halt.setEnabled(True)
        self.bar.show()
        self.state.setText('Запускаю сканер…')
        self.timer.start(1000)

    def poll(self):
        p = sv.read_progress(self.disk)
        if p:
            self.job = p.get('job') or self.job
            self.bar.setValue(int(10 * (p.get('percent') or 0)))
            eta = p.get('eta_seconds')
            self.state.setText(f'{p.get("phase_title", "")}: файлов {p.get("files_done", 0)} из {p.get("files_total", "?")}'
                               f' (из описи {p.get("reused_files", 0)}, прочитано {p.get("new_files", 0)}); прочитано '
                               f'{gb(p.get("read_bytes"))} из ~{gb(p.get("to_read_bytes"))} ГБ'
                               + (f'; осталось ~{max(1, round(eta / 60))} мин' if eta else ''))
        if self.proc is not None and self.proc.poll() is not None:
            self.finished_scan(self.proc.returncode)

    def stop(self):
        sv.rescan_files(self.disk)[1].write_text('stop', encoding='utf-8')
        self.halt.setEnabled(False)
        self.state.setText('Останавливаю: текущий файл дочитывается…')

    def finished_scan(self, code):
        self.timer.stop()
        self.running = False
        self.halt.setEnabled(False)
        self.close_btn.setEnabled(True)
        p = sv.read_progress(self.disk)
        self.job = p.get('job') or self.job
        status = p.get('status', '')
        log = sv.rescan_files(self.disk)[2]
        if code == 0 and str(status).startswith('complete'):
            self.bar.setValue(1000)
            self.state.setText('Сканирование закончено. Применяю к базе…')
            self.win.apply_new(then=lambda _res: self.accepted())
            return
        tail = ''
        try:
            tail = log.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-1]
        except (OSError, IndexError):
            pass
        self.state.setText(f'Сканирование не закончено ({status or "код " + str(code)}). {tail}\n'
                           f'Подробно: {log}' + (f'\nЗадание: {self.job}' if self.job else ''))
        if self.job and status in ('interrupted', 'error', 'inventory_incomplete'):
            self.go.setText('Продолжить сканирование…')
            self.go.clicked.disconnect()
            self.go.clicked.connect(lambda: self.start(resume=True))
            self.go.setEnabled(True)

    def accepted(self):
        name = Path(self.job).name if self.job else ''

        def show(r):
            head = '<p><b>Принято базой</b></p>' if r['accepted'] else \
                '<p style="color:#c62828"><b>База скан не приняла</b></p>'
            body = ''.join(f'<p>{html.escape(x)}</p>' for x in r['lines'] + r['warn'])
            self.text.setHtml(head + body + getattr(self, 'plan_html', ''))
            self.state.setText('Готово.' if r['accepted'] else 'Готово, но скан не принят - причины выше.')
        self.win.bg.run(sv.partial_outcome, name, ok=show)

    def closeEvent(self, e):                                  # noqa: N802
        if self.running:
            QMessageBox.information(self, TITLE, 'Сканирование идёт. Сначала нажмите «Остановить».')
            e.ignore()
            return
        super().closeEvent(e)
