"""Список того, чего не хватает на HDD45 и HDD77 из выбранных папок HDD51 (J:, My Book 3 ТБ).

Только описи, диски не трогает. Куда копировать (ПЛАН_РАЗМЕЩЕНИЯ, раздел 1а):
  <диск 45>:\\ПЕРЕНОС с других дисков\\HDD51\\<тот же путь, что на J:>
  <диск 77>:\\ПЕРЕНОС с других дисков\\HDD51\\<тот же путь, что на J:>
В список попадает:
  - фото/видео (есть SHA-256): хеша нет на целевом диске; для HDD45 не берутся файлы,
    уже скопированные туда 11.11.2026 (Копирование на G - I и J\\список.tsv);
  - прочие файлы (без хеша, кроме мелких картинок): на целевом диске нет файла с тем же
    именем и размером; для HDD45 — тоже без уже скопированных 11.11.
Результат в «Каталог дисков\\J - недостающее на 45 и 77»: список.tsv, тома.tsv.
Скрипт для пользователя там же: «Копировать недостающее.ps1».

Запуск:  py catalog\\make_copy_j_missing.py
"""
import collections
import io
import json

import build_pilot as bp

SEP = '\\'
SRC = 'HDD51'
TARGETS = ('HDD45', 'HDD77')
IND = ' Перемещение перед Индонезией - временное'
FOLDERS = [IND + SEP + x for x in ('Видео из Франции', 'Фотографии из Франции', 'DenisPhotos', 'Москва')] + [
    'Метц', 'На разборку', 'Перемещение с Никона от 19 июля 2013', 'Перемещение с Никона от 30 апреля 2013',
    'Селекция Топ Озера 2013', 'Топ Озеро 2013 - фото - исходник']
OUT = bp.OUT_DIR / 'J - недостающее на 45 и 77'


def main():
    jobs = bp.find_jobs()
    sha_t, ns_t = {}, {}
    for d in TARGETS:
        with bp.ro(jobs[d]['dir'] / 'hashes.sqlite') as c:
            sha_t[d] = {s for (s,) in c.execute("select sha256 from hashes where status='verified'")}
        with bp.ro(jobs[d]['dir'] / 'inventory.sqlite') as c:
            ns_t[d] = {(p.rsplit(SEP, 1)[-1].lower(), s) for p, s in c.execute('select path, size from files')}
    copied = set()
    for line in io.open(bp.OUT_DIR / 'Копирование на G - I и J' / 'список.tsv', encoding='utf-8-sig'):
        f = line.rstrip('\r\n').split('\t')
        if f[0] == SRC:
            copied.add(f[1])
    with bp.ro(jobs[SRC]['dir'] / 'hashes.sqlite') as c:
        sha = dict(c.execute("select path, sha256 from hashes where status='verified'"))
    rows = []
    with bp.ro(jobs[SRC]['dir'] / 'inventory.sqlite') as c:
        for p, s, cat in c.execute('select path, size, category from files'):
            if not any(p.startswith(f + SEP) for f in FOLDERS):
                continue
            h = sha.get(p)
            if not h and cat == 'media_small':
                continue
            for d in TARGETS:
                if d == 'HDD45' and p in copied:
                    continue
                if h:
                    if h not in sha_t[d]:
                        rows.append((d, p, s, 'фото/видео'))
                elif (p.rsplit(SEP, 1)[-1].lower(), s) not in ns_t[d]:
                    rows.append((d, p, s, 'прочее'))
    rows.sort()
    OUT.mkdir(parents=True, exist_ok=True)
    with io.open(OUT / 'список.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for r in rows:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(OUT / 'тома.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for d in (SRC,) + TARGETS:
            ser = json.loads((jobs[d]['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
            f.write(f'{d}\t{ser}\n')
    t = collections.defaultdict(lambda: [0, 0])
    for d, p, s, k in rows:
        top = p.split(SEP)[1] if p.startswith(IND) else p.split(SEP)[0]
        for key in ((d, k, top), (d, 'ИТОГО', '')):
            t[key][0] += 1
            t[key][1] += s
    for k, v in sorted(t.items()):
        print(f'{k[0]} | {k[1]} | {k[2]} | {v[0]:,} файлов | {v[1] / bp.GIB:.2f} ГБ')


if __name__ == '__main__':
    main()
