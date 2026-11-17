"""«Задания на копирование»: тексты - пояснения под таблицей и у блока перемещения, числа и ГБ, время, папки и пути
(«F:\\Котуй 2026», «(файлы в корне)»), подписи дисков. Без Qt.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time

from hb_core import api as hb


INTRO = 'Одно задание копирует одну папку носителя на диск направления. Ничего не удаляется и не перезаписывается.'
RUN_NOTE = ('Каждое задание открывается в своём окне. Остановить — клавиша Q; повторный запуск продолжит с места '
            'остановки.')
MOVE_NOTE = 'Перемещается внутри носителя, все подпапки сохраняются. Так видно, что папка уже сохранена.'
MOVE_EMPTY = 'Пока нечего: папка появится здесь, когда её копирование закончится и копии проверятся.'


def gb(b):
    return f'{b / 1024 ** 3:,.1f}'.replace(',', ' ').replace('.', ',')


def n(x):
    return f'{x:,}'.replace(',', ' ')


def fmt_eta(sec):
    """Секунды -> «~1 ч 10 мин» / «~25 мин» / «меньше минуты»."""
    if sec is None:
        return ''
    sec = max(0, int(sec))
    if sec < 60:
        return 'меньше минуты'
    h, m = divmod((sec + 59) // 60, 60)
    if h >= 48:
        return f'~{h // 24} дн {h % 24} ч'
    return f'~{h} ч {m} мин' if h else f'~{m} мин'


def fmt_ago(sec):
    sec = int(sec)
    if sec < 90:
        return f'{sec} с назад'
    return f'{sec // 60} мин назад' if sec < 7200 else f'{sec // 3600} ч назад'


def disk_long(disk, letter, labels):
    """«HDD17 «Samsung 750» (K:)»: номер, название диска (метка или модель, как в «Дисках и папках») и буква."""
    title = (labels or {}).get(disk, '')
    return disk + (f' «{title}»' if title else '') + (f' ({letter})' if letter else '')


def _loc(letter, disk, rel):
    """«F:\\Котуй 2026»; носитель не подключён - «HDD09\\Котуй 2026»; файлы в корне - «F:\\»."""
    base = letter or disk or '?'
    return base + '\\' + (rel or '')


def _where(letter, folder):
    """Папка носителя для «Что и куда»: «F:\\Котуй 2026», «Котуй 2026», «F:\\ (файлы в корне)», «(файлы в корне)»."""
    if not folder:                                           # None и '' - файлы в корне носителя
        return (letter + '\\ ' if letter else '') + '(файлы в корне)'
    return _loc(letter, '', folder) if letter else folder


def _date(ts):
    return time.strftime('%d.%m.%Y', time.localtime(ts)) if ts else ''


def _num(disk):
    return disk[3:] if disk.upper().startswith('HDD') and disk[3:].isdigit() else disk


def disks_words(disks, labels):
    """«диски 45 «Бэкап фото и видео» и 77 «Путешествия»» / «диск 78 «Работа Сафари»»."""
    items = [_num(d) + (f' «{labels[d]}»' if labels.get(d) else '') for d in disks]
    if not items:
        return 'диски направления'
    if len(items) == 1:
        return 'диск ' + items[0]
    return 'диски ' + ', '.join(items[:-1]) + ' и ' + items[-1]


def _folder_word(folder):
    return folder if folder else '(файлы в корне)'


def move_line(letter, disk, folder, dest):
    """«F:\\Котуй 2026 → F:\\Скопировано на Работа и Сафари (78)\\Котуй 2026» (тот же путь, что считает mvlist).
    Второй проход (этап 13): «F:\\Скопировано на A\\Поход → F:\\Скопировано на A и B\\Поход» - без вложенности."""
    src = _loc(letter, disk, folder) + ('' if folder else ' (файлы в корне)')
    r1, rest = hb.copied_inside(folder or '')
    dst = _loc(letter, disk, dest + ('\\' + rest if rest else '') if r1 else dest + '\\' + (folder or ''))
    return f'{src} → {dst}'


def _on_disks(disks):
    return ('диске ' if len(set(disks)) == 1 else 'дисках ') + hb.disk_nums(disks)
