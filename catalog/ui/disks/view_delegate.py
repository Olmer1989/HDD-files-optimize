"""«Диски и папки»: FolderDelegate - рисует полоску состава под именем папки и плашку «Решение владельца».

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from .texts_tree import DEC_COLORS, TYPE_COLORS
from .common import MARK_ROLE, TYPES_ROLE, T_DEC, T_NAME


class FolderDelegate(QStyledItemDelegate):
    """Колонка «Папка» - тонкая цветная полоска состава под именем; «Решение владельца» - плашка."""
    BAR = 4

    def paint(self, painter, option, index):
        if index.column() == T_DEC:
            mark = index.data(MARK_ROLE)
            if mark and mark.get('text'):
                self.initStyleOption(option, index)
                option.text = ''
                st = option.widget.style() if option.widget else None
                if st:
                    st.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
                bg, fg, border = DEC_COLORS.get(mark['kind'], DEC_COLORS['unset'])
                f = QFont(option.font)
                fm = QFontMetrics(f)
                text = mark['text'] + ('' if mark.get('own') else ' ↑')
                w = min(fm.horizontalAdvance(text) + 16, option.rect.width() - 6)
                r = QRectF(option.rect.left() + 3, option.rect.center().y() - fm.height() / 2 - 2, w, fm.height() + 4)
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                c = QColor(bg)
                if not mark.get('own'):
                    c = c.lighter(104)
                painter.setBrush(c)
                painter.setPen(QColor(border))
                painter.drawRoundedRect(r, 8, 8)
                painter.setPen(QColor(fg))
                painter.setFont(f)
                painter.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                                 fm.elidedText(text, Qt.ElideRight, int(r.width() - 12)))
                painter.restore()
                return
            return super().paint(painter, option, index)
        super().paint(painter, option, index)
        if index.column() != T_NAME:
            return
        types = index.data(TYPES_ROLE)
        total = sum(types) if types else 0
        if not total:
            return
        st = option.widget.style() if option.widget else None
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        tr = st.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget) if st else opt.rect
        x0, width = tr.left() + 2, max(20, min(tr.width() - 8, 260))
        y = option.rect.bottom() - self.BAR - 2
        painter.save()
        x = float(x0)
        for v, color in zip(types, TYPE_COLORS):
            w = width * v / total
            if w > 0:
                painter.fillRect(QRectF(x, y, max(w, 1.0), self.BAR), QColor(color))
            x += w
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        return QSize(s.width() + (30 if index.column() == T_DEC else 0), max(s.height() + self.BAR + 6, 28))
