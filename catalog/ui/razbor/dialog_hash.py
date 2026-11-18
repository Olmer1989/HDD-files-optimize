"""Окно «Посчитать хеш — HDD18» (кнопка «Посчитать хеш (N)» на «Выбор источников», 18.11.2026, макет владельца).

Короткое окно вместо общего «Пересканировать папки» (rescan_dialog.RescanDialog - он остаётся для «Дисков и папок» и
«Списка файлов"): механика та же - предпросмотр по оглавлению (service.rescan_plan, в фоне), сканер отдельным
процессом (service.rescan_start) только по кнопке «Посчитать», ход раз в секунду, «Остановить» - файл остановки,
«Продолжить» - то же задание. Типы файлов - только типы этих N файлов (nh['cats']); галочек типов, «Перечитать всё» и
второго вопроса нет. «Готово» - только после приёма скана базой и повторной проверки service.nohash_check.
Тексты - texts_hash.py; здесь только Qt."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

import hash_types
import service as sv

from . import texts_hash as T
from .common import TITLE, safe

RESUMABLE = ('interrupted', 'error', 'inventory_incomplete')
BUSY_STAGES = ('apply', 'check')                                # приём в базу и повторная проверка - закрыть нельзя


def hash_plan(disk, folders):
    """Фон: предпросмотр (файлы не читаются) и подтверждённые хеши в базе. -> ('ok', plan) / ('no', причина)."""
    try:
        p = sv.rescan_plan(disk, folders, False)
    except sv.Refused as e:
        return 'no', str(e)
    except Exception as e:                                      # noqa: BLE001 - показать в окне, не падать
        return 'no', str(e) or type(e).__name__
    try:
        p['confirmed'] = sv.rescan_confirmed(disk, p['folders'])
    except Exception:                                           # noqa: BLE001 - без предупреждения о потере
        p['confirmed'] = None
    return 'ok', p


class HashDialog(QDialog):
    """win - главное окно (bg, apply_new); nh - ответ nohash_check (n, folders, cats); target - «H:»; check() ->
    (носитель, направление, черновик) для повторной проверки или None - берётся ОДИН раз при открытии (итог - для тех
    носителя, направления и отметок, для которых окно открыто); list_html(nh) - список «без хеша»;
    show(заголовок, html) - окно с текстом. Атрибуты для тестов: head, body, go, halt, close_btn, bar, stage, args."""

    def __init__(self, win, disk, nh, target, check, list_html, show):
        super().__init__(win)
        self.win, self.disk, self.nh, self.target = win, disk, nh, target
        self.list_html, self.show_text = list_html, show
        a = check()
        self.args = None if a is None else (a[0], a[1], list(a[2]))
        self.folders = list(nh.get('folders') or [])
        cats = list(nh.get('cats') or [])
        self.cats = None if not cats or hash_types.is_all(cats) else cats
        self.plan = self.proc = self.job = self.after = None
        self.read = (0, 0)
        self.warn = []
        self.running = self.stopping = False
        self.n_done = 0
        self.stage = 'plan'
        self.setWindowTitle(T.title(disk))
        self.resize(640, 320)
        lay = QVBoxLayout(self)
        self.head = QLabel(T.head_html(nh['n'], disk))
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.body = QLabel('')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.body.linkActivated.connect(self.link)
        lay.addWidget(self.body, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch()
        self.go = QPushButton(T.BTN_GO)
        self.go.setDefault(True)
        self.go.setEnabled(False)
        self.go.clicked.connect(self.start)
        self.halt = QPushButton(T.BTN_STOP)
        self.halt.hide()
        self.halt.clicked.connect(self.stop)
        self.close_btn = QPushButton(T.BTN_CANCEL)
        self.close_btn.clicked.connect(self.close)
        for b in (self.go, self.halt, self.close_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.body.setText(T.intro_html(nh['n'], cats, target) + f'<p>{T.WAIT_PLAN}</p>')
        self.win.bg.run(hash_plan, disk, self.folders, ok=self.show_plan)

    # --- 1) перед запуском ---
    def show_plan(self, res):
        kind, val = res
        cats = self.nh.get('cats') or []
        if kind != 'ok' or val.get('errors'):
            self.plan = None
            err = val if kind != 'ok' else '; '.join(str(x) for x in val['errors'])
            self.body.setText(T.intro_html(self.nh['n'], cats, self.target) + T.error_html(err))
            self.go.setEnabled(False)
            return
        self.plan = val
        self.head.setText(T.head_html(self.nh['n'], self.disk, val.get('letter')))
        if 'items' in val:
            rule = None if self.cats is None else hash_types.scanner_rule(self.cats)
            est = sv._scanner()[0].by_types(val, rule)
        else:
            est = dict(read=val.get('read') or [0, 0], skip=[0, 0], skip_paths=[])
        self.read = tuple(est['read'])
        conf = val.get('confirmed')
        lost = sum(1 for x in est.get('skip_paths') or [] if x in (conf or {}))
        unknown = T.unknown_lost_html() if conf is None and (est.get('skip') or [0])[0] else ''
        self.body.setText(T.intro_html(self.nh['n'], cats, self.target, self.read) + T.lost_html(lost) + unknown
                          + f'<p>{T.more_link()}</p>')
        self.go.setEnabled(True)
        self.go.setFocus()

    def link(self, href):
        if href == 'more' and self.plan:
            self.show_text(f'{T.MORE.rstrip("…")} — {self.disk}', T.details_html(self.plan.get('lines')))
        elif href == 'nh-list' and self.after:
            self.show_text(f'Без хеша - {self.disk}', self.list_html(self.after))

    # --- 2) идёт ---
    def start(self, resume=False):
        if self.running or (not resume and not self.plan):
            return
        p = self.plan or {}
        try:
            self.proc = sv.rescan_start(self.disk, p.get('letter', ''), p.get('folders') or self.folders, False,
                                        job=self.job if resume else None, cats=self.cats)
        except Exception as e:                                  # noqa: BLE001 - показать, окно не падает
            self.body.setText(T.error_html(str(e) or type(e).__name__))
            return
        self.running, self.stopping, self.stage = True, False, 'run'
        self.go.hide()
        self.close_btn.hide()
        self.halt.setEnabled(True)
        self.halt.show()
        self.bar.show()
        self.body.setText(f'<p>{T.STARTING}</p>' + T.running_html(self.n_done, self.read[0]))
        self.timer.start(1000)

    def poll(self):
        p = sv.read_progress(self.disk)
        if p:
            self.job = p.get('job') or self.job
            self.n_done = p.get('new_files') or 0
            self.bar.setValue(int(10 * (p.get('percent') or 0)))
            note = f'<p>{T.STOPPING}</p>' if self.stopping else ''
            self.body.setText(note + T.running_html(self.n_done, self.read[0], p.get('eta_seconds')))
        if self.proc is not None and self.proc.poll() is not None:
            self.finished_scan(self.proc.returncode)

    def stop(self):
        try:
            sv.rescan_files(self.disk)[1].write_text('stop', encoding='utf-8')
        except OSError as e:
            self.halt.setEnabled(True)
            self.body.setText(T.stop_failed_html(str(e) or type(e).__name__) + T.running_html(self.n_done, self.read[0]))
            return
        self.stopping = True
        self.halt.setEnabled(False)
        self.body.setText(f'<p>{T.STOPPING}</p>' + T.running_html(self.n_done, self.read[0]))

    # --- 3) остановлено / не закончено ---
    def finished_scan(self, code):
        self.timer.stop()
        self.running = False
        self.halt.hide()
        p = sv.read_progress(self.disk) or {}
        self.job = p.get('job') or self.job
        self.n_done = p.get('new_files') or self.n_done
        status = str(p.get('status') or '')
        self.close_btn.setText(T.BTN_CLOSE)
        self.close_btn.setEnabled(True)
        self.close_btn.show()
        if code == 0 and status.startswith('complete'):
            self.bar.setValue(1000)
            self.stage = 'apply'
            self.close_btn.setEnabled(False)
            self.body.setText(f'<p>{T.APPLYING}</p>')
            try:
                self.win.apply_new(then=lambda _res: self.accepted())
            except Exception as e:                              # noqa: BLE001 - показать, окно можно закрыть
                self.end(T.refused_html([str(e) or type(e).__name__]))
            return
        tail = ''
        try:
            tail = sv.rescan_files(self.disk)[2].read_text(encoding='utf-8', errors='replace').strip().splitlines()[-1]
        except (OSError, IndexError):
            pass
        self.stage = 'stopped'
        self.body.setText(T.stopped_html(self.stopping and status == 'interrupted', status or f'код {code}',
                                         self.n_done, self.read[0], tail))
        if self.job and status in RESUMABLE:
            self.go.setText(T.BTN_RESUME)
            self.go.clicked.disconnect()
            self.go.clicked.connect(lambda: self.start(resume=True))
            self.go.setEnabled(True)
            self.go.show()

    # --- 4) готово: приём базой и повторная проверка ---
    def accepted(self):
        name = Path(self.job).name if self.job else ''
        self.win.bg.run(safe, sv.partial_outcome, name, ok=self.outcome)

    def end(self, html):
        """Конечное состояние 4: текст, окно можно закрыть."""
        self.stage = 'done'
        self.body.setText(html)
        self.close_btn.setEnabled(True)

    def outcome(self, res):
        kind, val = res
        if kind != 'ok':
            self.end(T.refused_html([last_line(val)]))
            return
        if not isinstance(val, dict):
            self.end(T.check_failed_html('нет ответа базы'))
            return
        if not val.get('accepted'):
            self.end(T.refused_html(list(val.get('lines') or []) + list(val.get('warn') or [])))
            return
        self.warn = list(val.get('warn') or [])
        if self.args is None:
            self.end(T.check_failed_html('диск назначения не выбран') + T.warn_html(self.warn))
            return
        self.stage = 'check'
        self.body.setText(f'<p>{T.CHECKING}</p>')
        self.win.bg.run(safe, sv.nohash_check, *self.args, ok=self.checked)

    def checked(self, res):
        kind, val = res
        warn = T.warn_html(self.warn)
        if kind != 'ok' or not isinstance(val, dict):
            self.end(T.check_failed_html('нет ответа' if kind == 'ok' else last_line(val)) + warn)
            return
        self.after = val
        self.end(T.done_html(val.get('n') or 0, self.target) + warn)

    # --- закрыть нельзя, пока идёт подсчёт, приём в базу и повторная проверка ---
    def busy_text(self):
        return T.BUSY if self.running else T.BUSY_APPLY if self.stage in BUSY_STAGES else ''

    def reject(self):
        if self.busy_text():
            QMessageBox.information(self, TITLE, self.busy_text())
            return
        super().reject()

    def closeEvent(self, e):                                  # noqa: N802
        if self.busy_text():
            QMessageBox.information(self, TITLE, self.busy_text())
            e.ignore()
            return
        super().closeEvent(e)


def last_line(val):
    """Последняя строка текста ошибки (или сам ответ)."""
    s = str(val).strip()
    return s.splitlines()[-1] if s else str(val)
