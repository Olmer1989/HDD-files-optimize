"""Окно «Пересканировать папки…» (раздел «Диски и папки», 15.11.2026).

Предпросмотр по оглавлению диска (файлы не читаются) → подтверждение владельца → сканер отдельным процессом без
консоли (scanner\\portable.py start --folder …) → ход по файлу хода, «Остановить» - файл остановки → по окончании
окно применяет новые модули базы и показывает итог приёма. Сканирование начинается ТОЛЬКО по кнопке с подтверждением.
16.11.2026 (сканер 1.6.0): галочки типов файлов для хеша - те же, что «Что копировать» у направлений; правило - одно
(hash_types.py -> derived.copy_kind); под галочками - оценка по предпросмотру, сколько прочитать и что останется без хеша.
"""
import html
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QTextBrowser, QVBoxLayout)

import hash_types
import service as sv
from directions_page import CAT_LABELS      # подписи типов - те же, что в «Что копировать»

TITLE = 'Архив дисков'


def gb(x):
    return f'{(x or 0) / 1e9:,.1f}'.replace(',', ' ').replace('.', ',')


def num(n):
    return f'{n or 0:,}'.replace(',', ' ')


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
        # Типы файлов для хеша (сканер 1.6.0). По умолчанию - все (как раньше: хеш у всех файлов, и у программ, и у
        # служебных). Невыбранный тип не читается: прежний годный хеш сканера берётся, иначе файл остаётся без хеша.
        lay.addWidget(QLabel('Считать хеш у файлов:'))
        grid = QGridLayout()
        self.all_types = QCheckBox('Все типы')
        self.all_types.setChecked(True)
        self.all_types.setToolTip('Хеш у всех файлов папок, как раньше (в том числе у программ, системных и временных) '
                                  '— для точного ответа «можно ли удалять».')
        self.all_types.toggled.connect(self.toggle_all)
        grid.addWidget(self.all_types, 0, 0)
        self.type_box = {}
        for i, (cat, text) in enumerate(CAT_LABELS, start=1):
            b = QCheckBox(text)
            b.setChecked(True)
            b.toggled.connect(self.types_changed)
            self.type_box[cat] = b
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)
        self.types_line = QLabel('')
        self.types_line.setWordWrap(True)
        lay.addWidget(self.types_line)
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
                p = sv.rescan_plan(disk, folders, rehash)
            except sv.Refused as e:
                return 'no', str(e)
            try:                                  # подтверждённые хеши в базе - для предупреждения о потере
                p['confirmed'] = sv.rescan_confirmed(disk, p['folders'])
            except Exception:                     # noqa: BLE001 - база недоступна: без предупреждения, но честно
                p['confirmed'] = None
            return 'ok', p
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
        self.types_changed()

    # --- типы файлов ---
    def cats(self):
        return [c for c, b in self.type_box.items() if b.isChecked()]

    def toggle_all(self, on):
        for b in self.type_box.values():
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.types_changed()

    def types_changed(self, *_):
        cats = self.cats()
        self.all_types.blockSignals(True)
        self.all_types.setChecked(hash_types.is_all(cats))
        self.all_types.blockSignals(False)
        self.est = None
        if not cats:
            self.types_line.setText('<span style="color:#c62828">Отметьте хотя бы один тип файлов.</span>')
            self.go.setEnabled(False)
            return
        p = self.plan
        if not self.running and p is not None:
            self.go.setEnabled(not p['errors'])
        if p is None or 'items' not in p:
            self.types_line.setText('')
            return
        rescan = sv._scanner()[0]
        e = self.est = rescan.by_types(p, hash_types.scanner_rule(cats))
        text = f'Будет прочитано примерно {num(e["read"][0])} файлов, {gb(e["read"][1])} ГБ.'
        if e['skip'][0]:
            text += (f' Без хеша останется {num(e["skip"][0])} файлов ({gb(e["skip"][1])} ГБ) невыбранных типов'
                     ' — у них нет годного прежнего хеша.')
            conf = p.get('confirmed')
            lost = sum(1 for x in e['skip_paths'] if x in conf) if conf else 0
            if lost:
                text += (f' <span style="color:#c62828">У {num(lost)} из них в базе сейчас подтверждённый хеш — '
                         'после приёма скана подтверждение пропадёт.</span>')
            elif conf is None:
                text += ' Есть ли у них подтверждённый хеш в базе — проверить не удалось.'
        self.types_line.setText(text)

    # --- запуск, ход, остановка ---
    def start(self, resume=False):
        p = self.plan
        if not resume and not p:
            return
        if resume:
            q = f'Продолжить сканирование {self.disk}? Готовые хеши сохранены, дочитаются остальные файлы.'
        else:
            cats = self.cats()
            if not cats:
                return
            e = getattr(self, 'est', None)
            if e:
                q = (f'Начать сканирование {self.disk} ({p["letter"]})?\n\nХеш считать у: {hash_types.label(cats)}.\n'
                     f'Прочитать с диска: {num(e["read"][0])} файлов, {gb(e["read"][1])} ГБ. '
                     f'Хеш из прежней описи: {num(e["reuse"][0])} файлов.'
                     + (f' Без хеша останется: {num(e["skip"][0])} файлов.' if e['skip'][0] else ''))
            else:
                nm = p.get('read_nonmedia') or [0, 0]
                q = (f'Начать сканирование {self.disk} ({p["letter"]})?\n\nХеш считать у: {hash_types.label(cats)}.\n'
                     f'Прочитать с диска: {p["read"][0]} файлов, '
                     f'{gb(p["read"][1])} ГБ (из них не фото и не видео: {nm[0]} файлов, {gb(nm[1])} ГБ). '
                     f'Хеш из прежней описи: {p["reuse"][0]} файлов.')
            if not hash_types.is_all(cats):
                conf = p.get('confirmed')
                if not e or (e['skip'][0] and conf is None):
                    q += ('\n\nВНИМАНИЕ: не удалось проверить, сколько подтверждённых хешей пропадёт у файлов '
                          'невыбранных типов. Продолжить?')
                elif e['skip'][0]:
                    lost = sum(1 for x in e['skip_paths'] if x in conf)
                    if lost:
                        q += f'\n\nУ {num(lost)} файлов невыбранных типов подтверждение хеша в базе пропадёт.'
            q +='\n\nСканер только читает диск. Остановить можно в любой момент - готовые хеши сохранятся.'
        if QMessageBox.question(self, TITLE, q) != QMessageBox.Yes:
            return
        letter = p['letter'] if p else ''
        folders = p['folders'] if p else self.folders
        cats = None if hash_types.is_all(self.cats()) else self.cats()
        self.proc = sv.rescan_start(self.disk, letter, folders, self.rehash.isChecked(), job=self.job if resume else None,
                                    cats=cats)
        self.running = True
        # Типы и «перечитать» после запуска не меняются: продолжение задания идёт по правилу, записанному в задании.
        for b in (self.go, self.rehash, self.close_btn, self.all_types, *self.type_box.values()):
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
