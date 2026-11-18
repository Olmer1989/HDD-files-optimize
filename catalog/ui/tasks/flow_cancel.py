"""«Копирование»: кнопка «Отменить задание…» - выбор (выделенная строка и отмеченные галочками), окно подтверждения,
перенос папок в «_Отменённые» (service.cancel_tasks, в фоне), итог одним сообщением (часть-«примесь» класса TasksPage).

Правило (утверждено владельцем 18.11.2026): отменяются только задания копирования «не запускалось», «прервано»,
«готово с ошибками». Перемещения, идущие и готовые - нет. Ничего не удаляется."""
import service as sv

from .texts_cancel import CANCEL_NONE, CANCEL_TIP, CONFIRM_NO, CONFIRM_YES, confirm_text, disabled_tip, result_text


class CancelFlow:
    """Часть TasksPage: «Отменить задание…»."""

    def cancel_targets(self):
        """Выделенная строка и отмеченные галочками - в порядке списка. -> ([можно], [(нельзя, причина)])."""
        cur = self.current()
        names = set(self.checked) | ({cur['task']} if cur else set())
        ok, bad = [], []
        for r in self.rows:
            if r['task'] in names:
                why = sv.can_cancel(r)
                if why:
                    bad.append((r, why))
                else:
                    ok.append(r)
        return ok, bad

    def update_cancel_btn(self):
        if not hasattr(self, 'cancel_btn'):
            return
        ok, bad = self.cancel_targets()
        self.cancel_btn.setEnabled(bool(ok))
        self.cancel_btn.setToolTip(CANCEL_TIP if ok else disabled_tip(bad))

    def cancel_task(self):
        ok, bad = self.cancel_targets()
        if not ok:
            self.say(disabled_tip(bad) if bad else CANCEL_NONE)
            return
        if not self.confirm(confirm_text(ok, bad), CONFIRM_YES, CONFIRM_NO):
            return
        self.win.statusBar().showMessage('Отменяю: переношу папки заданий в «_Отменённые»…')
        self.win.bg.run(sv.cancel_tasks, [r['task'] for r in ok], ok=self._cancelled)

    def _cancelled(self, res):
        self.win.statusBar().clearMessage()
        self.checked -= {x['task'] for x in res if x['ok']}
        self.say(result_text(res))
        self.refresh()
