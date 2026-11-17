"""«Диски и папки»: действия с папкой - «Открыть в Проводнике», «Чего нет на дисках направления», «Пересканировать
выбранные…» (часть-«примесь» класса DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os

import rescan_dialog
import service as sv
from ui_common import TITLE
from overview_page import gb_ru, n_ru

from PySide6.QtWidgets import QMessageBox


class FolderFlow:
    """Часть DisksPage: действия с выбранными папками."""

    def open_explorer(self):
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку).')
            return
        for disk, path, _n, _g in t[:10]:
            letter = self.row_of(disk).get('letter')
            if not letter:
                QMessageBox.information(self, TITLE, f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
                return
            p = letter + '\\' + path
            if os.path.isdir(p):
                os.startfile(p)
            else:
                QMessageBox.information(self, TITLE, f'Папки «{p}» на диске нет (её переименовали или переместили?). '
                                        'Пересканируйте носитель.')
        if len(t) > 10:
            self.info.setText(f'Открыты первые 10 папок из {len(t)}.')

    def presence(self):
        """Чего из выбранных папок нет на дисках направлений, отмеченных в «Обзоре» (по SHA-256)."""
        import directions_page
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку).')
            return
        dirs = directions_page.chosen()
        targets = list(dict.fromkeys(x for d in dirs for x in d.disks))
        if not targets:
            QMessageBox.information(self, TITLE, 'В «Обзоре» не отмечено ни одного направления с диском. Отметьте '
                                    'направления галочками — их диски и проверятся.')
            return
        self.info.setText('Считаю…')

        def job():
            return [(d, p, sv.folder_missing(d, p, targets)) for d, p, _n, _g in t[:30]]

        def show(res):
            import html as h
            lines = []
            for d, p, r in res:
                where = f'{d}\\{p}' if p else f'{d} (весь диск)'
                parts = []
                for x in targets:
                    n, g = r['missing'][x]
                    weak = r.get('weak', {}).get(x, 0)
                    parts.append(f'нет на {x} — <b>{n_ru(n)}</b> файлов, {gb_ru(g)} ГБ' +
                                 (f' (у {n_ru(weak)} из них там есть непроверенная копия)' if weak else '')
                                 if n else f'<span style="color:#2e7d32">на {x} есть всё</span>')
                extra = f'; без хеша (сравнить нельзя) — {n_ru(r["nohash"])}' if r['nohash'] else ''
                if r.get('stale'):
                    extra += f'; хеш устарел — файл изменён после подсчёта (сравнить нельзя) — {n_ru(r["stale"])}'
                lines.append(f'<b>{h.escape(where)}</b>: файлов с хешем {n_ru(r["files"])} ({gb_ru(r["gib"])} ГБ); '
                             + '; '.join(parts) + extra + '.')
            if len(t) > 30:
                lines.append(f'Показаны первые 30 папок из {len(t)}.')
            self.info.setText('<br>'.join(lines))
        self.win.bg.run(job, ok=show)

    def rescan(self):
        """Пересканировать выбранные папки подключённого диска: окно предпросмотра; скан - только по подтверждению."""
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку). Весь диск целиком - '
                                    'это полное сканирование, его делает сканер дисков.')
            return
        disks = sorted({x[0] for x in t})
        if len(disks) > 1:
            QMessageBox.information(self, TITLE, f'Выбраны папки разных дисков ({", ".join(disks)}). Пересканировать '
                                    'можно папки одного диска за раз.')
            return
        disk = disks[0]
        if not self.row_of(disk).get('letter'):
            QMessageBox.information(self, TITLE, f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, [p for _d, p, _n, _g in t])
        self.win.rescan.show()
