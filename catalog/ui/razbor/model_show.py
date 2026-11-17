"""Model, часть «показ, «Уже есть», предпросмотр записи»: тексты и цвета строк дерева.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import collections

from hb_core import api as hb
from hb_core import razbor as rz
from hb_core.consts import CAT_OF_TYPE, N_TYPES
from hb_core.directions import R_DIR, R_SKIP, R_UNSET

from directions_look import show_num                 # «Н2» на экране - «А2» (18.11.2026)

from .common import INHERIT, SEP, SKIP_INH, SKIP_OWN, UNSET_BG, dir_colors, last


class ShowPart:
    """Часть Model (часть «показ, «Уже есть», предпросмотр записи»); атрибуты - у Model."""

    def label(self, r):
        if r.state == R_DIR:
            d = self.dirs.get(r.num)
            t = d.label() if d else str(r.num)
            return t + (self.moved_word(r) if r.moved else '')
        if r.state == R_SKIP:
            return 'не копировать' + (f' (старое «{r.mark.label}»)' if r.mark is not None and r.mark.legacy else '')
        if r.state == R_UNSET:
            return hb.mark_text(r.mark, self.dirs)
        return 'уже перенесено' if r.moved else 'не отмечено'

    def moved_word(self, r):
        if rz.is_second(r, self.roots):
            return ' — ещё одна копия (папка уже в «Скопировано на …»)'
        return ' — дополнительная копия (папка уже перенесена)'

    def mode_text(self, r):
        if r.mark is None:
            return 'режим не выбран — файлы «не отмечены»'
        if r.state == R_DIR:
            return f'всё — в {self.label(r)}, кроме отмеченных'
        if r.state == R_SKIP:
            return 'ничего, кроме отмеченных'
        return self.label(r)

    def cell(self, f, saved=False):
        """Ячейка «Куда»: dict(text, kind 'own'/'inherited'/'none'/'service', dirty None/'own'/'drop'/'inherited', tip)."""
        if self.is_service(f):
            return dict(text='служебная папка: уже перенесено', kind='service', dirty=None,
                        tip='Папка, куда файлы перенесли раньше. Её саму отметить нельзя; папки внутри неё можно '
                            'отметить, чтобы ДОПОЛНИТЕЛЬНО скопировать их в другое направление (второй раз они не '
                            'перемещаются).')
        o = self.orig(f)
        r = (self.route_saved if saved else self.route)[f]
        own = r.mark is not None and r.mark.path.lower() == o.lower()
        tips = []
        if not f:
            text = self.mode_text(r)
            kind = 'own' if r.mark is not None else 'none'
        else:
            text = self.label(r)
            if own:
                kind = 'own'
            elif r.mark is not None:
                kind = 'inherited'
                src = 'режима' if r.mark.path == '' else f'«{last(r.mark.path)}»'
                text += f' — от {src}'
                tips.append('Унаследовано от ' + ('режима всего носителя' if r.mark.path == '' else
                                                  f'папки «{r.mark.path}»') + '.')
            else:
                kind = 'none'
        dirty = None
        if not saved:
            d = self.drafts.get(o.lower())
            rs = self.route_saved[f]
            if d is not None and d['verdict'] == INHERIT:
                dirty = 'drop'
                text = '• снять свою отметку → ' + text
                tips.append('Своя отметка снимается (сохраняется…); папка получит отметку родителя.')
            elif d is not None:
                dirty = 'own'
                text = '• ' + text
                tips.append('Своя отметка — сохраняется…')
            elif (r.state, r.num, r.moved) != (rs.state, rs.num, rs.moved):
                dirty = 'inherited'
                text = '• ' + text
                tips.append(f'Изменится после сохранения из-за отметки выше; сейчас сохранено: {self.cell(f, True)["text"]}.')
            elif own:
                tips.append('Своя отметка этой папки (сохранена).')
            if d is not None and d['base'] != self.saved_key(o.lower()):
                tips.append('Пока вы отмечали, отметку этой папки изменили в другом месте.')
        others = [x for x in self.aliases.get(o.lower(), []) if x != f]
        if f and others:
            tips.append('Та же отметка действует и на: ' + '; '.join(f'«{x}»' for x in others[:3]) + '.')
        return dict(text=text, kind=kind, dirty=dirty, tip=' '.join(tips))

    def look(self, f):
        """Как показать папку в дереве (этап 6, вместо колонки «Куда»): dict(kind 'dir'/'skip'/'unset'/'none'/'moved'/
        'service', num, own, dirty, tip, bg - цвет фона или None). Своя отметка - насыщенный цвет направления,
        унаследованная - бледный; «не копировать» - серый (зачёркивание ставит страница)."""
        c = self.cell(f)
        r = self.route[f]
        own = c['kind'] == 'own'
        if c['kind'] == 'service':
            return dict(kind='service', num=None, own=False, dirty=None, tip=c['tip'], bg=None)
        if r.state == R_DIR:
            kind, d = 'dir', self.dirs.get(r.num)
            head = f'{show_num(r.num)} {d.label() if d else ""}'.strip()
            if r.moved:
                head += self.moved_word(r)
            bg = dir_colors(r.num)[0 if own else 1]
        elif r.state == R_SKIP:
            kind, head, bg = 'skip', self.label(r)[:1].upper() + self.label(r)[1:], SKIP_OWN if own else SKIP_INH
        elif r.state == R_UNSET:
            kind, head, bg = 'unset', self.label(r), UNSET_BG
        elif r.moved:
            kind, head, bg = 'moved', 'Уже перенесено раньше', None
        else:
            kind, head, bg = 'none', 'Не отмечено' + (' — режим не выбран' if r.mark is None else ''), None
        if not f:
            src = ' (режим всего носителя)' if r.mark is not None else ''
        elif own:
            src = ' (своя отметка)'
        elif r.mark is not None:
            src = ' (от режима всего носителя)' if r.mark.path == '' else f' (от папки «{r.mark.path}»)'
        else:
            src = ''
        extra = c['tip'].replace('Своя отметка этой папки (сохранена).', '')
        if r.mark is not None:
            extra = extra.replace('Унаследовано от ' + ('режима всего носителя' if r.mark.path == '' else
                                                        f'папки «{r.mark.path}»') + '.', '')
        tip = head + src + '. ' + extra.strip()
        if c['dirty']:
            tip = '• НЕ СОХРАНЕНО. ' + tip
        return dict(kind=kind, num=r.num if kind == 'dir' else None, own=own, dirty=c['dirty'], tip=tip.strip(), bg=bg)

    def docs_near_map(self):
        """Папки, где документы «рядом с фото и видео» - те же правила, что в ядре (razbor.planner, «документы
        рядом»): фото или видео в самой папке или в подпапках с той же решающей отметкой; корень носителя и сама
        служебная папка - нет. Отметки отдельных файлов (только из командной строки) здесь не учитываются."""
        direct = {}
        for f in self.order:
            n = self.folders[f][2]
            direct[f] = n[0] + n[1]
        for f in self.order:
            if f and hb.parent_of(f) in direct:
                n = self.folders[f][2]
                direct[hb.parent_of(f)] -= n[0] + n[1]
        ident = lambda r: (r.mark.row if r.mark else None, r.moved, r.state, r.num)
        ms = {}
        for f in reversed(self.order):
            k = direct[f]
            for ch in self.children.get(f, ()):
                if ident(self.route[ch]) == ident(self.route[f]):
                    k += ms[ch]
            ms[f] = k
        return {f: bool(f) and f not in self.roots and ms[f] > 0 for f in self.order}

    def set_have(self, have, disks_):
        self.have, self.have_disks = have, list(disks_)
        self.have_disk_cache = {}
        self.have_sub = self.have_counts()

    def have_counts(self):
        """«Уже есть» по поддереву: у каждой папки - СВОЁ направление для файлов прямо в ней (с хешем, типы, которые
        направление копирует, есть на всех его дисках), затем сумма детей. None - ещё не посчитано."""
        if self.have is None:
            return None
        near = self.docs_near_map()
        own = {}
        for f, masks in self.have.items():
            r = self.route.get(f)
            if r is None or r.state != R_DIR:
                continue
            d = self.dirs.get(r.num)
            if d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
                continue
            need = sum(1 << self.have_disks.index(x) for x in d.disks)
            types = [k for k, cat in CAT_OF_TYPE.items() if cat in d.cats       # что копирует направление;
                     and not (cat == hb.CAT_DOC and d.docs_near and not near.get(f))]  # документы - только «рядом»
            n = b = 0
            for mask, c in masks.items():
                if mask & need == need:
                    n += sum(c[k] for k in types)
                    b += sum(c[N_TYPES + k] for k in types)
            if n:
                own[f] = (n, b)
        sub = collections.defaultdict(lambda: [0, 0])
        for f in reversed(self.order):
            v = own.get(f)
            if v:
                sub[f][0] += v[0]
                sub[f][1] += v[1]
            if f and f in sub:
                p = sub[hb.parent_of(f)]
                p[0] += sub[f][0]
                p[1] += sub[f][1]
        return dict(sub)

    def have_on_disk(self, num_):
        """«Уже есть на диске» по КАЖДОМУ диску направления num_ (этап 12, 45 и 77 раздельно): файлы с хешем, которые
        направление копирует (те же папки, типы и «документы рядом», что у колонки «Уже есть» и в ядре), и у которых
        на этом диске уже есть подтверждённая копия с тем же SHA-256 (razbor_have: маска по дискам). Ядро не менялось:
        у него «уже есть» - только на всех дисках сразу. -> {диск: (файлов, байт)} или None (ещё не посчитано).
        Ответ запоминается до правки отметок или нового «Уже есть» (recalc / set_have): ячейка перерисовывается часто.
        Замер на настоящей базе без кэша: HDD45 (25 тыс. папок) - 0,06 с, HDD09 - 0,03 с."""
        cache = getattr(self, 'have_disk_cache', None)
        if cache is None:
            cache = self.have_disk_cache = {}
        if num_ not in cache:
            cache[num_] = self._have_on_disk(num_)
        return cache[num_]

    def _have_on_disk(self, num_):
        d = self.dirs.get(num_)
        if self.have is None or d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
            return None
        near = self.docs_near_map()
        types_all = [k for k, cat in CAT_OF_TYPE.items() if cat in d.cats]
        types_far = [k for k in types_all if not (CAT_OF_TYPE[k] == hb.CAT_DOC and d.docs_near)]
        res = {x: [0, 0] for x in d.disks}
        bits = {x: 1 << self.have_disks.index(x) for x in d.disks}
        for f, masks in self.have.items():
            r = self.route.get(f)
            if r is None or r.state != R_DIR or r.num != num_:
                continue
            types = types_all if near.get(f) else types_far
            full = sum(bits.values())
            for mask, c in masks.items():
                if r.moved and not rz.is_second(r, self.roots) and mask & full == full:
                    continue                              # перенесено и есть везде - в «отмечено» не входит (ядро)
                n = sum(c[k] for k in types)
                if not n:
                    continue
                b = sum(c[N_TYPES + k] for k in types)
                for x, bit in bits.items():
                    if mask & bit:
                        res[x][0] += n
                        res[x][1] += b
        return {x: tuple(v) for x, v in res.items()}

    def direct_types(self):
        """Файлы прямо в папке (без подпапок) по 9 типам: {папка: ([n0..n8], [b0..b8])} - из сумм таблицы folders, как в
        ядре (razbor.planner: «прочие» n3 минус n5..n8, tree['extra']). От отметок не зависит - один раз на загрузку."""
        got = getattr(self, 'direct_cache', None)
        if got is not None and got[0] is self.folders:
            return got[1]
        extra, z = self.tree.get('extra') or {}, ((0,) * (N_TYPES - 5),) * 2
        sub = {}
        for f in self.order:
            v, ex = self.folders[f], extra.get(f, z)
            n, b = list(v[2]) + list(ex[0]), list(v[3]) + list(ex[1])
            n[hb.F_OTHER] -= sum(ex[0])
            b[hb.F_OTHER] -= sum(ex[1])
            sub[f] = (n, b)
        direct = {f: (list(n), list(b)) for f, (n, b) in sub.items()}
        for f in self.order:
            p = hb.parent_of(f) if f else None
            if p in direct:
                for i in range(N_TYPES):
                    direct[p][0][i] -= sub[f][0][i]
                    direct[p][1][i] -= sub[f][1][i]
        self.direct_cache = (self.folders, direct)
        return direct

    def not_on_disk(self, num_):
        """«На HDD09 нет на H:» (18.11.2026, решение владельца) по каждому диску направления num_, кроме самого носителя:
        файлы ВСЕГО носителя тех типов, что копирует направление (те же типы, «документы рядом» и исключения, что у
        колонки «Уже есть» и в ядре), без подтверждённой копии с тем же SHA-256 на этом диске (маски razbor_have).
        «В отмеченных» - папки, идущие в num_ (столько же, сколько «Копировать на H:» в ячейке: туда входят и файлы
        без хеша - marked_nohash); «в неотмеченных» - остальные файлы с хешем; файлы без хеша в неотмеченных папках -
        отдельно (nohash): есть ли они на диске, проверить нельзя. Только суммы по папкам, без запроса к базе.
        -> {диск: dict(marked, marked_nohash, unmarked, nohash - (файлов, байт), folders - {папка: [неотм. n, b,
        отм. n, b, без хеша n, b, отм. без хеша n, b]} по поддереву)} или None (ещё не посчитано). Кэш - до recalc."""
        cache = getattr(self, 'have_disk_cache', None)
        if cache is None:
            cache = self.have_disk_cache = {}
        if ('not', num_) not in cache:
            cache[('not', num_)] = self._not_on_disk(num_)
        return cache[('not', num_)]

    def _not_on_disk(self, num_):
        d = self.dirs.get(num_)
        if self.have is None or d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
            return None
        near, direct = self.docs_near_map(), self.direct_types()
        types_all = [k for k, cat in CAT_OF_TYPE.items() if cat in d.cats]
        types_far = [k for k in types_all if not (CAT_OF_TYPE[k] == hb.CAT_DOC and d.docs_near)]
        bits = {x: 1 << self.have_disks.index(x) for x in d.disks if x != self.disk}
        own = {x: {} for x in bits}
        for f in self.order:
            types = types_all if near.get(f) else types_far
            masks = self.have.get(f) or {}
            r = self.route.get(f)
            marked = r is not None and r.state == R_DIR and r.num == num_
            un = sum(direct[f][0][k] for k in types) - sum(c[k] for c in masks.values() for k in types)
            ub = sum(direct[f][1][k] for k in types) - sum(c[N_TYPES + k] for c in masks.values() for k in types)
            for x, bit in bits.items():
                n = sum(c[k] for mask, c in masks.items() if not mask & bit for k in types)
                b = sum(c[N_TYPES + k] for mask, c in masks.items() if not mask & bit for k in types)
                if n or un:
                    v = own[x].setdefault(f, [0] * 8)
                    if marked:
                        v[2:4] = [n + un, b + ub]
                        v[6:8] = [un, ub]
                    else:
                        v[0:2] = [n, b]
                        v[4:6] = [un, ub]
        res = {}
        for x in bits:
            sub = {}
            for f in reversed(self.order):                # от глубоких к мелким: сумма по поддереву
                v, cur = own[x].get(f), sub.get(f)
                if v:
                    cur = sub[f] = [a + b for a, b in zip(cur, v)] if cur else list(v)
                if f and cur:
                    p = hb.parent_of(f)
                    sub[p] = [a + b for a, b in zip(sub[p], cur)] if p in sub else list(cur)
            t = sub.get('', [0] * 8)
            res[x] = dict(unmarked=(t[0], t[1]), marked=(t[2], t[3]), nohash=(t[4], t[5]), marked_nohash=(t[6], t[7]),
                          folders=sub)
        return res

    def batch(self):
        """Неизменяемая копия пакета для записи: [(физический путь, решение)] и ключи."""
        return [(d['phys'], d['verdict']) for d in self.drafts.values()], {k: d['verdict'] for k, d in self.drafts.items()}

    def change_lines(self):
        """«было → станет» по каждой записи черновика, вложенные папки, отметки, изменённые в другом месте."""
        lines, conflicts = [], []
        for k, d in sorted(self.drafts.items(), key=lambda kv: kv[1]['path'].lower()):
            f = d['phys']
            where = f'{self.disk}\\{f}' if f else f'{self.disk} (весь носитель)'
            before, after = self.cell(f, True)['text'], self.cell(f)['text'].lstrip('• ')
            lines.append(f'{where}: было «{before}» → станет «{after}»')
            if d['base'] != self.saved_key(k):
                conflicts.append(f'{where}: отметку изменили в другом месте, пока вы отмечали; ваша отметка заменит её.')
        paths = sorted(d['path'].lower() for d in self.drafts.values() if d['path'])
        nested = any(b.startswith(a + SEP) for a in paths for b in paths if a != b) or ('' in self.drafts and paths)
        return lines, conflicts, bool(nested)
