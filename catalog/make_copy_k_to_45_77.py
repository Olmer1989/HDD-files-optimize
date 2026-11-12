"""Список копирования с HDD17 (K:, «700 гиг») на HDD45 и HDD77 — по разделам пользователя (12.11.2026).

K: становится диском раздела «Саша, Таня, Наташа». На 45 и 77 уходят фото и видео, которых
там нет (по SHA-256), КРОМЕ:
  - раздела «Саша, Таня, Наташа» (остаётся на K:);
  - оцифровок (AVI/MPEG в папках с файлами от 7 ГБ и папки с «оцифров», «кассет» и т. п.) —
    пойдут на диск «Оцифровки»;
  - фильмов;
  - «Дмитрюсев - Золотое кольцо» (пойдёт на диск с «Эквадором», решение 12.11.2026);
  - «Проба HDTV кодирования» (пока не трогаем, решение 12.11.2026);
  - того, что пользователь удалил 11.11.2026 из «Монтаж Эквадора копия винчестера».
Только описи, диски не трогает. Мелкие картинки (без хеша) не берутся.

Куда: <диск>:\\ПЕРЕНОС с других дисков\\HDD17\\<тот же путь, что на K:>
Результат: «Каталог дисков\\K - на 45 и 77»: список.tsv, тома.tsv (+ скрипт копирования).

Запуск:  py catalog\\make_copy_k_to_45_77.py
"""
import collections
import io
import json
import os
import re

import build_pilot as bp

SEP = '\\'
SRC = 'HDD17'
TARGETS = ('HDD45', 'HDD77')
OUT = bp.OUT_DIR / 'K - на 45 и 77'
R = lambda s: re.compile(s, re.I)
FILM = R(r'фильм|мультфильм|сериал|blu-?ray|hd-?rip|bdrip|dvdrip|\\films?\\|movies|ромен')
FILM_EX = R(r'эстонское кино|описание фильмов|оцифров')
SASHA = R(r'зверев|сашин|саша|танин|таня|наташ|соммелье')
DIGI = R(r'оцифров|denisvideos|семейная хроника|видеоисходник|кассет|vhs|minidv|mini dv')
DIGI_EXT = {'.avi', '.mpg', '.mpeg', '.m2p', '.dv'}
SKIP = ('Дмитрюсев - Золотое кольцо' + SEP, 'Проба HDTV кодирования' + SEP) + tuple(
    'Монтаж Эквадора копия винчестера' + SEP + x for x in (
        'Рабочие материалы ( слегка подмонтированные исхоники )' + SEP, 'Проекты Encore DVD' + SEP,
        'Проекты Adobe' + SEP, 'Adobe Premiere Pro Auto-Save' + SEP, 'Encoded Files' + SEP,
        'CD-ROM_640x480_PAL.avi', 'MPEG2_DVD_PAL.mpg', 'Монтаж ФИЛЬМА.prproj'))


def main():
    jobs = bp.find_jobs()
    on = {}
    for d in TARGETS:
        with bp.ro(jobs[d]['dir'] / 'hashes.sqlite') as c:
            on[d] = {s for (s,) in c.execute("select sha256 from hashes where status='verified'")}
    rows = [r for r in bp.load_disk(SRC, jobs[SRC]) if r[4] not in (bp.T_CACHE, bp.T_SMALL)]
    big = {r[1].rsplit(SEP, 1)[0] for r in rows if os.path.splitext(r[6])[1] in DIGI_EXT and r[2] >= 7 * 2 ** 30}
    out, why = [], collections.Counter()
    for disk, path, size, mtime, t, key, name in rows:
        folder = path.rsplit(SEP, 1)[0] if SEP in path else ''
        if path.startswith(SKIP):
            why['решение пользователя / удалено'] += size
            continue
        if FILM.search(path) and not FILM_EX.search(path):
            why['фильмы'] += size
            continue
        if SASHA.search(path):
            why['Саша, Таня, Наташа (остаётся на K:)'] += size
            continue
        if t == 'Видео' and (DIGI.search(path) or (os.path.splitext(name)[1] in DIGI_EXT and folder in big)):
            why['оцифровки'] += size
            continue
        if key[0] != 'h':
            continue
        for d in TARGETS:
            if key[1] not in on[d]:
                out.append((d, path, size, 'фото/видео'))
    out.sort()
    OUT.mkdir(parents=True, exist_ok=True)
    with io.open(OUT / 'список.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for r in out:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(OUT / 'тома.tsv', 'w', encoding='utf-8-sig', newline='\r\n') as f:
        for d in (SRC,) + TARGETS:
            ser = json.loads((jobs[d]['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
            f.write(f'{d}\t{ser}\n')
    for k, v in why.items():
        print(f'не копируется — {k}: {v / bp.GIB:.1f} ГБ')
    t = collections.defaultdict(lambda: [0, 0])
    for d, p, s, _ in out:
        top = SEP.join(p.split(SEP)[:2]) if p.count(SEP) >= 2 else p.split(SEP)[0]
        for k in ((d, top), (d, 'ИТОГО')):
            t[k][0] += 1
            t[k][1] += s
    for k, v in sorted(t.items(), key=lambda kv: (kv[0][0], -kv[1][1])):
        if v[1] >= 0.1 * bp.GIB or k[1] == 'ИТОГО':
            print(f'{k[0]} | {k[1]} | {v[0]:,} файлов | {v[1] / bp.GIB:.2f} ГБ')


if __name__ == '__main__':
    main()
