"""Пути проекта: база, таблицы владельца, ответы, шаблоны, задания. ЕДИНСТВЕННОЕ место, где они хранятся.
Читать только как атрибут модуля: paths.DB (после set_root() в тестах значение меняется)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import glob
import hashlib
import os
import re
import shutil
from pathlib import Path
import build_pilot as bp


__all__ = ['set_root', 'journal_paths', 'child_env', 'template_parts', 'template_problems', 'copy_template',
           'part_sha', 'part_text', 'parse_parts', 'TemplateBroken']   # пути не копируются через import *: читать paths.X


def set_root(out_dir):
    """Где лежат база и таблицы поправок (в тестах - временная папка)."""
    global BASE_DIR, DB, SNAP, MANUAL, DECISIONS, EXCLUSIONS, ANSWERS, TEMPLATE, MOVE_TEMPLATE, TASKS, DIRECTIONS, RAZBORY
    BASE_DIR = Path(out_dir) / '_БАЗА'
    DB = BASE_DIR / 'хеши.sqlite'          # рабочая база: снимок описей + поправки
    SNAP = BASE_DIR / 'описи.sqlite'       # снимок описей; пересобирается, только если изменились сами описи
    MANUAL = BASE_DIR / 'ручные операции.tsv'
    DECISIONS = BASE_DIR / 'решения.tsv'
    EXCLUSIONS = BASE_DIR / 'исключения.tsv'   # папки, которые база не учитывает (временные копии владельца)
    DIRECTIONS = BASE_DIR / 'направления.tsv'  # направления разбора (логика v3): номер, имя, диски, что копировать
    RAZBORY = BASE_DIR / 'разборы'             # манифесты разборов носителей (логика v3)
    ANSWERS = BASE_DIR / 'ответы'
    TEMPLATE = Path(out_dir) / '_ШАБЛОН копирования'
    MOVE_TEMPLATE = Path(out_dir) / '_ШАБЛОН перемещения'
    TASKS = Path(out_dir).parent / 'Запускаемые скрипты'   # готовые задания владельца (правило 13.11.2026)


def journal_paths():
    """Журналы скриптов: в папках задач «Каталог дисков\\<задача>» и «Запускаемые скрипты\\<задание>»."""
    res = []
    for root in (bp.OUT_DIR, TASKS):
        res += glob.glob(str(Path(root) / '*' / 'Журнал*.tsv'))
    return res


def child_env():
    """Корни для подпроцесса (окно запускает команды отдельным процессом): он видит те же данные, что и окно.
    В работе это значения по умолчанию, в тестах - временные папки."""
    return {'HB_ROOT': str(BASE_DIR.parent), 'HB_SCAN_ROOTS': os.pathsep.join(str(x) for x in bp.SCAN_ROOTS)}


# Шаблон из частей (шаблон копирования 2.8, 17.11.2026): главный .ps1 + части .psm1 рядом («Запустить.cmd»
# запускает только *.ps1). Главный перечисляет части с SHA-256 их текста (таблица $PartSha, строка на часть) и не
# начнёт работу, если части нет или она изменена. Здесь - единственное место в Python, которое знает состав шаблона.
_PART_RE = re.compile(r"^\s*'([^'\\/:*?\"<>|]+\.psm1)'\s*=\s*'([0-9A-F]{64})'\s*$")
_TABLE_HEAD = '$PartSha = [ordered]@{'


class TemplateBroken(ValueError):
    """Главный шаблона или его часть повреждены: таблица $PartSha не разбирается, часть не UTF-8."""


def part_text(data):
    """Текст части из байтов - как в главном: строгий UTF-8 (битые байты - ошибка, а не замена), без BOM в начале,
    концы строк - LF (CRLF и одиночный CR -> LF)."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as e:
        raise TemplateBroken(f'не UTF-8 ({e.reason}, байт {e.start})') from None
    return text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')


def part_sha(path_or_bytes):
    """SHA-256 текста части так же, как считает главный, заглавными. Принимает путь или уже прочитанные байты."""
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    return hashlib.sha256(part_text(data).encode('utf-8')).hexdigest().upper()


def parse_parts(main_text):
    """Таблица $PartSha главного: [(имя, SHA-256)]. Таблицы нет (однофайловый шаблон 2.7 и старше) - [].
    Любая строка внутри таблицы, которая не разобралась, нет конца таблицы, таблица пустая, повтор имени, второе
    упоминание $PartSha = [ordered] - TemplateBroken (не пропуск: иначе часть молча выпала бы из проверки и доставки)."""
    lines = main_text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    heads = [i for i, x in enumerate(lines) if x.strip().startswith('$PartSha') and '=' in x and 'ordered' in x]
    if not heads:
        if '$PartSha' in main_text:              # главный 2.8 без разборчивой таблицы - повреждён
            raise TemplateBroken('таблица $PartSha не разобрана')
        return []
    if len(heads) > 1 or lines[heads[0]].strip() != _TABLE_HEAD:
        raise TemplateBroken(f'строка {heads[0] + 1}: начало таблицы $PartSha не разобрано')
    res = []
    for i in range(heads[0] + 1, len(lines)):
        x = lines[i]
        if x.strip() == '}':
            break
        m = _PART_RE.match(x)
        if not m:
            raise TemplateBroken(f'строка {i + 1} таблицы $PartSha не разобрана: «{x.strip()[:80]}»')
        if any(n.lower() == m.group(1).lower() for n, _ in res):
            raise TemplateBroken(f'часть «{m.group(1)}» записана в $PartSha дважды')
        res.append((m.group(1), m.group(2)))
    else:
        raise TemplateBroken('у таблицы $PartSha нет конца «}»')
    if not res:
        raise TemplateBroken('таблица $PartSha пустая')
    return res


def template_parts(main):
    """Части шаблона по таблице $PartSha главного: [(имя, SHA-256)]; однофайловый шаблон - []; повреждена -
    TemplateBroken."""
    return parse_parts(Path(main).read_bytes().decode('utf-8', errors='strict'))


def _check(folder, main, read):
    """Общая проверка для template_problems и copy_template: read(имя) -> байты. -> (части, [проблемы])."""
    try:
        parts = parse_parts(read(main).decode('utf-8'))
    except (TemplateBroken, UnicodeDecodeError) as e:
        return [], [f'{main} повреждён: {e}']
    res = []
    for name, sha in parts:
        try:
            if part_sha(read(name)) != sha:
                res.append(f'часть «{name}» изменена (SHA-256 не тот, что записан в {main})')
        except FileNotFoundError:
            res.append(f'нет части «{name}»')
        except TemplateBroken as e:
            res.append(f'часть «{name}» повреждена: {e}')
        except OSError as e:
            res.append(f'часть «{name}» не читается: {e}')
    return parts, res


def template_problems(folder, main):
    """Что не так с шаблоном в папке: [] - всё на месте; иначе строки «нет части …», «часть … изменена»,
    «… повреждён»."""
    folder = Path(folder)
    try:
        return _check(folder, main, lambda n: (folder / n).read_bytes())[1]
    except OSError as e:
        return [f'{main} не читается: {e}']


def copy_template(src, dst, main, extra=('Запустить.cmd',)):
    """Кладёт шаблон в папку задания: главный, `extra` и все его части. Каждый файл эталона читается ОДИН раз;
    проверяются (таблица и SHA-256 частей) и записываются те же байты; записанное читается обратно и сверяется.
    Эталон повреждён или запись не совпала - исключение, уже записанные файлы шаблона убираются. -> имена файлов."""
    src, dst = Path(src), Path(dst)
    snap = {}

    def read(n):
        if n not in snap:
            snap[n] = (src / n).read_bytes()
        return snap[n]

    parts, bad = _check(src, main, read)
    if bad:
        raise RuntimeError(f'Шаблон {src} испорчен: ' + '; '.join(bad))
    names = [main, *extra, *(n for n, _ in parts)]
    done = []
    try:
        for n in names:
            (dst / n).write_bytes(read(n))
            done.append(n)
            shutil.copystat(src / n, dst / n)
            if (dst / n).read_bytes() != read(n):
                raise RuntimeError(f'{dst / n}: записанная копия шаблона не совпала с прочитанной')
    except BaseException:
        for n in done:
            try:
                (dst / n).unlink()
            except OSError:
                pass
        raise
    return names


def _from_env():
    """HB_ROOT - папка «Каталог дисков» (база, таблицы, задачи), HB_SCAN_ROOTS - папки описей через «;».
    Добавлено 15.11.2026 для окна и тестов; без переменных всё как раньше."""
    if os.environ.get('HB_ROOT'):
        bp.OUT_DIR = Path(os.environ['HB_ROOT'])
    if os.environ.get('HB_SCAN_ROOTS'):
        bp.SCAN_ROOTS = [Path(x) for x in os.environ['HB_SCAN_ROOTS'].split(os.pathsep) if x]


_from_env()
set_root(bp.OUT_DIR)
