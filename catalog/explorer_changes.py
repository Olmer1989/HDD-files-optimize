"""Вкладка «Что изменилось на диске» страницы «Я сделал в Проводнике»."""
import threading

from PySide6.QtCore import QDate, QDateTime, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QTreeWidget, QVBoxLayout, QWidget)

import explorer_diff as ed
import service as sv
from explorer_common import TITLE, ROLE, num, SpaceToggles
from explorer_changes_draw import ChangesDrawMixin


# ---------- вкладка 1: что изменилось ----------

class ChangesTab(ChangesDrawMixin, QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.disks, self.diff, self.busy, self.off_sizes, self.shown = win, [], None, False, {}, None
        self.stop, self.prog = None, None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.show_progress)
        self.recount = QTimer(self)
        self.recount.setSingleShot(True)
        self.recount.timeout.connect(self.update_summary)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('Носитель:'))
        self.disk = QComboBox()
        self.disk.setMinimumWidth(320)
        self.disk.currentIndexChanged.connect(self.disk_changed)
        top.addWidget(self.disk)
        self.reload_btn = QPushButton('Обновить список дисков')
        self.reload_btn.clicked.connect(self.refresh)
        top.addWidget(self.reload_btn)
        top.addStretch()
        lay.addLayout(top)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.mode = QStackedWidget()
        self.mode.addWidget(self._online())
        self.mode.addWidget(self._offline())
        lay.addWidget(self.mode, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel('Когда вы это сделали:'))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setDisplayFormat('dd.MM.yyyy')
        self.date.setCalendarPopup(True)
        self.date.setMaximumDate(QDate.currentDate())
        bottom.addWidget(self.date)
        self.summary = QLabel('Ничего не отмечено.')
        self.summary.setWordWrap(True)
        bottom.addWidget(self.summary, 1)
        self.write_btn = QPushButton('Записать…')
        self.write_btn.clicked.connect(self.write)
        bottom.addWidget(self.write_btn)
        lay.addLayout(bottom)

    # --- раскладка ---
    def _online(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Vertical)
        g1 = QGroupBox('1. Где искать изменения (отметьте папки и нажмите «Проверить»)')
        l1 = QVBoxLayout(g1)
        self.folders = QListWidget()
        self.folders.setSelectionMode(QAbstractItemView.ExtendedSelection)
        SpaceToggles(self.folders, lambda: self._toggle_list(self.folders))
        l1.addWidget(self.folders)
        row = QHBoxLayout()
        for text, fn in (('Отметить все', lambda: self._set_all(Qt.Checked)), ('Снять все', lambda: self._set_all(Qt.Unchecked))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.progress = QLabel()
        row.addWidget(self.progress)
        self.check_btn = QPushButton('Проверить')
        self.check_btn.clicked.connect(self.start_scan)
        self.stop_btn = QPushButton('Остановить')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.stop and self.stop.set())
        row.addWidget(self.check_btn)
        row.addWidget(self.stop_btn)
        l1.addLayout(row)
        split.addWidget(g1)
        g2 = QGroupBox('2. Что изменилось - отметьте то, что вы сделали (Shift/Ctrl + мышь - выделить несколько, пробел - отметить выделенные)')
        l2 = QVBoxLayout(g2)
        row = QHBoxLayout()
        self.only_after = QCheckBox('Показывать только изменённое после:')
        self.only_after.toggled.connect(self.apply_filter)
        self.after = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.after.setDisplayFormat('dd.MM.yyyy HH:mm')
        self.after.setCalendarPopup(True)
        self.after.dateTimeChanged.connect(self.apply_filter)
        row.addWidget(self.only_after)
        row.addWidget(self.after)
        row.addStretch()
        for text, st in (('Отметить выделенные', Qt.Checked), ('Снять с выделенных', Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=st: self._set_selected(s))
            row.addWidget(b)
        l2.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Что', 'Файлов', 'Размер', 'Изменено (подсказка)'])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemChanged.connect(lambda *_: self.recount.start(0))
        SpaceToggles(self.tree, self._toggle_tree)
        l2.addWidget(self.tree, 1)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l2.addWidget(self.notes)
        split.addWidget(g2)
        split.setSizes([200, 500])
        lay.addWidget(split)
        return w

    def _offline(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel('Диск не подключён - отметьте папки по каталогу базы (раскрываются по стрелке):'))
        self.otree = QTreeWidget()
        self.otree.setHeaderLabels(['Папка', 'Файлов', 'ГБ'])
        self.otree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.otree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.otree.itemExpanded.connect(self._expand_offline)
        self.otree.itemChanged.connect(lambda *_: self.recount.start(0))
        SpaceToggles(self.otree, lambda: self._toggle_items(self.otree.selectedItems()))
        lay.addWidget(self.otree, 1)
        form = QHBoxLayout()
        form.addWidget(QLabel('Что вы сделали с отмеченными папками:'))
        self.oact = QComboBox()
        self.oact.addItems(['удалено', 'перемещено', 'скопировано'])
        self.oact.currentTextChanged.connect(self._offline_act)
        form.addWidget(self.oact)
        self.oto_label = QLabel('Куда - диск:')
        form.addWidget(self.oto_label)
        self.odisk2 = QComboBox()
        form.addWidget(self.odisk2)
        self.odest = QLineEdit()
        self.odest.setPlaceholderText('в папку (например Фото\\2014; пусто - в корень диска)')
        self.odest.textChanged.connect(lambda *_: self.recount.start(0))
        self.odisk2.currentIndexChanged.connect(lambda *_: self.recount.start(0))
        form.addWidget(self.odest, 1)
        lay.addLayout(form)
        self._offline_act('удалено')
        return w

    # --- данные ---
    def refresh(self):
        if not self.busy:
            self.win.bg.run(sv.disks, ok=self.got_disks)

    def got_disks(self, rows):
        cur = self.disk.currentData()
        before = {r['disk']: r['letter'] for r in self.disks}
        self.disks = rows
        self.disk.blockSignals(True)
        self.disk.clear()
        self.odisk2.clear()
        for r in sorted(rows, key=lambda r: (not r['letter'], r['disk'])):
            state = f'подключён ({r["letter"]})' if r['letter'] else 'не подключён'
            self.disk.addItem(f'{r["disk"]} - {r["label"]} - {state}', r['disk'])
            self.odisk2.addItem(r['disk'], r['disk'])
        i = self.disk.findData(cur)
        self.disk.setCurrentIndex(i if i >= 0 else 0)
        self.disk.blockSignals(False)
        now = self.disk.currentData()
        if now != self.shown or before.get(now) != {r['disk']: r['letter'] for r in rows}.get(now):
            self.disk_changed()             # другой диск или его подключили/отключили; иначе отметки владельца не трогаем

    def current(self):
        d = self.disk.currentData()
        return next((r for r in self.disks if r['disk'] == d), None)

    def disk_changed(self, *_):
        r = self.current()
        self.shown = r['disk'] if r else None
        self.diff = None
        self.tree.clear()
        self.notes.clear()
        if not r:
            return
        if r['letter']:
            self.mode.setCurrentIndex(0)
            self.info.setText(f'{r["disk"]} подключён как {r["letter"]}. Окно сравнит то, что знает база, с тем, что лежит '
                              'на диске сейчас (только имена, размеры и даты - файлы не открываются).')
            self.win.bg.run(self._folders_of, r['disk'], ok=self.got_folders)
        else:
            self.mode.setCurrentIndex(1)
            self.info.setText(f'{r["disk"]} не подключён. Подключите его, и окно само найдёт, что изменилось; '
                              'или отметьте папки по каталогу базы ниже.')
            self._fill_offline(r['disk'])
        self.update_summary()

    def _folders_of(self, disk):
        root, serial = ed.disk_root(disk)
        return disk, root, serial, ed.top_folders(disk, root)

    def got_folders(self, res):
        disk, self.root, self.serial, rows = res
        if disk != self.disk.currentData():
            return
        self.folders.clear()
        for r in rows:
            if r['path'] == '':
                text = 'Файлы в корне диска'
            else:
                text = r['path'] + (f'   ({num(r["files"])} файлов по базе)' if r['files'] else '')
                if r['new']:
                    text += '   - новая папка на диске'
                elif r['on_disk'] is False:
                    text += '   - на диске её нет'
                if r['files'] and r['files'] >= ed.BIG_FOLDER:
                    text += '   - очень большая, проверка займёт много минут'
            it = QListWidgetItem(text)
            it.setData(ROLE, r['path'])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r['checked'] else Qt.Unchecked)
            self.folders.addItem(it)

    # --- галочки ---
    def _set_all(self, st):
        for i in range(self.folders.count()):
            self.folders.item(i).setCheckState(st)

    def _toggle_list(self, lw):
        items = lw.selectedItems() or ([lw.currentItem()] if lw.currentItem() else [])
        if items:
            st = Qt.Unchecked if items[0].checkState() == Qt.Checked else Qt.Checked
            for it in items:
                it.setCheckState(st)

    def _toggle_items(self, items):
        items = [x for x in items if x.flags() & Qt.ItemIsUserCheckable]
        if items:
            st = Qt.Unchecked if items[0].checkState(0) == Qt.Checked else Qt.Checked
            for it in items:
                it.setCheckState(0, st)

    def _toggle_tree(self):
        self._toggle_items(self.tree.selectedItems() or ([self.tree.currentItem()] if self.tree.currentItem() else []))

    def _set_selected(self, st):
        tree = self.tree if self.mode.currentIndex() == 0 else self.otree
        for it in tree.selectedItems():
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(0, st)

    # --- проверка ---
    def start_scan(self):
        r = self.current()
        if not r or self.busy:
            return
        folders, root_files = [], False
        for i in range(self.folders.count()):
            it = self.folders.item(i)
            if it.checkState() == Qt.Checked:
                if it.data(ROLE) == '':
                    root_files = True
                else:
                    folders.append(it.data(ROLE))
        if not folders and not root_files:
            QMessageBox.information(self, TITLE, 'Отметьте хотя бы одну папку, где искать изменения.')
            return
        self.busy, self.stop, self.prog = True, threading.Event(), None
        self.check_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.write_btn.setEnabled(False)
        self.tree.clear()
        self.notes.setText('Проверяю… Пока идёт проверка, не меняйте эти папки в Проводнике.')
        self.timer.start(300)
        stop = self.stop

        def run():
            try:
                return ed.scan(r['disk'], self.root, folders, root_files, progress=self._progress, stop=stop, serial=self.serial)
            except ed.Stopped:
                return None
        self.win.bg.run(run, ok=self.got_diff)

    def _progress(self, d):
        self.prog = d

    def show_progress(self):
        if self.prog:
            self.progress.setText(f'Просмотрено папок: {num(self.prog["dirs"])}, файлов: {num(self.prog["files"])}')

    def _done(self):
        self.busy = False
        self.timer.stop()
        self.check_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.write_btn.setEnabled(True)

    def got_diff(self, diff):
        self._done()
        self.show_progress()
        if diff is None:
            self.notes.setText('Проверка остановлена - результат не используется. Нажмите «Проверить», чтобы начать заново.')
            return
        if diff.disk != self.disk.currentData():
            return
        self.diff = diff
        self.fill_tree()

    # --- что записать ---
    def choice(self):
        res = {}
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                it = g.child(j)
                tag = it.data(0, ROLE)
                if not tag or tag[0] != 'unit' or it.isHidden() or not it.flags() & Qt.ItemIsUserCheckable:
                    continue
                st = it.checkState(0)
                if st == Qt.Checked:
                    res[tag[1]] = None
                elif st == Qt.PartiallyChecked and it.childCount():
                    res[tag[1]] = [it.child(k).data(0, ROLE)[2] for k in range(it.childCount())
                                   if it.child(k).checkState(0) == Qt.Checked]
        return res

    def offline_checked(self):
        res = []

        def walk(it):
            for k in range(it.childCount()):
                c = it.child(k)
                p = c.data(0, ROLE)
                if p is None:
                    continue
                if c.checkState(0) == Qt.Checked:
                    res.append(p)
                walk(c)
        walk(self.otree.invisibleRootItem())
        return res

    def rows(self):
        """Строки к записи и признак «папка целиком» (для сводки)."""
        r = self.current()
        if not r:
            return []
        if self.mode.currentIndex() == 0:
            return ed.selection_rows(self.diff, self.choice()) if self.diff else []
        act = self.oact.currentText()
        out = []
        for row in ed.offline_rows(r['disk'], act, self.offline_checked(), self.odisk2.currentData() or '', self.odest.text()):
            n, b = self.off_sizes.get(row[2], (0, 0))
            out.append(row + (n, b, True))
        return out

    def update_summary(self):
        try:
            self.summary.setText(ed.summary(self.rows()))
        except sv.Refused as e:
            self.summary.setText(str(e))

    def write(self):
        try:
            rows = self.rows()
        except sv.Refused as e:
            QMessageBox.information(self, TITLE, str(e))
            return
        if not rows:
            QMessageBox.information(self, TITLE, 'Ничего не отмечено. Отметьте галочками то, что вы сделали в Проводнике.')
            return
        date = self.date.date().toString('dd.MM.yyyy')
        lines = [ed.summary(rows), '', f'Дата: {date}.']
        lines += ['  ' + ed.describe([date] + list(r[:5])).split(': ', 1)[1] for r in rows[:12]]
        if len(rows) > 12:
            lines.append(f'  … и ещё {len(rows) - 12}')
        if any(r[0] == 'перемещено' for r in rows):
            lines.append('\nВы подтверждаете, что действительно переместили (переименовали) эти файлы? База перенесёт на новое '
                         'место их хеши и подтверждение.')
        if any(r[0] == 'скопировано' for r in rows):
            lines.append('\nКопия «со слов» не подтверждена: удалять оригиналы по ней нельзя (для подтверждения - пересканируйте).')
        if any(r[0] == 'удалено' for r in rows):
            lines.append('\n«Удалено» уберёт эти записи из базы (с диска ничего не удаляется).')
        if QMessageBox.question(self, TITLE, '\n'.join(lines) + '\n\nЗаписать?') != QMessageBox.Yes:
            return
        self.busy = True
        self.write_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.notes.setText('Записываю…')
        diff = self.diff if self.mode.currentIndex() == 0 else None
        self.win.bg.run(self._write, date, rows, diff, ok=self.written)

    @staticmethod
    def _write(date, rows, diff):
        try:
            return ed.write(date, rows, diff=diff)
        except sv.Refused as e:
            return str(e)

    def written(self, res):
        self.busy = False
        self.write_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        if isinstance(res, str):
            self.notes.setText('Не записано: ' + res)
            QMessageBox.warning(self, TITLE, 'Ничего не записано.\n\n' + res)
            return
        text = ed.result_text(res)
        self.notes.setText(text + '\nЧтобы увидеть, что осталось, нажмите «Проверить» ещё раз.')
        (QMessageBox.warning if res['failed'] else QMessageBox.information)(self, TITLE, text)
        self.diff = None
        self.tree.clear()
        if self.mode.currentIndex() == 1:
            self._fill_offline(self.disk.currentData())
        self.update_summary()

    def can_close(self):
        return not self.busy
