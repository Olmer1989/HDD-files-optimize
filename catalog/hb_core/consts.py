"""Константы: диски 45/77, степени подтверждения, классы файлов, папки «ПЕРЕНЕСЕНО», версии сборки."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import re


SEP = '\\'
GIB = 1024 ** 3
MAIN = ('HDD45', 'HDD77')
DISK_RE = re.compile(r'^(HDD|Flash)\d+', re.I)
# Старые журналы (до единого шаблона): в них нет имён дисков, только буквы на день запуска.
OLD_LOGS = {
    'Копирование на G - I и J': {'G:': 'HDD45', 'I:': 'HDD55', 'J:': 'HDD51'},
    'Дубли фильмов на I': {'I:': 'HDD55', 'J:': 'HDD51'},
    'K - На HDD77': {'K:': 'HDD59'},
}
# Журналы перемещения целых папок («Время, Результат, Папка»): диск, откуда и куда - из самого скрипта.
FOLDER_MOVES = {
    'Зойкин компьютер - ФОТОГРАФИИ': ('HDD55', 'Зойкин компьютер - перенос', 'Зойкин компьютер - перенос\\ФОТОГРАФИИ'),
}
MANUAL_HEAD = 'дата\tдействие\tдиск\tпуть\tдиск2\tпуть2\tкомментарий'
DECISION_HEAD = 'диск\tпуть\tрешение\tкомментарий'
EXCLUSION_HEAD = 'диск\tпуть\tкомментарий'
PARTIAL_DIR = 'Повторное сканирование'     # частичные сканы папок: <корень сканов>\Повторное сканирование\<носитель>\<задание>

# Степень подтверждения записи «файл лежит на носителе». Колонка sha заполнена ТОЛЬКО у подтверждённых (S и C):
# поэтому всё, что сравнивается по sha, сравнивается по измеренным хешам. У остальных ожидаемый хеш лежит в sha_exp.
EV_SCAN, EV_COPY, EV_SIZE, EV_USER, EV_STALE, EV_NONE = 'S', 'C', 'Z', 'U', 'X', 'N'
EV_NAME = {EV_SCAN: 'хеш измерен сканером по самому файлу',
           EV_COPY: 'скопировано скриптом, хеш прочитанных байтов посчитан',
           EV_SIZE: 'НЕ подтверждено: скрипт сверил только размер или увидел «уже есть»',
           EV_USER: 'НЕ подтверждено: со слов пользователя (Проводник)',
           EV_STALE: 'НЕ подтверждено: файл изменился после подсчёта хеша',
           EV_NONE: 'хеш не считался'}

# Классы файлов без хеша (по расширению). «Значимые» участвуют в поиске уникальных папок.
C_DOC, C_PROJ, C_ARCH, C_MUSIC, C_OTHER = 'документы', 'проекты монтажа и графики', 'архивы и образы', 'музыка и звук', 'прочее'
C_MEDIA, C_PROG, C_JUNK, C_EMPTY = 'мелкие картинки и медиа без хеша', 'программы и системное', 'служебные и временные', 'пустые файлы'
C_BIGMEDIA = 'фото и видео без хеша (от 1 МБ)'
SIGNIFICANT = (C_DOC, C_PROJ, C_ARCH, C_MUSIC, C_BIGMEDIA, C_OTHER)
CLASS_ORDER = SIGNIFICANT + (C_MEDIA, C_PROG, C_JUNK, C_EMPTY)
EXT_CLASS = {}
for _cls, _exts in (
        (C_DOC, 'doc docx docm dot xls xlsx xlsm ppt pptx pps ppsx pdf txt rtf odt ods odp djvu djv fb2 epub csv md wri pub vsd one'),
        (C_PROJ, 'prproj prel aep aepx veg vf psd psb cdr ai indd fla dwg dxf max blend ses sesx ncor xmp cpr als flp sfk drp'),
        (C_ARCH, 'zip rar 7z iso nrg mdf mds tar gz bz2 tgz arj img vhd vhdx'),
        (C_MUSIC, 'mp3 wav flac ogg wma aac m4a ape aiff aif mid midi ac3 mpa cda'),
        (C_PROG, 'exe dll sys msi cab inf ocx drv com bat cmd reg ini dat bin hlp chm manifest cat mui nls ax cpl scr jar '
                 'class js css php asp aspx py pyc lib obj pdb so cfg conf mst msp nfo diz htm html shtml xml json swf dbf '
                 'cdx ntx db mdb sqlite gfr gfa gfd gfo cse pak dmg plist strings nib icns ttf otf fon cur ani ico'),
        (C_JUNK, 'tmp temp lnk url bak log pek cfa pkf mpgindex mpegindex ims xmpses dmp mdmp hdmp old chk sfv md0 thm')):
    for _e in _exts.split():
        EXT_CLASS['.' + _e] = _cls
JUNK_NAMES = {'thumbs.db', 'desktop.ini', '.ds_store', 'ehthumbs.db', 'folder.jpg', 'albumartsmall.jpg', 'pagefile.sys'}
NOHASH_VIDEO = ('.m2t', '.dv')    # видео, которому сканер полных описей хеш не считает: копию ищем и по имени и размеру


# ---------- сборщик: модули -> одна рабочая база ----------
# Модуль - неизменяемый первоисточник: полная опись носителя, частичный скан папок, журнал скрипта, строка таблицы
# ручных операций, строка таблицы исключений. Таблица applied помнит, какие модули учтены. При каждой команде
# применяются только новые модули (и дописанные строки журналов). Изменился уже учтённый модуль - база
# собирается заново целиком. Команда rebuild собирает базу с нуля и сверяет её с собранной по шагам.

BUILD_VERSION = 5          # правила сборки и устройство базы; изменились - база пересобирается целиком
STATE_KINDS = ('журнал', 'ручная операция', 'частичный скан')     # события, упорядоченные по времени
KIND_ORDER = {'опись': 0, 'исключение': 1, 'журнал': 2, 'частичный скан': 3, 'ручная операция': 4}


# ---------- готовые таблицы для быстрых ответов: presence (по хешу) и folders (по папкам) ----------
# presence: есть ли хеш на 45 и на 77 и с какой степенью, на скольких носителях подтверждён.
# folders: суммы по каждой папке каждого носителя (вместе с подпапками) с разбивкой по типам файлов.
# При сборке по шагам обе таблицы правятся только для затронутых строк (их отмечают временные триггеры).

EV_RANK = "(case ev when 'S' then '1S' when 'C' then '2C' when 'Z' then '3Z' when 'U' then '4U' when 'X' then '5X' else '6' || ev end)"
FOLDER_TYPES = ('фото', 'видео', 'тексты', 'прочие', 'мусор')
F_PHOTO, F_VIDEO, F_TEXT, F_OTHER, F_JUNK = range(5)


MOVED_PREFIX = 'ПЕРЕНЕСЕНО → '        # папки на источнике после копирования (логика v2, раздел 5)
TRASH_DIR = 'МУСОР'
MOVED_FOLDER = {frozenset(MAIN): MOVED_PREFIX + '45 и 77', frozenset([MAIN[0]]): MOVED_PREFIX + 'только 45',
                frozenset([MAIN[1]]): MOVED_PREFIX + 'только 77'}


NOHASH_NOTE = ('Сравнение по имени и размеру. «Копия не найдена» - файла с таким именем и размером нет ни на одном\n'
               'другом диске (под другим именем копия может существовать). Совпадение имени и размера - вероятная\n'
               'копия, но не доказательство: для решения «можно удалять» оно не засчитывается.')


MAX_LINES = 20            # ответ команды на экран - не больше 20 строк (ТЗ v3, 6.2); остальное - в файл
