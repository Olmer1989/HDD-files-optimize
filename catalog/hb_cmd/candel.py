"""Команда candel."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
from hb_core.consts import CLASS_ORDER, C_EMPTY, MAIN, SEP
from hb_core.util import gb, is_drop, out
from hb_core.report import save, table
from hb_core.db import connect
from hb_core.query import CAND_NOTE, NAME_ONLY, RENAMED_NOTE, candidates, renamed, check_disk, class_rules, decision_of, decisions_for, evidence_notes, issues_for, presence, unhashed


def cmd_candel(a):
    """Можно ли удалять. «ДА» - только когда у КАЖДОГО файла есть подтверждённые копии на обоих главных дисках,
    не считая удаляемого, опись полна и ничего не исключено по умолчанию. Иначе «НЕТ» или «НЕДОСТАТОЧНО»."""
    c, jobs = connect()
    check_disk(c, a.disk)
    folder = (a.folder or '').rstrip(SEP)
    decs, crules = decisions_for(a.disk), class_rules(a.disk)
    rows = presence(c, a.disk, folder, exclude=(a.disk, folder), weak=True)
    rest = unhashed(c, a.disk, folder)
    if not rows and not rest:
        out('В базе нет файлов по этому пути (проверьте написание пути и номер диска).')
        return
    reasons = []
    status = (c.execute('select status from disks where disk=?', (a.disk,)).fetchone() or ['?'])[0] or '?'
    if not status.startswith('complete'):
        reasons.append(f'опись диска не завершена (состояние «{status}»)')
    iss = issues_for(c, a.disk, folder)
    if iss:
        reasons.append(f'опись неполная: сканер не прочитал {len(iss)} мест в этой области (первое: «{iss[0][0] or "корень диска"}»)')
    reasons += evidence_notes(c)

    dropped, lack, weak_only = 0, [], 0
    for p, s, sha, o45, o77, n, w45, w77 in rows:
        if is_drop(decision_of(p, decs)):
            dropped += 1
            continue
        if not (o45 and o77):
            lack.append((p, s, 'да' if o45 else ('не подтверждено' if w45 else 'нет'),
                         'да' if o77 else ('не подтверждено' if w77 else 'нет'), sha))
            weak_only += bool((o45 or w45) and (o77 or w77))
    # Файл с хешем, у которого на недостающем главном диске нет подтверждённой копии, но лежит тот же файл без хеша
    # (ev N, то же имя и размер): это не «нет», а «не подтверждено» - как тот же файл без хеша. «НЕТ» остаётся, если
    # хотя бы на одном недостающем диске кандидата без хеша нет (в том числе при Z/U/X - правило прежнее).
    cand = candidates(c, a.disk, [r[0] for r in lack], targets=MAIN, exclude=(a.disk, folder))
    probable = []
    for r in list(lack):
        cm = cand.get(r[0], {})
        if all(r[2 + i] == 'да' or MAIN[i] in cm for i in (0, 1)):
            lack.remove(r)
            probable.append(r)
    if probable:
        weak_only = sum(1 for r in lack if 'нет' not in (r[2], r[3]))
    unconf = collections.defaultdict(lambda: [0, 0, 0])            # класс: файлов, байт, из них копия не найдена нигде
    unconf_rows = []
    for p, s, nm, k, others, dup in rest:
        if k == C_EMPTY:
            continue                                               # пустой файл: терять нечего
        if is_drop(decision_of(p, decs)) or is_drop(crules.get(k.lower())):
            dropped += 1
            continue
        u = unconf[k]
        u[0] += 1; u[1] += s; u[2] += others == 0
        unconf_rows.append((p, s, k, 'копия не найдена нигде' if others == 0 else NAME_ONLY))
    confirmed = len(rows) - len(lack) - len(probable)
    for r in probable:
        unconf_rows.append((r[0], r[1], 'с хешем, копия без хеша',
                            f'{NAME_ONLY} на ' + ', '.join(MAIN[i] for i in (0, 1) if r[2 + i] != 'да')))
    # подсказка «возможно, переименована» (тот же размер и дата, другое имя, от 1 МБ) - вердикт не меняет
    hint = renamed(c, a.disk, [r[0] for r in lack] + [r[0] for r in unconf_rows if r[3] == 'копия не найдена нигде'],
                   targets=MAIN, exclude=(a.disk, folder))
    lack = [r + ('возможно, переименована: ' + ', '.join(f'{d}: {q}' for d, q in sorted(hint[r[0]].items()))
                 if r[0] in hint else '',) for r in lack]
    unconf_rows = [r[:3] + (r[3] + ('; возможно, переименована: ' + ', '.join(f'{d}: {q}' for d, q in sorted(hint[r[0]].items()))
                                    if r[0] in hint and r[3] == 'копия не найдена нигде' else ''),) for r in unconf_rows]

    out(f'{a.disk}\\{folder}: проверка перед удалением')
    out(f'Файлов с подтверждённым SHA-256: {len(rows)}, {gb(sum(r[1] for r in rows))} ГБ')
    out(f'  подтверждённые копии есть и на {MAIN[0]}, и на {MAIN[1]} (не считая удаляемого): {confirmed}')
    out(f'  нет хотя бы на одном: {len(lack)}, {gb(sum(r[1] for r in lack))} ГБ'
        + (f' (у {weak_only} из них копии лежат, но не подтверждены: сверен только размер или со слов)' if weak_only else ''))
    if probable:
        out(f'  только вероятная копия на {MAIN[0]}/{MAIN[1]}: {len(probable)}, {gb(sum(r[1] for r in probable))} ГБ '
            f'({CAND_NOTE})')
    n_unconf = sum(v[0] for v in unconf.values()) + len(probable)
    if unconf:
        out(f'Файлов БЕЗ подтверждённого хеша: {n_unconf - len(probable)}, {gb(sum(v[1] for v in unconf.values()))} ГБ - '
            f'их сохранность доказать нечем:')
        table(('класс', 'файлов', 'ГБ', 'копия не найдена нигде'),
              [(k, unconf[k][0], gb(unconf[k][1]), unconf[k][2]) for k in CLASS_ORDER if k in unconf])
    if hint:
        out(f'Подсказка: у {len(hint)} файлов без копии на {MAIN[0]}/{MAIN[1]} есть файл того же размера и даты с другим '
            f'именем ({RENAMED_NOTE}).')
    if dropped:
        out(f'Исключено решениями «не нужно»: {dropped} файлов.')
    for r in reasons:
        out('ВНИМАНИЕ: ' + r)
    if lack:
        out(f'ОТВЕТ: НЕТ - у {len(lack)} файлов нет подтверждённой копии на обоих дисках. Удалять нельзя.')
    elif reasons or n_unconf:
        out('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ - удалять по этому ответу нельзя.')
        if n_unconf:
            out('  Что можно сделать: посчитать этим файлам хеши (окно: «Пересканировать папку…» - хеш считается у всех '
                'файлов; и у копий на 45 и 77, если их хеш не считался); либо владелец записывает решение «не нужно» '
                'для папки или для класса (строка «класс: <название>» в решения.tsv).')
    else:
        out(f'ОТВЕТ: ДА - у каждого файла есть подтверждённые копии на {MAIN[0]} и {MAIN[1]}, не считая удаляемого.')
    tag = f'{a.disk} {folder}'.replace(SEP, ' - ')
    if lack:
        marked = any(r[5] for r in lack)                       # столбец «пометка» - только если есть подсказки
        head = ('путь', 'размер', 'на ' + MAIN[0], 'на ' + MAIN[1], 'SHA-256') + (('пометка',) if marked else ())
        out(f'Чего не хватает: {save(f"нельзя удалять - {tag}", head, sorted(r if marked else r[:5] for r in lack))}')
    if unconf_rows:
        out(f'Файлы без подтверждения: {save(f"нельзя удалять, без подтверждения - {tag}", ("путь", "размер", "класс", "что известно"), sorted(unconf_rows))}')
    out('Основание: описи, журналы скриптов, таблицы ручных операций и решений; диски не читались. Удаляет только пользователь.')

NAMES = ('candel',)
HELP = 'можно ли удалять: есть ли всё на 45 и на 77'
# для окна «Архив дисков» (раздел «Команды»); командная строка их не использует
GUI_GROUP, GUI_ORDER = 'Вопросы о диске', 5
GUI_TITLE = 'Можно ли удалить папку с этого диска?'
GUI_HINT = ('Проверяет, есть ли у каждого файла папки подтверждённые копии и на 45, и на 77 (саму удаляемую папку '
            'не считает).\nОтвет: «ДА» — можно удалять; «НЕТ» — части файлов нет на 45 или 77; '
            '«НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ» — есть файлы без хеша, опись неполная или копии не подтверждены.\n'
            'Сама программа ничего не удаляет.')
GUI_ARGS = {'disk': 'Диск, с которого хотите удалить', 'folder': 'Папка, которую хотите удалить'}


def add_args(p, name):
    p.add_argument('disk'); p.add_argument('folder')


def run(a):
    cmd_candel(a)
