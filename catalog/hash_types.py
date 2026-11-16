"""Пересканирование папок: у каких типов файлов сканер считает хеш (16.11.2026, сканер 1.6.0).

Типы - те же, что в «Что копировать» у направлений (hb.COPY_CATS), и определяются ОДНОЙ функцией derived.copy_kind.
Сканер - отдельная переносимая программа и ядро каталога не импортирует, поэтому окно передаёт ему готовое правило
ключами (scanner\\rescan.wants_hash его исполняет):
  --hash-ext       - расширения выбранных типов (когда «Другие» не выбраны), или
  --hash-skip-ext  - расширения НЕвыбранных типов (когда «Другие» выбраны: они - остаток, перечислить их нельзя);
  --hash-skip-names, --hash-skip-path-re - служебные и временные файлы по имени и по пути (кэш монтажа): copy_kind
                     относит их к мусору при любом расширении.
Тип расширения узнаётся вызовом самого copy_kind на имени «f<расширение>» (непустой файл, путь без кэша), так что
правило одно; тест test_rescan_types сверяет решение сканера с copy_kind на всех известных расширениях и примерах.
Все 7 типов («Все типы») - ключей выбора нет, сканер считает хеш у всех обычных файлов, как до 1.6.0 (в том числе у
программ, системных и временных файлов) - прежнее поведение; ключ --hash-all-types записывает это явно.
При неполном выборе программы, системные и временные файлы хеш не получают: они не входят ни в один тип.
"""
import build_pilot as bp
from hb_core import api as hb
from hb_core.consts import CAT_OF_TYPE, EXT_CLASS, JUNK_NAMES, NEVER_COPY_EXT
from hb_core.derived import copy_kind

ALL = tuple(hb.COPY_CATS)
PROBE_SIZE = 10 * 1024 * 1024          # непустой файл: тип по copy_kind от размера больше не зависит


def known_ext():
    """Все расширения, о которых правило что-то знает (неизвестные и без расширения - «Другие»)."""
    return sorted(set(bp.EXT_TYPE) | set(EXT_CLASS) | set(NEVER_COPY_EXT))


def cat_of_ext(ext):
    """Тип «что копировать» непустого файла с этим расширением (обычное имя, путь без кэша): одна из hb.COPY_CATS
    или None (программы и системное, служебные и временные - не копируются никогда, выбрать их нельзя)."""
    name = 'f' + ext
    return CAT_OF_TYPE.get(copy_kind(name, name, PROBE_SIZE))


def ext_table():
    """{расширение: тип или None} для всех известных расширений."""
    return {e: cat_of_ext(e) for e in known_ext()}


def is_all(cats):
    return set(cats) >= set(ALL)


def scanner_args(cats):
    """Ключи сканера для выбранных типов. Все типы - [] (прежнее поведение, окно добавит --hash-all-types).
    Пустой выбор - ValueError (окно его не допускает)."""
    cats = set(cats)
    if not cats:
        raise ValueError('Не выбран ни один тип файлов')
    if is_all(cats):
        return []
    table = ext_table()
    if hb.CAT_OTHER in cats:
        args = ['--hash-skip-ext', ','.join(e for e, c in table.items() if c not in cats)]
    else:
        args = ['--hash-ext', ','.join(e for e, c in table.items() if c in cats)]
    names = sorted(JUNK_NAMES) + ['~$*']
    return args + ['--hash-skip-names', ','.join(names), '--hash-skip-path-re', bp.CACHE_RE.pattern]


def scanner_rule(cats):
    """То же правило в виде, который понимает rescan.hash_rule/wants_hash (для предпросмотра в окне). None - все типы."""
    a = scanner_args(cats)
    if not a:
        return None
    import service as sv
    rescan = sv._scanner()[0]
    v = dict(zip(a[::2], a[1::2]))
    mode = 'only' if '--hash-ext' in v else 'skip'
    return rescan.hash_rule({'hash_types': {
        'mode': mode, 'ext': sorted(rescan.parse_ext(v.get('--hash-ext') or v.get('--hash-skip-ext'))),
        'junk_names': rescan.parse_list(v['--hash-skip-names']), 'junk_path_re': v['--hash-skip-path-re']}})


def label(cats):
    """«фото, видео» / «все типы» - для подтверждения и журнала окна."""
    return 'все типы' if is_all(cats) else ', '.join(c for c in ALL if c in set(cats))
