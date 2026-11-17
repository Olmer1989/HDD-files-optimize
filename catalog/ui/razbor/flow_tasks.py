"""RazborPage, «Начать копирование…»: пробный расчёт, сверка оглавления, окно подтверждения, создание заданий в фоне и
запуск всего набора через «Задания на копирование».

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md).
18.11.2026 (решение владельца): кнопка «Начать копирование…» вместо «Подготовить задания…»; окно StartDialog вместо
TextDialog и вопроса «Создать заданий…?»; после подтверждения - новые задания создаются (уже созданные не дублируются),
затем ВСЕ задания набора (новые и ждущие / прерванные) запускаются по очереди (TasksPage.launch, её проверки те же)."""
import time

from PySide6.QtWidgets import QDialog, QMessageBox

import disk_ui
import service as sv

from directions_look import show_num
from ui.tasks.model_load import load_all, tasks_info

from .common import TITLE, safe
from .dialog_start import StartDialog
from .texts_head import short_place
from .texts_start import WAIT, start_html, start_mode


def spec_keys(specs):
    """Что владелец подтверждает: имя, папка, направление, файлов, байт, диски (без признака «уже было»)."""
    return sorted((s['name'], str(s['folder']), s['num'], s['files'], s['bytes'], tuple(s['targets'])) for s in specs)


def tasks_check(disk, nums, toc=True):
    """Пробный расчёт заданий направлений nums по сохранённым отметкам, место по каждому диску (service.capacity),
    затем - по порядку, не параллельно - сверка оглавления носителя для новых заданий тех направлений, что помещаются.
    Направление, которому не хватает места хотя бы на одном диске, исключается целиком (ни на 45, ни на 77).
    -> dict(res, specs, new, short, cap, nums, at, toc, nohash, states, speed)."""
    nums = list(nums)
    res = sv.razbor_tasks(disk, dry=True, only=nums)
    P = res['plan']
    dd = sorted(set(P.part_b) | {x for n in nums if n in P.dirs for x in P.dirs[n].disks})
    cap = sv.capacity(P.part_b, sv.disk_space(dd), sv.queued_copy(disk), disks=dd)
    short = [n for n in sv.short_directions(P.dirs, cap) if n in nums]
    specs = [s for s in res['specs'] if s['num'] not in short]
    new = [s for s in specs if not s.get('exists')]
    out = dict(res=res, specs=specs, new=new, short=short, cap=cap, nums=nums, at=time.strftime('%H:%M:%S'), toc=None)
    # 17.11.2026 (решение владельца): SHA-256 у всех копируемых - последняя проверка по тем же строкам заданий
    out['nohash'] = len({r[1] for s in new for r in s['rows'] if r[3] == 'без хеша'})
    # 18.11.2026: состояния уже созданных заданий набора и скорость прошлых копирований на их диски (окно подтверждения)
    out['states'], out['speed'] = tasks_info([s['name'] for s in specs if s.get('exists')],
                                             sorted({x for s in specs for x in s['targets']}))
    if toc and new:
        folders, root, zones = sv.toc_targets(P, new)
        out['toc'] = sv.toc_check(disk, folders, root, zones)
    return out


def tasks_dry(disk, nums=None):
    """Пробный расчёт без сверки оглавления (nums None - все направления)."""
    if nums is None:
        nums = list(sv.directions())
    return tasks_check(disk, nums, toc=False)


def tasks_create(disk, nums, shown):
    """Непосредственно перед созданием - снова пробный расчёт и место: если список другой, ничего не создаётся
    (показывается новый, со свежей сверкой оглавления). Затем создание только для помещающихся направлений (под замком
    таблиц, ядро) и сверка созданного с подтверждённым."""
    dry = tasks_dry(disk, nums)
    if spec_keys(dry['specs']) != shown:
        return 'changed', tasks_check(disk, nums)
    allowed = [n for n in nums if n not in dry['short']]
    if not allowed:
        return 'changed', tasks_check(disk, nums)
    if dry['new']:                       # носитель мог измениться, пока владелец читал окно: сверка ещё раз
        folders, root, zones = sv.toc_targets(dry['res']['plan'], dry['new'])
        toc = sv.toc_check(disk, folders, root, zones)
        if not toc['connected'] or toc['problems']:
            dry['toc'] = toc
            return 'changed', dry
    res = sv.razbor_tasks(disk, dry=False, only=allowed)
    return 'created', dict(res=res, differs=spec_keys(res['specs']) != shown)


class TasksFlow:
    """Часть RazborPage («Начать копирование…»); атрибуты - у RazborPage."""

    def prepare(self, nums=None):
        """«Начать копирование…»: nums - направления (None - диск назначения; кнопка ячейки «Копировать на диск»).
        Сохранённые отметки -> пробный расчёт, место по каждому диску, сверка оглавления носителя (в фоне, по порядку)
        -> окно подтверждения -> снова пробный расчёт и место -> создание новых -> запуск всего набора."""
        m = self.model
        if m is None or self.writing:
            return
        if nums is None:
            nums = [self.dest] if self.dest else []
            if not nums:
                QMessageBox.information(self, TITLE, 'Диска назначения нет: назначьте диск направлению на вкладке «Назначить Архивный диск».')
                return
        nums = list(nums)
        if m.drafts or self.saving:                       # этап 16: задания - из сохранённых; сначала дописать отметки
            self.save_then.append(lambda: self.prepare(nums))
            if not self.saving:
                self.save_timer.stop()
                self.autosave()
            return
        disk = self.disk
        self.set_writing(True)
        self.sum_state.setText('Считаю, что копировать, по сохранённым отметкам и сверяю оглавление носителя с описью…')
        self.win.bg.run(safe, tasks_check, disk, nums, ok=lambda res: self.show_tasks(disk, nums, res), quiet=True)

    def disk_label(self, x):
        """«H:» - буква подключённого диска, иначе его номер («HDD45»)."""
        return next((r.get('letter') for r in self.disk_rows if r['disk'] == x), None) or x

    def start_title(self, disk, val):
        """«Начать копирование: HDD09 → H: Бэкап фото и видео (А1)»."""
        P = val['res']['plan']
        by = {r['disk']: r for r in self.disk_rows}
        parts = [' и '.join(short_place(by.get(x), x) for x in P.dirs[n].disks if x != disk) + f' ({show_num(n)})'
                 for n in val['nums'] if n in P.dirs and n not in val['short'] and P.dirs[n].disks]
        return f'Начать копирование: {disk} → ' + ('; '.join(parts) or 'диск назначения')

    def show_tasks(self, disk, nums, res, note=''):
        kind, val = res
        self.set_writing(False)
        self.sum_state.setText('')
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Не посчитано, что копировать: ' + (val if kind == 'refused' else
                                                                               val.strip().splitlines()[-1]))
            return
        if val.get('nohash'):
            QMessageBox.warning(self, TITLE, f'У {val["nohash"]} файлов, которые пойдут на диск, нет хеша (SHA-256). '
                                'Копирование не начинается: сначала «Посчитать хеш» в ячейке «Копировать на диск».')
            return
        toc = val.get('toc')
        extra = None
        if toc is not None and toc['connected'] and toc['problems']:
            sub = [p['folder'] for p in toc['problems'] if p['folder'] is not None]
            if sub:
                extra = (f'Пересканировать эти папки ({len(sub)})…', lambda: self.rescan(disk, sub))
        self.last_tasks = val
        mode = start_mode(val)
        dlg = StartDialog(self, self.start_title(disk, val), start_html(val, self.disk_label, note), mode, extra=extra)
        if dlg.exec() != QDialog.Accepted:
            return
        if mode == 'running':
            self.win.open_page(disk_ui.TASKS_PAGE)
            return
        if mode != 'start':
            return
        if not val['new']:                                # все задания набора уже созданы - только запуск
            self.start_set([s['name'] for s in val['specs']])
            return
        self.set_writing(True)
        self.win.bg.run(safe, tasks_create, disk, nums, spec_keys(val['specs']),
                        ok=lambda r: self.tasks_created(disk, nums, r), quiet=True)

    def rescan(self, disk, folders, cats=None):
        """Готовое окно «Пересканировать папки» (Диски и папки) с папками, где сверка нашла расхождения (или с папками
        файлов без хеша - тогда cats: галочки только этих типов)."""
        import rescan_dialog
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders, cats=cats)
        self.win.rescan.finished.connect(lambda *_: self.refresh())     # новая опись - дерево и итог заново
        self.win.rescan.show()

    def tasks_created(self, disk, nums, res):
        self.set_writing(False)
        kind, val = res
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не созданы: ' + (val if kind == 'refused' else
                                                                     val.strip().splitlines()[-1]))
            return
        what, data = val
        if what == 'changed':                             # список изменился до создания - показать и спросить снова
            self.show_tasks(disk, nums, ('ok', data), note='Пока вы смотрели, отметки, база, место на дисках или '
                                                           'сам носитель изменились: проверьте окно ещё раз.')
            return
        if data.get('differs'):                           # данные изменились в последний миг - не запускать вслепую
            QMessageBox.warning(self, TITLE, 'Задания созданы, но список отличается от подтверждённого (данные '
                                'изменились в последний момент). Копирование не запущено: проверьте задания в «3. '
                                'Копирование» и запустите их там.')
            self.win.open_page(disk_ui.TASKS_PAGE)
            return
        self.start_set([s['name'] for s in data['res']['specs']])

    def start_set(self, names):
        """Запуск набора names через «Задания на копирование»: свежий список заданий (в фоне), затем ждущие и прерванные
        задания набора - TasksPage.launch (по очереди, без второго вопроса; её проверки «уже идёт», «перемещение с того
        же носителя» - те же); открыть «3. Копирование»."""
        self.sum_state.setText('Запускаю копирование…')
        self.win.bg.run(load_all, ok=lambda res: self.launch_set(set(names), res))

    def launch_set(self, names, res):
        self.sum_state.setText('')
        tp = self.win.page(disk_ui.TASKS_PAGE)
        tp.render(*res)
        sel = [r for r in tp.rows if r['task'] in names and r['state'] in WAIT]
        self.win.open_page(disk_ui.TASKS_PAGE)
        if not sel:
            QMessageBox.information(self, TITLE, 'Запускать нечего: задания этого набора уже идут или готовы.')
            return
        tp.launch(sel, sequential=True, confirmed=True)
