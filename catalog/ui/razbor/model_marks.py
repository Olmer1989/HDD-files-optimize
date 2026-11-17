"""Model, часть «загрузка, пути, отметки»: черновик, сохранённые отметки, отмена.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections

from hb_core import api as hb
from hb_core import razbor as rz
from hb_core.consts import COPIED_PREFIX
from hb_core.directions import R_DIR, R_SKIP

from .common import INHERIT, SEP, SKIP, UNDO_MAX


class MarksPart:
    """Часть Model (часть «загрузка, пути, отметки»); атрибуты - у Model."""

    def load(self, tree):
        self.tree = tree
        self.inflight = {}                # новое состояние таблицы прочитано - записанный пакет уже в нём
        self.folders, self.roots, self.dirs = tree['folders'], set(tree['roots']), tree['dirs']
        self.built, self.sig = tree.get('built'), tree.get('sig')
        self.order = sorted(self.folders, key=lambda f: (f.count(SEP) + 1 if f else 0, f))
        kids = collections.defaultdict(list)
        for f in self.order:
            if f:
                kids[hb.parent_of(f)].append(f)
        self.children = {p: sorted(v, key=lambda f: (-self.folders[f][1], f.lower())) for p, v in kids.items()}
        self.aliases = collections.defaultdict(list)      # исходный путь -> физические папки (в служебной и вне её)
        for f in self.order:
            if not self.is_service(f):
                self.aliases[self.orig(f).lower()].append(f)
        self.saved_ms = hb.MarkSet.build(tree['rows'], self.dirs)
        self.recalc()

    def reload(self, tree):
        """Новые данные носителя (новое поколение базы или запись таблиц): черновик сохраняется, совпавшее с сохранённым
        уходит из него. -> число убранных записей черновика."""
        self.load(tree)
        return self.prune()

    def prune(self):
        gone = [k for k, d in self.drafts.items() if self.equal_saved(k, d['verdict'])]
        for k in gone:
            del self.drafts[k]
        self.recalc()
        return len(gone)

    def is_service(self, f):
        """Сама старая служебная папка переноса («ПЕРЕНЕСЕНО → …»): отметить нельзя. «Скопировано на …» (этап 13) -
        можно: её и папки внутри отмечают для ДРУГОГО направления (вторая копия)."""
        return bool(f) and SEP not in f and f in self.roots and not f.startswith(COPIED_PREFIX)

    def is_copied(self, f):
        """Сама папка «Скопировано на …» из журнала перемещения (этап 13)."""
        return bool(f) and SEP not in f and f in self.roots and f.startswith(COPIED_PREFIX)

    def orig(self, f):
        """Путь, по которому хранится отметка папки: исходный, а внутри «Скопировано на …» - нынешний (этап 13)."""
        return rz.mark_path(f, self.roots) if f else ''

    def markable(self, f):
        return f in self.folders and not self.is_service(f)

    def saved_key(self, key):
        """Сохранённая отметка пути (вид, номер); пакет, который сейчас пишется (автосохранение, этап 16), считается уже
        сохранённым: правка во время записи сравнивается с ним, а не со старым состоянием таблицы."""
        if key in self.inflight:
            v = self.inflight[key]
            return None if v == INHERIT else hb.parse_verdict(v, self.dirs)[:2]
        m = self.saved_ms.by_key.get(key)
        return None if m is None else (m.kind, m.num)

    def equal_saved(self, key, verdict):
        if verdict == INHERIT:
            return self.saved_key(key) is None
        return self.saved_key(key) == hb.parse_verdict(verdict, self.dirs)[:2]

    def own_verdict(self, key):
        """Своя действующая отметка пути текстом для записи (черновик, иначе сохранённая); нет своей - «как у
        родителя». Старая строка («раздел: …», «не нужно») - равнозначной отметкой v3."""
        d = self.drafts.get(key)
        if d is not None:
            return d['verdict']
        if key in self.inflight:
            return self.inflight[key]
        m = self.saved_ms.by_key.get(key)
        if m is None:
            return INHERIT
        if m.kind == R_DIR and m.num in self.dirs:
            return self.dirs[m.num].verdict()
        if m.kind == R_SKIP:
            return SKIP
        return m.verdict

    def draft_rows(self):
        return [(d['path'], d['verdict']) for d in self.drafts.values()]

    def ms(self):
        return hb.MarkSet.build(self.tree['rows'], self.dirs, self.draft_rows())

    def routes(self, ms):
        """Действующая отметка каждой папки - та же функция, что в ядре (hb_core.razbor.folder_routes): корень -
        отметка всего носителя; «ПЕРЕНЕСЕНО → …» - внутри только явные отметки исходного пути; «Скопировано на …» -
        только отметки, поставленные внутри неё (этап 13); иначе - своя отметка или маршрут родителя."""
        return rz.folder_routes(self.order, ms, self.dirs, self.roots)

    def recalc(self):
        self.full_ms = self.ms()
        self.route = self.routes(self.full_ms)
        self.route_saved = self.routes(self.saved_ms)
        self.have_disk_cache = {}
        self.partial_cache = {}                           # этап 17: папки D с исключениями внутри - по направлению
        self.have_sub = self.have_counts()

    def partial(self, num):
        """Частичные галочки для направления num (этапы 17-18) -> {папка: что делает щелчок}: 'off' - папка идёт в num,
        но внутри есть папка, которая в num не идёт (исключение, другой диск) - щелчок снимает всю; 'on' - папка в num
        НЕ идёт, но внутри есть папка, которая идёт (HDD09: «Алтай 2022 …» без своей отметки, 4 подпапки отмечены) -
        щелчок выбирает всю. По ДЕЙСТВУЮЩИМ маршрутам: для каждой папки со своей отметкой - предки, у которых маршрут
        другой (самая глубокая отметка решает). Кэш - до recalc (любая правка, отмена, перечитка)."""
        got = self.partial_cache.get(num)
        if got is None:
            got = {}
            for k in self.full_ms.by_key:
                if not k:
                    continue
                for f in self.aliases.get(k, ()):
                    s = self.is_dir(self.route.get(f), num)
                    a = f
                    while a:
                        a = hb.parent_of(a)
                        if not a:
                            break
                        sa = self.is_dir(self.route.get(a), num)
                        if sa != s and a not in got:
                            got[a] = 'off' if sa else 'on'
            self.partial_cache[num] = got
        return got

    def set_mark(self, folders, verdict):
        """Черновая отметка папок (физические пути; '' - весь носитель). -> сколько записей черновика изменилось."""
        return self.set_marks([(f, verdict) for f in folders])

    def set_marks(self, pairs, record=True):
        """Несколько отметок одним шагом «Отменить последнее»: [(физический путь, решение)]. Черновик живёт до
        автосохранения (этап 16). Шаг отмены - прежние свои отметки изменённых папок (record=False - это сама отмена)."""
        changed, step = 0, []
        for f, verdict in pairs:
            if f and not self.markable(f):
                continue
            o = self.orig(f)
            key = o.lower()
            cur = self.drafts.get(key)
            prev = self.own_verdict(key)
            if self.equal_saved(key, verdict):
                if cur is not None:
                    del self.drafts[key]
                    changed += 1
                    step.append((f, prev))
                continue
            if cur is None or cur['verdict'] != verdict:
                self.drafts[key] = dict(path=o, phys=f, verdict=verdict,
                                        base=cur['base'] if cur else self.saved_key(key))
                changed += 1
                step.append((f, prev))
        if step and record:
            self.undo_stack.append(step)
            del self.undo_stack[:-UNDO_MAX]
        self.recalc()
        return changed

    def undo(self):
        """«Отменить последнее»: вернуть прежние свои отметки шага - это новая правка, она тоже сохраняется сразу
        (таблица только дописывается; «как у родителя» снимает свою отметку, строки не прибавляет, если её нет)."""
        if not self.undo_stack:
            return False
        self.set_marks(self.undo_stack.pop(), record=False)
        return True

    def discard(self):
        """Забыть черновик (запись не удалась): на экране - сохранённые отметки."""
        if self.drafts:
            self.drafts = {}
            self.recalc()

    def own_choice(self, f):
        """Что стоит у папки своё (для выпадающего списка): текст решения или «как у родителя»."""
        m = self.full_ms.get(self.orig(f))
        if m is None:
            return INHERIT
        if m.kind == R_DIR and m.num in self.dirs:
            return self.dirs[m.num].verdict()
        if m.kind == R_SKIP:
            return SKIP
        return None
