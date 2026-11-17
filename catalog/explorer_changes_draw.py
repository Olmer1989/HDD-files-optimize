"""Вкладка «Что изменилось на диске»: рисование дерева и папок без диска (примесь)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyle, QTreeWidgetItem

import explorer_diff as ed
import service as sv
from explorer_common import ROLE, GROUPS, RESCAN_HINT, num, checkable


class ChangesDrawMixin:
    """Методы рисования дерева изменений и папок без диска для ChangesTab (вынесено из explorer_page)."""

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
