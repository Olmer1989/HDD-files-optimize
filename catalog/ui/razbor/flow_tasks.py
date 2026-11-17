"""RazborPage, «Подготовить задания»: пробный расчёт, сверка оглавления, создание заданий в фоне.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time

from PySide6.QtWidgets import QDialog, QMessageBox

import disk_ui
import service as sv

from .common import TITLE, safe
from .dialogs import TextDialog
from .texts_tasks import tasks_html


def spec_keys(specs):
    """Что владелец подтверждает: имя, папка, направление, файлов, байт, диски (без признака «уже было»)."""
    return sorted((s['name'], str(s['folder']), s['num'], s['files'], s['bytes'], tuple(s['targets'])) for s in specs)


def tasks_check(disk, nums, toc=True):
    """Пробный расчёт заданий направлений nums по сохранённым отметкам, место по каждому диску (service.capacity),
    затем - по порядку, не параллельно - сверка оглавления носителя для новых заданий тех направлений, что помещаются.
    Направление, которому не хватает места хотя бы на одном диске, исключается целиком (ни на 45, ни на 77).
    -> dict(res, specs, new, short, cap, nums, at, toc)."""
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
    """Часть RazborPage («Подготовить задания»); атрибуты - у RazborPage."""

    def prepare(self, nums=None):
        """«Подготовить задания»: nums - направления (None - диск назначения; кнопка ячейки «Копировать на диск»).
        Сохранённые отметки -> пробный расчёт, место по каждому диску, сверка оглавления носителя (в фоне, по порядку)
        -> окно -> «Создать» -> снова пробный расчёт и место -> создание."""
        m = self.model
        if m is None or self.writing:
            return
        if nums is None:
            nums = [self.dest] if self.dest else []
            if not nums:
                QMessageBox.information(self, TITLE, 'Диска назначения нет: назначьте диск направлению в «Обзоре».')
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
        self.sum_state.setText('Считаю задания по сохранённым отметкам и сверяю оглавление носителя с описью…')
        self.win.bg.run(safe, tasks_check, disk, nums, ok=lambda res: self.show_tasks(disk, nums, res), quiet=True)

    def show_tasks(self, disk, nums, res, note=''):
        kind, val = res
        self.set_writing(False)
        self.sum_state.setText('')
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не посчитаны: ' + (val if kind == 'refused' else
                                                                       val.strip().splitlines()[-1]))
            return
        if val.get('nohash'):
            QMessageBox.warning(self, TITLE, f'У {val["nohash"]} файлов, которые пойдут на диск, нет хеша (SHA-256). '
                                'Задания не создаются: сначала «Отсканировать эти папки» в ячейке «Копировать на диск».')
            return
        body, new = tasks_html(val, self.disk_name, note)
        toc = val.get('toc')
        blocked = toc is not None and (not toc['connected'] or toc['problems'])
        extra = None
        if blocked and toc['connected']:
            sub = [p['folder'] for p in toc['problems'] if p['folder'] is not None]
            if sub:
                extra = (f'Пересканировать эти папки ({len(sub)})…', lambda: self.rescan(disk, sub))
        self.last_tasks = val
        dlg = TextDialog(self, f'Подготовить задания - {disk}', body,
                         ok_text=f'Создать задания ({len(new)})' if new and not blocked else None, width=1000, height=640,
                         extra=extra)
        if dlg.exec() != QDialog.Accepted or not new or blocked:
            return
        if QMessageBox.question(self, TITLE, f'Создать заданий: {len(new)} в «Запускаемые скрипты»?\n\nНичего не '
                                'копируется и не запускается: запускаете задания вы - в разделе «Задания на копирование».') != QMessageBox.Yes:
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
        specs = data['res']['specs']
        made = [s for s in specs if not s.get('exists')]
        diff = data.get('differs')
        msg = (f'Создано заданий: {len(made)}' + (f' (уже были подготовлены раньше: {len(specs) - len(made)})'
                                                   if len(specs) != len(made) else '') + '.')
        if diff:
            msg += '\n\nВНИМАНИЕ: созданный список отличается от подтверждённого (данные изменились в последний момент). ' \
                   'Проверьте их в «Заданиях на копирование» перед запуском.'
        if QMessageBox.question(self, TITLE, msg + '\n\nПерейти в «Задания на копирование»?') == QMessageBox.Yes:
            self.win.open_page(disk_ui.TASKS_PAGE)
