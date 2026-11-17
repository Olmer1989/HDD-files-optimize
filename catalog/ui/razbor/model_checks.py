"""Model, часть «галочки диска назначения» (этап 8): галочка - вид отметок, не отдельное хранилище.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import Qt

from hb_core import api as hb
from hb_core.directions import R_DIR, R_SKIP

from directions_look import show_num                 # «Н2» на экране - «А2» (18.11.2026)

from .common import INHERIT, SEP, SKIP


class ChecksPart:
    """Часть Model (часть «галочки диска назначения» (этап 8)); атрибуты - у Model."""

    def own_mark(self, f):
        """Своя действующая (с черновиком) отметка папки; '' - отметка всего носителя. None - своей нет."""
        return self.full_ms.get(self.orig(f) if f else '')

    @staticmethod
    def is_dir(r, num):
        return r is not None and r.state == R_DIR and r.num == num

    def ancestors(self, f):
        while f:
            f = hb.parent_of(f)
            yield f

    def parent_is(self, f, num, pending):
        """Идёт ли родитель папки f в направление num с учётом ещё не применённых изменений пакета pending
        {исходный путь (нижний регистр): решение}. Правила - те же, что Model.routes: служебная папка переноса - не
        направление; самая глубокая своя отметка решает."""
        if f in self.roots:
            return False                                  # служебная папка: отметка носителя в неё не проникает
        for a in self.ancestors(f):
            if self.is_service(a):
                return False
            key = self.orig(a).lower() if a else ''
            if key in pending:
                v = pending[key]
                if v == INHERIT:
                    if self.is_copied(a):
                        return False
                    continue
                kind, n = hb.parse_verdict(v, self.dirs)[:2]
                return kind == R_DIR and n == num
            if self.full_ms.by_key.get(key) is not None:
                return self.is_dir(self.route.get(a), num)
            if self.is_copied(a):
                return False                              # отметка носителя в «Скопировано на …» не проникает
        return False

    def own_after(self, f, pending):
        """(вид, номер) своей отметки папки с учётом пакета; None - своей нет."""
        key = self.orig(f).lower()
        if key in pending:
            v = pending[key]
            return None if v == INHERIT else hb.parse_verdict(v, self.dirs)[:2]
        m = self.full_ms.by_key.get(key)
        return None if m is None else (m.kind, m.num)

    def include_pairs(self, folders, num, pending=None):
        """«Сделать D» (галочка в «Только выбранные»/«Все папки», бросок в ячейку, снятие исключения): родитель уже
        идёт в D - своя отметка снимается; иначе своя отметка = D. Папки по порядку от мелких путей к глубоким, родитель
        считается с уже сделанными изменениями пакета. -> [(физический путь, решение)]."""
        d = self.dirs.get(num)
        if d is None:
            return []
        pending = {} if pending is None else pending
        out = []
        for f in sorted({f for f in folders if f and self.markable(f)}, key=lambda x: (x.count(SEP), x.lower())):
            key = self.orig(f).lower()
            own = self.own_after(f, pending)
            if self.parent_is(f, num, pending):
                v = None if own is None or own == (R_DIR, num) else INHERIT
            else:
                v = None if own == (R_DIR, num) else d.verdict()
            if v is not None:
                pending[key] = v
                out.append((f, v))
        return out

    def exclude_pairs(self, folders, num, pending=None):
        """«Сделать не D» (снять галочку; галочка в «Все, кроме выбранных»): своя отметка D при родителе не в D -
        снимается («как у родителя»); иначе - «не копировать». Папка и так не идёт в D - ничего."""
        pending = {} if pending is None else pending
        out = []
        for f in sorted({f for f in folders if f and self.markable(f)}, key=lambda x: (x.count(SEP), x.lower())):
            key = self.orig(f).lower()
            own = self.own_after(f, pending)
            par = self.parent_is(f, num, pending)
            cur = own == (R_DIR, num) if own is not None else par
            if not cur:
                continue
            v = INHERIT if own is not None and not par else SKIP
            pending[key] = v
            out.append((f, v))
        return out

    def check(self, f, num, mode):
        """Галочка папки для направления num в режиме mode ('only'/'all'/'except'). -> None (весь носитель, служебная
        папка - галочки нет) или dict(on, gray - унаследовано/менять нельзя, checkable, tag - «Н2» у своей отметки другого
        направления, tip)."""
        if not f or not self.markable(f):
            return None
        r = self.route[f]
        own = self.own_mark(f)
        tag, tip = '', ''
        if own is not None and own.kind == R_DIR and own.num != num:
            d = self.dirs.get(own.num)
            tag = show_num(own.num)                       # 18.11.2026: на экране «А2», в данных «Н2»
            tip = f'Папка отмечена для «{show_num(own.num)} {d.name if d else ""}» ({hb.disk_nums(d.disks) if d and d.disks else "диск не назначен"}).'
        elif r.state == R_DIR and r.num != num:
            d = self.dirs.get(r.num)
            src = 'всего носителя' if r.mark is not None and r.mark.path == '' else f'папки «{r.mark.path}»' if r.mark else ''
            tip = f'Идёт в «{show_num(r.num)} {d.name if d else ""}» (от {src}).'
        if mode == 'except':
            on = r.state == R_SKIP
            own_skip = own is not None and own.kind == R_SKIP
            gray = on and not own_skip
            checkable = not gray and (self.is_dir(r, num) or own_skip)
            if tag or (r.state == R_DIR and r.num != num):
                tip += (' В режиме «Все, кроме выбранных» галочка значит «исключить»; чтобы копировать эту папку на '
                        'этот диск, перетащите её в ячейку «Копировать на диск» справа.')
            elif gray:
                tip = 'Исключена вместе с родительской папкой.'
        else:
            on = self.is_dir(r, num)
            gray = on and not (own is not None and own.kind == R_DIR and own.num == num)
            checkable = True                              # этап 17: и у выбранной с родителем - снять = исключить
            if tag:
                tip += ' Поставьте галочку — отметка перейдёт на этот диск назначения.'
            elif gray:
                tip = (('Выбрана вместе с родительской папкой.' if r.mark is not None and r.mark.path
                        else 'Выбрана вместе со всем носителем.') + ' Снимите галочку — эта папка не будет копироваться.')
            elif own is not None and own.kind == R_SKIP and self.parent_is(f, num, {}):
                tip = 'Исключена: не копируется, хотя родительская папка выбрана. Поставьте галочку — исключение снимется.'
            pm = self.partial(num).get(f)
            if on and pm == 'off':
                tip = (tip + ' Внутри есть исключённые папки (частичная галочка). Щелчок — снять всю папку.').strip()
                return dict(on=on, gray=gray, checkable=checkable, tag=tag, tip=tip, state=Qt.PartiallyChecked,
                            click='off')
            if not on and pm == 'on':
                tip = (tip + ' Внутри есть папки, выбранные для этого диска (частичная галочка). Щелчок — выбрать '
                             'всю папку.').strip()
                return dict(on=on, gray=gray, checkable=checkable, tag=tag, tip=tip, state=Qt.PartiallyChecked,
                            click='on')
        return dict(on=on, gray=gray, checkable=checkable, tag=tag, tip=tip.strip())

    def own_skips(self):
        """Свои «не копировать» у папок (без всего носителя): [физический путь]."""
        return [self.aliases[k][0] for k, m in self.full_ms.by_key.items()
                if k and m.kind == R_SKIP and self.aliases.get(k)]

    def skips_back_to(self, num, pending=None):
        """Свои «не копировать», снятие которых вернёт папку в направление num (родительская цепочка - в num, с учётом
        пакета pending, например новой отметки всего носителя). Исключения внутри веток других направлений - нет."""
        pending = dict(pending or {})
        out = []
        for f in sorted(self.own_skips(), key=lambda x: (x.count(SEP), x.lower())):
            if self.parent_is(f, num, pending):
                pending[self.orig(f).lower()] = INHERIT
                out.append(f)
        return out

    def own_excluded(self, num):
        """Сколько папок исключил владелец из num: своя «не копировать» при родителе, идущем в num."""
        return len([f for f in self.own_skips() if self.parent_is(f, num, {})])

    def tops(self, pick):
        """Сколько «верхних» папок с признаком pick(маршрут): у самой признак есть, у родителя - нет (у верхних папок
        носителя родитель - весь носитель, его признак не считается). Служебные и уже перенесённые не считаются."""
        n = 0
        for f in self.order:
            if not f or self.is_service(f) or (self.route[f].moved and self.route[f].state != R_DIR):
                continue
            p = hb.parent_of(f)
            if pick(self.route[f]) and (not p or self.is_service(p) or not pick(self.route[p])):
                n += 1
        return n
