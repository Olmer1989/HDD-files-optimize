"""Применение исключений и список уникальных файлов в исключённых папках."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import os
import build_pilot as bp
from hb_core.consts import NOHASH_VIDEO
from hb_core.util import gb, prefix_cond
from hb_core.report import save


def apply_exclusions(c, excl, report):
    """Папки из исключений не учитываются вовсе: строки внутри них убираются, откуда бы они ни пришли
    (что убрано - запоминается в таблице excluded, чтобы проверить, не единственные ли это экземпляры)."""
    for disk, folders in excl.items():
        for f in folders:
            cond, args = prefix_cond('path', f)
            c.execute(f'insert or replace into excluded select disk, path, size, coalesce(sha, sha_exp), name_lc, origin '
                      f'from files where disk=? and {cond}', [disk] + args)
            n = c.execute(f'delete from files where disk=? and {cond}', [disk] + args).rowcount
            if n:
                report.setdefault('excluded', []).append(f'{disk}\\{f}: убрано записей {n}')


def excluded_unique(c, report):
    """Фото и видео из исключённых папок, которых нет больше ни на одном носителе в базе (по SHA-256): их нельзя
    потерять при ручном переносе. Список - в «ответы», в отчёт сборки - одна строка на носитель."""
    report['unique'] = {}
    report['unique_info'] = {}
    by_disk = collections.defaultdict(list)
    q = '''select e.disk, e.path, e.size, e.sha,
                  exists(select 1 from files g where g.name_lc=e.name_lc and g.size=e.size)
           from excluded e where e.sha is not null
             and not exists(select 1 from files g where g.sha=e.sha)
             and not exists(select 1 from files g where g.sha_exp=e.sha)'''
    for disk, p, size, sha, probable in c.execute(q):
        ext = os.path.splitext(p)[1].lower()
        if ext in bp.EXT_TYPE or ext in NOHASH_VIDEO:
            kind = bp.file_type(p, size or 0) or 'Видео'
            by_disk[disk].append((p, size, kind, 'есть файл с тем же именем и размером' if probable else '', sha))
    for disk, rr in sorted(by_disk.items()):
        path = save(f'исключения - больше нигде нет - {disk}', ('путь', 'размер', 'тип', 'сравнение только по имени и размеру', 'SHA-256'),
                    sorted(rr))
        small = sum(1 for r in rr if r[2] == bp.T_SMALL)
        nohash = sum(1 for r in rr if os.path.splitext(r[0])[1].lower() in NOHASH_VIDEO)
        # то же числами - для окна («Обзор» → «Требует внимания», 16.11.2026): без разбора строки
        report['unique_info'][disk] = dict(files=len(rr), bytes=sum(r[1] or 0 for r in rr), small=small,
                                           nohash=nohash, list=str(os.path.abspath(path)))
        report['unique'][disk] = (f'в исключённых папках {disk} {len(rr)} фото и видео ({gb(sum(r[1] for r in rr))} ГБ) нет больше '
                           f'ни на одном носителе в базе (из них мелких картинок {small}; видео .m2t/.dv, которым на других '
                           f'дисках хеш не считали, {nohash}) - не потерять при ручном переносе: {path}')
