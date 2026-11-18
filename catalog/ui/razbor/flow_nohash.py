"""RazborPage, «Без хеша» (17.11.2026, решение владельца: SHA-256 у всех копируемых файлов): только то, что пойдёт на
диск назначения - расчёт в фоне (service.nohash_check), списки, «Отсканировать эти папки» и «отсканировать на H:».

Ответ принимается только для той ревизии итога, носителя и направления, для которых считался (правка отметок, смена
направления, новые данные после пересканирования - новая ревизия или направление - считается заново)."""
from PySide6.QtWidgets import QMessageBox

from hb_core import razbor as rz
from hb_core.razbor_scope import SHOW_MAX

import service as sv

from . import dialog_hash
from .common import TITLE, safe
from .dialogs import TextDialog
from .texts_hash import ALREADY
from .texts_cell import esc, files_word, num


def visible(dlg):
    """Окно ещё открыто (уже удалённое Qt-окно - не открыто)."""
    try:
        return bool(dlg.isVisible())
    except (RuntimeError, AttributeError):
        return False


class NohashFlow:
    """Часть RazborPage («без хеша»); атрибуты - у RazborPage."""

    def nohash_key(self):
        """Для чего считать: (носитель, ревизия принятого итога, направление); None - итог устарел или нет диска."""
        if self.model is None or not self.plan or self.plan_rev != self.rev or self.dest_dir() is None:
            return None
        return self.disk, self.rev, self.dest

    def run_nohash(self):
        """Запуск расчёта для текущего ключа - один раз; копировать нечего - без расчёта (пустой ответ)."""
        key = self.nohash_key()
        cur = getattr(self, 'nh', None)
        if key is None or (cur and cur['key'] == key):
            return
        P = self.plan[0]
        if not P.part_a.get((rz.O_COPY, self.dest), (0, 0))[0]:
            self.nh = dict(key=key, res=dict(n=0, bytes=0, folders=[], root=0, cats=[], sample=[], unread=[],
                                             copies={}, errors=[]))
            return
        self.nh = dict(key=key, res=None)
        self.win.bg.run(safe, sv.nohash_check, key[0], key[2], list(self.model.draft_rows()),
                        ok=lambda res, k=key: self.got_nohash(k, res), quiet=True)

    def got_nohash(self, key, res):
        cur = getattr(self, 'nh', None)
        if not cur or cur['key'] != key:
            return                                        # ответ для прежнего состояния - не нужен
        kind, val = res
        if kind != 'ok':
            val = {'error': val if kind == 'refused' else (val.strip().splitlines() or ['ошибка'])[-1]}
        elif val is None:
            val = dict(n=0, bytes=0, folders=[], root=0, cats=[], sample=[], unread=[], copies={}, errors=[])
        cur['res'] = val
        if self.model is not None:
            self.render_cells()

    def nohash_result(self):
        """Ответ для текущего ключа или None (ещё считается / итог устарел)."""
        cur = getattr(self, 'nh', None)
        key = self.nohash_key()
        return cur['res'] if cur and key and cur['key'] == key else None

    def scan_nohash(self):
        """«Посчитать хеш (N)»: своё короткое окно (18.11.2026, dialog_hash) - папки файлов без хеша и только их типы.
        Уже идёт пересканирование - сообщение; окно уже открыто (в любом состоянии) - поднимается, второе не
        открывается; окно - в win.rescan, по закрытию - refresh."""
        nh = self.nohash_result()
        if not (nh and nh.get('folders') and not self.writing):
            return
        old = getattr(self.win, 'rescan', None)
        if old is not None and (getattr(old, 'running', False) or visible(old)):
            if getattr(old, 'running', False):                 # идёт сканирование - прежнее сообщение
                QMessageBox.information(self, TITLE, ALREADY)
            old.raise_()                                       # окно уже открыто - поднять его, второе не открывать
            old.activateWindow()
            return
        P = self.plan[0] if self.plan else None
        d = P.dirs.get(self.dest) if P is not None else None
        target = ' и '.join(self.disk_label(x) for x in d.disks if x != self.disk) if d is not None else ''
        dlg = dialog_hash.HashDialog(self.win, self.disk, nh, target or 'диск назначения', self.hash_check_args,
                                     self.nohash_list_html, self.show_text)
        self.win.rescan = dlg
        dlg.finished.connect(lambda *_: self.refresh())      # новая опись - дерево и итог заново
        dlg.show()

    def hash_check_args(self):
        """Повторная проверка «без хеша» после подсчёта: (носитель, направление, черновик отметок) или None."""
        if not self.dest:
            return None
        return self.disk, self.dest, list(self.model.draft_rows()) if self.model is not None else []

    def show_text(self, title, body):
        self._nh_dlg = TextDialog(self, title, body, width=1000, height=600)
        self._nh_dlg.show()
        return self._nh_dlg

    def nohash_link(self, href):
        """Ссылки строк «без хеша»: nh-list (файлы без хеша), nh-unread (не прочитаны), nh-copies:<диск> (окно
        пересканирования архивного диска с папками возможных копий)."""
        nh = self.nohash_result()
        kind, _, x = str(href).partition(':')
        if not nh or 'error' in nh:
            return None
        if kind == 'nh-copies':
            k = (nh.get('copies') or {}).get(x)
            if k and k['folders'] and not self.writing:
                self.rescan(x, k['folders'], k['cats'] or None)
            return None
        if kind == 'nh-list':
            title, body = f'Без хеша - {self.disk}', self.nohash_list_html(nh)
        elif kind == 'nh-unread':
            title, bad = f'Не прочитаны при пересканировании - {self.disk}', nh['unread']
            body = (f'<p><b>{files_word(len(bad))}</b> снова не прочитаны при пересканировании — в задания не входят '
                    '(остальные файлы копируются). Причина — как её записал сканер.'
                    + (f' Показаны первые {num(SHOW_MAX)}.' if len(bad) > SHOW_MAX else '') + '</p><ul>'
                    + ''.join(f'<li>{esc(p)} — {esc(w or "причина не записана")}</li>' for p, w, _s in bad[:SHOW_MAX])
                    + '</ul>')
        else:
            return None
        return self.show_text(title, body)

    def nohash_list_html(self, nh):
        shown = nh['sample']
        more = (f' Показаны первые {num(len(shown))} из {num(nh["n"])}.' if len(shown) < nh['n'] else '')
        return (f'<p><b>{files_word(nh["n"])}</b> без хеша — из тех, что пойдут на диск.{more}</p>'
                '<p><b>Папки для пересканирования</b></p><ul>'
                + ''.join(f'<li>{esc(f)}</li>' for f in nh['folders'])
                + (f'<li>корень носителя: {files_word(nh["root"])}</li>' if nh.get('root') else '')
                + '</ul><p><b>Файлы</b></p><ul>' + ''.join(f'<li>{esc(p)}</li>' for p in shown) + '</ul>')
