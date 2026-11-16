"""Страница окна «Я сделал в Проводнике» (вместо форм manual и fix-manual раздела «Команды»).

Вкладка «Что изменилось на диске»: окно само сравнивает базу с оглавлением подключённого диска
(explorer_diff, содержимое файлов не читается), владелец отмечает галочками, что записать. Диск не подключён -
папки из каталога базы с галочками и действие.
Вкладка «Записанные действия»: все строки «ручные операции.tsv» словами; «Редактировать» - через service.fix_manual.
Запись - только через service (единый путь записи). Подключение в окно: ('Я сделал в Проводнике', ExplorerPage(self)).
"""
import threading

from PySide6.QtCore import QDate, QDateTime, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStackedWidget, QStyle,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import explorer_diff as ed
import service as sv

TITLE = 'Я сделал в Проводнике'
ROLE = Qt.UserRole
GROUPS = [
    ('move', 'Я переместил или переименовал внутри этого диска (хеш и подтверждение сохранятся)', True),
    ('gone', 'Исчезли с диска → записать «удалено»', True),
    ('copy', 'Появились, такие же файлы есть на другом диске → «скопировано оттуда» (копия «со слов», не подтверждена)', True),
    ('new', 'Появились, откуда - неизвестно: записать нельзя, пересканируйте папку', False),
]
RESCAN_HINT = ('Чтобы база узнала новые файлы и получила их хеши, пересканируйте эти папки: раздел «Диски и папки» → '
               '«Пересканировать папку». Пересканирование читает сами файлы и считает хеши - это отдельное действие.')


def today():
    return QDate.currentDate().toString('dd.MM.yyyy')


def num(n):
    return f'{n:,}'.replace(',', ' ')


class SpaceToggles(QObject):
    """Пробел отмечает или снимает галочки у ВСЕХ выделенных строк (выделение мышью, Shift, Ctrl)."""

    def __init__(self, view, toggle):
        super().__init__(view)
        self.toggle = toggle
        view.installEventFilter(self)

    def eventFilter(self, obj, ev):                              # noqa: N802
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Space:
            self.toggle()
            return True
        return False


def checkable(item, on=True):
    if on:
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
    else:
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)


# ---------- вкладка 1: что изменилось ----------

class ChangesTab(QWidget):
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

    def fill_tree(self):
        diff = self.diff
        self.tree.blockSignals(True)
        self.tree.clear()
        style = self.style()
        icon_dir, icon_file = style.standardIcon(QStyle.SP_DirIcon), style.standardIcon(QStyle.SP_FileIcon)
        units = diff.units[:ed.UNITS_MAX]
        children_left = 50000
        for kind, title, writable in GROUPS:
            idx = [i for i, u in enumerate(units) if u['kind'] == kind]
            if not idx:
                continue
            g = QTreeWidgetItem([f'{title}  ({num(len(idx))})'])
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            g.setData(0, ROLE, ('group', kind))
            if writable:
                g.setFlags(g.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                g.setCheckState(0, Qt.Unchecked)
            else:
                checkable(g, False)
            self.tree.addTopLevelItem(g)
            for i in idx:
                u = units[i]
                it = QTreeWidgetItem([self.unit_text(u), num(u['files']), ed.gb_text(u['bytes']), ed.when_text(u['when'])])
                it.setIcon(0, icon_dir if u['is_dir'] else icon_file)
                it.setData(0, ROLE, ('unit', i))
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                g.addChild(it)
                if writable:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.Unchecked)
                    if u['children'] and len(u['children']) <= children_left:
                        children_left -= len(u['children'])
                        it.setFlags(it.flags() | Qt.ItemIsAutoTristate)
                        for j, ch in enumerate(u['children']):
                            text = ch['path'][len(u.get('src') or u['path']) + 1:] if kind == 'move' else ch['path'][len(u['path']) + 1:]
                            c = QTreeWidgetItem([text, '1', ed.gb_text(ch['bytes']), ed.when_text(ch.get('mtime'))])
                            c.setIcon(0, icon_file)
                            c.setData(0, ROLE, ('child', i, j))
                            c.setFlags(c.flags() | Qt.ItemIsUserCheckable)
                            c.setCheckState(0, Qt.Unchecked)
                            it.addChild(c)
                    elif u['is_dir']:
                        it.setToolTip(0, 'Папка большая - записывается только целиком.')
                else:
                    checkable(it, False)
            g.setExpanded(True)
        info = []
        for title, rows in (('Изменился размер (тот же путь) - пересканируйте эти файлы', [f'{p}: было {num(a)} байт, стало {num(b)}' for p, a, b in diff.changed]),
                            ('Тот же размер, но другая дата изменения - содержимое могли изменить, пересканируйте эти файлы',
                             [f'{p}: дата в базе {ed.when_text(a)}, на диске {ed.when_text(b)}' for p, a, b in diff.touched]),
                            ('Изменилось только написание имени (большие/маленькие буквы) - не записывается', [f'{a} → {b}' for a, b in diff.case]),
                            ('Не проверено (не прочитано или пропущено) - в этих местах исчезновения не ищутся', [f'{p}: {why}' for p, why in diff.bad]),
                            ('Два имени, различающихся только регистром - такие места не записываются', diff.dup)):
            if rows:
                g = QTreeWidgetItem([f'{title}  ({num(len(rows))})'])
                g.setForeground(0, QColor('#6d4c41'))
                checkable(g, False)
                self.tree.addTopLevelItem(g)
                for x in rows[:500]:
                    c = QTreeWidgetItem([x])
                    checkable(c, False)
                    g.addChild(c)
        self.tree.blockSignals(False)
        notes = [f'Проверено папок: {num(diff.scanned)}, файлов на диске: {num(diff.files)}. Различий: {num(len(diff.units))}.']
        if not diff.units and not diff.changed:
            notes.append('База и диск совпадают - записывать нечего.')
        if len(diff.units) > ed.UNITS_MAX:
            notes.append(f'Показаны первые {num(ed.UNITS_MAX)} различий - отметьте меньше папок и проверьте снова, чтобы увидеть остальные.')
        if any(u['kind'] == 'new' for u in units):
            notes.append(RESCAN_HINT)
        self.notes.setText('\n'.join(notes))
        self.apply_filter()

    @staticmethod
    def unit_text(u):
        if u['kind'] == 'move':
            a, b = u['src'], u['path']
            if ed.parent(a) == ed.parent(b):
                return f'переименовано: {a}  →  {b.rsplit(ed.SEP, 1)[-1]}'
            return f'{a}  →  {b}'
        if u['kind'] == 'copy':
            more = f' (такой же файл ещё на {u["others"]} дисках)' if u.get('others') else ''
            return f'{u["path"]}   ← с {u["src_disk"]}\\{u["src"]}{more}'
        return u['path']

    def apply_filter(self, *_):
        on = self.only_after.isChecked()
        cut = self.after.dateTime().toSecsSinceEpoch()
        hidden = 0
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                it = g.child(j)
                tag = it.data(0, ROLE)
                if not tag or tag[0] != 'unit':
                    continue
                hide = on and (self.diff.units[tag[1]]['when'] or 0) < cut
                it.setHidden(hide)
                hidden += hide
        self.only_after.setText(f'Показывать только изменённое после:' + (f' (скрыто {num(hidden)})' if on else ''))
        self.update_summary()

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

    # --- диск не подключён ---
    def _fill_offline(self, disk):
        self.otree.clear()
        self.off_sizes = {}
        self.win.bg.run(sv.folder_children, disk, '', ok=lambda rows: self._add_offline(self.otree.invisibleRootItem(), rows))

    def _add_offline(self, parent, rows):
        self.otree.blockSignals(True)
        for r in rows:
            it = QTreeWidgetItem([r['name'], num(r['files']), f'{r["gib"]:.2f}'])
            it.setData(0, ROLE, r['path'])
            checkable(it)
            if parent is not self.otree.invisibleRootItem() and parent.checkState(0) == Qt.Checked:
                it.setCheckState(0, Qt.Checked)
            self.off_sizes[r['path']] = (r['files'], r['gib'] * ed.hb.GIB)
            ph = QTreeWidgetItem(['…'])
            checkable(ph, False)
            it.addChild(ph)
            parent.addChild(it)
        self.otree.blockSignals(False)

    def _expand_offline(self, item):
        if item.childCount() == 1 and item.child(0).data(0, ROLE) is None:
            item.takeChild(0)
            self.win.bg.run(sv.folder_children, self.disk.currentData(), item.data(0, ROLE),
                            ok=lambda rows: self._add_offline(item, rows))

    def _offline_act(self, act):
        on = act != 'удалено'
        for w in (self.oto_label, self.odisk2, self.odest):
            w.setVisible(on)
        self.recount.start(0)

    def can_close(self):
        return not self.busy


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


# ---------- страница ----------

class ExplorerPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        head = QLabel('<b>Я сделал в Проводнике</b> - отметьте, что вы скопировали, переместили или удалили сами, '
                      'чтобы база знала, что где лежит.')
        head.setWordWrap(True)
        lay.addWidget(head)
        self.tabs = QTabWidget()
        self.changes, self.records = ChangesTab(win), RecordsTab(win)
        self.tabs.addTab(self.changes, 'Что изменилось на диске')
        self.tabs.addTab(self.records, 'Записанные действия')
        self.tabs.currentChanged.connect(lambda *_: self.refresh())
        lay.addWidget(self.tabs, 1)

    def refresh(self):
        (self.changes if self.tabs.currentIndex() == 0 else self.records).refresh()

    def can_close(self):
        """Окно не закрывать во время записи или исправления."""
        return not self.changes.busy and not self.records.busy
