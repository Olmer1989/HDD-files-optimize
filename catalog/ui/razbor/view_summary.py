"""RazborPage, блок «итог» и «Уже есть»: расчёт в фоне, вкладка «Подробно».

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time

from hb_core import razbor as rz

import disk_ui
import service as sv

from .common import safe
from .texts_cell import GRAY, GREEN, RED, esc, gb, num


class SummaryView:
    """Часть RazborPage (блок «итог» и «Уже есть»); атрибуты - у RazborPage."""

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
            dd = sorted(set(P.part_b) | {x for d in P.dirs.values() for x in d.disks})
            return P, sv.disk_space(dd), sv.queued_copy(disk), time.strftime('%H:%M:%S')
        self.win.bg.run(safe, job, self.disk, drafts, ok=lambda res, s=snap: self.got_summary(s, res), quiet=True)

    def got_summary(self, snap, res):
        self.sum_busy = False
        if snap[0] == self.disk and snap[1] == self.rev:
            kind, val = res
            if kind == 'ok':
                self.plan, self.plan_rev = val, snap[1]
                self.render_summary(*val)
                self.render_cells()
                self.show_head()
                self.sum_state.setText(f'<span style="color:{GRAY}">Посчитано в {val[3]}.</span>')
                self.sum_state.setToolTip('Отметки сохраняются сразу; задания строятся из сохранённых.')
                self.show_busy(False)
            else:
                self.show_busy(False)
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

    def render_summary(self, P, space, queued, at):
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
            cap = sv.capacity(P.part_b, space, queued)
            for d, (n, b) in sorted(P.part_b.items()):
                x = cap[d]
                if d in space:
                    short = x['state'] == 'short'
                    place = (f'<span style="color:{RED if short else GREEN}">{gb(x["free"])} ГБ ({esc(x["letter"])})'
                             + (f' — НЕ ПОМЕЩАЕТСЯ: нужно {gb(x["need"] + x["reserve"])} ГБ с запасом' if short else '')
                             + '</span>')
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
