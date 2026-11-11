"""Что лежит на диске и что из этого уже есть на G (HDD45) и HDD77.

Только описи (inventory.sqlite, hashes.sqlite), сами диски не трогает. Работает секунды.

Для каждой папки (по умолчанию — верхнего уровня) выводит:
  файлов, всего ГБ, фото/видео ГБ (файлы с SHA-256), сколько из них есть на G, на HDD77,
  на обоих, и сколько нет ни на G, ни на HDD77.
С ключом --everywhere добавляет колонку «больше нигде»: SHA-256 нет ни на одном другом
отсканированном диске (медленнее: читаются хеши всех дисков).

Совпадение — только по SHA-256 (АЛГОРИТМ, раздел 2). Файлы без хеша (документы, музыка,
программы, мелочь) входят в «всего», но не в сравнение.
ГБ — двоичные (1024³), как показывает Проводник.

Запуск:
  py catalog\\disk_vs_45_77.py HDD17
  py catalog\\disk_vs_45_77.py HDD17 HDD61 --depth 2 --min 1 --everywhere
  py catalog\\disk_vs_45_77.py HDD17 --tsv          (ещё и таблица в «Каталог дисков\\Сверка с 45 и 77»)
  py catalog\\disk_vs_45_77.py HDD61 --list   (Excel: каждый файл, которого нет ни на 45, ни на 77,
                                              и на каких ещё дисках он есть; включает --everywhere)
"""
import argparse
import collections
import io
import sys

import build_pilot as bp

SEP = '\\'
BASE = ('HDD45', 'HDD77')
OUT = bp.OUT_DIR / 'Сверка с 45 и 77'
COLS = ('файлов', 'всего ГБ', 'фото/видео ГБ', 'на G (HDD45)', 'на HDD77', 'на обоих',
        'нет ни на G, ни на HDD77')
MEDIA = ('media_ge_1MiB', 'media_small')


def hashes(job):
    """Путь -> SHA-256 для проверенных хешей диска."""
    with bp.ro(job['dir'] / 'hashes.sqlite') as c:
        return dict(c.execute("select path, sha256 from hashes where status='verified'"))


def sha_set(job):
    """Только множество SHA-256 диска (для G, HDD77 и --everywhere)."""
    with bp.ro(job['dir'] / 'hashes.sqlite') as c:
        return {sha for (sha,) in c.execute("select sha256 from hashes where status='verified'")}


def folder_of(path, depth):
    parts = path.split(SEP)
    if len(parts) == 1:
        return '(файлы в корне)'
    return SEP.join(parts[:min(depth, len(parts) - 1)])


def analyse(disk, jobs, depth, sha_g, sha_77, sha_other, listed=None):
    sha_of = hashes(jobs[disk])
    t = collections.defaultdict(lambda: [0] * (len(COLS) + 1))
    unhashed = {c: [0, 0] for c in MEDIA}  # фото/видео без проверенного хеша: [файлов, байт]
    with bp.ro(jobs[disk]['dir'] / 'inventory.sqlite') as c:
        for path, size, cat in c.execute('select path, size, category from files'):
            r = t[folder_of(path, depth)]
            r[0] += 1
            r[1] += size
            sha = sha_of.get(path)
            if not sha:
                if cat in MEDIA:
                    unhashed[cat][0] += 1
                    unhashed[cat][1] += size
                continue
            g, s77 = sha in sha_g, sha in sha_77
            r[2] += size
            r[3] += size * g
            r[4] += size * s77
            r[5] += size * (g and s77)
            if not g and not s77:
                r[6] += size
                if listed is not None:
                    listed.append((path, size, sorted(sha_other.get(sha, set()) - {disk})))
                if sha_other is not None:
                    others = sha_other.get(sha)
                    if not others or others == {disk}:
                        r[7] += size
    return t, unhashed


def write_list(disk, listed):
    """Excel: файлы диска, которых нет ни на HDD45, ни на HDD77 (по SHA-256)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = 'Нет на 45 и 77'
    ws.append(['Папка', 'Файл', 'МБ', 'Только здесь', 'Есть ещё на дисках'])
    for c in ws[1]:
        c.font = Font(bold=True)
    listed.sort(key=lambda x: x[0].lower())
    for path, size, others in listed:
        folder, _, name = path.rpartition(SEP)
        ws.append([folder, name, round(size / 1024 ** 2, 1), 'да' if not others else '', ', '.join(others)])
    total = sum(x[1] for x in listed)
    only = sum(x[1] for x in listed if not x[2])
    ws.append([])
    ws.append(['ИТОГО', f'{len(listed):,} файлов', round(total / 1024 ** 2, 1),
               f'только здесь {only / bp.GIB:,.1f} ГБ', f'всего {total / bp.GIB:,.1f} ГБ'])
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:E{len(listed) + 1}'
    for col, w in zip('ABCDE', (80, 40, 10, 12, 30)):
        ws.column_dimensions[col].width = w
    OUT.mkdir(parents=True, exist_ok=True)
    name = OUT / f'{disk} - файлы, которых нет на 45 и 77.xlsx'
    wb.save(name)
    return name


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='Сверка диска с HDD45 (G) и HDD77 по описям')
    ap.add_argument('disks', nargs='+', help='номера дисков, например HDD17 HDD61')
    ap.add_argument('--depth', type=int, default=1, help='уровень папок (1 — верхний)')
    ap.add_argument('--min', type=float, default=0.3, help='не показывать папки меньше N ГБ')
    ap.add_argument('--everywhere', action='store_true', help='колонка «больше нигде» по всем дискам')
    ap.add_argument('--list', action='store_true', help='Excel со списком файлов, которых нет ни на 45, ни на 77')
    ap.add_argument('--tsv', action='store_true', help='сохранить таблицу в «Каталог дисков»')
    a = ap.parse_args()
    if a.depth < 1:
        sys.exit('--depth должен быть 1 или больше')
    if a.min < 0:
        sys.exit('--min не может быть отрицательным')

    jobs = bp.find_jobs()
    disks = [d.upper() for d in a.disks]
    base_missing = [d for d in BASE if d not in jobs]
    if base_missing:
        sys.exit(f'Нет скана опорных дисков {", ".join(base_missing)} — сверять не с чем')
    missing = [d for d in disks if d not in jobs]
    if missing:
        sys.exit(f'Нет скана для: {", ".join(missing)}. Есть: {", ".join(sorted(jobs))}')

    sha_g = sha_set(jobs['HDD45'])
    sha_77 = sha_set(jobs['HDD77'])
    if a.list:
        a.everywhere = True
    sha_other = None
    if a.everywhere:
        sha_other = collections.defaultdict(set)
        for d, job in jobs.items():
            if d in BASE:
                continue
            try:
                for sha in sha_set(job):
                    sha_other[sha].add(d)
            except Exception as e:  # битая или пустая база одного диска не должна ронять отчёт
                print(f'Внимание: хеши {d} не прочитаны ({e}); «больше нигде» может быть завышено')

    cols = COLS + (('больше нигде',) if a.everywhere else ())
    for disk in disks:
        listed = [] if a.list else None
        t, unhashed = analyse(disk, jobs, a.depth, sha_g, sha_77, sha_other, listed)
        total = [sum(r[i] for r in t.values()) for i in range(len(cols))]
        rows = sorted(t.items(), key=lambda kv: -kv[1][1])
        shown = [(k, r) for k, r in rows if r[1] >= a.min * bp.GIB]
        print(f'\n===== {disk}: {total[0]:,} файлов, {total[1] / bp.GIB:,.1f} ГБ '
              f'(фото/видео {total[2] / bp.GIB:,.1f} ГБ)')
        print(' | '.join(('папка',) + cols))
        for k, r in shown + [('ИТОГО', total)]:
            print(' | '.join([k, f'{r[0]:,}'] + [f'{x / bp.GIB:,.1f}' for x in r[1:len(cols)]]))
        n, b = unhashed['media_ge_1MiB']
        if n:
            print(f'ВНИМАНИЕ: фото/видео от 1 МБ без проверенного SHA-256 (в сравнение не вошли): '
                  f'{n:,} файлов, {b / bp.GIB:,.1f} ГБ')
        n, b = unhashed['media_small']
        if n:
            print(f'Мелкие фото/видео до 1 МБ (сканер их не хеширует, в сравнение не вошли): '
                  f'{n:,} файлов, {b / bp.GIB:,.1f} ГБ')
        if len(shown) < len(rows):
            print(f'(ещё {len(rows) - len(shown)} папок меньше {a.min} ГБ — в ИТОГО учтены)')
        if a.tsv:
            OUT.mkdir(parents=True, exist_ok=True)
            name = OUT / f'{disk} - глубина {a.depth}.tsv'
            with io.open(name, 'w', encoding='utf-8-sig', newline='\r\n') as f:
                f.write('\t'.join(('папка',) + cols) + '\n')
                for k, r in rows + [('ИТОГО', total)]:
                    f.write('\t'.join([k, str(r[0])] + [f'{x / bp.GIB:.2f}' for x in r[1:len(cols)]]) + '\n')
            print('Таблица:', name)
        if a.list:
            print('Список файлов:', write_list(disk, listed))


if __name__ == '__main__':
    main()
