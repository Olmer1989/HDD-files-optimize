"""Команда mvlist (часть 3, разбивка 17.11.2026): логика v3 - путь назначения, отчёт, запись задания, повторная проверка."""
import io
import shutil
import sys
from pathlib import Path
from hb_core import paths
from hb_core.consts import SEP
from hb_core.util import copied_tail, gb, out
from hb_core.sources import read_tsv
from hb_core.mvlist_v1 import _n
from hb_core.mvlist_v3 import V3_META, ROOT_WORD, _write_json, plan_v3

def dest_path(row):
    """Строка перемещение.tsv -> путь после переноса (7-я колонка «снять» - второй проход, этап 13)."""
    # имена папок - как записаны: пробелы не обрезаются (этап 16), только «\» и перевод строки последнего поля
    path, folder = row[0], str(row[3]).strip(SEP + '\r\n')
    strip = str(row[6]).strip(SEP + '\r\n') if len(row) >= 7 else ''
    if strip and path.startswith(strip + SEP):
        return folder + SEP + path[len(strip) + 1:]
    return folder + SEP + path


def report_v3(res):
    src = res['src']
    where = src['folder'] or ROOT_WORD
    n_, b_ = len(res['lines']), sum(r[1] for r in res['lines'])
    how = 'папкой целиком, одним переименованием' if res['whole'] else 'по файлам, все пути сохраняются'
    if res.get('strip'):
        r1 = res['strip']
        inner = where[len(r1) + 1:] if where.startswith(r1 + SEP) else ''
        out(f'{src["disk"]}: вторая копия ({", ".join(src["disks"])}) - «{where}» переедет в «{res["dest"]}» '
            '(по сведениям базы)')
        if res['lines']:
            out(f'  -> {src["disk"]}:\\{res["dest"]}\\{inner + SEP if inner else ""}…: {_n(n_)} файлов, {gb(b_)} ГБ - {how}')
    else:
        out(f'{src["disk"]}: перенести папку «{where}» в «{res["dest"]}» (по сведениям базы)')
        if res['lines']:
            out(f'  -> {src["disk"]}:\\{res["dest"]}\\{src["folder"] or ""}{SEP if src["folder"] else ""}…: '
                f'{_n(n_)} файлов, {gb(b_)} ГБ - {how}')
    out(f'Всего в папке по описи: {_n(res["total"][0])} файлов, {gb(res["total"][1])} ГБ.')
    for why, (k, b) in sorted(res['stays'].items()):
        out(f'Остаются на месте - {why}: {_n(k)} файлов, {gb(b)} ГБ')
    for why, k in res['via'].items():
        out(f'  из них {_n(k)} файлов без хеша в описи подтверждены {why}')
    if res['lines'] and not res['whole'] and src['folder']:
        out('Папка уходит по файлам: на старом месте останутся перечисленные выше файлы и пустые папки.')
    out(f'Можно перенести: {_n(n_)} файлов, {gb(b_)} ГБ. Ничего не удаляется и не перезаписывается, все подпапки '
        'сохраняются. Содержимое источника перед перемещением не проверялось: шаблон сверяет размер и дату с описью.')


def _write_task_v3(name, res, serial):
    import time
    src = res['src']
    task = paths.TASKS / name
    task.mkdir(parents=True, exist_ok=False)
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{src["disk"]}\t{serial}\n')
    with io.open(task / 'перемещение.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in res['lines']:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(task / 'папки целиком.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in res['whole']:
            f.write('\t'.join(map(str, r)) + '\n')
    write_roots(task, res)
    for fn in ('Переместить.ps1', 'Запустить.cmd'):
        shutil.copy2(paths.MOVE_TEMPLATE / fn, task / fn)
    _write_json(task / V3_META, {
        'версия': 3, 'носитель': src['disk'], 'задание копирования': src['copy_task'], 'манифест': src['manifest'],
        'папка': src['folder'], 'ключ': src['key'], 'направление': src['num'], 'имя направления': src['direction'],
        'обязательные диски': src['disks'], 'отметка': src['mark'], 'строка отметки': src['mark_row'],
        'группа': src.get('group'),
        'перемещать на носителе': src['allowed'], 'куда': res['dest'], 'целиком': bool(res['whole']),
        'снять': res.get('strip'), 'части': res.get('parts') or [copied_tail(src['direction'], src['disks'])],
        'файлов': len(res['lines']), 'байт': sum(r[1] for r in res['lines']), 'всего в папке': res['total'],
        'остаток': res['stays'], 'создано': time.strftime('%d.%m.%Y %H:%M'), 'создано_ts': time.time()})
    (task / 'Как запустить.txt').write_text(
        f'Задание: перенести на носителе {src["disk"]} папку «{src["folder"] or ROOT_WORD}» в «{res["dest"]}».\n'
        f'Файлов: {len(res["lines"])}, {gb(sum(r[1] for r in res["lines"]))} ГБ; '
        + ('папкой целиком (одно переименование).\n' if res['whole'] else 'по файлам.\n') +
        'Все папки и подпапки сохраняются: K:\\Поход 2010\\Фото\\1.jpg -> K:\\<папка переноса>\\Поход 2010\\Фото\\1.jpg.\n'
        'Ничего не удаляется и не перезаписывается: это переименование внутри того же диска.\n\n'
        'Запускайте из окна программы («Задания» -> «Можно переместить на носителе»): окно перед запуском ещё раз\n'
        'проверит задание по свежей базе. Двойной щелчок по «Запустить.cmd» этой проверки не делает.\n'
        f'Q - остановиться после текущей операции; повторный запуск продолжит и сам восстановит прерванный перенос\n'
        'по записи намерения («Намерение перемещения.tsv»).\n', encoding='utf-8-sig')
    return task


def write_roots(task, res):
    """корни.tsv для шаблона: служебные папки носителя (источник не может лежать в них) и папка назначения -
    «известен» (её создал журнал перемещения, она в базе) или «новый» (создаст этот шаблон)."""
    rows = [(r, 'известен') for r in res['roots'] if r != res['dest']]
    rows.append((res['dest'], 'известен' if res['known'] else 'новый'))
    tmp = Path(task) / 'корни.tsv.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write('\t'.join(r) + '\n')
    import os
    os.replace(tmp, Path(task) / 'корни.tsv')


def recheck_v3(c, jobs, task, meta):
    src = dict(copy_task=meta.get('задание копирования'), copy_dir=None, manifest=meta.get('манифест'),
               disk=meta['носитель'], folder=meta.get('папка'), key=meta.get('ключ'), num=meta['направление'],
               direction=meta['имя направления'], disks=list(meta['обязательные диски']), mark=meta['отметка'],
               mark_row=meta['строка отметки'], allowed=meta.get('перемещать на носителе', True), group=meta.get('группа'))
    rows = [f for f in read_tsv(task / 'перемещение.tsv') if len(f) >= 4]
    res = plan_v3(c, jobs, src, only={f[0] for f in rows})
    # строка верна, только если совпадают путь, папка назначения и «снять» (этап 13: второй проход)
    ok = {(r[0], str(r[3]), str(r[6]) if len(r) >= 7 else '') for r in res['lines']}
    bad = [f[0] for f in rows if (f[0], f[3].strip(), f[6].strip() if len(f) >= 7 else '') not in ok and not
           c.execute('select 1 from files where disk=? and path=?', (src['disk'], dest_path(f))).fetchone()]
    if bad:
        out(f'Задание перемещения устарело: {len(bad)} из {len(rows)} файлов больше не проходят проверку '
            f'(например «{bad[0]}»).')
        sys.exit('Соберите задание заново: «Задания» -> «Можно переместить на носителе».')
    write_roots(task, res)
    out(f'Проверено: все {len(rows)} строк задания перемещения по-прежнему верны (диск {src["disk"]}).')
