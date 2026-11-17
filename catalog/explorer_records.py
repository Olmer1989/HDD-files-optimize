"""Вкладка «Записанные действия» страницы «Я сделал в Проводнике»: FixDialog и RecordsTab."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import explorer_diff as ed
import service as sv
from explorer_common import TITLE, ROLE


# ---------- вкладка 2: записанные действия ----------

class FixDialog(QDialog):
    """Исправление записанной строки: поля уже заполнены, обязательна причина."""

    def __init__(self, parent, row, disks):
        super().__init__(parent)
        self.setWindowTitle('Редактировать записанное действие')
        self.row, self.disks = row, disks
        f = row['fields']
        lay = QVBoxLayout(self)
        was = QLabel(f'<b>Было:</b> {row["text"]}' + (f'<br><span style="color:gray">{row["note"]}</span>' if row['note'] else ''))
        was.setWordWrap(True)
        lay.addWidget(was)
        form = QFormLayout()
        self.date = QDateEdit(QDate.fromString(f[0], 'dd.MM.yyyy') if QDate.fromString(f[0], 'dd.MM.yyyy').isValid() else QDate.currentDate())
        self.date.setDisplayFormat('dd.MM.yyyy')
        self.date.setCalendarPopup(True)
        form.addRow('Когда:', self.date)
        self.act = QComboBox()
        self.act.addItems(list(sv.ACTIONS))
        self.act.setCurrentText(f[1])
        form.addRow('Что сделали:', self.act)
        self.d1, self.p1 = self._place(f[2], f[3])
        form.addRow('Откуда - диск:', self.d1)
        form.addRow('Откуда - путь:', self.p1)
        self.d2, self.p2 = self._place(f[4], f[5])
        self.l_d2, self.l_p2 = QLabel('Куда - диск:'), QLabel('Куда - путь:')
        form.addRow(self.l_d2, self.d2)
        form.addRow(self.l_p2, self.p2)
        self.note = QLineEdit(f[6])
        form.addRow('Примечание:', self.note)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText('обязательно: например «перепутал папку», «не та дата»')
        form.addRow('<b>Почему исправляете:</b>', self.reason)
        lay.addLayout(form)
        self.will = QLabel()
        self.will.setWordWrap(True)
        lay.addWidget(self.will)
        warn = QLabel('После исправления база соберётся заново - это займёт несколько минут. Прежний текст строки и причина '
                      'сохранятся в её комментарии, копия таблицы - в «_БАЗА\\архив таблиц».')
        warn.setWordWrap(True)
        warn.setStyleSheet('color:#c62828')
        lay.addWidget(warn)
        self.msg = QLabel()
        self.msg.setStyleSheet('color:#c62828')
        lay.addWidget(self.msg)
        bb = QDialogButtonBox()
        self.ok = bb.addButton('Сохранить исправление', QDialogButtonBox.AcceptRole)
        bb.addButton('Отмена', QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.check)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for w in (self.p1, self.p2, self.note, self.reason):
            w.textChanged.connect(self.changed)
        for w in (self.act, self.d1, self.d2):
            w.currentIndexChanged.connect(self.changed)
        self.date.dateChanged.connect(self.changed)
        self.resize(720, 0)
        self.changed()

    def _place(self, disk, path):
        cb = QComboBox()
        cb.addItem('', '')
        for d in self.disks:
            cb.addItem(d, d)
        if disk and cb.findData(disk) < 0:
            cb.addItem(disk, disk)
        cb.setCurrentIndex(max(cb.findData(disk), 0))
        return cb, QLineEdit(path)

    def fields(self):
        return [self.date.date().toString('dd.MM.yyyy'), self.act.currentText(), self.d1.currentData() or '',
                self.p1.text(), self.d2.currentData() or '', self.p2.text(), self.note.text().strip()]   # пути - без обрезки (этап 16)

    def changed(self, *_):
        on = self.act.currentText() != 'удалено'
        for w in (self.d2, self.p2, self.l_d2, self.l_p2):
            w.setVisible(on)
        f = self.fields()
        if not on:
            f[4] = f[5] = ''
        self.will.setText(f'<b>Станет:</b> {ed.describe(f)}')
        self.msg.clear()

    def check(self):
        try:
            self.result_fields = ed.fix_check(self.fields(), self.disks)
            if not self.reason.text().strip():
                raise sv.Refused('Напишите, почему исправляете.')
            if sv.hb.row_fields(self.result_fields, (3, 5)) == sv.hb.row_fields(self.row["fields"], (3, 5)):
                raise sv.Refused('Вы ничего не изменили.')
        except sv.Refused as e:
            self.msg.setText(str(e))
            return
        self.accept()


class RecordsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.disks, self.busy = win, [], [], False
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('Диск:'))
        self.disk = QComboBox()
        self.disk.addItem('все диски', '')
        self.disk.currentIndexChanged.connect(self.show_rows)
        top.addWidget(self.disk)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        top.addStretch()
        self.fix_btn = QPushButton('Редактировать')
        self.fix_btn.clicked.connect(self.fix)
        top.addWidget(self.fix_btn)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['№ строки', 'Дата', 'Что сделали', 'Откуда', 'Куда', 'Комментарий'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        for col in (3, 4):                          # длинные пути не раздвигают таблицу: полный путь - в подсказке
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, 340)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda *_: self.fix())
        lay.addWidget(self.table, 1)
        self.status = QLabel('Новые записи - сверху. Выберите строку и нажмите «Редактировать», если записано неверно.')
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

    def refresh(self):
        self.win.bg.run(lambda: (ed.recorded(), [r['disk'] for r in sv.disks()]), ok=self.got)

    def got(self, res):
        self.rows, self.disks = res
        cur = self.disk.currentData()
        used = sorted({x for r in self.rows for x in (r['fields'][2], r['fields'][4]) if x})
        self.disk.blockSignals(True)
        self.disk.clear()
        self.disk.addItem('все диски', '')
        for d in used:
            self.disk.addItem(d, d)
        self.disk.setCurrentIndex(max(self.disk.findData(cur), 0))
        self.disk.blockSignals(False)
        self.show_rows()

    def show_rows(self, *_):
        d = self.disk.currentData()
        rows = [r for r in self.rows if not d or d in (r['fields'][2], r['fields'][4])]
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([str(r['line']), r['date'], r['act'], r['src'], r['dst'], r['note']]):
                it = QTableWidgetItem(v)
                it.setData(ROLE, r['line'])
                it.setToolTip(r['text'] + ('\n' + r['note'] if r['note'] else ''))
                self.table.setItem(i, j, it)

    def selected(self):
        it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        line = it.data(ROLE) if it else None
        return next((r for r in self.rows if r['line'] == line), None)

    def fix(self):
        row = self.selected()
        if not row:
            QMessageBox.information(self, TITLE, 'Выберите строку в таблице.')
            return
        if self.busy:
            return
        dlg = FixDialog(self, row, self.disks)
        if dlg.exec() != QDialog.Accepted:
            return
        self.start_fix(row, dlg.result_fields, dlg.reason.text())

    def start_fix(self, row, fields, reason):
        self.busy = True
        self.fix_btn.setEnabled(False)
        self.status.setText('Исправляю и собираю базу заново - это несколько минут…')
        self.win.bg.run(self._fix, row['line'], row['fields'], fields, reason, ok=self.fixed)

    @staticmethod
    def _fix(line, old, fields, reason):
        try:
            ed.fix(line, old, fields, reason)
            return None
        except sv.Refused as e:
            return str(e)

    def fixed(self, err):
        self.busy = False
        self.fix_btn.setEnabled(True)
        if err:
            self.status.setText('Не исправлено: ' + err)
            QMessageBox.warning(self, TITLE, 'Не исправлено.\n\n' + err)
        else:
            self.status.setText('Исправлено, база собрана заново.')
        self.refresh()
