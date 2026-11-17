"""«Задания на копирование»: запуск: отмеченные, «Запустить все по очереди», проверка перемещения по свежей базе (mvlist
--recheck), перемещение на носителе (mvlist --razbor), повтор копирования (часть-«примесь» класса TasksPage).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import re
from pathlib import Path

from hb_core import api as hb

from PySide6.QtCore import QTimer

from .texts_words import _folder_word, n
from .model_rules import conflicts, move_blocks, run_all_set
from .model_run import can_move, queue_cmd, _retry, run_hb


class RunFlow:
    """Часть TasksPage: запуск: отмеченные, «Запустить все по очереди», проверка перемещения по свежей базе (mvlist
    --recheck), перемещение на носителе (mvlist --razbor), повтор копирования."""

    # --- запуск ---
    def launch_all(self):
        """«Запустить все по очереди»: ждущие и прерванные - тем же путём, что «По очереди» для отмеченных."""
        sel = run_all_set(self.rows)
        if not sel:
            self.say('Нет заданий, которые ждут запуска или прерваны.')
            return
        self.launch(sel, sequential=True)

    def launch_checked(self, sequential=False):
        sel = [r for r in self.rows if r['task'] in self.checked]
        if not sel:
            self.say('Отметьте галочками задания, которые нужно запустить.')
            return
        self.launch(sel, sequential)

    def launch(self, sel, sequential=False, confirmed=False):
        """Запуск заданий sel. confirmed - владелец уже подтвердил запуск в окне «Начать копирование» (разбор): вопроса
        «Запустить?» нет; проверки «уже идёт» и «перемещение с того же носителя» - те же."""
        busy = [r for r in sel if r['state'] == 'идёт']
        if busy:
            self.say('Уже идут: ' + ', '.join(f'«{r["task"]}»' for r in busy) + '. Их повторно не запускаю.')
            sel = [r for r in sel if r['state'] != 'идёт']
            if not sel:
                return
        block = move_blocks(sel, self.rows)
        if block:
            self.say('Так нельзя: перемещение и копирование с одного носителя одновременно ломают друг друга.\n\n'
                     + '\n'.join(block) + '\n\nДождитесь конца копирования, затем запускайте перемещение.')
            return
        running = [r for r in self.rows if r['state'] == 'идёт']
        clash = conflicts(sel + running)
        names = '\n'.join(f'  • {r["task"]} ({r["kind"]}, {r.get("disks", "")})' for r in sel)
        if confirmed:
            pass
        elif len(sel) > 1 and not sequential:
            text = f'Запустить {len(sel)} задания(й) сразу, каждое в своём окне?\n\n{names}'
            if clash:
                text += ('\n\nВнимание: одни и те же диски у нескольких заданий —\n' + '\n'.join(clash) +
                         '\nОдновременно диск делит скорость между заданиями; лучше по очереди.')
            how = self.choose(text, ['По очереди', 'Все сразу'] if clash else ['Все сразу', 'По очереди'])
            if not how:
                return
            sequential = how == 'По очереди'
        elif not self.ask(('Запустить по очереди в одном окне?\n\n' if sequential and len(sel) > 1 else 'Запустить?\n\n')
                          + names + '\n\nВ начале каждого задания проверьте сводку и введите «да»; в конце — Enter. '
                          'Остановить — клавиша Q, повторный запуск продолжит.' +
                          ('\n\nВнимание: ' + '; '.join(clash) + '.' if clash else '')):
            return
        moves = [r for r in sel if r['kind'] == 'перемещение']
        if moves:
            self.win.statusBar().showMessage('Проверяю задания перемещения по свежей базе…')
            self.win.bg.run(lambda: [(r, *run_hb('mvlist', '--recheck', str(hb.TASKS / r['task']))) for r in moves],
                            ok=lambda res: self._after_recheck(res, sel, sequential))
            return
        self._start(sel, sequential)

    def _after_recheck(self, res, sel, sequential):
        bad = [(r, text) for r, code, text in res if code != 0]
        if bad:
            self.show_text('Задание перемещения устарело', '\n\n'.join(f'«{r["task"]}»:\n{t}' for r, t in bad))
            sel = [r for r in sel if r not in [b[0] for b in bad]]
            if not sel:
                return
        self._start(sel, sequential)

    def _start(self, sel, sequential):
        dirs = [hb.TASKS / r['task'] for r in sel]
        if sequential and len(dirs) > 1:
            path = queue_cmd(dirs, hb.BASE_DIR / 'очередь заданий.cmd')
            self.queue = [r['task'] for r in sel]
            self.start_file(str(path))
        else:
            for d in dirs:
                self.start_file(str(d / 'Запустить.cmd'))
        self.win.statusBar().showMessage(f'Запущено заданий: {len(dirs)}. Окна PowerShell ждут вашего «да».', 8000)
        QTimer.singleShot(3000, self.refresh)
        self.timer.start(5000)

    def _v3_args(self, it):
        if it.get('copy_task'):
            return ['mvlist', '--razbor', it['copy_task']]
        return ['mvlist', '--razbor-manifest', it['manifest'], '--group', it['group']]

    def move_v3(self, it):
        args = self._v3_args(it)
        self.win.statusBar().showMessage(f'Считаю, что можно перенести из «{_folder_word(it.get("folder"))}»…')
        self.win.bg.run(run_hb, *args, '--dry', ok=lambda res: self._v3_preview(it, args, *res))

    def _v3_preview(self, it, args, code, text):
        self.win.statusBar().clearMessage()
        cnt = can_move(text) if code == 0 else 0
        intro = (f'Предпросмотр (ничего не перенесено). Папка уйдёт в «{it["dest"]}» на том же диске, все подпапки '
                 'сохраняются, ничего не удаляется и не перезаписывается.\n\n')
        if not cnt:
            self.show_text('Переместить на носителе', intro + text)
            return
        if not self.show_text('Переместить на носителе', intro + text, ok=f'Создать и запустить ({n(cnt)} файлов)'):
            return
        self.win.bg.run(run_hb, *args, ok=lambda res: self._v3_created(*res))

    def _v3_created(self, code, text):
        m = re.search(r'Папка задания: (.+)', text)
        if code != 0 or not m:
            self.show_text('Задание не создано', text)
            return
        self.refresh()
        self.run_move(Path(m.group(1).strip()).name)

    def run_move(self, name):
        row = next((r for r in self.rows if r['task'] == name), {'task': name, 'kind': 'перемещение'})
        block = move_blocks([row], self.rows)
        if block:
            self.say('Так нельзя: перенос и копирование одной и той же папки одновременно ломают друг друга.\n\n'
                     + '\n'.join(block) + '\n\nДождитесь конца копирования.')
            return
        self.checked = {name}
        self.win.statusBar().showMessage('Проверяю задание перемещения по свежей базе…')
        self.win.bg.run(lambda: run_hb('mvlist', '--recheck', str(hb.TASKS / name)),
                        ok=lambda res: self._after_recheck([({'task': name}, *res)], [{'task': name}], False))

    def retry_copy(self, it):
        tasks = it.get('retry_tasks') or [it['copy_task']]
        left = sum(r.get('left', 0) for r in self.rows if r['task'] in tasks)
        names = ', '.join(f'«{t} — повтор»' for t in tasks)
        if not self.ask(f'Создать {"задание" if len(tasks) == 1 else "задания"} {names} из {n(left)} не скопированных '
                        'файлов и запустить? Старое задание не перезапускается: то, что уже скопировано (и, возможно, '
                        'перенесено), повторно не читается.'):
            return
        for t in tasks:
            self.win.bg.run(_retry, t, ok=self._retried)

    def _retried(self, res):
        if isinstance(res, str):
            self.say(res)
            return
        self.refresh()
        self.start_file(str(Path(res['task']) / 'Запустить.cmd'))
        self.win.statusBar().showMessage(f'Запущен повтор: {Path(res["task"]).name} ({n(res["files"])} файлов). '
                                         'Окно PowerShell ждёт вашего «да».', 8000)
