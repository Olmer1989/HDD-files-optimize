"""Готовит копирование на G (HDD45) того, чего там нет, с HDD55 (I:) и HDD51 (J:).

Только описи, диски не трогает. В список попадает:
  - фото и видео с SHA-256, которого нет на HDD45 (в том числе «спорные»: на G есть
    файл с тем же именем и размером, но другим хешем — АЛГОРИТМ, раздел 2);
  - файлы, названные пользователем явно (EXTRA).
Не берутся папки фильмов и музыки (на G не нужны) и прочие файлы без хеша.

Результат в «Каталог дисков\\Копирование на G - I и J»:
  список.tsv  — диск <TAB> относительный путь <TAB> размер <TAB> пометка
  Копировать на G.ps1 — скрипт для пользователя

Запуск:  py catalog\\make_copy_to_g.py
"""
import collections
import io
import json

import build_pilot as bp

SEP = '\\'
TARGET = 'HDD45'
SOURCES = {
    'HDD55': ('Фильмы в HD качестве', 'Отбор фильмов с Роменом Дюри', 'Фильмы HD-Rip', 'Мультфильмы'),
    'HDD51': ('Фильмы', 'Music'),
}
EXTRA = {('HDD51', 'На разборку\\Сен Мишель - розовый гранит.iso')}
OUT = bp.OUT_DIR / 'Копирование на G - I и J'


def main():
    jobs = bp.find_jobs()
    on_g = set()
    with bp.ro(jobs[TARGET]['dir'] / 'hashes.sqlite') as c:
        for (sha,) in c.execute("select sha256 from hashes where status='verified'"):
            on_g.add(sha)
    g_name_size = set()
    with bp.ro(jobs[TARGET]['dir'] / 'inventory.sqlite') as c:
        for p, s in c.execute('select path, size from files'):
            g_name_size.add((p.rsplit(SEP, 1)[-1].lower(), s))
    rows = []
    serials = {}
    for disk, skip in SOURCES.items():
        serials[disk] = json.loads((jobs[disk]['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
        with bp.ro(jobs[disk]['dir'] / 'hashes.sqlite') as c:
            sha_of = dict(c.execute("select path, sha256 from hashes where status='verified'"))
        with bp.ro(jobs[disk]['dir'] / 'inventory.sqlite') as c:
            for p, s in c.execute('select path, size from files'):
                if (disk, p) in EXTRA:
                    rows.append((disk, p, s, 'указан пользователем'))
                    continue
                if p.split(SEP)[0] in skip:
                    continue
                sha = sha_of.get(p)
                if not sha or sha in on_g:
                    continue
                mark = 'спорный' if (p.rsplit(SEP, 1)[-1].lower(), s) in g_name_size else 'нет на G'
                rows.append((disk, p, s, mark))
    rows.sort()
    OUT.mkdir(parents=True, exist_ok=True)
    with io.open(OUT / 'список.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for disk, p, s, mark in rows:
            f.write(f'{disk}\t{p}\t{s}\t{mark}\n')
    with io.open(OUT / 'тома.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for disk, ser in serials.items():
            f.write(f'{disk}\t{ser}\n')
        f.write(f"{TARGET}\t{json.loads((jobs[TARGET]['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']}\n")
    t = collections.defaultdict(lambda: [0, 0])
    for disk, p, s, mark in rows:
        t[(disk, mark)][0] += 1
        t[(disk, mark)][1] += s
    for k, v in sorted(t.items()):
        print(f'{k[0]} {k[1]:22} {v[0]:6,} файлов {v[1] / 1024 ** 3:7.1f} ГБ')
    print(f'Всего {len(rows):,} файлов, {sum(s for _, _, s, _ in rows) / 1024 ** 3:.1f} ГБ')


if __name__ == '__main__':
    main()
