"""Логика v3: направления разбора и отметки папок (15.11.2026, «Логика_v3_разбор_носителя.md», раздел 1).

Направления - таблица «_БАЗА\\направления.tsv» (номер, имя, прежние имена, диски, что копировать, комментарий).
Строки только дописываются: каждая строка - полная новая версия направления с этим номером, действует последняя.
Прежние имена = колонка последней строки + все прежние имена этого номера из истории (переименование не ломает
старые отметки «раздел: <старое имя>»).

Отметки - строки «решения.tsv» новых видов: «направление: Н3 <имя>», «не копировать», «как у родителя»; пустой путь -
отметка всего носителя (режим разбора). Читает их только маршрут (MarkSet); старые команды (query.decisions_for) их
не видят. Старые строки читаются так: «не нужно» и «пока не трогаем» -> «не копировать»; «раздел: X» -> направление
с именем или прежним именем X, иначе «направление не задано (раздел X)»; строки «класс: …» маршрут не учитывает.

Порядок (раунд 2 спора с GPT, п. 16): строки применяются строго в порядке файла, строки диска «*» и своего диска -
одним потоком; ключ - путь без учёта регистра; «как у родителя» снимает любую действующую отметку этого пути.
Черновые (несохранённые) отметки окна применяются ПОСЛЕ сохранённых тем же механизмом, с отрицательными номерами.
Здесь нет обращений к базе: только таблицы владельца.
"""
import collections
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from hb_core import paths
from hb_core.consts import DIRECTION_HEAD, KIND_ALL, KIND_MEDIA, MARK_DIR, MARK_INHERIT, MARK_SKIP, SEP
from hb_core.util import copied_folder, disk_nums, tsv_rows

DIR_NAME_BAD = set('\\/:*?"<>|;')
DIR_NAME_MAX = 30
KINDS = (KIND_MEDIA, KIND_ALL)
# состояния маршрута
R_DIR, R_SKIP, R_UNSET, R_NONE = 'направление', 'не копировать', 'не задано', 'не отмечено'


@dataclass(frozen=True)
class Direction:
    num: str                    # «Н1»
    name: str
    former: tuple = ()
    disks: tuple = ()
    kind: str = KIND_ALL
    note: str = ''
    desc: str = field(default=None, compare=False)   # None - строка без 7-й колонки (наследует описание)

    @property
    def media_only(self):
        return self.kind == KIND_MEDIA

    def label(self):
        return f'{self.name} ({disk_nums(self.disks)})' if self.disks else f'{self.name} (диск не назначен)'

    def folder(self):
        """Имя папки на носителе после переноса; у направления без диска - None."""
        return copied_folder(self.name, self.disks) if self.disks else None

    def verdict(self):
        return f'{MARK_DIR} {self.num} {self.name}'


def num_key(num):
    try:
        return int(str(num)[1:])
    except ValueError:
        return 10 ** 9


def norm_num(text):
    """«Н3», «н3», «H3» (латиница), «3» -> «Н3»; иначе None."""
    t = (text or '').strip()
    if t[:1] in ('Н', 'н', 'H', 'h'):
        t = t[1:]
    return f'Н{int(t)}' if t.isdigit() else None


def table_bytes(path):
    """Таблица целиком в памяти: снимок для расчёта и его подпись (sha1 тех самых байтов)."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return b''


def signature(*blobs):
    return hashlib.sha1(b'\0'.join(blobs)).hexdigest()[:16]


def _rows(data):
    data = data[:data.rfind(b'\n') + 1]              # только целые строки (как read_table)
    return tsv_rows(data)


def parse_directions(data):
    """Байты направления.tsv -> {номер: Direction} (последняя строка номера), по возрастанию номера."""
    cur, names_seen, descs = {}, collections.defaultdict(list), {}
    for f in _rows(data):
        has_desc = len(f) >= 7
        f = [x.strip() for x in f] + [''] * 7
        num = norm_num(f[0])
        if not num or not f[1]:
            continue                                   # заголовок и пустые строки
        names_seen[num].append(f[1])
        former = [x.strip() for x in f[2].split(';') if x.strip()]
        disks = tuple(dict.fromkeys(x.strip() for x in f[3].split(',') if x.strip()))
        kind = f[4] if f[4] in KINDS else KIND_ALL
        cur[num] = (f[1], former, disks, kind, f[5])
        if has_desc:
            descs[num] = f[6]
    res = {}
    for num in sorted(cur, key=num_key):
        name, former, disks, kind, note = cur[num]
        allf = []
        for x in former + names_seen[num]:
            if x.casefold() != name.casefold() and x.casefold() not in {y.casefold() for y in allf}:
                allf.append(x)
        res[num] = Direction(num, name, tuple(allf), disks, kind, note, descs.get(num, ''))
    return res


def read_directions(data=None):
    return parse_directions(table_bytes(paths.DIRECTIONS) if data is None else data)


def find_direction(dirs, text, by_num=True):
    """Направление по номеру («Н3», «Н3 Работа» - главное номер), имени или прежнему имени (без учёта регистра)."""
    t = (text or '').strip()
    if by_num and t.split():
        num = norm_num(t.split()[0])
        if num in dirs:
            return dirs[num]
    for d in dirs.values():
        if t.casefold() == d.name.casefold():
            return d
    for d in dirs.values():
        if t.casefold() in {x.casefold() for x in d.former}:
            return d
    return None


def direction_of_disk(dirs, disk):
    for d in dirs.values():
        if disk in d.disks:
            return d
    return None


def check_name(name):
    """Ошибка в имени направления (текст) или None."""
    n = (name or '').strip()
    if not n:
        return 'Имя направления пустое.'
    if len(n) > DIR_NAME_MAX:
        return f'Имя длиннее {DIR_NAME_MAX} знаков (оно входит в путь на носителе): «{n}».'
    bad = sorted(set(n) & DIR_NAME_BAD)
    if bad:
        return f'В имени нельзя использовать символы {" ".join(bad)} (они запрещены в имени папки Windows или служебные).'
    return None


def direction_row(d):
    row = [d.num, d.name, '; '.join(d.former), ', '.join(d.disks), d.kind, d.note]
    return row + [d.desc] if d.desc is not None else row      # без описания - 6 колонок: описание наследуется


# ---------- отметки ----------

@dataclass(frozen=True)
class Mark:
    kind: str                   # R_DIR / R_SKIP / R_UNSET
    num: str = None             # номер направления (R_DIR)
    label: str = ''             # для чтения человеком
    row: int = 0                # номер строки в решения.tsv (черновик - отрицательный)
    path: str = ''              # исходный путь отметки ('' - весь носитель)
    verdict: str = ''           # текст решения как записан
    legacy: bool = False        # старая строка («раздел: …», «не нужно», «пока не трогаем»)


def parse_verdict(verdict, dirs):
    """Текст решения -> (вид, номер направления, подпись, старая ли строка). «как у родителя» -> вид MARK_INHERIT."""
    v = (verdict or '').strip()
    low = v.lower()
    if low.startswith(MARK_DIR):
        rest = v.split(':', 1)[1].strip()
        d = find_direction(dirs, rest)
        if d:
            return R_DIR, d.num, d.name, False
        return R_UNSET, None, f'нет направления «{rest}»', False
    if low == MARK_SKIP:
        return R_SKIP, None, MARK_SKIP, False
    if low == MARK_INHERIT:
        return MARK_INHERIT, None, MARK_INHERIT, False
    if low.startswith('не нужно'):
        return R_SKIP, None, 'не нужно', True
    if low.startswith('пока не трогаем'):
        return R_SKIP, None, 'пока не трогаем', True
    if low.startswith('раздел:'):
        name = v.split(':', 1)[1].strip()
        d = find_direction(dirs, name, by_num=False)
        if d:
            return R_DIR, d.num, d.name, True
        return R_UNSET, None, f'раздел: {name}', True
    return R_UNSET, None, v, True


def mark_rows(disk, data):
    """Строки решения.tsv для носителя (и «*») в порядке файла: [(номер строки, путь, решение)]. Номер строки -
    как у service (заголовок - строка 1). Строки «класс: …» пропускаются."""
    res = []
    for i, f in enumerate(_rows(data), start=1):
        f = [x.strip() for x in f] + [''] * 4
        if i == 1 and f[0].lower() == 'диск':
            continue
        if f[0] in (disk, '*') and f[2] and not f[1].lower().startswith('класс:'):
            res.append((i, f[1].strip(SEP), f[2]))
    return res


@dataclass
class MarkSet:
    """Действующие отметки одного носителя: ключ - путь в нижнем регистре."""
    by_key: dict = field(default_factory=dict)

    @classmethod
    def build(cls, rows, dirs, drafts=()):
        """rows - mark_rows(); drafts - [(путь, решение)] черновика окна, применяются после (номера -1, -2, …)."""
        ms = cls()
        events = list(rows) + [(-(i + 1), p.strip(SEP), v) for i, (p, v) in enumerate(drafts)]
        for row, path, verdict in events:
            kind, num, label, legacy = parse_verdict(verdict, dirs)
            key = path.lower()
            if kind == MARK_INHERIT:
                ms.by_key.pop(key, None)
            else:
                ms.by_key[key] = Mark(kind, num, label, row, path, verdict, legacy)
        return ms

    def get(self, path):
        return self.by_key.get((path or '').strip(SEP).lower())

    def __len__(self):
        return len(self.by_key)

    def paths(self):
        return [m.path for m in self.by_key.values()]


def mark_text(m, dirs):
    if m is None:
        return 'как у родителя'
    if m.kind == R_DIR:
        d = dirs.get(m.num)
        return d.label() if d else m.label
    if m.kind == R_UNSET:
        return f'направление не задано ({m.label})'
    return m.label
