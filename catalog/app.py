"""«Архив дисков» - окно программы: Обзор, Задания, Диски и папки, Команды (этап 1 переноса команд, 15.11.2026).

Запуск: ярлык на рабочем столе или  pythonw catalog\\app.py
Окно - оболочка над тем же ядром: считает hashbase.py, данные даёт service.py, копируют и перемещают те же
шаблоны (в своём окне PowerShell, с вопросом «да» и остановкой по Q). Окно ничего не удаляет и базу открытой
не держит. Каждые 10 секунд оно проверяет, не появились ли новые журналы или строки таблиц, и само применяет
их к базе. Ошибки - в «_БАЗА\\ответы\\окно - ошибки.log».
"""
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hb_core import api as hb  # noqa: E402  (ядро; hashbase.py - только обёртка командной строки)
import service as sv           # noqa: E402
import commands_page           # noqa: E402
import rescan_dialog           # noqa: E402

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal   # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication                                  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,  # noqa: E402
                               QListWidget, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
STATE_COLOR = {'идёт': '#1565c0', 'готово': '#2e7d32', 'готово с ошибками': '#c62828', 'прервано': '#e65100',
               'состояние неизвестно': '#6d4c41', 'не запускалось': '#455a64'}


def log_error(text):
    try:
        hb.ANSWERS.mkdir(parents=True, exist_ok=True)
        with open(hb.ANSWERS / 'окно - ошибки.log', 'a', encoding='utf-8') as f:
            f.write(time.strftime('%d.%m.%Y %H:%M:%S ') + text + '\n')
    except OSError:
        pass


def gib(x):
    return f'{x:,.1f}'.replace(',', ' ')


# ---------- фоновые задачи: окно не замирает ----------

class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, fn, args, ok, fail):
        super().__init__()
        self.fn, self.args, self.sig = fn, args, _Signals()
        self.sig.done.connect(ok)
        self.sig.failed.connect(fail)

    def run(self):
        try:
            self.sig.done.emit(self.fn(*self.args))
        except SystemExit as e:
            self.sig.failed.emit(str(e))
        except Exception:                                     # noqa: BLE001
            self.sig.failed.emit(traceback.format_exc())


class Background:
    """Запуск функции в фоне; ответ приходит в главный поток. Держит ссылки, пока задача не закончится."""

    def __init__(self, window):
        self.window, self.jobs = window, set()

    def run(self, fn, *args, ok=None, quiet=False):
        def done(res, job=None):
            if ok:
                ok(res)

        def fail(text):
            log_error(text)
            if not quiet:
                self.window.show_error(text)
        job = Job(fn, args, done, fail)
        self.jobs.add(job)
        job.sig.done.connect(lambda *_: self.jobs.discard(job))
        job.sig.failed.connect(lambda *_: self.jobs.discard(job))
        QThreadPool.globalInstance().start(job)


def table(headers, stretch=0):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


def cell(text, right=False, color=None):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it


# ---------- Обзор ----------

class OverviewPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn = QPushButton('Обновить')
        self.btn.clicked.connect(self.refresh)
        top.addWidget(QLabel('<b>Обзор</b>'))
        top.addStretch()
        top.addWidget(self.btn)
        lay.addLayout(top)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(False)
        lay.addWidget(self.text)

    def refresh(self):
        self.text.setHtml('<p>Считаю…</p>')
        self.win.bg.run(lambda: (sv.overview(), sv.tasks()), ok=self.render)

    def render(self, res):
        ov, tasks = res
        h = [f'<p>База собрана <b>{ov["built"]}</b>: носителей {ov["disks"]}, файлов {ov["files"]:,}.</p>'.replace(',', ' ')]
        h.append('<table cellpadding="6" border="1" style="border-collapse:collapse">'
                 '<tr><th>Диск</th><th>Сейчас</th><th>Свободно</th><th>Учтено файлов, ГБ</th>'
                 '<th>Подтверждено (S, C)</th><th>НЕ подтверждено (Z, U, X)</th></tr>')
        for d, m in ov['main'].items():
            ev = m['ev']
            conf = ev.get('S', 0) + ev.get('C', 0)
            weak = ev.get('Z', 0) + ev.get('U', 0) + ev.get('X', 0)
            free = f'{gib(m["free_gib"])} ГБ' if 'free_gib' in m else '—'
            h.append(f'<tr><td><b>{d}</b></td><td>{m["letter"] or "не подключён"}</td><td align="right">{free}</td>'
                     f'<td align="right">{gib(m["gib"])}</td><td align="right">{conf:,}</td>'
                     f'<td align="right" style="color:{"#c62828" if weak else "#2e7d32"}">{weak:,}</td></tr>'.replace(',', ' '))
        h.append(f'</table><p style="color:gray">Свободное место проверено в {ov["checked"]}.</p>')
        att = []
        for t in tasks:
            if t['state'] not in ('готово', 'не запускалось'):
                att.append(f'Задание «{t["task"]}»: {t["state"]} ({t["done"]} из {t["total"]}, ошибок {t["errors"]})')
        waiting = [t['task'] for t in tasks if t['state'] == 'не запускалось']
        att += [f'Журнал не прочитан программой: {x}' for x in ov['skipped']]
        att += ov['warn']
        h.append('<h3>Требует внимания</h3>')
        h.append('<ul>' + ''.join(f'<li>{x}</li>' for x in att) + '</ul>' if att else '<p>Ничего.</p>')
        if waiting:
            h.append('<h3>Ждут запуска</h3><ul>' + ''.join(f'<li>{x}</li>' for x in waiting) + '</ul>')
        self.text.setHtml(''.join(h))


# ---------- Задания ----------

class TasksPage(QWidget):
    HEAD = ['Задание', 'Вид', 'Состояние', 'Обработано', 'Ошибок и пропусков']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows = win, []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('<b>Задания</b> - папки в «Запускаемые скрипты». Копирование и перемещение идут в '
                             'своём окне: там спросят «да», остановка - клавиша Q.'))
        self.t = table(self.HEAD)
        lay.addWidget(self.t)
        bar = QHBoxLayout()
        for text, fn in (('Обновить', self.refresh), ('Запустить…', self.launch), ('Открыть папку', self.open_dir),
                         ('Открыть журнал', self.open_log), ('Сводка для чата', self.to_chat)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def refresh(self):
        self.win.bg.run(sv.tasks, ok=self.render, quiet=True)

    def render(self, rows):
        sel = self.current()
        self.rows = rows
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.t.setItem(i, 0, cell(r['task']))
            self.t.setItem(i, 1, cell(r['kind']))
            self.t.setItem(i, 2, cell(r['state'], color=STATE_COLOR.get(r['state'])))
            self.t.setItem(i, 3, cell(f'{r["done"]} из {r["total"]}', right=True))
            self.t.setItem(i, 4, cell(r['errors'] + r['skipped'], right=True))
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        busy = any(r['state'] == 'идёт' for r in rows)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()

    def current(self):
        i = self.t.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def need(self):
        r = self.current()
        if not r:
            QMessageBox.information(self, TITLE, 'Сначала выберите задание в таблице.')
        return r

    def launch(self):
        r = self.need()
        if not r:
            return
        d = hb.TASKS / r['task']
        if r['state'] == 'идёт':
            QMessageBox.information(self, TITLE, 'Это задание уже идёт.')
            return
        how = (Path(d) / 'Как запустить.txt')
        info = how.read_text(encoding='utf-8-sig')[:900] if how.exists() else ''
        ans = QMessageBox.question(self, TITLE, f'Запустить «{r["task"]}»?\n\n{info}\n\nОткроется отдельное окно: проверьте '
                                   'сводку и введите «да». Остановить - клавиша Q, повторный запуск продолжит.')
        if ans != QMessageBox.Yes:
            return
        os.startfile(str(d / 'Запустить.cmd'))
        QTimer.singleShot(3000, self.refresh)
        self.timer.start(5000)

    def open_dir(self):
        r = self.need()
        if r:
            os.startfile(str(hb.TASKS / r['task']))

    def open_log(self):
        r = self.need()
        if r and r['journal']:
            os.startfile(r['journal'])
        elif r:
            QMessageBox.information(self, TITLE, 'Журнала ещё нет: задание не запускалось.')

    def to_chat(self):
        r = self.need()
        if r:
            QGuiApplication.clipboard().setText(
                f'Задание «{r["task"]}» ({r["kind"]}): {r["state"]}; обработано {r["done"]} из {r["total"]}, ошибок '
                f'{r["errors"]}, пропусков {r["skipped"]}. Журнал: {r["journal"] or "нет"}')
            self.win.statusBar().showMessage('Сводка скопирована - вставьте её в чат.', 5000)


# ---------- Диски и папки ----------

class DisksPage(QWidget):
    HEAD = ['Диск', 'Метка', 'Сейчас', 'Файлов', 'ГБ', 'Опись', 'Состояние описи', 'Частичных сканов']
    TREE = ['Папка', 'Файлов', 'ГБ', 'фото', 'видео', 'тексты', 'прочие', 'мусор', 'Решение владельца']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.disk = win, [], None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('<b>Диски и папки</b>'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти папки по словам, например: Сафари')
        self.search.returnPressed.connect(self.find)
        top.addWidget(self.search, 1)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter(Qt.Vertical)
        self.t = table(self.HEAD, stretch=1)
        self.t.itemSelectionChanged.connect(self.pick)
        split.addWidget(self.t)
        low = QWidget()
        ll = QVBoxLayout(low)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.TREE)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)      # несколько папок - с Ctrl
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemSelectionChanged.connect(lambda: self.info.setText(''))
        ll.addWidget(self.tree)
        bar = QHBoxLayout()
        b = QPushButton('Чего из папки нет на 45 и 77?')
        b.clicked.connect(self.presence)
        bar.addWidget(b)
        self.rescan_btn = QPushButton('Пересканировать папку…')
        self.rescan_btn.setToolTip('Подключённый диск: заново прочитать только новые и изменённые файлы выбранных папок '
                                   '(можно выбрать несколько с Ctrl). Сначала - предпросмотр, затем подтверждение.')
        self.rescan_btn.clicked.connect(self.rescan)
        bar.addWidget(self.rescan_btn)
        self.info = QLabel('')
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setWordWrap(True)
        bar.addWidget(self.info, 1)
        ll.addLayout(bar)
        split.addWidget(low)
        split.setSizes([260, 520])
        lay.addWidget(split)

    def refresh(self):
        self.win.bg.run(sv.disks, ok=self.render)

    def render(self, rows):
        self.rows = rows
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r['disk'], r['label'], r['letter'] or '—', f'{r["files"]:,}'.replace(',', ' '), gib(r['gib']),
                    r['scanned'], r['status'], r['partial'] or '']
            for j, v in enumerate(vals):
                self.t.setItem(i, j, cell(v, right=j in (3, 4, 7), color='#2e7d32' if j == 2 and r['letter'] else None))

    def pick(self):
        i = self.t.currentRow()
        if 0 <= i < len(self.rows):
            self.disk = self.rows[i]['disk']
            self.tree.clear()
            self.info.setText('')
            root = QTreeWidgetItem([f'{self.disk} (весь диск)'])
            root.setData(0, Qt.UserRole, '')
            self.tree.addTopLevelItem(root)
            self.load(root)
            root.setExpanded(True)

    def load(self, item):
        disk, path = self.disk, item.data(0, Qt.UserRole)

        def fill(rows):
            item.takeChildren()
            for r in rows:
                ch = QTreeWidgetItem([r['name'], f'{r["files"]:,}'.replace(',', ' '), gib(r['gib'])] +
                                     [gib(x) for x in r['types']] + [r['decision']])
                for k in range(1, 8):
                    ch.setTextAlignment(k, Qt.AlignRight | Qt.AlignVCenter)
                ch.setData(0, Qt.UserRole, r['path'])
                ch.addChild(QTreeWidgetItem(['…']))            # раскрывается лениво
                item.addChild(ch)
        item.setData(1, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, disk, path, ok=fill)

    def expand(self, item):
        if not item.data(1, Qt.UserRole):
            self.load(item)

    def presence(self):
        it = self.tree.currentItem()
        if not it or self.disk is None:
            QMessageBox.information(self, TITLE, 'Выберите диск и папку.')
            return
        path = it.data(0, Qt.UserRole) or ''
        self.info.setText('Считаю…')

        def show(r):
            self.info.setText(f'{self.disk}\\{path or "(весь диск)"}: фото и видео с хешем {r["files"]:,} ({gib(r["gib"])} ГБ). '
                              f'Нет на 45: {gib(r["no45"])} ГБ, нет на 77: {gib(r["no77"])} ГБ, больше нигде: '
                              f'{gib(r["only"])} ГБ. Без хеша (не сравниваются): {r["nohash"]:,}.'.replace(',', ' '))
        self.win.bg.run(sv.folder_presence, self.disk, path, ok=show)

    def rescan(self):
        """Пересканировать выбранные папки подключённого диска: окно предпросмотра; скан - только по подтверждению."""
        items = [it for it in self.tree.selectedItems() if it.data(0, Qt.UserRole)]
        if self.disk is None or not items:
            QMessageBox.information(self, TITLE, 'Выберите диск и одну или несколько его папок (с Ctrl). '
                                    'Весь диск целиком - это полное сканирование, его делает сканер дисков.')
            return
        row = next((r for r in self.rows if r['disk'] == self.disk), {})
        if not row.get('letter'):
            QMessageBox.information(self, TITLE, f'{self.disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, self.disk, [it.data(0, Qt.UserRole) for it in items])
        self.win.rescan.show()

    def find(self):
        words = self.search.text().split()
        if not words:
            return

        def show(rows):
            self.tree.clear()
            self.disk = None
            for r in rows:
                it = QTreeWidgetItem([f'{r["disk"]}\\{r["path"]}', f'{r["files"]:,}'.replace(',', ' '), gib(r['gib'])])
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                self.tree.addTopLevelItem(it)
            self.info.setText(f'Найдено папок: {len(rows)} (вложенные совпадения не показаны).')
        self.win.bg.run(sv.find_folders, words, ok=show)


# ---------- главное окно ----------

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.resize(1250, 800)
        self.bg = Background(self)
        self.updating, self.sig = False, None
        self.pages = [('Обзор', OverviewPage(self)), ('Задания', TasksPage(self)), ('Диски и папки', DisksPage(self)),
                      ('Команды', commands_page.CommandsPage(self))]
        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
        f = QFont()
        f.setPointSize(11)
        self.nav.setFont(f)
        self.stack = QStackedWidget()
        for name, page in self.pages:
            self.nav.addItem(name)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.go)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_sources)
        self.timer.start(10000)
        self.nav.setCurrentRow(0)
        self.apply_new()

    def go(self, i):
        self.stack.setCurrentIndex(i)
        if not hb.DB.exists() or sv.generation() is None:
            self.statusBar().showMessage('База собирается - экран откроется, когда она будет готова (при первом запуске - несколько минут).')
            return
        self.pages[i][1].refresh()

    def page(self, name):
        return next(p for n, p in self.pages if n == name)

    def open_page(self, name):
        self.nav.setCurrentRow([n for n, _ in self.pages].index(name))

    def closeEvent(self, e):                                  # noqa: N802
        if not self.page('Команды').can_close():
            e.ignore()
            return
        if getattr(self, 'rescan', None) is not None and self.rescan.running:
            QMessageBox.information(self, TITLE, 'Идёт пересканирование папок. Сначала остановите его.')
            e.ignore()
            return
        super().closeEvent(e)

    def show_error(self, text):
        short = text.strip().splitlines()[-1] if text.strip() else 'ошибка'
        QMessageBox.warning(self, TITLE, f'Не получилось: {short}\n\nПодробно - в «_БАЗА\\ответы\\окно - ошибки.log».')

    def check_sources(self):
        if self.updating:
            return
        self.bg.run(sv.sources_signature, ok=self.on_signature, quiet=True)

    def on_signature(self, sig):
        if self.sig is not None and sig != self.sig:
            self.apply_new()
        self.sig = sig

    def apply_new(self, then=None):
        """Применить новые модули (журналы, строки таблиц, сканы) - в фоне; затем перечитать экран.
        then(результат) - вызвать после применения (окно пересканирования показывает итог приёма)."""
        if self.updating:
            if then:                                  # идёт другое применение - повторить после него
                QTimer.singleShot(2000, lambda: self.apply_new(then))
            return
        self.updating = True
        self.statusBar().showMessage('Проверяю новые журналы и записи…')

        def done(res):
            self.updating = False
            gen = sv.generation()
            msg = {'update': 'Применены новые модули. ', 'rebuild': 'База собрана заново. '}.get(res, '')
            self.statusBar().showMessage(f'{msg}База собрана {gen}.')
            if gen:
                self.stack.currentWidget().refresh()
            if then:
                then(res)

        def fail(text):
            self.updating = False
            log_error(text)
            self.statusBar().showMessage('Не удалось обновить базу - подробности в «окно - ошибки.log».')
            if then:
                then(None)
        job = Job(hb.update, (None, True), done, fail)
        self.bg.jobs.add(job)
        QThreadPool.globalInstance().start(job)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    sys.excepthook = lambda t, v, tb: (log_error(''.join(traceback.format_exception(t, v, tb))),
                                       QMessageBox.warning(None, TITLE, f'Ошибка: {v}'))
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
