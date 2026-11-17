"""RazborPage, блок «диск назначения и режим» (этапы 8, 10): плашка, три режима, список дисков.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFontMetrics, QTextDocument
from PySide6.QtWidgets import QComboBox, QSizePolicy, QStyle, QStyleOptionComboBox, QStylePainter, QStyledItemDelegate

from hb_core import api as hb
from hb_core import razbor as rz
from hb_core.directions import R_DIR

import directions_page

from .common import INHERIT, MODE_TEXT, SKIP
from .texts_cell import EVERY, EXCEPT, GRAY, ONLY, ORANGE, esc, files_word, folders_word, gb
from .texts_head import MODE_NOTE, dest_html, dest_info_html, dest_text, head_html


class HtmlDelegate(QStyledItemDelegate):
    """Пункт выпадающего списка «Диск назначения» с HTML (имя направления оранжевым)."""

    def paint(self, painter, option, index):
        html_ = index.data(Qt.UserRole + 5)
        if not html_:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        option.text = ''
        st = option.widget.style() if option.widget else None
        if st:
            st.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(option.font)
        doc.setHtml(html_)
        painter.save()
        painter.translate(option.rect.left() + 6, option.rect.top() + (option.rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter, QRectF(0, 0, option.rect.width() - 8, option.rect.height()))
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), QFontMetrics(option.font).height() + 14))   # строки списка - выше


class RichCombo(QComboBox):
    """Выпадающий список, у которого и пункты, и закрытое поле рисуются HTML (Qt.UserRole + 5); текст пункта - простой
    (для поиска и тестов)."""

    def __init__(self):
        super().__init__()
        self.setItemDelegate(HtmlDelegate(self))
        self.setMinimumHeight(QFontMetrics(self.font()).height() + 16)    # поле выше: низ текста не обрезается
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)      # во всю ширину столбца полей

    def add(self, text, html_, data):
        self.addItem(text, data)
        self.setItemData(self.count() - 1, html_, Qt.UserRole + 5)
        need = max(self.html_width(self.itemData(i, Qt.UserRole + 5)) for i in range(self.count())) + 40
        self.view().setMinimumWidth(need)            # выпадающий список - во всю ширину самого длинного пункта
        self.setMinimumWidth(min(need + 30, 520))    # закрытое поле растягивается; «…» только если окно очень узкое

    def html_width(self, html_):
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.font())
        doc.setHtml(html_ or '')
        return int(doc.idealWidth()) + 8

    def current_html(self):
        return self.itemData(self.currentIndex(), Qt.UserRole + 5) if self.currentIndex() >= 0 else ''

    def paintEvent(self, e):                                  # noqa: N802
        html_ = self.current_html()
        if not html_:
            return super().paintEvent(e)
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ''
        p.drawComplexControl(QStyle.CC_ComboBox, opt)
        r = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.font())
        doc.setHtml(html_ if self.isEnabled() else f'<span style="color:{GRAY}">{esc(self.currentText())}</span>')
        if doc.idealWidth() > r.width() - 4:          # не влезает - одной строкой с «…» (весь текст - в подсказке)
            text = QFontMetrics(self.font()).elidedText(self.currentText(), Qt.ElideRight, r.width() - 6)
            doc.setHtml(f'<span style="color:{"#000" if self.isEnabled() else GRAY}">{esc(text)}</span>')
        self.setToolTip(self.currentText())
        p.save()
        p.setClipRect(r)
        p.translate(r.left() + 4, r.top() + (r.height() - doc.size().height()) / 2)
        doc.drawContents(p, QRectF(0, 0, r.width(), r.height()))
        p.restore()


class HeadView:
    """Часть RazborPage (блок «диск назначения и режим» (этапы 8, 10)); атрибуты - у RazborPage."""

    def preferred(self):
        """Направления, отмеченные галочкой в «Обзоре» (directions_page.chosen: есть сейчас и с диском), по номеру."""
        if self.model is None:
            return []
        return sorted(directions_page.chosen(self.model.dirs), key=lambda d: hb.num_key(d.num))

    def dest_dirs(self):
        """Направления, у которых есть диск, по номеру: только они могут быть диском назначения."""
        if self.model is None:
            return []
        return sorted((d for d in self.model.dirs.values() if d.disks), key=lambda d: hb.num_key(d.num))

    def default_dest(self):
        """Первое по номеру направление из «Обзора»; иначе направление отметки всего носителя (если у него есть диск);
        иначе первое с диском."""
        pref = self.preferred()
        if pref:
            return pref[0].num
        r = self.model.route.get('', rz.NONE_ROUTE)
        dd = self.dest_dirs()
        if r.state == R_DIR and any(d.num == r.num for d in dd):
            return r.num
        return dd[0].num if dd else None

    def use_choice(self):
        """Переход из «Обзора» («Перейти к написанию команды…»): диск назначения - первое по номеру отмеченное
        направление (отметки носителя не меняются)."""
        self.want_choice = True
        if self.model is not None:
            self.fill_dest()

    def fill_dest(self):
        """Список «Диск назначения»; выбор сохраняется, если такое направление ещё есть."""
        dd = self.dest_dirs()
        nums = [d.num for d in dd]
        if self.want_choice or self.dest not in nums:
            self.dest = self.default_dest()
        self.want_choice = False
        self.dest_box.blockSignals(True)
        self.dest_box.clear()
        for d in dd:
            self.dest_box.add(dest_text(d, self.disk_rows), dest_html(d, self.disk_rows), d.num)
        if self.dest in nums:
            self.dest_box.setCurrentIndex(nums.index(self.dest))
        self.dest_box.blockSignals(False)
        self.sync_mode()
        self.update_items()

    def dest_changed(self, _i=None):
        v = self.dest_box.currentData()
        if v and v != self.dest:
            self.dest = v
            self.sync_mode()
            self.update_items()
            self.show_head()

    def set_dest(self, num_):
        """Выбрать диск назначения (для тестов и перехода)."""
        i = self.dest_box.findData(num_)
        if i >= 0:
            self.dest_box.setCurrentIndex(i)
            self.dest_changed()

    def dest_dir(self):
        return self.model.dirs.get(self.dest) if self.model is not None and self.dest else None

    def root_is_dest(self):
        m = self.model
        return m is not None and self.dest is not None and m.is_dir(m.route.get('', rz.NONE_ROUTE), self.dest)

    def mode(self):
        """Режим из отметки всего носителя: корень ≠ D - «Только выбранные»; корень = D - выбор владельца в окне
        («Все папки» / «Все, кроме выбранных»), без выбора: есть свои исключения - «Все, кроме», иначе «Все папки»."""
        if not self.root_is_dest():
            return ONLY
        pref = self.mode_pref.get((self.disk, self.dest))
        if pref in (EVERY, EXCEPT):
            return pref
        return EXCEPT if self.model.own_skips() else EVERY

    def show_head(self):
        space = self.plan[1] if self.plan else None
        d = self.dest_dir()
        others = [x for x in self.preferred() if d is None or x.num != d.num]
        self.where.setText(head_html(d, self.disk_rows, space, others))
        self.dest_info.setText(dest_info_html(d, self.disk_rows, space))
        m = self.model
        r = m.route.get('', rz.NONE_ROUTE) if m else rz.NONE_ROUTE
        mode = self.mode() if (m is not None and self.dest) else ONLY
        note = MODE_NOTE[mode]
        if m is not None and self.dest and mode == ONLY and r.state == R_DIR and r.num in m.dirs:
            rest = m.dirs[r.num]
            amount = ''
            if self.plan:
                v = [self.plan[0].part_a.get((o, rest.num), (0, 0)) for o in (rz.O_COPY, rz.O_HAVE)]
                amount = f' ({files_word(v[0][0] + v[1][0])}, {gb(v[0][1] + v[1][1])} ГБ)'
            note += (f' <span style="color:{ORANGE}">Весь носитель отмечен «Всё — в {esc(rest.label())}»: папки без '
                     f'галочки идут туда{amount}. «{MODE_TEXT[EVERY]}» или «{MODE_TEXT[EXCEPT]}» заменят эту отметку.'
                     '</span>')
        self.mode_note.setText(note)

    def sync_mode(self):
        """Кнопки режимов - по действующей (с черновиком) отметке всего носителя. Режим выбран всегда: без диска
        назначения кнопки неактивны, но «Только выбранные папки» подсвечена."""
        m = self.model
        if m is None:
            return
        mode = self.mode() if self.dest else ONLY
        for w in self.mode_btn.values():
            w.blockSignals(True)
        for k, w in self.mode_btn.items():
            w.setChecked(k == mode)
            w.setEnabled(bool(self.dest) and not self.writing)
        for w in self.mode_btn.values():
            w.blockSignals(False)
        self.mode_hint.setText('• сохраняется…' if '' in m.drafts else '')
        self.show_head()

    def mode_changed(self, k):
        m, d = self.model, self.dest_dir()
        if m is None or d is None or self.writing:
            return
        key = (self.disk, d.num)
        pairs, msg = [], ''
        if k == ONLY:
            self.mode_pref.pop(key, None)
            before = self.root_before.pop(key, None)      # этап 16: отметка носителя до «Все папки» (уже сохранена)
            if self.root_is_dest():
                saved = m.saved_ms.by_key.get('')
                if before not in (None, INHERIT) and hb.parse_verdict(before, m.dirs)[:2] != (R_DIR, d.num):
                    pairs = [('', before)]
                elif saved is not None and not m.is_dir(m.route_saved.get(''), d.num):
                    pairs = [('', saved.verdict)]        # вернуть сохранённую отметку всего носителя
                else:
                    pairs = [('', SKIP)]
        else:
            self.mode_pref[key] = k
            if not self.root_is_dest():
                self.root_before[key] = m.own_verdict('')
                pairs.append(('', d.verdict()))
            skips = m.own_skips()
            if k == EVERY and skips:
                drop = m.skips_back_to(d.num, dict((m.orig(f).lower(), v) for f, v in pairs))
                pairs += [(f, INHERIT) for f in drop]
                if drop:
                    msg = (f'«{MODE_TEXT[EVERY]}»: сняты исключения у {folders_word(len(drop))} («Отменить последнее» '
                           'вернёт). Исключения внутри папок других дисков не тронуты.')
            elif k == EXCEPT and skips and pairs:
                msg = (f'Исключения ({folders_word(len(skips))}) действуют и для этого диска — у них галочка. Снимите '
                       'галочку, если папку тоже нужно копировать.')
        if pairs and m.set_marks(pairs):
            self.after_marks()
        else:
            self.sync_mode()
            self.update_items()
        if msg:
            self.win.statusBar().showMessage(msg, 10000)

    def after_marks(self):
        self.save_failed = False                          # новая правка владельца - снова пробуем записать
        self.update_items()
        self.sync_mode()
        self.changed()
        self.marks_changed.emit(self.rev)                 # этап 17: окно «Список файлов» обновляет галочки

    def set_in_dest(self, folders, on):
        """Окно «Список файлов» (этап 17): папки - в диск назначения (on) или не копировать, независимо от режима
        страницы; тот же черновик, отмена и автосохранение. -> число изменённых записей черновика."""
        m = self.model
        if m is None or self.writing or self.saving or not self.dest:
            return 0
        ok = [f for f in folders if f and m.markable(f)]
        pairs = m.include_pairs(ok, self.dest) if on else m.exclude_pairs(ok, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        if n:
            self.after_marks()
        return n
