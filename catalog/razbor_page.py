"""Страница окна «Разбор носителя» (логика v3, этап 2, 15.11.2026).

Документ - «Проверка Архитектуры сортировки файлов\\Логика_v3_разбор_носителя.md» (разделы 1.2-1.6, 2.2, «Этап 2: экран»).
Владелец выбирает носитель и режим («всё - в направление, кроме отмеченных» или «ничего, кроме отмеченных»), ставит
папкам «Куда» (направление, «не копировать», «как у родителя») и сразу видит итог: что будет с каждым файлом (сумма =
опись) и сколько писать на каждый диск. «Сохранить отметки» - предпросмотр, затем запись одним пакетом через
service.add_marks_batch. «Подготовить задания» - расчёт, показ, создание через service.razbor_tasks, переход в «Задания».

Как устроено:
- Дерево строится по таблице folders (service.razbor_tree - один запрос, ≤ 60 тыс. папок); элементы дерева создаются
  только при раскрытии узла. «Куда» считается в окне по всем папкам одним проходом (Model.routes - те же правила, что в
  ядре: hb_core.razbor.planner, разбор отметок - общий hb_core.directions.MarkSet), после правки обновляются тексты
  уже созданных строк. Своя отметка - чёрным, унаследованная - серым «… — от «папка»», несохранённое - синим с «•».
- Черновик - несохранённые отметки окна: словарь «исходный путь без регистра → отметка». Итог считается с черновиком
  (service.razbor(disk, drafts)), задания - только из сохранённых отметок.
- Итог и «Уже есть» (service.razbor_have) - в фоне, не больше одного расчёта каждого вида; ответ принимается, только если
  с его запуска ничего не менялось (ревизия), иначе считается заново по последнему состоянию.
- Запись: в предпросмотр и запись уходит неизменяемая копия пакета; страница на это время недоступна. После любого
  исхода сохранённые отметки перечитываются, из черновика уходит только то, что совпало с сохранённым.
Подключение в окно: ('Разбор носителя', RazborPage(self)).
"""
import collections
import html
import time
import traceback

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QMenu, QMessageBox, QPushButton, QRadioButton, QSplitter, QStyledItemDelegate,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from hb_core import api as hb
from hb_core import razbor as rz
from hb_core.consts import F_PHOTO, F_TEXT, F_VIDEO
from hb_core.directions import R_DIR, R_NONE, R_SKIP, R_UNSET
import disk_ui
import service as sv

TITLE = 'Архив дисков'
SEP = '\\'
ROLE = Qt.UserRole
C_NAME, C_TO, C_FILES, C_GB, C_PHOTO, C_VIDEO, C_OTHER, C_HAVE = range(8)
HEAD = ['Папка', 'Куда', 'Файлов', 'ГБ', 'Фото', 'Видео', 'Прочее', 'Уже есть']
GRAY, BLUE, BLUE2, ORANGE, RED, GREEN = '#757575', '#1565c0', '#5c6bc0', '#e65100', '#c62828', '#2e7d32'
INHERIT, SKIP = hb.MARK_INHERIT, hb.MARK_SKIP
DEBOUNCE_MS = 600
UNDO_MAX = 50


def num(n):
    return f'{n or 0:,}'.replace(',', ' ')


def gb(b):
    return f'{(b or 0) / hb.GIB:,.1f}'.replace(',', ' ').replace('.', ',')


def esc(x):
    return html.escape(str(x))


def last(path):
    return path.rsplit(SEP, 1)[-1] if path else ''


def safe(fn, *a):
    """Для фона: всегда ответ («ok», результат) / («refused», причина) / («error», подробности) - окно само решает,
    что показать, и черновик не теряется ни при каком исходе."""
    try:
        return 'ok', fn(*a)
    except sv.Refused as e:
        return 'refused', str(e)
    except Exception:                                      # noqa: BLE001
        return 'error', traceback.format_exc()


# ---------- модель без Qt: папки, отметки, маршрут, черновик ----------

class Model:
    """Данные одного носителя: папки (folders), служебные папки, направления, сохранённые отметки и черновик."""

    def __init__(self, tree, drafts=None):
        self.disk = tree['disk']
        self.drafts = {}                 # исходный путь (нижний регистр) -> dict(path, phys, verdict, base)
        self.undo_stack = []
        self.have = self.have_disks = None
        self.load(tree)
        if drafts:
            self.drafts = drafts
            self.prune()

    # --- загрузка ---
    def load(self, tree):
        self.tree = tree
        self.folders, self.roots, self.dirs = tree['folders'], set(tree['roots']), tree['dirs']
        self.built, self.sig = tree.get('built'), tree.get('sig')
        self.order = sorted(self.folders, key=lambda f: (f.count(SEP) + 1 if f else 0, f))
        kids = collections.defaultdict(list)
        for f in self.order:
            if f:
                kids[hb.parent_of(f)].append(f)
        self.children = {p: sorted(v, key=lambda f: (-self.folders[f][1], f.lower())) for p, v in kids.items()}
        self.aliases = collections.defaultdict(list)      # исходный путь -> физические папки (в служебной и вне её)
        for f in self.order:
            if not self.is_service(f):
                self.aliases[self.orig(f).lower()].append(f)
        self.saved_ms = hb.MarkSet.build(tree['rows'], self.dirs)
        self.recalc()

    def reload(self, tree):
        """Новые данные носителя (новое поколение базы или запись таблиц): черновик сохраняется, совпавшее с сохранённым
        уходит из него. -> число убранных записей черновика."""
        self.load(tree)
        return self.prune()

    def prune(self):
        gone = [k for k, d in self.drafts.items() if self.equal_saved(k, d['verdict'])]
        for k in gone:
            del self.drafts[k]
        self.recalc()
        return len(gone)

    # --- пути ---
    def is_service(self, f):
        """Сама служебная папка переноса («ПЕРЕНЕСЕНО → …», «Скопировано на …» из журнала): отметить нельзя."""
        return bool(f) and SEP not in f and f in self.roots

    def orig(self, f):
        return rz.original_of(f, self.roots)[0] if f else ''

    def markable(self, f):
        return f in self.folders and not self.is_service(f)

    # --- отметки ---
    def saved_key(self, key):
        m = self.saved_ms.by_key.get(key)
        return None if m is None else (m.kind, m.num)

    def equal_saved(self, key, verdict):
        if verdict == INHERIT:
            return self.saved_ms.by_key.get(key) is None
        return self.saved_key(key) == hb.parse_verdict(verdict, self.dirs)[:2]

    def draft_rows(self):
        return [(d['path'], d['verdict']) for d in self.drafts.values()]

    def ms(self):
        return hb.MarkSet.build(self.tree['rows'], self.dirs, self.draft_rows())

    def routes(self, ms):
        """Действующая отметка каждой папки - как в ядре (hb_core.razbor.planner, раздел «маршрут по папкам»):
        корень - отметка всего носителя; служебная папка переноса - ничего (отметка носителя туда не наследуется);
        внутри неё - только явные отметки исходного пути; иначе - своя отметка или маршрут родителя."""
        route = {}
        for f in self.order:
            if not f:
                m = ms.get('')
                route[f] = rz._mark_route(m, self.dirs) if m else rz.NONE_ROUTE
                continue
            top = f.split(SEP, 1)[0]
            parent = route.get(hb.parent_of(f), rz.NONE_ROUTE)
            if top in self.roots:
                if f == top:
                    route[f] = rz.Route(R_NONE, None, None, True)
                    continue
                m = ms.get(f[len(top) + 1:])
                route[f] = rz._mark_route(m, self.dirs, True) if m else parent
                continue
            m = ms.get(f)
            route[f] = rz._mark_route(m, self.dirs) if m else parent
        return route

    def recalc(self):
        self.full_ms = self.ms()
        self.route = self.routes(self.full_ms)
        self.route_saved = self.routes(self.saved_ms)
        self.have_sub = self.have_counts()

    def push_undo(self):
        self.undo_stack.append({k: dict(v) for k, v in self.drafts.items()})
        del self.undo_stack[:-UNDO_MAX]

    def set_mark(self, folders, verdict):
        """Черновая отметка папок (физические пути; '' - весь носитель). -> сколько записей черновика изменилось."""
        self.push_undo()
        changed = 0
        for f in folders:
            if f and not self.markable(f):
                continue
            o = self.orig(f)
            key = o.lower()
            cur = self.drafts.get(key)
            if self.equal_saved(key, verdict):
                if cur is not None:
                    del self.drafts[key]
                    changed += 1
                continue
            if cur is None or cur['verdict'] != verdict:
                self.drafts[key] = dict(path=o, phys=f, verdict=verdict,
                                        base=cur['base'] if cur else self.saved_key(key))
                changed += 1
        if not changed:
            self.undo_stack.pop()
        self.recalc()
        return changed

    def undo(self):
        if not self.undo_stack:
            return False
        self.drafts = self.undo_stack.pop()
        self.recalc()
        return True

    def discard(self):
        if self.drafts:
            self.push_undo()
            self.drafts = {}
            self.recalc()

    def own_choice(self, f):
        """Что стоит у папки своё (для выпадающего списка): текст решения или «как у родителя»."""
        m = self.full_ms.get(self.orig(f))
        if m is None:
            return INHERIT
        if m.kind == R_DIR and m.num in self.dirs:
            return self.dirs[m.num].verdict()
        if m.kind == R_SKIP:
            return SKIP
        return None

    # --- показ ---
    def label(self, r):
        if r.state == R_DIR:
            d = self.dirs.get(r.num)
            t = d.label() if d else str(r.num)
            return t + (' — дополнительная копия (папка уже перенесена)' if r.moved else '')
        if r.state == R_SKIP:
            return 'не копировать' + (f' (старое «{r.mark.label}»)' if r.mark is not None and r.mark.legacy else '')
        if r.state == R_UNSET:
            return hb.mark_text(r.mark, self.dirs)
        return 'уже перенесено' if r.moved else 'не отмечено'

    def mode_text(self, r):
        if r.mark is None:
            return 'режим не выбран — файлы «не отмечены»'
        if r.state == R_DIR:
            return f'всё — в {self.label(r)}, кроме отмеченных'
        if r.state == R_SKIP:
            return 'ничего, кроме отмеченных'
        return self.label(r)

    def cell(self, f, saved=False):
        """Ячейка «Куда»: dict(text, kind 'own'/'inherited'/'none'/'service', dirty None/'own'/'drop'/'inherited', tip)."""
        if self.is_service(f):
            return dict(text='служебная папка: уже перенесено', kind='service', dirty=None,
                        tip='Папка, куда файлы перенесли раньше. Её саму отметить нельзя; папки внутри неё можно '
                            'отметить, чтобы ДОПОЛНИТЕЛЬНО скопировать их в другое направление (второй раз они не '
                            'перемещаются).')
        o = self.orig(f)
        r = (self.route_saved if saved else self.route)[f]
        own = r.mark is not None and r.mark.path.lower() == o.lower()
        tips = []
        if not f:
            text = self.mode_text(r)
            kind = 'own' if r.mark is not None else 'none'
        else:
            text = self.label(r)
            if own:
                kind = 'own'
            elif r.mark is not None:
                kind = 'inherited'
                src = 'режима' if r.mark.path == '' else f'«{last(r.mark.path)}»'
                text += f' — от {src}'
                tips.append('Унаследовано от ' + ('режима всего носителя' if r.mark.path == '' else
                                                  f'папки «{r.mark.path}»') + '.')
            else:
                kind = 'none'
        dirty = None
        if not saved:
            d = self.drafts.get(o.lower())
            rs = self.route_saved[f]
            if d is not None and d['verdict'] == INHERIT:
                dirty = 'drop'
                text = '• снять свою отметку → ' + text
                tips.append('Своя отметка будет снята при сохранении; папка получит отметку родителя.')
            elif d is not None:
                dirty = 'own'
                text = '• ' + text
                tips.append('Своя отметка — НЕ сохранена (кнопка «Сохранить отметки»).')
            elif (r.state, r.num, r.moved) != (rs.state, rs.num, rs.moved):
                dirty = 'inherited'
                text = '• ' + text
                tips.append(f'Изменится после сохранения из-за отметки выше; сейчас сохранено: {self.cell(f, True)["text"]}.')
            elif own:
                tips.append('Своя отметка этой папки (сохранена).')
            if d is not None and d['base'] != self.saved_key(o.lower()):
                tips.append('Пока вы отмечали, отметку этой папки изменили в другом месте.')
        others = [x for x in self.aliases.get(o.lower(), []) if x != f]
        if f and others:
            tips.append('Та же отметка действует и на: ' + '; '.join(f'«{x}»' for x in others[:3]) + '.')
        return dict(text=text, kind=kind, dirty=dirty, tip=' '.join(tips))

    # --- «Уже есть» ---
    def set_have(self, have, disks_):
        self.have, self.have_disks = have, list(disks_)
        self.have_sub = self.have_counts()

    def have_counts(self):
        """«Уже есть» по поддереву: у каждой папки - СВОЁ направление для файлов прямо в ней (с хешем, типы, которые
        направление копирует, есть на всех его дисках), затем сумма детей. None - ещё не посчитано."""
        if self.have is None:
            return None
        own = {}
        for f, masks in self.have.items():
            r = self.route.get(f)
            if r is None or r.state != R_DIR:
                continue
            d = self.dirs.get(r.num)
            if d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
                continue
            need = sum(1 << self.have_disks.index(x) for x in d.disks)
            types = (F_PHOTO, F_VIDEO, F_TEXT) if d.media_only else (0, 1, 2, 3)
            n = b = 0
            for mask, c in masks.items():
                if mask & need == need:
                    n += sum(c[k] for k in types)
                    b += sum(c[5 + k] for k in types)
            if n:
                own[f] = (n, b)
        sub = collections.defaultdict(lambda: [0, 0])
        for f in reversed(self.order):
            v = own.get(f)
            if v:
                sub[f][0] += v[0]
                sub[f][1] += v[1]
            if f and f in sub:
                p = sub[hb.parent_of(f)]
                p[0] += sub[f][0]
                p[1] += sub[f][1]
        return dict(sub)

    # --- предпросмотр записи ---
    def batch(self):
        """Неизменяемая копия пакета для записи: [(физический путь, решение)] и ключи."""
        return [(d['phys'], d['verdict']) for d in self.drafts.values()], {k: d['verdict'] for k, d in self.drafts.items()}

    def change_lines(self):
        """«было → станет» по каждой записи черновика, вложенные папки, отметки, изменённые в другом месте."""
        lines, conflicts = [], []
        for k, d in sorted(self.drafts.items(), key=lambda kv: kv[1]['path'].lower()):
            f = d['phys']
            where = f'{self.disk}\\{f}' if f else f'{self.disk} (весь носитель)'
            before, after = self.cell(f, True)['text'], self.cell(f)['text'].lstrip('• ')
            lines.append(f'{where}: было «{before}» → станет «{after}»')
            if d['base'] != self.saved_key(k):
                conflicts.append(f'{where}: отметку изменили в другом месте, пока вы отмечали; ваша отметка заменит её.')
        paths = sorted(d['path'].lower() for d in self.drafts.values() if d['path'])
        nested = any(b.startswith(a + SEP) for a in paths for b in paths if a != b) or ('' in self.drafts and paths)
        return lines, conflicts, bool(nested)


# ---------- выпадающий список «Куда» в ячейке ----------

class ToDelegate(QStyledItemDelegate):
    """Двойной щелчок по «Куда»: список для ОДНОЙ папки (для нескольких - панель «Применить к выделенным» или меню)."""

    def __init__(self, page):
        super().__init__(page.tree)
        self.page = page

    def createEditor(self, parent, option, index):           # noqa: N802
        f = index.siblingAtColumn(C_NAME).data(ROLE)
        m = self.page.model
        if m is None or f is None or not f or not m.markable(f):
            return None
        cb = QComboBox(parent)
        for text, verdict in self.page.choices():
            cb.addItem(text, verdict)
        cb.activated.connect(lambda _i, cb=cb: (self.commitData.emit(cb), self.closeEditor.emit(cb)))
        QTimer.singleShot(0, cb.showPopup)
        return cb

    def setEditorData(self, ed, index):                      # noqa: N802
        f = index.siblingAtColumn(C_NAME).data(ROLE)
        i = ed.findData(self.page.model.own_choice(f)) if self.page.model else -1
        ed.setCurrentIndex(max(i, 0))

    def setModelData(self, ed, model, index):                # noqa: N802
        f, v = index.siblingAtColumn(C_NAME).data(ROLE), ed.currentData()
        QTimer.singleShot(0, lambda: self.page.apply([f], v))


class CloseGuard(QObject):
    """Фильтр событий ГЛАВНОГО окна: закрытие при несохранённых отметках - только с согласия; во время записи - нельзя."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, obj, ev):                          # noqa: N802
        if ev.type() != QEvent.Close:
            return False
        p = self.page
        if p.writing:
            QMessageBox.information(p.win, TITLE, 'Идёт запись отметок или создание заданий («Разбор носителя»). '
                                    'Дождитесь окончания.')
            ev.ignore()
            return True
        n = len(p.model.drafts) if p.model else 0
        if n and QMessageBox.question(p.win, TITLE, f'На странице «Разбор носителя» есть несохранённые отметки ({n}).\n\n'
                                      'Закрыть окно без сохранения? Они пропадут.') != QMessageBox.Yes:
            ev.ignore()
            return True
        return False


class TextDialog(QDialog):
    """Окно с текстом (HTML) и кнопками: ok_text - главная кнопка (None - только «Закрыть»)."""

    def __init__(self, parent, title, body, ok_text=None, cancel_text='Отмена', width=900, height=600):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, height)
        lay = QVBoxLayout(self)
        self.text = QTextBrowser()
        self.text.setHtml(body)
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.ok = None
        if ok_text:
            self.ok = QPushButton(ok_text)
            self.ok.setDefault(True)
            self.ok.clicked.connect(self.accept)
            row.addWidget(self.ok)
        b = QPushButton(cancel_text if ok_text else 'Закрыть')
        b.clicked.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)


# ---------- «Пересчитать хеши спорных файлов» (разбор и «Команды» после «НЕТ / НЕДОСТАТОЧНО») ----------

class ContestedDialog(QDialog):
    """По service.contested: на каких дисках и в каких папках спорные файлы; подключённый диск - открыть «Пересканировать
    папки» с этими папками (хеш у всех файлов там всегда включён); неподключённый - какой диск подключить."""

    def __init__(self, win, disk, folder=''):
        super().__init__(win)
        self.win, self.disk, self.folder = win, disk, (folder or '').strip(SEP)
        self.rows = None
        self.setWindowTitle(f'Пересчитать хеши спорных файлов - {disk}')
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        where = f'{disk}\\{self.folder}' if self.folder else f'{disk} (весь носитель)'
        lay.addWidget(QLabel(f'<b>{esc(where)}</b>: где лежат файлы без хеша и '
                             'неподтверждённые копии, из-за которых ответ «можно ли удалить» - «НЕТ» или «НЕДОСТАТОЧНО».'
                             ' Пересканирование посчитает хеш у всех файлов этих папок.'))
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)
        self.buttons = QVBoxLayout()
        lay.addLayout(self.buttons)
        row = QHBoxLayout()
        again = QPushButton('Проверить заново')
        again.clicked.connect(self.load)
        row.addWidget(again)
        row.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.load()

    def load(self):
        self.text.setHtml('<p>Ищу спорные файлы по базе (диски не читаются)…</p>')
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.win.bg.run(safe, sv.contested, self.disk, self.folder, ok=self.show_rows, quiet=True)

    def show_rows(self, res):
        kind, val = res
        if kind != 'ok':
            self.text.setHtml(f'<p style="color:{RED}">Не получилось: {esc(val.strip().splitlines()[-1] if val.strip() else val)}</p>')
            return
        self.rows = val
        if not val:
            self.text.setHtml('<p>Спорных файлов нет: пересчитывать хеши незачем.</p>')
            return
        h = []
        for d, letter, folders in val:
            total = sum(n for _, n in folders)
            state = (f'<b style="color:{GREEN}">подключён ({esc(letter)})</b>' if letter else
                     f'<b style="color:{ORANGE}">не подключён — подключите его и нажмите «Проверить заново»</b>')
            h.append(f'<p><b>{esc(d)}</b>: {state}; папок {len(folders)}, спорных файлов {num(total)}</p><ul>')
            for f, n in folders[:30]:
                if f == '':
                    h.append(f'<li>весь носитель — {num(n)} спорных файлов, часть лежит прямо в корне, поэтому папками '
                             f'не обойтись: запустите полное сканирование {esc(d)} в программе «Сканер дисков»</li>')
                else:
                    h.append(f'<li>{esc(f)} — {num(n)}</li>')
            if len(folders) > 30:
                h.append(f'<li>… и ещё {len(folders) - 30} папок (все войдут в пересканирование)</li>')
            h.append('</ul>')
            sub = [f for f, _ in folders if f]
            if letter and sub:
                b = QPushButton(f'Пересканировать эти папки на {d} ({letter})…  — {len(sub)} папок')
                b.clicked.connect(lambda _=False, d=d, sub=sub: self.rescan(d, sub))
                self.buttons.addWidget(b)
        self.text.setHtml(''.join(h))

    def rescan(self, disk, folders):
        import rescan_dialog
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.show()


# ---------- страница ----------

class RazborPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.model, self.disk, self.disk_rows = win, None, None, []
        self.items = {}                                   # физический путь папки -> элемент дерева
        self.rev = 0                                      # ревизия входов итога (любая правка, носитель, база)
        self.sum_busy = self.sum_pending = False
        self.have_busy = self.have_pending = False
        self.writing = False
        self.plan = None                                  # последний принятый итог: (план, свободно, время)
        self.plan_rev = -1                                # его ревизия (равна self.rev - итог актуален)
        self.loading = None                               # носитель, данные которого читаются
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('<b>Разбор носителя</b>'))
        top.addSpacing(16)
        top.addWidget(QLabel('Носитель:'))
        from commands_page import DiskCombo               # тот же список, что в «Командах»: подключённые сверху
        self.disk_box = DiskCombo(optional=False)
        self.disk_box.setMinimumWidth(380)
        self.disk_box.currentIndexChanged.connect(self.disk_changed)
        top.addWidget(self.disk_box)
        self.info = QLabel('')
        self.info.setStyleSheet(f'color:{GRAY}')
        top.addWidget(self.info, 1)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        lay.addLayout(top)
        self.banner = QLabel('')
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f'background:#fff3e0; color:{ORANGE}; padding:6px; border:1px solid #ffcc80')
        self.banner.hide()
        lay.addWidget(self.banner)
        # шаг 1 - режим
        g1 = QGroupBox('Шаг 1. Что делать со всем носителем')
        l1 = QHBoxLayout(g1)
        self.mode_all = QRadioButton('Всё — в')
        self.mode_dir = QComboBox()
        self.mode_dir.setMinimumWidth(240)
        self.mode_none = QRadioButton('Ничего, кроме отмеченных папок')
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_all)
        self.mode_group.addButton(self.mode_none)
        self.mode_all.toggled.connect(lambda on: on and self.mode_changed())
        self.mode_none.toggled.connect(lambda on: on and self.mode_changed())
        self.mode_dir.activated.connect(lambda _i: self.mode_all.isChecked() and self.mode_changed())
        l1.addWidget(self.mode_all)
        l1.addWidget(self.mode_dir)
        l1.addWidget(QLabel(', кроме отмеченных папок'))
        l1.addSpacing(30)
        l1.addWidget(self.mode_none)
        self.mode_hint = QLabel('')
        self.mode_hint.setStyleSheet(f'color:{GRAY}')
        l1.addWidget(self.mode_hint, 1)
        lay.addWidget(g1)
        # шаг 2 - дерево и шаг 3 - итог
        split = QSplitter(Qt.Horizontal)
        g2 = QGroupBox('Шаг 2. Куда идут папки (отметка действует на все подпапки, пока у подпапки нет своей)')
        l2 = QVBoxLayout(g2)
        row = QHBoxLayout()
        self.sel_label = QLabel('Выделено папок: 0.')
        row.addWidget(self.sel_label)
        row.addWidget(QLabel('Куда:'))
        self.apply_box = QComboBox()
        self.apply_box.setMinimumWidth(240)
        row.addWidget(self.apply_box)
        self.apply_btn = QPushButton('Применить к выделенным')
        self.apply_btn.clicked.connect(self.apply_selected)
        row.addWidget(self.apply_btn)
        row.addStretch()
        l2.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(HEAD)
        hd = self.tree.header()
        hd.setSectionResizeMode(QHeaderView.Interactive)
        hd.setStretchLastSection(False)
        self.tree.setColumnWidth(C_NAME, 230)
        self.tree.setColumnWidth(C_TO, 330)
        for c in range(C_FILES, C_HAVE + 1):                 # числа - по ширине (строк немного: дерево ленивое)
            hd.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        tips = {C_TO: 'Двойной щелчок - выбрать для одной папки. Несколько папок: выделите (Shift/Ctrl) и «Применить к '
                      'выделенным» или правая кнопка мыши.',
                C_PHOTO: 'Число фото в папке с подпапками', C_VIDEO: 'Число видео в папке с подпапками',
                C_OTHER: 'Документы, прочие файлы и мусор (Thumbs.db и т. п.)',
                C_HAVE: 'Файлов с хешем, которые уже лежат на ВСЕХ дисках своего направления (по базе): их копировать '
                        'не нужно. «—» - направления с диском нет.'}
        for c, t in tips.items():
            self.tree.headerItem().setToolTip(c, t)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegateForColumn(C_TO, ToDelegate(self))
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemDoubleClicked.connect(self.double_click)
        self.tree.itemSelectionChanged.connect(self.selection_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        l2.addWidget(self.tree, 1)
        hint = QLabel('Своя отметка — чёрным, унаследованная — серым («— от …»), несохранённое — синим с «•». '
                      '«Куда»: двойной щелчок по ячейке; для нескольких папок — выделите их (Shift/Ctrl) и «Применить '
                      'к выделенным» или правая кнопка мыши.')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color:{GRAY}')
        l2.addWidget(hint)
        split.addWidget(g2)
        g3 = QGroupBox('Шаг 3. Итог')
        l3 = QVBoxLayout(g3)
        self.sum_state = QLabel('')
        self.sum_state.setWordWrap(True)
        l3.addWidget(self.sum_state)
        self.summary = QTextBrowser()
        l3.addWidget(self.summary, 1)
        split.addWidget(g3)
        split.setSizes([900, 460])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        # шаг 4 - кнопки
        bar = QHBoxLayout()
        self.save_btn = QPushButton('Сохранить отметки')
        self.save_btn.clicked.connect(lambda: self.save())
        self.undo_btn = QPushButton('Отменить последнее')
        self.undo_btn.clicked.connect(self.undo)
        self.discard_btn = QPushButton('Отменить все несохранённые')
        self.discard_btn.clicked.connect(self.discard)
        self.contested_btn = QPushButton('Пересчитать хеши спорных файлов…')
        self.contested_btn.setToolTip('Где лежат файлы без хеша и неподтверждённые копии выделенной папки (или всего '
                                      'носителя); подключённые диски - пересканировать с хешем всех файлов.')
        self.contested_btn.clicked.connect(self.contested)
        self.tasks_btn = QPushButton('Подготовить задания…')
        self.tasks_btn.setToolTip('Одно задание копирования на каждую отмеченную папку - по СОХРАНЁННЫМ отметкам. '
                                  'Сначала - расчёт и показ, задания создаются после подтверждения.')
        self.tasks_btn.clicked.connect(self.prepare)
        for w in (self.save_btn, self.undo_btn, self.discard_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.contested_btn)
        bar.addWidget(self.tasks_btn)
        lay.addLayout(bar)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.run_summary)
        self.guard = CloseGuard(self)
        win.installEventFilter(self.guard)
        self.update_buttons()

    # ---------- носители и данные ----------
    def refresh(self):
        """При показе раздела и после применения новых модулей: список носителей; у выбранного - новые данные, если
        изменились поколение базы или таблицы владельца (черновик сохраняется)."""
        self.win.bg.run(safe, self._probe, ok=self.got_probe, quiet=True)

    @staticmethod
    def _probe():
        return sv.disks(), sv.generation(), sv.snapshot()['sig']

    def got_probe(self, res):
        kind, val = res
        if kind != 'ok':
            return
        rows, gen, sig = val
        self.disk_rows = rows
        self.disk_box.blockSignals(True)
        self.disk_box.fill(rows)
        if self.disk:
            self.disk_box.setCurrentText(self.disk)
        self.disk_box.blockSignals(False)
        if self.disk is None:
            on = [r for r in disk_ui.ordered(rows) if r.get('letter')]
            if on:
                self.disk_box.setCurrentText(on[0]['disk'])       # -> disk_changed
            else:
                self.sum_state.setText('Выберите носитель в списке вверху.')
            return
        m = self.model
        if m is not None and self.loading is None and not self.writing and (gen != m.built or sig != m.sig):
            self.load_disk(self.disk, keep=True)

    def disk_changed(self, _i=None):
        new = self.disk_box.value()
        if not new or new == self.disk:
            return
        n = len(self.model.drafts) if self.model else 0
        if n and QMessageBox.question(self, TITLE, f'У носителя {self.disk} есть несохранённые отметки ({n}).\n\n'
                                      f'Перейти к {new} без сохранения? Они пропадут.') != QMessageBox.Yes:
            self.disk_box.blockSignals(True)
            self.disk_box.setCurrentText(self.disk)
            self.disk_box.blockSignals(False)
            return
        self.choose_disk(new)

    def choose_disk(self, disk):
        """Выбрать носитель (из списка или из теста): дерево, итог и «Уже есть» - заново."""
        self.disk, self.model, self.plan = disk, None, None
        self.disk_box.blockSignals(True)
        self.disk_box.setCurrentText(disk)
        self.disk_box.blockSignals(False)
        self.tree.clear()
        self.items = {}
        self.summary.setHtml('')
        self.banner.hide()
        self.update_buttons()
        self.load_disk(disk, keep=False)

    def load_disk(self, disk, keep):
        self.loading = disk
        self.sum_state.setText('Читаю папки носителя из базы…')
        self.win.bg.run(safe, sv.razbor_tree, disk, ok=lambda res, d=disk, k=keep: self.got_tree(d, k, res), quiet=True)

    def got_tree(self, disk, keep, res):
        if disk != self.disk:
            return
        self.loading = None
        kind, val = res
        if kind != 'ok':
            self.sum_state.setText(f'<span style="color:{RED}">Не получилось прочитать носитель: '
                                   f'{esc(val.strip().splitlines()[-1] if val.strip() else val)}</span>')
            return
        old = self.model
        old_have = (old.have, old.have_disks) if old is not None else None
        if keep and old is not None:
            same_tree = set(old.folders) == set(val['folders']) and old.roots == set(val['roots'])
            gen_changed = old.built != val['built']
            pruned = old.reload(val)
            if pruned:
                self.win.statusBar().showMessage(f'Отметки, которые уже сохранены так же: {pruned} - убраны из '
                                                 'несохранённых.', 6000)
            if same_tree:
                self.update_items()
            else:
                self.rebuild_tree()
        else:
            self.model = Model(val)
            gen_changed = True
            self.rebuild_tree()
        self.show_disk_info()
        self.sync_mode()
        self.fill_choices()
        need = self.direction_disks()
        if old_have and old_have[0] is not None and old_have[1] == need:
            self.model.set_have(*old_have)                 # прежние цифры видны, пока считаются новые
            self.update_items()
        if gen_changed or not old_have or old_have[1] != need:
            self.run_have()
        self.changed(debounce=False)

    def direction_disks(self):
        m = self.model
        return sorted({d for x in m.dirs.values() for d in x.disks}) if m else []

    def show_disk_info(self):
        m = self.model
        row = next((r for r in self.disk_rows if r['disk'] == self.disk), {'disk': self.disk, 'label': m.tree['label']})
        title = disk_ui.disk_title(row) or ''
        sc = m.tree.get('scanned')
        st = disk_ui.status_text(m.tree.get('status'))
        bits = [title, f'опись от {time.strftime("%d.%m.%Y", time.localtime(sc))}' if sc else 'дата описи неизвестна',
                f'опись: {st}']
        if m.tree.get('issues'):
            bits.append(f'непрочитанных мест: {num(m.tree["issues"])}')
        bits.append('подключён (' + row['letter'] + ')' if row.get('letter') else 'не подключён')
        self.info.setText(' · '.join(x for x in bits if x))
        d = hb.direction_of_disk(m.dirs, self.disk)
        if d:
            self.banner.setText(f'{self.disk} — сам диск направления «{d.name}» ({hb.disk_nums(d.disks)}): копировать с '
                                f'него на остальные диски направления можно, перемещать на нём ничего нельзя.')
            self.banner.show()
        else:
            self.banner.hide()

    # ---------- дерево ----------
    def rebuild_tree(self):
        """Перестроить дерево, сохранив раскрытые узлы, выделение и прокрутку (по путям)."""
        expanded = {p for p, it in self.items.items() if it.isExpanded()}
        selected = {it.data(C_NAME, ROLE) for it in self.tree.selectedItems()}
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self.items = {}
        m = self.model
        root = QTreeWidgetItem([f'{self.disk} (весь носитель)'])
        root.setData(C_NAME, ROLE, '')
        self.tree.addTopLevelItem(root)
        self.items[''] = root
        self.set_item(root, '')
        self.fill(root)
        root.setExpanded(True)
        for p in sorted(expanded, key=lambda x: x.count(SEP)):
            it = self.items.get(p)
            if it is not None and p in m.folders:
                it.setExpanded(True)                     # -> expand(): дети создаются
        for p in selected:
            if p in self.items:
                self.items[p].setSelected(True)
        QTimer.singleShot(0, lambda: self.tree.verticalScrollBar().setValue(scroll))

    def fill(self, item):
        """Создать детей узла (лениво: внуки - по раскрытию)."""
        p = item.data(C_NAME, ROLE)
        item.takeChildren()
        item.setData(C_TO, ROLE, True)                   # дети созданы
        for f in self.model.children.get(p, ()):
            ch = QTreeWidgetItem([last(f)])
            ch.setData(C_NAME, ROLE, f)
            for c in range(C_FILES, C_HAVE + 1):
                ch.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            if self.model.markable(f):
                ch.setFlags(ch.flags() | Qt.ItemIsEditable)
            self.items[f] = ch
            self.set_item(ch, f)
            if self.model.children.get(f):
                ch.addChild(QTreeWidgetItem(['…']))
            item.addChild(ch)

    def expand(self, item):
        if not item.data(C_TO, ROLE) and item.data(C_NAME, ROLE) is not None:
            self.fill(item)

    def double_click(self, item, col):
        if col == C_TO:
            f = item.data(C_NAME, ROLE)
            if f and self.model and self.model.markable(f):
                self.tree.editItem(item, C_TO)
            elif f == '':
                QMessageBox.information(self, TITLE, 'Весь носитель - это режим: выберите его в «Шаге 1» над деревом.')
            elif f:
                QMessageBox.information(self, TITLE, self.model.cell(f)['tip'])
        else:
            item.setExpanded(not item.isExpanded())

    def set_item(self, it, f):
        m = self.model
        files, size, n, b = m.folders.get(f, (0, 0, (0,) * 5, (0,) * 5))
        cell = m.cell(f)
        it.setText(C_TO, cell['text'])
        it.setToolTip(C_TO, cell['tip'])
        font = QFont()
        font.setItalic(bool(cell['dirty']))
        font.setBold(not f)
        it.setFont(C_TO, font)
        color = {'own': None, 'inherited': GRAY, 'none': GRAY, 'service': GRAY}[cell['kind']]
        if cell['dirty'] in ('own', 'drop'):
            color = BLUE
        elif cell['dirty'] == 'inherited':
            color = BLUE2
        elif m.route[f].state == R_UNSET:
            color = ORANGE
        it.setForeground(C_TO, QBrush(QColor(color)) if color else QBrush())
        r = m.route[f]
        if m.is_service(f) or (r.moved and r.state != R_DIR):
            it.setForeground(C_NAME, QBrush(QColor(GRAY)))
        it.setText(C_FILES, num(files))
        it.setText(C_GB, gb(size))
        it.setText(C_PHOTO, num(n[0]))
        it.setText(C_VIDEO, num(n[1]))
        it.setText(C_OTHER, num(n[2] + n[3] + n[4]))
        it.setToolTip(C_GB, f'фото {gb(b[0])} ГБ, видео {gb(b[1])} ГБ, документы {gb(b[2])} ГБ, прочие {gb(b[3])} ГБ, '
                            f'мусор {gb(b[4])} ГБ')
        it.setToolTip(C_OTHER, f'документы {num(n[2])}, прочие {num(n[3])}, мусор {num(n[4])}')
        if m.have_sub is None:
            it.setText(C_HAVE, '…')
            it.setToolTip(C_HAVE, 'Считаю, что уже есть на дисках направлений…')
        else:
            v = m.have_sub.get(f)
            r = m.route.get(f)
            with_disk = r is not None and r.state == R_DIR and m.dirs.get(r.num) is not None and m.dirs[r.num].disks
            it.setText(C_HAVE, num(v[0]) if v else ('0' if with_disk else '—'))
            it.setToolTip(C_HAVE, f'{num(v[0])} файлов, {gb(v[1])} ГБ уже есть на всех дисках своего направления (по '
                                  'хешу)' if v else 'Ничего из этой папки на дисках направления по хешу не найдено.')

    def update_items(self):
        for f, it in self.items.items():
            if self.model and f in self.model.folders:
                self.set_item(it, f)

    # ---------- отметки ----------
    def choices(self):
        m = self.model
        res = [(d.label(), d.verdict()) for d in m.dirs.values()] if m else []
        return res + [('не копировать', SKIP), ('как у родителя (снять свою отметку)', INHERIT)]

    def fill_choices(self):
        cur = self.apply_box.currentData()
        self.apply_box.clear()
        for text, v in self.choices():
            self.apply_box.addItem(text, v)
        i = self.apply_box.findData(cur)
        self.apply_box.setCurrentIndex(max(i, 0))
        cur = self.mode_dir.currentData()
        self.mode_dir.blockSignals(True)
        self.mode_dir.clear()
        for d in self.model.dirs.values():
            self.mode_dir.addItem(d.label(), d.verdict())
        self.sync_mode()
        self.mode_dir.blockSignals(False)

    def sync_mode(self):
        """Радиокнопки по действующей (с черновиком) отметке всего носителя."""
        m = self.model
        if m is None:
            return
        r = m.route.get('', rz.NONE_ROUTE)
        for b in (self.mode_all, self.mode_none):
            b.blockSignals(True)
        self.mode_group.setExclusive(False)
        self.mode_all.setChecked(r.mark is not None and r.state == R_DIR)
        self.mode_none.setChecked(r.mark is not None and r.state == R_SKIP)
        self.mode_group.setExclusive(True)
        for b in (self.mode_all, self.mode_none):
            b.blockSignals(False)
        if r.state == R_DIR and r.num in m.dirs:
            self.mode_dir.blockSignals(True)
            self.mode_dir.setCurrentIndex(max(0, self.mode_dir.findData(m.dirs[r.num].verdict())))
            self.mode_dir.blockSignals(False)
        elif self.mode_dir.currentIndex() < 0 and self.mode_dir.count():
            self.mode_dir.setCurrentIndex(0)
        if r.mark is None:
            self.mode_hint.setText('Сначала выберите режим: без него файлы «не отмечены».')
            self.mode_hint.setStyleSheet(f'color:{ORANGE}')
        else:
            d = m.drafts.get('')
            self.mode_hint.setText('• не сохранено' if d else '')
            self.mode_hint.setStyleSheet(f'color:{BLUE}')

    def mode_changed(self):
        if self.model is None:
            return
        if self.mode_all.isChecked():
            v = self.mode_dir.currentData()
            if v:
                self.apply([''], v)
        elif self.mode_none.isChecked():
            self.apply([''], SKIP)

    def selected_folders(self):
        return [it.data(C_NAME, ROLE) for it in self.tree.selectedItems() if it.data(C_NAME, ROLE)]

    def selection_changed(self):
        fs = self.selected_folders()
        ok = [f for f in fs if self.model and self.model.markable(f)]
        self.sel_label.setText(f'Выделено папок: {len(fs)}.' + (f' (служебных, их не отметить: {len(fs) - len(ok)})'
                                                                 if len(ok) != len(fs) else ''))
        self.apply_btn.setText(f'Применить к выделенным ({len(ok)})' if len(ok) != 1 else 'Применить к выделенной')
        self.apply_btn.setEnabled(bool(ok) and not self.writing)

    def apply_selected(self):
        self.apply(self.selected_folders(), self.apply_box.currentData())

    def menu(self, pos):
        if self.model is None:
            return
        fs = [f for f in self.selected_folders() if self.model.markable(f)]
        if not fs:
            return
        menu = QMenu(self)
        head = menu.addAction(f'Куда для {len(fs)} выделенных папок:' if len(fs) > 1 else f'Куда для «{last(fs[0])}»:')
        head.setEnabled(False)
        acts = {}
        for text, v in self.choices():
            acts[menu.addAction('   ' + text)] = v
        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if act in acts:
            self.apply(fs, acts[act])

    def apply(self, folders, verdict):
        if self.model is None or verdict is None or self.writing:
            return
        if self.model.set_mark(folders, verdict):
            self.update_items()
            self.sync_mode()
            self.changed()

    def undo(self):
        if self.model and self.model.undo():
            self.update_items()
            self.sync_mode()
            self.changed()

    def discard(self):
        if not self.model or not self.model.drafts:
            return
        if QMessageBox.question(self, TITLE, f'Отменить все несохранённые отметки ({len(self.model.drafts)})?\n\n'
                                '«Отменить последнее» вернёт их обратно.') != QMessageBox.Yes:
            return
        self.model.discard()
        self.update_items()
        self.sync_mode()
        self.changed()

    def changed(self, debounce=True):
        """Любая правка входов итога: ревизия растёт сразу, итог помечается устаревшим и считается заново."""
        self.rev += 1
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

    def update_buttons(self):
        n = len(self.model.drafts) if self.model else 0
        busy = self.writing or self.model is None
        self.save_btn.setText(f'Сохранить отметки ({n})' if n else 'Сохранить отметки')
        self.save_btn.setEnabled(bool(n) and not busy)
        self.undo_btn.setEnabled(bool(self.model and self.model.undo_stack) and not busy)
        self.discard_btn.setEnabled(bool(n) and not busy)
        self.tasks_btn.setEnabled(not busy)
        self.contested_btn.setEnabled(not busy)
        self.selection_changed()

    # ---------- итог ----------
    def run_summary(self):
        if self.model is None:
            return
        if self.sum_busy:
            self.sum_pending = True
            return
        self.sum_busy = True
        snap = (self.disk, self.rev)
        drafts = list(self.model.draft_rows())

        def job(disk, drafts):
            P = sv.razbor(disk, drafts)
            return P, sv.free_space(list(P.part_b)), time.strftime('%H:%M:%S')
        self.win.bg.run(safe, job, self.disk, drafts, ok=lambda res, s=snap: self.got_summary(s, res), quiet=True)

    def got_summary(self, snap, res):
        self.sum_busy = False
        if snap[0] == self.disk and snap[1] == self.rev:
            kind, val = res
            if kind == 'ok':
                self.plan, self.plan_rev = val, snap[1]
                self.render_summary(*val)
                self.sum_state.setText(f'<span style="color:{GRAY}">Посчитано в {val[2]}, с несохранёнными отметками.'
                                       '</span>')
                self.sum_state.setToolTip('Итог учитывает и несохранённые отметки; задания строятся только из сохранённых.')
            else:
                self.sum_state.setText(f'<span style="color:{RED}">Итог не посчитан: '
                                       f'{esc(val.strip().splitlines()[-1] if val.strip() else val)}</span>')
            if not self.sum_pending:
                return
        self.sum_pending = False
        if self.model is not None and not self.debounce.isActive():   # иначе его запустит таймер правки
            self.run_summary()

    def disk_name(self, d):
        row = next((r for r in self.disk_rows if r['disk'] == d), None)
        t = disk_ui.disk_title(row) if row else ''
        return f'{d} «{t}»' if t else d

    def render_summary(self, P, free, at):
        h = []
        h.append(f'<p><b>{esc(self.disk_name(P.disk))}</b>: {num(P.total[0])} файлов, {gb(P.total[1])} ГБ. '
                 f'Отметок: {len(P.marks)}' + (f' (несохранённых {len(self.model.drafts)})' if self.model.drafts else '')
                 + '.</p>')
        if P.errors:
            h.append(f'<p style="color:{RED}"><b>ИТОГ НЕВЕРЕН:</b> {esc("; ".join(P.errors))}. Задания не создаются.</p>')
        h.append('<p><b>А. Что будет с каждым файлом носителя</b></p>'
                 '<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                 '<tr><th align="left">Что будет</th><th>Файлов</th><th>ГБ</th></tr>')
        for text, n, b in rz.part_a_rows(P):
            h.append(f'<tr><td>{esc(text)}</td><td align="right">{num(n)}</td><td align="right">{gb(b)}</td></tr>')
        h.append(f'<tr><td><b>Итого = опись носителя</b></td><td align="right"><b>{num(P.total[0])}</b></td>'
                 f'<td align="right"><b>{gb(P.total[1])}</b></td></tr></table>')
        if P.moved_copy[0]:
            h.append(f'<p style="color:{GRAY}">Из «будет скопирован» {num(P.moved_copy[0])} лежат в уже перенесённых '
                     'папках: копируются дополнительно, второй раз не перемещаются.</p>')
        h.append('<p><b>Б. Сколько писать на каждый диск</b></p>')
        if P.part_b:
            h.append('<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                     '<tr><th align="left">Диск</th><th>Файлов</th><th>ГБ</th><th>Свободно</th></tr>')
            for d, (n, b) in sorted(P.part_b.items()):
                if d in free:
                    letter, fr = free[d]
                    short = b / hb.GIB > fr
                    place = (f'<span style="color:{RED if short else GREEN}">{gb(fr * hb.GIB)} ГБ ({esc(letter)})'
                             + (' — НЕ ХВАТАЕТ МЕСТА' if short else '') + '</span>')
                else:
                    place = f'<span style="color:{GRAY}">не подключён — место не проверено</span>'
                h.append(f'<tr><td>{esc(self.disk_name(d))}</td><td align="right">{num(n)}</td>'
                         f'<td align="right">{gb(b)}</td><td>{place}</td></tr>')
            h.append(f'</table><p style="color:{GRAY}">Свободное место — на {at}; задания вы запустите позже.</p>')
        else:
            h.append('<p>Писать на диски нечего.</p>')
        groups = list(P.groups.values())
        if groups:
            copy = sum(1 for g in P.groups if P.group_state(g) == rz.G_COPY)
            nod = sorted({g['direction'] for k, g in P.groups.items() if P.group_state(k) == rz.G_NODISK})
            h.append(f'<p>Отмеченных папок (будущих заданий): {len(groups)}; есть что копировать: {copy}.'
                     + (f' Направления без диска (задание не создаётся): {esc(", ".join(nod))}.' if nod else '') + '</p>')
        if P.docs_near:
            h.append(f'<p style="color:{GRAY}">Документы рядом с фото и видео (поедут в «Семейный архив»): '
                     f'{num(sum(x[1] for x in P.docs_near))} в {num(len(P.docs_near))} папках.</p>')
        att = [x for x in rz.attention_lines(P) if not x.startswith(f'{P.disk} - диск направления')]
        if att:
            h.append('<p><b>Нужно внимание</b></p><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in att) + '</ul>')
        self.summary.setHtml(''.join(h))
        self.tasks_btn.setEnabled(not P.errors and not self.writing)

    # ---------- «Уже есть» ----------
    def run_have(self):
        if self.model is None:
            return
        if self.have_busy:
            self.have_pending = True
            return
        self.have_busy = True
        disks_ = self.direction_disks()
        snap = (self.disk, tuple(disks_))
        self.win.bg.run(safe, sv.razbor_have, self.disk, disks_, ok=lambda res, s=snap: self.got_have(s, res), quiet=True)

    def got_have(self, snap, res):
        self.have_busy = False
        kind, val = res
        if self.model is not None and snap[0] == self.disk and list(snap[1]) == self.direction_disks() and kind == 'ok':
            self.model.set_have(val, list(snap[1]))
            self.update_items()
        if self.have_pending or (self.model is not None and snap[0] != self.disk):
            self.have_pending = False
            self.run_have()

    # ---------- сохранение отметок ----------
    def set_writing(self, on):
        self.writing = on
        self.tree.setEnabled(not on)
        for w in (self.mode_all, self.mode_none, self.mode_dir, self.disk_box, self.apply_box):
            w.setEnabled(not on)
        self.update_buttons()

    def save(self, then=None):
        """Предпросмотр (service.marks_preview) -> окно «было → станет» -> «Записать» -> add_marks_batch одним пакетом.
        then() - после успешной записи (подготовка заданий)."""
        m = self.model
        if m is None or not m.drafts or self.writing:
            return
        rows, sent = m.batch()
        changes, conflicts, nested = m.change_lines()
        disk = self.disk
        self.set_writing(True)

        def shown(res):
            kind, val = res
            if kind != 'ok':
                self.set_writing(False)
                QMessageBox.warning(self, TITLE, 'Предпросмотр не получился, ничего не записано:\n\n' +
                                    (val if kind == 'refused' else val.strip().splitlines()[-1]))
                return
            h = [f'<p><b>{esc(val["lines"][0])}</b> Папок в списке: {len(rows)}.</p><p><b>Было → станет</b></p><ul>']
            h += [f'<li>{esc(x)}</li>' for x in changes]
            h.append('</ul><p><b>Что проверила программа</b></p><ul>')
            h += [f'<li>{esc(x)}</li>' for x in val['lines'][1:]]
            h.append('</ul>')
            if nested:
                h.append(f'<p style="color:{ORANGE}">Среди папок есть вложенные друг в друга: их размеры пересекаются, '
                         'складывать их нельзя. Действует отметка самой глубокой папки.</p>')
            if conflicts:
                h.append(f'<p style="color:{RED}"><b>Изменено в другом месте:</b></p><ul>' +
                         ''.join(f'<li>{esc(x)}</li>' for x in conflicts) + '</ul>')
            h.append(f'<p style="color:{GRAY}">Запись - одним пакетом в «решения.tsv» (копия таблицы до записи - в '
                     '«_БАЗА\\архив таблиц»). Файлы не копируются: это делают задания.</p>')
            dlg = TextDialog(self, 'Сохранить отметки', ''.join(h), ok_text='Записать')
            if dlg.exec() != QDialog.Accepted:
                self.set_writing(False)
                return
            self.win.bg.run(lambda: (safe(sv.add_marks_batch, disk, rows), safe(sv.razbor_tree, disk)),
                            ok=written, quiet=True)

        def written(res):
            (kind, val), (tkind, tree) = res
            self.set_writing(False)
            if disk != self.disk or self.model is None:
                return
            if tkind == 'ok':
                self.model.reload(tree)
                self.update_items()
                self.sync_mode()
                self.fill_choices()
            left = {k for k in sent if k in self.model.drafts}
            done = len(sent) - len(left)
            if kind == 'ok':
                self.win.statusBar().showMessage(f'Записано отметок: {len(val["fields"])}. Копия таблицы - в «_БАЗА\\'
                                                 'архив таблиц».', 8000)
            elif kind == 'refused':
                QMessageBox.warning(self, TITLE, f'Не записано: {val}\n\nНесохранённые отметки остались на экране.')
            else:
                sv_log(val)
                QMessageBox.warning(self, TITLE, 'Запись прервалась ошибкой. Я перечитал таблицу: сохранено '
                                    f'{done} из {len(sent)}, остальные остались несохранёнными.\n\n'
                                    'Подробно - в «_БАЗА\\ответы\\окно - ошибки.log».')
            self.changed(debounce=False)
            if kind == 'ok' and then:
                then()
        self.win.bg.run(safe, sv.marks_preview, disk, rows, ok=shown, quiet=True)

    # ---------- задания ----------
    def prepare(self):
        m = self.model
        if m is None or self.writing:
            return
        if m.drafts:
            if QMessageBox.question(self, TITLE, f'Есть несохранённые отметки ({len(m.drafts)}). Задания строятся только '
                                    'из сохранённых.\n\nСохранить отметки сейчас (сначала - предпросмотр)?') == QMessageBox.Yes:
                self.save(then=self.prepare)
            return
        disk = self.disk
        self.set_writing(True)
        self.sum_state.setText('Считаю задания по сохранённым отметкам…')
        self.win.bg.run(safe, tasks_dry, disk, ok=lambda res: self.show_tasks(disk, res), quiet=True)

    def show_tasks(self, disk, res, note=''):
        kind, val = res
        self.set_writing(False)
        self.sum_state.setText('')
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не посчитаны: ' + (val if kind == 'refused' else
                                                                       val.strip().splitlines()[-1]))
            return
        body, new = tasks_html(val, self.disk_name, note)
        dlg = TextDialog(self, f'Подготовить задания - {disk}', body,
                         ok_text=f'Создать задания ({len(new)})' if new else None, width=1000, height=640)
        if dlg.exec() != QDialog.Accepted or not new:
            return
        if QMessageBox.question(self, TITLE, f'Создать заданий: {len(new)} в «Запускаемые скрипты»?\n\nНичего не '
                                'копируется и не запускается: запускаете задания вы - в разделе «Задания».') != QMessageBox.Yes:
            return
        self.set_writing(True)
        self.win.bg.run(safe, tasks_create, disk, spec_keys(val['res']['specs']),
                        ok=lambda r: self.tasks_created(disk, r), quiet=True)

    def tasks_created(self, disk, res):
        self.set_writing(False)
        kind, val = res
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не созданы: ' + (val if kind == 'refused' else
                                                                     val.strip().splitlines()[-1]))
            return
        what, data = val
        if what == 'changed':                             # список изменился до создания - показать и спросить снова
            self.show_tasks(disk, ('ok', data), note='Пока вы смотрели, отметки или база изменились: список заданий '
                                                     'другой. Проверьте его и подтвердите ещё раз.')
            return
        specs = data['res']['specs']
        made = [s for s in specs if not s.get('exists')]
        diff = data.get('differs')
        msg = (f'Создано заданий: {len(made)}' + (f' (уже были подготовлены раньше: {len(specs) - len(made)})'
                                                   if len(specs) != len(made) else '') + '.')
        if diff:
            msg += '\n\nВНИМАНИЕ: созданный список отличается от подтверждённого (данные изменились в последний момент). ' \
                   'Проверьте задания в «Заданиях» перед запуском.'
        if QMessageBox.question(self, TITLE, msg + '\n\nПерейти в «Задания»?') == QMessageBox.Yes:
            self.win.open_page('Задания')

    # ---------- спорные файлы ----------
    def contested(self):
        if self.model is None:
            return
        fs = self.selected_folders()
        if len(fs) > 1:
            QMessageBox.information(self, TITLE, 'Выберите одну папку (или ни одной - тогда весь носитель).')
            return
        self._contested = ContestedDialog(self.win, self.disk, fs[0] if fs else '')
        self._contested.show()


def sv_log(text):
    try:
        import app
        app.log_error(text)
    except Exception:                                     # noqa: BLE001
        pass


def spec_keys(specs):
    """Что владелец подтверждает: имя, папка, направление, файлов, байт, диски (без признака «уже было»)."""
    return sorted((s['name'], str(s['folder']), s['num'], s['files'], s['bytes'], tuple(s['targets'])) for s in specs)


def tasks_dry(disk):
    res = sv.razbor_tasks(disk, dry=True)
    targets = sorted({d for s in res['specs'] for d in s['targets']})
    return dict(res=res, free=sv.free_space(targets), at=time.strftime('%H:%M:%S'))


def tasks_create(disk, shown):
    """Непосредственно перед созданием - снова пробный расчёт: если список другой, ничего не создаётся (владелец
    подтверждает новый). Затем создание (под замком таблиц, ядро) и сверка созданного с подтверждённым."""
    dry = tasks_dry(disk)
    if spec_keys(dry['res']['specs']) != shown:
        return 'changed', dry
    res = sv.razbor_tasks(disk, dry=False)
    return 'created', dict(res=res, differs=spec_keys(res['specs']) != shown)


def tasks_html(val, disk_name, note=''):
    """Окно «Подготовить задания»: таблица заданий, папки без диска, «копировать нечего», внимание. -> (html, новые)."""
    res, free, at = val['res'], val['free'], val['at']
    P, specs, states = res['plan'], res['specs'], res['states']
    new = [s for s in specs if not s.get('exists')]
    h = []
    if note:
        h.append(f'<p style="color:{RED}"><b>{esc(note)}</b></p>')
    if P.info.get('is_target'):
        names = ', '.join(P.dirs[n].name for n in P.info['is_target'])
        h.append(f'<p style="color:{ORANGE}"><b>{esc(P.disk)} — сам диск направления «{esc(names)}»:</b> копировать с '
                 'него на остальные диски можно, перемещать на нём ничего нельзя (после копирования «Переместить» '
                 'предложено не будет).</p>')
    if specs:
        h.append('<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                 '<tr><th align="left">Задание</th><th>Файлов</th><th>ГБ</th><th align="left">На диски</th></tr>')
        for s in specs:
            old = ' <span style="color:gray">(уже подготовлено раньше)</span>' if s.get('exists') else ''
            h.append(f'<tr><td>{esc(s["name"])}{old}</td><td align="right">{num(s["files"])}</td>'
                     f'<td align="right">{gb(s["bytes"])}</td><td>{esc(", ".join(disk_name(d) for d in s["targets"]))}'
                     '</td></tr>')
        h.append('</table>')
        per = collections.defaultdict(int)
        for s in new:
            for d in s['targets']:
                per[d] += sum(r[2] for r in s['rows'] if r[0] == d)
        if per:
            h.append('<p><b>Писать на диски (новые задания):</b></p><ul>')
            for d, b in sorted(per.items()):
                if d in free:
                    short = b / hb.GIB > free[d][1]
                    place = (f'свободно {gb(free[d][1] * hb.GIB)} ГБ ({esc(free[d][0])}) на {at}' +
                             (' — <b style="color:#c62828">НЕ ХВАТАЕТ МЕСТА</b>' if short else ''))
                else:
                    place = '<span style="color:gray">не подключён — место не проверено</span>'
                h.append(f'<li>{esc(disk_name(d))}: {gb(b)} ГБ; {place}</li>')
            h.append('</ul>')
    else:
        h.append('<p>Заданий копирования нет: копировать нечего (или у направлений нет дисков).</p>')
    nod = [g for g in states if g['state'] == rz.G_NODISK]
    if nod:
        h.append(f'<p>Без задания — направление без диска: {len(nod)} папок ('
                 f'{esc(", ".join(sorted({g["direction"] for g in nod})))}). Назначьте диск направлению.</p>')
    have = [g for g in states if g['state'] == rz.G_HAVE]
    if have:
        h.append(f'<p>Копировать нечего (всё уже есть на дисках направления): {len(have)} папок. Это ещё не разрешение '
                 'перемещать — его проверит перемещение по базе.</p>')
    att = [x for x in rz.attention_lines(P) if not x.startswith(f'{P.disk} - диск направления')]
    if att:
        h.append('<p><b>Нужно внимание</b></p><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in att) + '</ul>')
    if new:
        h.append(f'<p style="color:gray">Будет создано заданий: {len(new)} в «Запускаемые скрипты». Ничего не копируется '
                 'и не запускается; запуск - в разделе «Задания».</p>')
    elif specs:
        h.append('<p>Все задания уже подготовлены раньше - новых нет.</p>')
    return ''.join(h), new
