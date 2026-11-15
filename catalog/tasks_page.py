"""Раздел окна «Задания» (15.11.2026): что сейчас идёт, ход и оценка времени по журналам, запуск отмеченных
заданий (каждое в своём окне PowerShell или по очереди в одном), «Разложить на источнике…» после копирования.

Окно ничего не копирует и не перемещает само: оно открывает «Запустить.cmd» задания, а задание перемещения
создаёт командой mvlist (отдельным процессом, как раздел «Команды»). Состояние задания - service.task_state
(правила, раздел 6); здесь к нему добавляется ход: сколько файлов и ГБ, скорость, сколько осталось.
Спор с GPT - «Проверка Архитектуры сортировки файлов\\Перемещение_на_любые_диски_v1.md».
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import build_pilot as bp
import commands_page as cpg
import service as sv
from hb_core import api as hb

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

TITLE = 'Архив дисков'
STATE_COLOR = {'идёт': '#1565c0', 'готово': '#2e7d32', 'готово с ошибками': '#c62828', 'прервано': '#e65100',
               'состояние неизвестно': '#6d4c41', 'не запускалось': '#455a64', 'в очереди': '#6a1b9a'}
DONE = ('готово', 'готово с ошибками')
MOVE_SUFFIX = ' - разложить на источнике'       # имя задания перемещения по умолчанию (mvlist --task)
MIN_BYTES, MIN_SEC = 10 * 1024 ** 2, 30          # раньше оценка времени не показывается
EXPLAIN = ('После копирования и проверки копий файлы на исходном диске можно перенести в папку «ПЕРЕНЕСЕНО → …» '
           'с сохранением всех папок и подпапок — так видно, что уже сохранено. Например, F:\\Котуй 2026\\Валере\\1.jpg '
           '→ F:\\ПЕРЕНЕСЕНО → 78\\Котуй 2026\\Валере\\1.jpg (78 — номер диска, где лежит копия). Это отдельный шаг '
           'с вашим подтверждением: кнопка «Разложить на источнике…» у законченного копирования. Ничего не удаляется. '
           'Переносится только файл, копия которого проверена по SHA-256 на всех дисках, куда его копировали.')


def gb(b):
    return f'{b / 1024 ** 3:,.1f}'.replace(',', ' ')


def n(x):
    return f'{x:,}'.replace(',', ' ')


def fmt_eta(sec):
    """Секунды -> «~1 ч 10 мин» / «~25 мин» / «меньше минуты»."""
    if sec is None:
        return ''
    sec = max(0, int(sec))
    if sec < 60:
        return 'меньше минуты'
    h, m = divmod((sec + 59) // 60, 60)
    if h >= 48:
        return f'~{h // 24} дн {h % 24} ч'
    return f'~{h} ч {m} мин' if h else f'~{m} мин'


def fmt_ago(sec):
    sec = int(sec)
    if sec < 90:
        return f'{sec} с назад'
    return f'{sec // 60} мин назад' if sec < 7200 else f'{sec // 3600} ч назад'


# ---------- ход задания по журналам ----------

_CACHE = {}
_TIME_RE = re.compile(r'^(\d\d):(\d\d):(\d\d)$')


def _read_log(log, kind):
    """Строки журнала -> [(ключ, результат, байты, секунды от полуночи дня запуска)]; кэш по размеру и времени файла."""
    st = log.stat()
    key = (str(log), st.st_size, st.st_mtime_ns, kind)
    if key in _CACHE:
        return _CACHE[key]
    rows, prev, day = [], None, 0
    for f in hb.read_tsv(log)[1:]:
        if kind == 'копирование' and len(f) >= 7:
            k, res, size = (f[1], f[5]), f[2], f[3]
        elif kind == 'перемещение' and len(f) >= 6:
            k, res, size = f[4], f[1], f[2]
        else:
            continue
        m = _TIME_RE.match(f[0].strip())
        t = None
        if m:
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if prev is not None and t < prev:
                day += 1                                  # время в журнале - только ЧЧ:ММ:СС: переход через полночь
            prev = t
            t += day * 86400
        try:
            size = int(size)
        except ValueError:
            size = 0
        rows.append((k, res, size, t))
    _CACHE.clear() if len(_CACHE) > 200 else None
    _CACHE[key] = rows
    return rows


def progress(task, kind, running=False, now=None):
    """Ход задания: обработано файлов и байт (по уникальной строке списка, последний результат), скорость
    текущего запуска, оценка оставшегося времени, примеры ошибок."""
    task, now = Path(task), now or time.time()
    lst = task / ('список.tsv' if kind == 'копирование' else 'перемещение.tsv')
    total_b = 0
    for f in hb.read_tsv(lst):
        try:
            total_b += int(f[2] if kind == 'копирование' else f[1])
        except (IndexError, ValueError):
            pass
    logs = sorted(task.glob(('Журнал копирования' if kind == 'копирование' else 'Журнал перемещения') + ' *.tsv'))
    last, cur, start = {}, [], None
    for log in logs:
        cur = _read_log(log, kind)
        for k, res, size, _t in cur:
            last[k] = (res, size)
        start = hb.log_time(log)
    ok_words = ('скопирован', 'уже есть') if kind == 'копирование' else ('перемещён', 'уже перемещён')
    done_b = sum(s for _r, s in last.values())
    errs = [f'{k[1] if isinstance(k, tuple) else k}: {r}' for k, (r, _s) in last.items()
            if not r.startswith(ok_words)][:5]
    res = dict(total_b=total_b, done_b=done_b, speed=None, eta=None, eta_text='', ago=None, examples=errs)
    if not logs or start is None:
        return res
    times = [t for _k, _r, _s, t in cur if t is not None]
    t0 = time.localtime(start)
    start_sod = t0.tm_hour * 3600 + t0.tm_min * 60 + t0.tm_sec
    last_ts = start + (times[-1] - start_sod) if times else start
    if times and last_ts < start:                          # первая строка «до» старта: старт в имени - с точностью до минуты
        last_ts = start
    moved_b = sum(s for _k, r, s, _t in cur if r.startswith('скопирован' if kind == 'копирование' else 'перемещён'))
    elapsed = (now if running else last_ts) - start
    if running:
        res['ago'] = max(0, now - last_ts)
    if kind == 'копирование':
        if elapsed > 0 and moved_b > 0:
            res['speed'] = moved_b / elapsed
        if running:
            if moved_b >= MIN_BYTES and elapsed >= MIN_SEC and res['speed']:
                res['eta'] = max(0, total_b - done_b) / res['speed']
                res['eta_text'] = fmt_eta(res['eta'])
            else:
                res['eta_text'] = 'оценка появится позже'
    return res


def task_disks(task, serials, letters):
    """Диски задания по тома.tsv: (подпись «HDD45 → HDD78 (L:)», серийные номера всех дисков, номер источника)."""
    p = Path(task) / 'тома.tsv'
    vols = [f for f in hb.read_tsv(p) if len(f) >= 2] if p.exists() else []
    names, sers = [], set()
    for f in vols:
        ser = f[1].strip().upper()
        sers.add(ser)
        name = serials.get(ser) or f[0].strip()          # физический носитель по серийному номеру
        names.append(name + (f' ({letters[ser]})' if letters.get(ser) else ''))
    label = names[0] + (' → ' + ', '.join(names[1:]) if len(names) > 1 else ' (внутри диска)') if names else ''
    src = serials.get(vols[0][1].strip().upper()) if vols else None
    return dict(disks=label, serials=sers, src_serial=vols[0][1].strip().upper() if vols else None, src=src)


_SERIALS = {'at': 0, 'map': {}}


def serial_names():
    if time.time() - _SERIALS['at'] > 300:
        try:
            _SERIALS['map'] = hb.serial_map(bp.find_jobs())
        except Exception:                                   # noqa: BLE001  - без имён дисков окно всё равно работает
            _SERIALS['map'] = {}
        _SERIALS['at'] = time.time()
    return _SERIALS['map']


def load(root=None, now=None):
    """Строки таблицы: состояние (service) + ход, диски, пометка «после копирования.json», есть ли уже задание раскладки."""
    root = Path(root or hb.TASKS)
    rows = sv.tasks(root)
    serials = serial_names()
    try:
        letters = sv.volumes()
    except (OSError, AttributeError):
        letters = {}
    names = {r['task'] for r in rows}
    for r in rows:
        d = root / r['task']
        r.update(progress(d, r['kind'], r['state'] == 'идёт', now))
        r.update(task_disks(d, serials, letters))
        mark = d / sv.MOVE_MARK
        try:
            r['mark'] = json.loads(mark.read_text(encoding='utf-8')) if mark.exists() else None
        except (OSError, ValueError):
            r['mark'] = None
        r['move_task'] = (r['task'] + MOVE_SUFFIX) if (r['task'] + MOVE_SUFFIX) in names else None
    return rows


# ---------- решения без экрана (их проверяют тесты) ----------

def headline(rows, queue=()):
    run = [r for r in rows if r['state'] == 'идёт']
    if run:
        parts = []
        for r in run:
            s = (f'Идёт: {r["task"]} — {r["disks"]}: {n(r["done"])} из {n(r["total"])} файлов')
            if r['kind'] == 'копирование':
                s += f', {gb(r["done_b"])} из {gb(r["total_b"])} ГБ'
                if r.get('eta_text'):
                    s += (', осталось ' + r['eta_text']) if r.get('eta') is not None else f' ({r["eta_text"]})'
            parts.append(s)
        waiting = sum(1 for r in rows if r['state'] == 'не запускалось')
        if waiting:
            parts.append(f'Ещё подготовлено, не запускалось: {waiting}')
        return '\n'.join(parts)
    waiting = sum(1 for r in rows if r['state'] == 'не запускалось')
    s = f'Ничего не идёт. Подготовлено, не запускалось: {waiting}'
    stopped = sum(1 for r in rows if r['state'] == 'прервано')
    if stopped:
        s += f'; прервано: {stopped}'
    offers = sum(1 for r in rows if r['kind'] == 'копирование' and r['state'] in DONE and not r.get('move_task'))
    if offers:
        s += f'; можно разложить на источнике: {offers}'
    return s


def conflicts(rows):
    """Пары заданий, которые одновременно работают с одним физическим диском (в любой роли)."""
    res = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            common = a.get('serials', set()) & b.get('serials', set())
            if common:
                res.append(f'«{a["task"]}» и «{b["task"]}» — общий диск')
    return res


def move_blocks(sel, rows):
    """Перемещение нельзя запускать, пока идёт или запускается копирование с того же носителя, и наоборот."""
    act = [r for r in rows if r['state'] == 'идёт'] + list(sel)
    res = []
    for m in (r for r in act if r['kind'] == 'перемещение'):
        for c in (r for r in act if r['kind'] == 'копирование'):
            if m.get('src_serial') and m['src_serial'] == c.get('src_serial'):
                res.append(f'«{m["task"]}» (перемещение) и «{c["task"]}» (копирование) — один и тот же источник')
    return res


def pending_offers(rows, offered):
    """Законченные копирования с пометкой «разложить после копирования», для которых окно ещё не предлагало раскладку."""
    return [r for r in rows if r.get('mark') and r['kind'] == 'копирование' and r['state'] in DONE
            and not r.get('move_task') and r['task'] not in offered]


def queue_cmd(dirs, path):
    """Один .cmd, который запускает задания друг за другом в одном окне консоли (call ждёт конца каждого)."""
    lines = ['@echo off', 'chcp 65001 >nul', 'title Задания по очереди',
             f'echo Задания по очереди: {len(dirs)}. Каждое спросит «да» в начале и Enter в конце.', 'echo.']
    for i, d in enumerate(dirs, 1):
        lines += [f'echo [{i} из {len(dirs)}] {Path(d).name}', f'call "{Path(d) / "Запустить.cmd"}"', 'echo.']
    lines += ['echo Очередь закончена.', 'pause']
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-8'))
    return path


def run_hb(*args, timeout=3600):
    """hashbase.py отдельным процессом (как раздел «Команды»): (код выхода, весь вывод)."""
    p = subprocess.run([cpg.python_exe(), '-X', 'utf8', '-u', str(cpg.SCRIPT), *args], cwd=str(cpg.CAT.parent),
                       env=cpg.child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return p.returncode, p.stdout.decode('utf-8', errors='replace')


def can_move(text):
    m = re.search(r'Можно перенести: ([\d ]+) файлов', text)
    return int(m.group(1).replace(' ', '')) if m else 0


# ---------- экран ----------

def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


def _cell(text, right=False, color=None, tip=''):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    if tip:
        it.setToolTip(tip)
    return it


class TextDialog(QDialog):
    """Весь ответ команды и кнопки: «ok» - согласие (например, «Создать задание перемещения»)."""

    def __init__(self, parent, title, text, ok=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        f = QFont('Consolas')
        f.setPointSize(10)
        view.setFont(f)
        lay.addWidget(view)
        box = QDialogButtonBox()
        if ok:
            box.addButton(ok, QDialogButtonBox.AcceptRole)
        box.addButton('Закрыть', QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)


class TasksPage(QWidget):
    HEAD = ['Задание (галочка - запустить)', 'Вид', 'Состояние', 'Ход', 'Скорость', 'Осталось', 'Ошибки', 'Диски']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.checked, self.offered, self.queue = win, [], set(), set(), []
        self.start_file = os.startfile                    # тесты подменяют: окно PowerShell не открывается
        lay = QVBoxLayout(self)
        self.head = QLabel('Задания: считаю…')
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.head.setFont(f)
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        lay.addWidget(QLabel('Папки в «Запускаемые скрипты». Каждое задание идёт в своём окне PowerShell: там спросят '
                             '«да», остановка — клавиша Q, повторный запуск продолжит с места остановки.'))
        self.t = _table(self.HEAD)
        self.t.itemChanged.connect(self.on_check)
        lay.addWidget(self.t, 1)
        self.note = QLabel(EXPLAIN)
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color:#37474f; background:#eef3f7; padding:8px; border-radius:4px')
        lay.addWidget(self.note)
        bar = QHBoxLayout()
        for text, fn in (('Обновить', self.refresh), ('Запустить отмеченные', self.launch_checked),
                         ('По очереди', lambda: self.launch_checked(sequential=True)),
                         ('Разложить на источнике…', self.move_current), ('Открыть папку', self.open_dir),
                         ('Открыть журнал', self.open_log), ('Сводка для чата', self.to_chat)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
            if text == 'Разложить на источнике…':
                self.move_btn = b
        bar.addStretch()
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.t.itemSelectionChanged.connect(self.on_select)

    # --- данные ---
    def refresh(self):
        self.win.bg.run(load, ok=self.render, quiet=True)

    def render(self, rows):
        sel = self.current()
        self.rows = rows
        running = {r['task'] for r in rows if r['state'] == 'идёт'}
        if self.queue and not running and all(r['state'] != 'не запускалось' for r in rows if r['task'] in self.queue):
            self.queue = []
        self.t.blockSignals(True)
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            state = r['state']
            if state == 'не запускалось' and r['task'] in self.queue:
                state = 'в очереди'
            box = _cell(r['task'])
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            box.setCheckState(Qt.Checked if r['task'] in self.checked else Qt.Unchecked)
            self.t.setItem(i, 0, box)
            self.t.setItem(i, 1, _cell(r['kind']))
            self.t.setItem(i, 2, _cell(state, color=STATE_COLOR.get(state)))
            hod = f'{n(r["done"])} из {n(r["total"])} файлов'
            if r['kind'] == 'копирование':
                hod += f' · {gb(r["done_b"])} из {gb(r["total_b"])} ГБ'
            self.t.setItem(i, 3, _cell(hod, right=True))
            sp = r.get('speed') if r['state'] == 'идёт' else None       # у законченного скорость не нужна
            self.t.setItem(i, 4, _cell((f'{sp / 1024 ** 2:,.0f} МБ/с' if sp >= 10 * 1024 ** 2 else
                                        f'{sp / 1024 ** 2:.1f} МБ/с').replace(',', ' ') if sp else '', right=True))
            left = r.get('eta_text', '')
            if r.get('ago') is not None and r['ago'] > 120:
                left += f' (последняя запись {fmt_ago(r["ago"])}: идёт большой файл или диск завис)'
            self.t.setItem(i, 5, _cell(left))
            bad = r['errors'] + r['skipped']
            self.t.setItem(i, 6, _cell(bad if bad else '', right=True, color='#c62828' if r['errors'] else None,
                                       tip='\n'.join(r.get('examples', []))))
            self.t.setItem(i, 7, _cell(r.get('disks', '')))
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        self.t.blockSignals(False)
        self.head.setText(headline(rows, self.queue))
        self.on_select()
        busy = bool(running) or bool(self.queue)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()
        for r in pending_offers(rows, self.offered):
            self.offered.add(r['task'])
            QTimer.singleShot(0, lambda r=r: self.offer_move(r, auto=True))

    def on_check(self, it):
        if it.column() != 0 or not (0 <= it.row() < len(self.rows)):
            return
        name = self.rows[it.row()]['task']
        (self.checked.add if it.checkState() == Qt.Checked else self.checked.discard)(name)

    def on_select(self):
        r = self.current()
        self.move_btn.setEnabled(bool(r and r['kind'] == 'копирование' and r['state'] in DONE))

    def current(self):
        i = self.t.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def need(self):
        r = self.current()
        if not r:
            self.say('Сначала выберите задание в таблице (щелчок по строке).')
        return r

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

    # --- запуск ---
    def launch_checked(self, sequential=False):
        sel = [r for r in self.rows if r['task'] in self.checked]
        if not sel:
            self.say('Отметьте галочками задания, которые нужно запустить.')
            return
        busy = [r for r in sel if r['state'] == 'идёт']
        if busy:
            self.say('Уже идут: ' + ', '.join(f'«{r["task"]}»' for r in busy) + '. Их повторно не запускаю.')
            sel = [r for r in sel if r['state'] != 'идёт']
            if not sel:
                return
        block = move_blocks(sel, self.rows)
        if block:
            self.say('Так нельзя: перемещение и копирование с одного носителя одновременно ломают друг друга.\n\n'
                     + '\n'.join(block) + '\n\nДождитесь конца копирования, затем запускайте перемещение.')
            return
        running = [r for r in self.rows if r['state'] == 'идёт']
        clash = conflicts(sel + running)
        names = '\n'.join(f'  • {r["task"]} ({r["kind"]}, {r.get("disks", "")})' for r in sel)
        if len(sel) > 1 and not sequential:
            text = f'Запустить {len(sel)} задания(й) сразу, каждое в своём окне?\n\n{names}'
            if clash:
                text += ('\n\nВнимание: одни и те же диски у нескольких заданий —\n' + '\n'.join(clash) +
                         '\nОдновременно диск делит скорость между заданиями; лучше по очереди.')
            how = self.choose(text, ['По очереди', 'Все сразу'] if clash else ['Все сразу', 'По очереди'])
            if not how:
                return
            sequential = how == 'По очереди'
        elif not self.ask(('Запустить по очереди в одном окне?\n\n' if sequential and len(sel) > 1 else 'Запустить?\n\n')
                          + names + '\n\nВ начале каждого задания проверьте сводку и введите «да»; в конце — Enter. '
                          'Остановить — клавиша Q, повторный запуск продолжит.' +
                          ('\n\nВнимание: ' + '; '.join(clash) + '.' if clash else '')):
            return
        moves = [r for r in sel if r['kind'] == 'перемещение']
        if moves:
            self.win.statusBar().showMessage('Проверяю задания перемещения по свежей базе…')
            self.win.bg.run(lambda: [(r, *run_hb('mvlist', '--recheck', str(hb.TASKS / r['task']))) for r in moves],
                            ok=lambda res: self._after_recheck(res, sel, sequential))
            return
        self._start(sel, sequential)

    def _after_recheck(self, res, sel, sequential):
        bad = [(r, text) for r, code, text in res if code != 0]
        if bad:
            self.show_text('Задание перемещения устарело', '\n\n'.join(f'«{r["task"]}»:\n{t}' for r, t in bad))
            sel = [r for r in sel if r not in [b[0] for b in bad]]
            if not sel:
                return
        self._start(sel, sequential)

    def _start(self, sel, sequential):
        dirs = [hb.TASKS / r['task'] for r in sel]
        if sequential and len(dirs) > 1:
            path = queue_cmd(dirs, hb.BASE_DIR / 'очередь заданий.cmd')
            self.queue = [r['task'] for r in sel]
            self.start_file(str(path))
        else:
            for d in dirs:
                self.start_file(str(d / 'Запустить.cmd'))
        self.win.statusBar().showMessage(f'Запущено заданий: {len(dirs)}. Окна PowerShell ждут вашего «да».', 8000)
        QTimer.singleShot(3000, self.refresh)
        self.timer.start(5000)

    # --- раскладка на источнике ---
    def move_current(self):
        r = self.need()
        if r:
            self.offer_move(r)

    def offer_move(self, r, auto=False):
        if r['kind'] != 'копирование' or r['state'] not in DONE:
            self.say('Разложить на источнике можно только после законченного копирования '
                     '(«готово» или «готово с ошибками»). Сейчас: ' + r['state'] + '.')
            return
        if r.get('move_task'):
            self.say(f'Задание раскладки уже создано: «{r["move_task"]}». Его можно запустить из таблицы.')
            return
        if auto and not self.ask(f'Копирование «{r["task"]}» закончилось ({r["state"]}).\n\nПри подготовке вы отметили '
                                 '«разложить на источнике после копирования». Посмотреть, сколько файлов и куда можно '
                                 'перенести? Сейчас ничего не переносится.'):
            return
        self.win.statusBar().showMessage(f'Считаю, что можно перенести после «{r["task"]}»…')
        self.win.bg.run(run_hb, 'mvlist', '--task', r['task'], '--dry', ok=lambda res: self._preview(r, *res))

    def _preview(self, r, code, text):
        self.win.statusBar().clearMessage()
        cnt = can_move(text) if code == 0 else 0
        intro = ('Предпросмотр (ничего не перенесено). Перенос — внутри того же диска, все папки и подпапки '
                 'сохраняются, ничего не удаляется.\n\n')
        if not cnt:
            self.show_text('Разложить на источнике', intro + text)
            return
        if not self.show_text('Разложить на источнике', intro + text, ok=f'Создать задание перемещения ({n(cnt)} файлов)'):
            return
        args = ['mvlist', '--task', r['task']]
        if 'главный архивный диск' in text:
            if not self.ask('Источник — главный архивный диск (45 или 77). Перенос в «ПЕРЕНЕСЕНО → …» изменит '
                            'структуру архива на нём. Всё равно создать задание?'):
                return
            args.append('--allow-main')
        self.win.bg.run(run_hb, *args, ok=lambda res: self._created(r, *res))

    def _created(self, r, code, text):
        if code != 0 or 'Папка задания:' not in text:
            self.show_text('Задание не создано', text)
            return
        name = r['task'] + MOVE_SUFFIX
        self.refresh()
        if self.ask(f'Создано задание «{name}».\n\nЗапустить его сейчас? Откроется окно PowerShell: подключите диск, '
                    'проверьте сводку и введите «да».'):
            self.checked = {name}
            self.win.bg.run(lambda: run_hb('mvlist', '--recheck', str(hb.TASKS / name)),
                            ok=lambda res: self._after_recheck([({'task': name}, *res)], [{'task': name}], False))

    # --- прочее ---
    def open_dir(self):
        r = self.need()
        if r:
            self.start_file(str(hb.TASKS / r['task']))

    def open_log(self):
        r = self.need()
        if r and r['journal']:
            self.start_file(r['journal'])
        elif r:
            self.say('Журнала ещё нет: задание не запускалось.')

    def to_chat(self):
        r = self.need()
        if r:
            QGuiApplication.clipboard().setText(
                f'Задание «{r["task"]}» ({r["kind"]}, {r.get("disks", "")}): {r["state"]}; обработано {r["done"]} из '
                f'{r["total"]}, ошибок {r["errors"]}, пропусков {r["skipped"]}. Журнал: {r["journal"] or "нет"}')
            self.win.statusBar().showMessage('Сводка скопирована - вставьте её в чат.', 5000)
