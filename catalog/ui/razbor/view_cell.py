"""RazborPage, блок «ячейки справа» (этап 8): ячейка «Копировать на диск …» (Cell), кнопки, «Отменить».

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hb_core import razbor as rz
from hb_core.directions import R_DIR

import disk_ui
from ui_common import timed
import service as sv

from .common import (BLOCK_LOOK, BUSY_CSS, C_NAME, DEBOUNCE_MS, DISKS_WORDS, HEAD_BG, MIME, ROLE, SHORT_BG, UNKNOWN_BG,
                     mime_folders)
from .texts_cell import ORANGE, RED, cell_numbers, dest_cell_html, disk_block_html, esc, files_word, nohash_html
from .texts_head import copies_word, hdds, short_place


class Cell(QFrame):
    """Ячейка справа (этап 8): «Копировать на диск …» (drop=True - единственная цель перетаскивания: бросок = включить
    папки в диск назначения, page.drop) или «Остаётся на носителе» (drop=False - только сведения)."""

    def __init__(self, page, drop):
        super().__init__()
        self.page, self.drop_ok = page, drop
        self.setAcceptDrops(drop)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(180 if drop else 90)
        lay = QVBoxLayout(self)
        # этап 17: оранжевая мигающая плашка «Идёт пересчёт…» - в ячейке, на месте прежнего «Считаю…»
        self.busy = QLabel('Идёт пересчёт итога и места на диске…')
        self.busy.setStyleSheet(BUSY_CSS[0])
        self.busy.setToolTip('После изменения отметок итог и место на диске пересчитываются (в фоне, окно не замирает). '
                             'Бледные цифры ниже - прежний итог; обновятся, когда надпись исчезнет.')
        self.busy.hide()
        lay.addWidget(self.busy, 0, Qt.AlignLeft)
        self.title = QLabel('')
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.sub = QLabel('')                             # «Фильмы, HDD55»: имя направления оранжевым жирным (этап 12)
        self.sub.setTextFormat(Qt.RichText)
        f2 = QFont()
        f2.setPointSize(11)
        self.sub.setFont(f2)
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        self.body = QLabel('')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.body.linkActivated.connect(page.show_list)          # «Показать список» (этап 16)
        lay.addWidget(self.body)
        # направление на нескольких дисках: по блоку с рамкой на каждый диск («Копия 1 — H: …», этап 12)
        self.blocks_box = QWidget()
        self.blocks_lay = QVBoxLayout(self.blocks_box)
        self.blocks_lay.setContentsMargins(0, 4, 0, 0)
        self.blocks_lay.setSpacing(8)
        self.blocks = []                                  # [[диск, QFrame, QLabel, состояние]]
        self.blocks_box.hide()
        lay.addWidget(self.blocks_box)
        # «Без хеша» (17.11.2026): только то, что пойдёт на диск; кнопка «Отсканировать эти папки» - рядом с заданиями
        self.nohash = QLabel('')
        self.nohash.setWordWrap(True)
        self.nohash.setTextFormat(Qt.RichText)
        self.nohash.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.nohash.linkActivated.connect(page.nohash_link)
        self.nohash.hide()
        lay.addWidget(self.nohash)
        lay.addStretch(1)
        self.btn = self.scan_btn = None
        if drop:
            row = QHBoxLayout()
            row.addStretch(1)
            self.scan_btn = QPushButton('Отсканировать эти папки…')
            self.scan_btn.clicked.connect(lambda: page.scan_nohash())
            self.scan_btn.hide()
            row.addWidget(self.scan_btn)
            self.btn = QPushButton('Подготовить задания…')
            self.btn.clicked.connect(lambda: page.prepare())
            row.addWidget(self.btn)
            lay.addLayout(row)
        self.state = 'normal'

    def set_busy(self, on):
        """Пересчёт: плашка видна, прежний итог бледно (текст ячейки и блоков дисков - серым)."""
        self.busy.setVisible(on)
        css = 'color:#9e9e9e' if on else ''
        self.body.setStyleSheet(css)
        for b in self.blocks:
            b[2].setStyleSheet(css)

    def paint(self, border, bg, state='normal'):
        self.state = state
        self.setStyleSheet(f'Cell {{ border: 2px solid {border}; border-radius: 6px; background: {bg}; }}')

    def set_blocks(self, items):
        """Блоки дисков: items = [(диск, html, состояние)]; пусто - блоков нет (направление на один диск)."""
        if [x for x, _, _ in items] != [b[0] for b in self.blocks]:
            for b in self.blocks:
                b[1].setParent(None)
                b[1].deleteLater()
            self.blocks = []
            for x, _, _ in items:
                fr = QFrame()
                fr.setObjectName('diskblock')
                fl = QVBoxLayout(fr)
                fl.setContentsMargins(10, 8, 10, 8)
                lab = QLabel('')
                lab.setTextFormat(Qt.RichText)
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
                lab.linkActivated.connect(self.page.show_list)
                fl.addWidget(lab)
                self.blocks_lay.addWidget(fr)
                self.blocks.append([x, fr, lab, None])
        for blk, (x, html_, state) in zip(self.blocks, items):
            blk[2].setText(html_)
            blk[3] = state
            border, bg = BLOCK_LOOK.get(state, BLOCK_LOOK['none'])
            blk[1].setStyleSheet(f'QFrame#diskblock {{ border:1px solid {border}; border-radius:5px; background:{bg}; }}'
                                 'QFrame#diskblock QLabel { border:none; background:transparent; }')
        self.blocks_box.setVisible(bool(items))

    def block_texts(self):
        """Тексты блоков дисков (для тестов): {диск: html}."""
        return {b[0]: b[2].text() for b in self.blocks}

    def block_states(self):
        return {b[0]: b[3] for b in self.blocks}

    def dragEnterEvent(self, e):                              # noqa: N802
        if self.drop_ok and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):                               # noqa: N802
        self.dragEnterEvent(e)

    def dropEvent(self, e):                                   # noqa: N802
        folders = mime_folders(e.mimeData()) if self.drop_ok else []
        if folders:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.drop_folders(folders))
        else:
            e.ignore()

    def drop_folders(self, folders):
        """Обработчик сброса (вызывается и из тестов напрямую)."""
        return self.page.drop(folders) if self.drop_ok else 0


class CellView:
    """Часть RazborPage (блок «ячейки справа» (этап 8)); атрибуты - у RazborPage."""

    def plan_cap(self):
        if not self.plan:
            return {}
        P, space, queued = self.plan[0], self.plan[1], self.plan[2]
        return sv.capacity(P.part_b, space, queued, disks=[x for d in P.dirs.values() for x in d.disks])

    def counts(self):
        """Числа папок для ячеек: (выбрано для D, исключено владельцем - свои «не копировать» внутри D, остаётся)."""
        m, n = self.model, self.dest
        sel = m.tops(lambda r: m.is_dir(r, n))
        exc = m.own_excluded(n)
        stay = m.tops(lambda r: r.state != R_DIR)
        return sel, exc, stay

    @timed('Разбор: render_cells')
    def render_cells(self):
        m = self.model
        if m is None:
            return
        d = self.dest_dir()
        plan = self.plan[0] if self.plan else None
        cap = self.plan_cap()
        c = self.copy_cell
        sel, exc, stay = self.counts() if d else (0, 0, m.tops(lambda r: r.state != R_DIR))
        if d is None:
            c.title.setText('Копировать на диск')
            c.sub.setText('')
            c.set_blocks([])
            c.body.setText(f'<span style="color:{ORANGE}">Диска назначения нет: назначьте диск направлению в «Обзоре».'
                           '</span>')
            c.paint('#9e9e9e', '#fafafa')
            state = 'none'
        else:
            by = {r['disk']: r for r in self.disk_rows}
            many = len(d.disks) > 1
            if many:                                      # этап 12: по блоку на каждый диск
                c.title.setText(f'Копировать на {DISKS_WORDS.get(len(d.disks), f"{len(d.disks)} дисков")} — '
                                f'{copies_word(len(d.disks))}')
            else:
                c.title.setText('Копировать на диск ' + short_place(by.get(d.disks[0]), d.disks[0]))
            c.sub.setText(f'<span style="color:{ORANGE}"><b>{esc(d.name)}</b></span>, {esc(hdds(d))}')
            label = lambda x: (by.get(x) or {}).get('letter') or x                 # noqa: E731 - «H:» или «HDD45»
            html_, state = dest_cell_html(d, plan, cap, self.mode(), sel, exc, label, split=many)
            c.body.setText(html_)
            blocks = []
            if many and plan is not None:
                v = cell_numbers(d, plan)                     # те же числа, что у общей части ячейки
                total = (v['copy'][0] + v['have'][0], v['copy'][1] + v['have'][1])
                have = m.have_on_disk(d.num)
                for i, x in enumerate(d.disks, 1):
                    cx = cap.get(x) or dict(state='none', files=0, bytes=0, free=None, queued=[0, 0, 0])
                    blocks.append((x,) + disk_block_html(i, x, cx, plan, total, have and have.get(x),
                                                         disk_ui.disk_place(by.get(x) or x), label(x), v['have'][0],
                                                         v['skip'][0]))
            c.set_blocks(blocks)
            if state == 'short':
                c.paint(RED, SHORT_BG, state)
            elif state == 'unknown':
                c.paint('#43a047', UNKNOWN_BG, state)
            elif state == 'none':
                c.paint('#b0bec5', '#fafafa', state)          # копировать нечего - без «зелёного» фона
            else:
                c.paint('#43a047', HEAD_BG, state)
        hash_ok, nh = self.render_nohash(d, plan)
        can = (d is not None and plan is not None and not plan.errors and state != 'short' and not self.writing
               and any(plan.group_state(g) == rz.G_COPY for g, x in plan.groups.items() if x['num'] == d.num))
        c.btn.setEnabled(can and hash_ok)
        c.btn.setText('Подготовить задания…')
        if d is None:
            tip = ''
        elif can and not hash_ok:
            tip = ('Сначала хеш: у ' + files_word(nh['n']) + ', которые пойдут на диск, его нет - «Отсканировать эти '
                   'папки».' if nh and 'n' in nh else 'Проверяю, у всех ли файлов, которые пойдут на диск, есть хеш…')
        elif state == 'short':
            tip = 'Не помещается: снимите галочки у части папок.'
        elif not can and plan is not None:
            tip = 'Копировать нечего: поставьте галочки у папок (задания строятся по сохранённым отметкам).'
        else:
            tip = (f'Задания на копирование для «{d.num} {d.name}» по сохранённым отметкам; перед созданием - сверка '
                   'оглавления носителя и показ.')
        c.btn.setToolTip(tip)

    def render_nohash(self, d, plan):
        """Строки «без хеша» и кнопка «Отсканировать эти папки» (17.11.2026). -> (хеш у всех копируемых, ответ).
        Быстрый признак итога: файлов без хеша к записи на диски направления нет - хеш точно у всех; иначе - по ответу
        service.nohash_check (для этой ревизии, носителя и направления)."""
        c = self.copy_cell
        self.run_nohash()                                 # для этой ревизии и направления - один раз (в фоне)
        nh = self.nohash_result()
        if d is None or plan is None:
            c.nohash.hide()
            c.scan_btn.hide()
            return False, nh
        fast = sum(plan.unhashed_copy.get(x, (0, 0))[0] for x in d.disks if x != plan.disk)
        by = {r['disk']: r for r in self.disk_rows}
        label = lambda x: (by.get(x) or {}).get('letter') or x                     # noqa: E731
        html_ = nohash_html(nh, fast, ' и '.join(label(x) for x in d.disks if x != plan.disk) or 'диск',
                            cell_numbers(d, plan)['copy'][0], label)
        c.nohash.setText(html_)
        c.nohash.setVisible(bool(html_))
        ok = not fast or bool(nh and 'n' in nh and not nh['n'])
        show = bool(nh and nh.get('n') and nh.get('folders'))
        c.scan_btn.setVisible(show)
        if show:
            c.scan_btn.setText(f'Отсканировать эти папки ({len(nh["folders"])})…')
            c.scan_btn.setToolTip('Пересканировать только папки с файлами без хеша, которые пойдут на диск, и только '
                                  'их типы файлов: ' + ', '.join(nh['cats']) + '. Сначала окно покажет, сколько '
                                  'прочитать.')
        c.scan_btn.setEnabled(show and not self.writing)
        return ok, nh

    def drop(self, folders):
        """Папки сброшены в ячейку «Копировать на диск»: включить их в диск назначения (как галочка в «Только
        выбранные»; в «Все, кроме выбранных» - снять исключение). -> число изменённых записей черновика."""
        m = self.model
        if m is None or self.writing or not self.dest:
            return 0
        ok = [f for f in folders if f and m.markable(f)]
        if not ok:
            self.win.statusBar().showMessage('Эти папки отметить нельзя (весь носитель - это режим вверху; служебные '
                                             'папки переноса не отмечаются).', 6000)
            return 0
        pairs = m.include_pairs(ok, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        if n:
            self.after_marks()
            self.win.statusBar().showMessage(f'Папок: {len(ok)} → на диск {hdds(self.dest_dir())}. Сохраняется сразу.',
                                             8000)
        return n

    def selected_folders(self):
        return [it.data(C_NAME, ROLE) for it in self.tree.selectedItems() if it.data(C_NAME, ROLE)]

    def apply(self, folders, verdict):
        """Черновая отметка папок напрямую (весь носитель - ''; для тестов и служебных переходов)."""
        if self.model is None or verdict is None or self.writing:
            return
        if self.model.set_mark(folders, verdict):
            self.after_marks()

    def undo(self):
        """«Отменить последнее»: прежние отметки последнего шага - новой правкой (сохраняется сразу, этап 16)."""
        if self.model and not self.writing and self.model.undo():
            self.after_marks()

    def changed(self, debounce=True):
        """Любая правка входов итога: ревизия растёт сразу, итог помечается устаревшим и считается заново; черновик
        отметок записывается сразу (этап 16)."""
        self.schedule_save()
        self.rev += 1
        self.show_busy(True)
        self.update_buttons()
        if self.plan is not None:
            self.sum_state.setText(f'<span style="color:{ORANGE}">Итог устарел — пересчитываю…</span>')
        else:
            self.sum_state.setText('Считаю итог…')
        if debounce:
            self.debounce.start(DEBOUNCE_MS)
        else:
            self.debounce.stop()
            self.run_summary()

    def show_busy(self, on):
        """«Идёт пересчёт…» в ячейке «Копировать на диск …» (этап 17) - с правки до принятия итога этой ревизии;
        мигает; прежний итог - бледно."""
        self.copy_cell.set_busy(on)
        if on and not self.blink.isActive():
            self.blink_on = False
            self.blink.start()
        elif not on:
            self.blink.stop()
            self.busy_lab.setStyleSheet(BUSY_CSS[0])

    def blink_busy(self):
        self.blink_on = not getattr(self, 'blink_on', False)
        self.busy_lab.setStyleSheet(BUSY_CSS[1 if self.blink_on else 0])

    def update_buttons(self):
        busy = self.writing or self.model is None
        self.undo_btn.setEnabled(bool(self.model and self.model.undo_stack) and not busy)
        self.unique_btn.setEnabled(not busy)
        self.contested_btn.setEnabled(not busy)          # 17.11.2026: без числа - окно и список ищут спорные сами
        self.contested_list_btn.setEnabled(not busy)
        if self.model is not None:
            self.render_cells()
        else:
            self.tasks_btn.setEnabled(False)
