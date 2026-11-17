"""RazborPage, запись отметок (этап 16): автосохранение пакетом, запись перед закрытием (CloseGuard).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import traceback

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QMessageBox

import service as sv

from .common import AUTOSAVE_MS, FLUSH_WAIT_MS, TITLE, safe, sv_log


class CloseGuard(QObject):
    """Фильтр событий ГЛАВНОГО окна: перед закрытием несохранённые отметки записываются (этап 16); не записались -
    закрытие только с согласия; во время создания заданий - нельзя."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, obj, ev):                          # noqa: N802
        if ev.type() != QEvent.Close:
            return False
        p = self.page
        if p.writing:
            QMessageBox.information(p.win, TITLE, 'Идёт создание заданий («Разбор носителя»). Дождитесь окончания.')
            ev.ignore()
            return True
        if not p.flush_now('Закрыть окно без сохранения? Они пропадут.'):   # этап 16: отметки дописываются сразу
            ev.ignore()
            return True
        return False


class AutosaveFlow:
    """Часть RazborPage (запись отметок (этап 16)); атрибуты - у RazborPage."""

    def set_writing(self, on):
        self.writing = on
        self.tree.setEnabled(not on)
        self.disk_box.setEnabled(not on)
        self.update_buttons()
        if self.model is not None:
            self.sync_mode()

    def save(self, then=None):
        """Прежнее имя (тесты, переходы): записать черновик сейчас (автосохранение, этап 16)."""
        if then:
            self.save_then.append(then)
        self.save_timer.stop()
        self.autosave()

    def schedule_save(self):
        """Правка отметок -> запись сразу (на следующем шаге цикла событий: правки одного щелчка - одним пакетом).
        После ошибки записи (не отказа по правилам) черновик ждёт следующей правки владельца или закрытия окна - без
        повторов по кругу."""
        if self.model is not None and self.model.drafts and not self.saving and not self.save_failed:
            self.save_timer.start(AUTOSAVE_MS)

    def autosave(self):
        """Автосохранение (этап 16, решение владельца: «Сохранить отметки» убрать): черновик -> service.add_marks_batch
        (те же проверки и одна запись под замком, без окна предпросмотра). Пока пакет пишется, он считается сохранённым
        (Model.inflight): правки во время записи остаются черновиком и пишутся следующим пакетом. Этап 17 (критики по
        коду): записан - пакет уходит из черновика (даже если перечитка упала); отказ по правилам - пакет забывается
        (повторять бесполезно), сообщение; ошибка записи - черновик ОСТАЁТСЯ, сообщение, запись - при следующей правке
        или закрытии окна. Ответ задачи хранится в save_job: flush_now ждёт только эту запись и принимает её ответ сам."""
        m = self.model
        if m is None or self.saving:
            return
        if not m.drafts:
            self.run_then()
            return
        rows, sent = m.batch()
        disk = self.disk
        m.inflight = dict(sent)
        self.saving = True
        self.saving_changed.emit(True)
        self.update_buttons()
        self.win.statusBar().showMessage(f'Сохраняю отметки ({len(rows)})…', 4000)
        import threading
        job = dict(done=threading.Event(), res=None, handled=False)

        def written(res):
            if job['handled']:
                return                                    # ответ уже принял flush_now
            job['handled'] = True
            (kind, val), (tkind, tree) = res
            self.saving = False
            self.save_job = None
            self.saving_changed.emit(False)
            if self.model is not m or disk != self.disk:
                m.inflight = {}
                return
            if kind == 'ok' or kind == 'refused':         # записан - сохранён; отказ по правилам - забыт
                for k, v in sent.items():
                    if k in m.drafts and m.drafts[k]['verdict'] == v:
                        del m.drafts[k]
            else:
                m.inflight = {}                           # ошибка записи: таблица не менялась, черновик остаётся
                self.save_failed = True
            if kind != 'ok':
                self.save_then = []
            if tkind == 'ok':
                m.inflight = {}
                m.reload(tree)
                self.fill_dest()
            else:
                # перечитка не удалась: записанный пакет считается сохранённым (inflight - основа сравнения до новой
                # перечитки, повторной записи нет); дерево перечитывается заново, без записи
                if kind != 'ok':
                    m.inflight = {}
                sv_log(tree)
                m.recalc()
                QTimer.singleShot(0, lambda: self.disk == disk and self.load_disk(disk, keep=True))
            if kind == 'ok':
                self.save_failed = False
                self.win.statusBar().showMessage(f'Отметки сохранены ({len(val["fields"])}). «Отменить последнее» — '
                                                 'вернуть.', 6000)
            elif kind == 'refused':
                QMessageBox.warning(self, TITLE, f'Отметка не сохранена: {val}\n\nНа экране — отметки, какие сохранены.')
            else:
                sv_log(val)
                QMessageBox.warning(self, TITLE, 'Отметки не записались: ' + val.strip().splitlines()[-1] +
                                    '\n\nОни остались на экране несохранёнными (с «•») и запишутся при следующей '
                                    'отметке или при закрытии окна.')
            self.update_items()
            self.sync_mode()
            self.changed(debounce=False)                  # оставшийся черновик (правки во время записи) - следующим пакетом
            self.marks_changed.emit(self.rev)
            if not m.drafts:
                self.run_then()

        def work():
            res = (safe(sv.add_marks_batch, disk, rows), safe(sv.razbor_tree, disk))
            job['res'] = res
            job['done'].set()
            return res
        job['written'] = written
        self.save_job = job
        self.win.bg.run(work, ok=written, quiet=True)

    def run_then(self):
        then, self.save_then = self.save_then, []
        for fn in then:
            fn()

    def flush_now(self, question):
        """Перед сменой носителя и закрытием окна: ждём ТОЛЬКО свою идущую запись (save_job) не дольше FLUSH_WAIT_MS,
        без прокрутки цикла событий; не закончилась - второй записи нет, сообщение, действие отменяется. Закончилась - её
        ответ принимается здесь же (written; поздний ответ из очереди будет пропущен). Остаток черновика пишется сейчас
        же; «Записывать нечего» = все строки пакета уже так записаны (отказ - только когда пропущены ВСЕ). Не записалось -
        вопрос question. -> можно продолжать."""
        if self.saving:
            job = self.save_job
            if job is None or not job['done'].wait(FLUSH_WAIT_MS / 1000):
                QMessageBox.information(self, TITLE, 'Запись отметок ещё идёт — подождите несколько секунд и повторите.')
                return False
            job['written'](job['res'])
        m = self.model
        self.save_timer.stop()
        if m is None or not m.drafts:
            return True
        rows, _sent = m.batch()
        try:
            sv.add_marks_batch(self.disk, rows)
            m.drafts = {}
            self.save_failed = False
            return True
        except sv.Refused as e:
            if str(e).startswith('Записывать нечего'):       # все строки пакета уже записаны так же
                m.drafts = {}
                return True
            return QMessageBox.question(self, TITLE, f'Отметки не сохранились: {e}\n\n{question}') == QMessageBox.Yes
        except Exception as e:                            # noqa: BLE001 - ошибка записи
            sv_log(traceback.format_exc())
            return QMessageBox.question(self, TITLE, f'Отметки не сохранились: {e}\n\n{question}') == QMessageBox.Yes
