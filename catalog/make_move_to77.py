"""Готовит перемещение внутри HDD59 (K:) в папку «На HDD77» (только описи, диск не трогает).

В список попадает файл HDD59, который:
  - фото/видео с SHA-256: этот хеш есть на HDD45 и нет на HDD77;
  - прочий файл (без хеша): на HDD45 есть файл с тем же именем и размером, на HDD77 — нет.
Файлы из «ОСТАЕТСЯ ТУТ» и уже лежащие в «На HDD77» не берутся.

Результат в «Каталог дисков\\K - На HDD77»:
  список.tsv            относительный путь <TAB> размер — что перемещать
  Переместить на HDD77.ps1  скрипт для пользователя (просмотр, подтверждение, журнал)

Запуск:  py catalog\\make_move_to77.py
"""
import collections
import io

import build_pilot as bp

SEP = '\\'
SRC, HAVE, LACK = 'HDD59', 'HDD45', 'HDD77'
KEEP = ('ОСТАЕТСЯ ТУТ' + SEP, 'На HDD77' + SEP)
OUT = bp.OUT_DIR / 'K - На HDD77'
VOLUME_SERIAL = '1EB90771'


def ro(path):
    return bp.ro(path)


def main():
    jobs = bp.find_jobs()
    sha_disks = collections.defaultdict(set)
    for disk, job in jobs.items():
        with ro(job['dir'] / 'hashes.sqlite') as c:
            for (sha,) in c.execute("select sha256 from hashes where status='verified'"):
                sha_disks[sha].add(disk)
    name_size = {}
    for disk in (HAVE, LACK):
        s = set()
        with ro(jobs[disk]['dir'] / 'inventory.sqlite') as c:
            for p, size in c.execute('select path, size from files'):
                s.add((p.rsplit(SEP, 1)[-1].lower(), size))
        name_size[disk] = s
    with ro(jobs[SRC]['dir'] / 'hashes.sqlite') as c:
        src_sha = dict(c.execute("select path, sha256 from hashes where status='verified'"))
    rows = []
    with ro(jobs[SRC]['dir'] / 'inventory.sqlite') as c:
        for p, size in c.execute('select path, size from files'):
            if p.startswith(KEEP):
                continue
            sha = src_sha.get(p)
            if sha:
                ok = HAVE in sha_disks[sha] and LACK not in sha_disks[sha]
            else:
                key = (p.rsplit(SEP, 1)[-1].lower(), size)
                ok = key in name_size[HAVE] and key not in name_size[LACK]
            if ok:
                rows.append((p, size, 'хеш' if sha else 'имя+размер'))
    rows.sort()
    OUT.mkdir(parents=True, exist_ok=True)
    with io.open(OUT / 'список.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for p, size, how in rows:
            f.write(f'{p}\t{size}\t{how}\n')
    by = collections.Counter(how for _, _, how in rows)
    vol = sum(s for _, s, _ in rows)
    print(f'Файлов {len(rows):,}, {vol / 1024 ** 3:,.1f} ГБ; по хешу {by["хеш"]:,}, по имени и размеру {by["имя+размер"]:,}')
    print('Готово:', OUT)


if __name__ == '__main__':
    main()
