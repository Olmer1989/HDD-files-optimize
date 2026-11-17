"""RazborPage, блок «Выберите носитель»: список носителей, чтение дерева в фоне, сведения о носителе.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time

from hb_core import api as hb

import disk_ui
import service as sv

from .common import safe
from .model import Model
from .texts_cell import GREEN, ORANGE, RED, esc, files_word, gb, num


class CarrierView:
    """Часть RazborPage (блок «Выберите носитель»); атрибуты - у RazborPage."""

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
        if (m is not None and self.loading is None and not self.writing and not self.saving
                and (gen != m.built or sig != m.sig)):          # во время автосохранения - перечитает он сам
            self.load_disk(self.disk, keep=True)

    def disk_changed(self, _i=None):
        new = self.disk_box.value()
        if not new or new == self.disk:
            return
        if not self.flush_now(f'Перейти к {new} без сохранения? Они пропадут.'):
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
        self.fill_dest()
        need = self.direction_disks()
        if old_have and old_have[0] is not None and old_have[1] == need:
            self.model.set_have(*old_have)                 # прежние цифры видны, пока считаются новые
            self.update_items()
        if gen_changed or not old_have or old_have[1] != need:
            self.run_have()
        self.changed(debounce=False)                      # и «без хеша» (17.11.2026) - по новому итогу

    def direction_disks(self):
        m = self.model
        return sorted({d for x in m.dirs.values() for d in x.disks}) if m else []

    def show_disk_info(self):
        """Строка под полем носителя (макет): плашка «подключён (F:)» / «не подключён» · опись от …, полная · файлов, ГБ."""
        m = self.model
        row = next((r for r in self.disk_rows if r['disk'] == self.disk), {'disk': self.disk, 'label': m.tree['label']})
        sc = m.tree.get('scanned')
        st = disk_ui.status_text(m.tree.get('status'))
        files, size = m.folders.get('', (0, 0, None, None))[:2]
        if row.get('letter'):
            pill = (f'<span style="background:#c8e6c9; color:{GREEN}"><b>&nbsp;подключён ({esc(row["letter"])})&nbsp;</b>'
                    '</span>')
        else:
            pill = f'<span style="background:#ffe0b2; color:{ORANGE}"><b>&nbsp;не подключён&nbsp;</b></span>'
        bits = [(f'опись от {time.strftime("%d.%m.%Y", time.localtime(sc))}' if sc else 'дата описи неизвестна')
                + f', {st}', f'{files_word(files)}, {gb(size)} ГБ']
        if m.tree.get('issues'):
            bits.append(f'непрочитанных мест: {num(m.tree["issues"])}')
        self.info.setText(pill + ' &nbsp;· ' + esc(' · '.join(bits)))
        d = hb.direction_of_disk(m.dirs, self.disk)
        if d:
            self.banner.setText(f'{self.disk} — сам диск направления «{d.name}» ({hb.disk_nums(d.disks)}): копировать с '
                                f'него на остальные диски направления можно, перемещать на нём ничего нельзя.')
            self.banner.show()
        else:
            self.banner.hide()
