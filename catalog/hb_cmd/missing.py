"""Команда missing, only."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
from hb_core.consts import MAIN, SEP
from hb_core.util import gb, is_drop, out
from hb_core.report import save, table
from hb_core.db import connect
from hb_core.query import check_disk, decision_of, decisions_for, folder_key, issues_for, presence, unhashed_note, unhashed_report


# ---------- команды ----------

def cmd_missing(a, only=False):
    c, jobs = connect()
    check_disk(c, a.disk)
    prefix = (a.folder or '').rstrip(SEP)
    rows = presence(c, a.disk, prefix, weak=True)
    decs = decisions_for(a.disk)
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # файлов, байт, нет45, нет77, нет обоих, только тут
    detail, dropped = [], [0, 0]
    sections = collections.defaultdict(lambda: [0, 0, 0, 0])    # решение: файлов, байт, без копий где-либо: файлов, байт
    weak45 = weak77 = 0
    for path, size, sha, on45, on77, ndisks, w45, w77 in rows:
        v = decision_of(path, decs)
        if is_drop(v):
            dropped[0] += 1; dropped[1] += size
            continue
        if v:                                    # раздел или отсрочка: сохранять НУЖНО, но не на 45 и 77
            s = sections[v]
            s[0] += 1; s[1] += size
            if ndisks == 1:
                s[2] += 1; s[3] += size
            continue
        if only and ndisks > 1:
            continue
        k = agg[folder_key(path, prefix, a.depth)]
        k[0] += 1; k[1] += size
        if not on45: k[2] += size
        if not on77: k[3] += size
        if not on45 and not on77: k[4] += size
        if ndisks == 1: k[5] += size
        weak45 += (not on45) and bool(w45); weak77 += (not on77) and bool(w77)
        if only or not (on45 and on77):
            detail.append((path, size, 'да' if on45 else ('не подтверждено' if w45 else 'нет'),
                           'да' if on77 else ('не подтверждено' if w77 else 'нет'), ndisks - 1, sha))
    title = f'{a.disk}' + (f'\\{prefix}' if prefix else '')
    what = 'только на этом диске' if only else f'чего нет на {MAIN[0]} и {MAIN[1]}'
    out(f'{title}: {what} (ГБ, только файлы с SHA-256; всего таких {len(rows)})')
    out('Копией считается только подтверждённая: хеш измерен сканером или сверен скриптом при копировании.')
    tot = [sum(v[i] for v in agg.values()) for i in range(6)]
    head = ('папка', 'файлов', 'всего', f'нет на {MAIN[0]}', f'нет на {MAIN[1]}', 'нет на обоих', 'больше нигде')
    order = sorted(agg.items(), key=lambda kv: -(kv[1][1] if only else max(kv[1][2], kv[1][3])))
    body = [(k[:60], v[0], gb(v[1]), gb(v[2]), gb(v[3]), gb(v[4]), gb(v[5])) for k, v in order
            if only or v[2] or v[3]]
    table(head, body, total=('ИТОГО', tot[0], gb(tot[1]), gb(tot[2]), gb(tot[3]), gb(tot[4]), gb(tot[5])))
    if weak45 or weak77:
        out(f'Из «нет»: на {MAIN[0]} у {weak45} файлов и на {MAIN[1]} у {weak77} лежит НЕПОДТВЕРЖДЁННАЯ копия '
            f'(сверен только размер или со слов пользователя). Копией она не считается, пока файл не прочитан.')
    if sections:
        out('')
        out('По решениям пользователя (в таблицу выше не входят; сохранять их НУЖНО, место - по решению):')
        table(('решение', 'файлов', 'ГБ', 'без подтверждённой копии где-либо ещё: файлов', 'ГБ'),
              [(k[:50], v[0], gb(v[1]), v[2], gb(v[3])) for k, v in sorted(sections.items(), key=lambda kv: -kv[1][1])])
    if dropped[0]:
        out(f'По решению «не нужно» не показано: {dropped[0]} файлов, {gb(dropped[1])} ГБ')
    iss = issues_for(c, a.disk, prefix)
    if iss:
        out(f'ВНИМАНИЕ: опись неполная - сканер не прочитал {len(iss)} мест в этой области; файлы оттуда программе неизвестны.')
    tag = f'{a.disk} {prefix.replace(SEP, " - ")}'.strip()
    p = save(f'{"только" if only else "нет на 45 и 77"} - {tag}',
             ('путь', 'размер', f'на {MAIN[0]}', f'на {MAIN[1]}', 'на скольких других дисках', 'SHA-256'), sorted(detail))
    out(f'По файлам ({len(detail)}): {p}')
    if only:
        unhashed_report(c, a.disk, prefix, [d for d in decs if is_drop(d[1])], f'только, без хеша - {tag}')
    else:
        unhashed_note(c, a.disk, prefix)

NAMES = ('missing', 'only')
HELP = {'missing': 'чего с диска нет на 45 и 77, по папкам', 'only': 'что лежит только на этом диске'}


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('folder', nargs='?', default='')
    p.add_argument('--depth', type=int, default=1)


def run(a):
    cmd_missing(a, a.cmd == 'only')
