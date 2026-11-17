"""Общая основа тестов страницы «Разбор носителя» (бывшая шапка test_razbor_page.py): временные данные, PageBase.

Шаг А разбивки (17.11.2026). Тесты - в соседних test_*.py; диалоги подменяются у классов (QMessageBox, TextDialog),
имена модулей - там, где используются (flow_tasks.tasks_dry, flow_autosave.FLUSH_WAIT_MS).
Настоящие диски, таблицы и задания не используются.
"""
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtCore import QPoint, QPointF, QThreadPool    # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox         # noqa: E402

import app                                                 # noqa: E402
import hashbase as hb                                      # noqa: E402
import razbor_page as rp                                   # noqa: E402 - переходник: прежние имена
import service as sv                                       # noqa: E402
from hb_core import razbor as rz                           # noqa: E402
from ui.razbor import dialogs, flow_autosave, flow_tasks   # noqa: E402,F401 - подмены там, где имя используется
from test_app import put, wait                             # noqa: E402
from test_hashbase import make_disk, S                     # noqa: E402
from test_logic_v3 import SRC, FILES, H, V3Base            # noqa: E402

N1 = 'направление: Н1 Семейный архив'
N2 = 'направление: Н2 Работа'
N3 = 'направление: Н3 Без диска'
MOVED = 'ПЕРЕНЕСЕНО → 45 и 77'
H50 = f'{50:064x}'


def reference_route(model, f, ms):
    """Независимо от окна и ядра: самая глубокая отметка над папкой (по частям пути, без регистра); внутри служебной
    папки - только явные отметки исходного пути, сама служебная папка и наследование режима - нет."""
    parts = f.split('\\') if f else []
    if parts and parts[0] in model.roots:
        if len(parts) == 1:
            return None
        parts = parts[1:]
        cands = ['\\'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    else:
        cands = [''] + ['\\'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    best = None
    for c in cands:
        m = ms.by_key.get(c.lower())
        if m is not None:
            best = m
    return best


class PageBase(V3Base):
    def setUp(self):
        super().setUp()
        self.asked, self.dialogs = [], []
        self.answer = rp.QMessageBox.Yes

        def ask(*a, **k):
            self.asked.append(a[2])
            return self.answer

        self.dlgs = []

        def exec_(dlg):
            self.dlgs.append(dlg)
            self.dialogs.append(dlg.text.toPlainText())
            return QDialog.Accepted
        self.patches = [mock.patch.object(QMessageBox, 'question', ask),
                        mock.patch.object(QMessageBox, 'information', lambda *a, **k: self.asked.append(a[2])),
                        mock.patch.object(QMessageBox, 'warning', lambda *a, **k: self.asked.append(a[2])),
                        mock.patch.object(dialogs.TextDialog, 'exec', exec_)]
        for x in self.patches:
            x.start()
        self.w = app.Window()
        self.w.show_error = self.asked.append
        self.assertTrue(wait(lambda: not self.w.updating), 'первая сборка базы в фоне не закончилась')
        self.p = self.w.page('Разбор носителя')
        self.w.open_page('Разбор носителя')
        self.assertTrue(wait(lambda: self.p.disk_rows))

    def tearDown(self):
        if self.p.model is not None:
            self.p.model.drafts.clear()
        self.w.timer.stop()
        QThreadPool.globalInstance().waitForDone(20000)
        self.w.close()
        for x in self.patches:
            x.stop()
        super().tearDown()

    # --- помощники ---
    def skip_hash_gate(self):
        """Тесты заданий на общей обвязке (документы без хеша идут в копирование): последняя проверка «без хеша»
        (17.11.2026) проверяется отдельно (test_nohash), здесь - как будто хеш у всех."""
        orig = flow_tasks.tasks_check

        def check(*a, **k):
            out = orig(*a, **k)
            out['nohash'] = 0
            return out
        p = mock.patch.object(flow_tasks, 'tasks_check', check)
        p.start()
        self.patches.append(p)

    def open(self, disk=SRC):
        self.p.choose_disk(disk)
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.model.disk == disk), 'дерево не прочиталось')
        self.settle()

    def settle(self):
        self.assertTrue(wait(lambda: self.p.plan_rev == self.p.rev and not self.p.sum_busy and not self.p.have_busy
                             and not self.p.writing and not self.p.saving and not self.p.save_timer.isActive()
                             and self.p.model.have is not None, 60), self.p.sum_state.text())

    def own(self, path):
        """Своя действующая отметка папки: черновик или уже сохранённая (этап 16: отметки сохраняются сразу)."""
        return self.p.model.own_verdict(path.lower())

    def owns(self):
        """Все свои отметки носителя (черновик поверх сохранённых), кроме «как у родителя»: {путь: отметка}."""
        m = self.p.model
        keys = set(m.drafts) | set(m.saved_ms.by_key) | set(m.inflight)
        return {k: m.own_verdict(k) for k in keys if m.own_verdict(k) != rp.INHERIT}

    def item(self, path):
        parts = path.split('\\')
        for i in range(1, len(parts)):
            self.p.items['\\'.join(parts[:i])].setExpanded(True)
        return self.p.items[path]

    def to(self, path):
        """Текст «куда» папки (колонки «Куда» с этапа 6 нет - тот же текст даёт Model.cell, цвет - Model.look)."""
        if path:
            self.item(path)
        return self.p.model.cell(path)['text']

    def plan(self):
        self.settle()
        return self.p.plan[0]


TOC_OK = dict(connected=True, reason='', letter='K:', checked=5, problems=[])
