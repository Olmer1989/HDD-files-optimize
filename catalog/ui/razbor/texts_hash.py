"""Тексты окна «Посчитать хеш — HDD18» (кнопка «Посчитать хеш (N)» на «Выбор источников», 18.11.2026, макет владельца).
Все слова окна - здесь (правка текста касается только этого файла); окно (Qt) - dialog_hash.py.

Четыре состояния: перед запуском (intro_html), идёт (running_html), остановлено / не закончено (stopped_html),
готово (done_html - после приёма скана базой и повторной проверки «без хеша»)."""
from .texts_cell import GREEN, ORANGE, RED, esc, files_word, num, plural

GRAY_CSS = 'color:#757575'
NOTE = ('Время будет видно после начала. Диск только читается. '
        'После подсчёта экран «Выбор источников» обновится.')
WAIT_PLAN = 'Читаю оглавление диска…'
STARTING = 'Запускаю…'
STOPPING = 'Останавливаю: текущий файл дочитывается…'
APPLYING = 'Подсчёт закончен. Применяю к базе…'
CHECKING = 'Проверяю, у всех ли нужных файлов теперь есть хеш…'
CAN_STOP = 'Можно остановить — посчитанное сохранится, потом можно продолжить.'
BUSY = 'Хеш считается. Сначала нажмите «Остановить».'
BUSY_APPLY = 'Посчитанное применяется к базе и проверяется - подождите, окно закроется после этого.'
ALREADY = 'Уже идёт пересканирование - дождитесь его или остановите.'
BTN_GO, BTN_CANCEL, BTN_STOP, BTN_RESUME, BTN_CLOSE = 'Посчитать', 'Отмена', 'Остановить', 'Продолжить', 'Закрыть'
MORE = 'Подробнее…'
CAT_WORDS = {'другие': 'другие файлы'}


def gb(x):
    """ГБ - как в окне «Пересканировать папки» (rescan_dialog.gb)."""
    return f'{(x or 0) / 1e9:,.1f}'.replace(',', ' ').replace('.', ',')


def of_files(n):
    """«у 1 файла», «у 5 файлов»."""
    n = n or 0
    return f'{num(n)} ' + ('файла' if n % 10 == 1 and n % 100 != 11 else 'файлов')


def title(disk):
    return f'Посчитать хеш — {disk}'


def letter_text(letter):
    s = str(letter or '').strip()
    return s if not s or s.endswith(':') else s + ':'


def types_words(cats):
    """['фото', 'документы'] -> «Фото и документы»."""
    w = [CAT_WORDS.get(c, c) for c in cats or []]
    if not w:
        return 'Файлы'
    s = w[0] if len(w) == 1 else ', '.join(w[:-1]) + ' и ' + w[-1]
    return s[:1].upper() + s[1:]


def head_html(n, disk, letter=''):
    lt = letter_text(letter)
    return (f'<p style="font-size:13pt"><b>Посчитать хеш у {of_files(n)} на {esc(disk)}'
            + (f' ({esc(lt)})' if lt else '') + '</b></p>')


def intro_html(n, cats, target, read=None):
    """Состояние 1 (без заголовка). read - (файлов, байт) по предпросмотру или None (ещё читается оглавление)."""
    h = (f'<p>{esc(types_words(cats))} из отмеченных папок, которые пойдут на {esc(target)}. '
         'Без хеша их нельзя скопировать.</p>')
    if read is not None:
        r, b = read
        h += f'<p>Программа прочитает {files_word(r)} ({gb(b)} ГБ)'
        h += (f': сканер читает папку целиком, поэтому хеш заодно появится ещё у {of_files(r - n)}.</p>'
              if r > n else '.</p>')
    return h + f'<p style="{GRAY_CSS}">{NOTE}</p>'


def lost_html(lost):
    """Предупреждение (как в «Пересканировать папки»): у файлов других типов в этих папках без годного прежнего хеша
    сканера подтверждение в базе после приёма скана пропадёт."""
    if not lost:
        return ''
    return (f'<p style="color:{RED}">У {of_files(lost)} других типов в этих папках подтверждение хеша в базе '
            'пропадёт после подсчёта.</p>')


def unknown_lost_html():
    """Не удалось узнать подтверждённые хеши в базе, а файлы других типов в этих папках останутся без хеша."""
    return (f'<p style="color:{ORANGE}">Не удалось проверить, пропадёт ли подтверждение хеша у файлов других типов '
            'в этих папках.</p>')


def stop_failed_html(text):
    return f'<p style="color:{RED}">Не удалось остановить: {esc(text)}</p>'


def warn_html(lines):
    """Предупреждения базы при принятом скане - серым под итогом."""
    return ''.join(f'<p style="{GRAY_CSS}">{esc(x)}</p>' for x in lines or [])


def error_html(text):
    return f'<p style="color:{RED}">Не получилось: {esc(text)}</p>'


def more_link():
    return f'<a href="more">{MORE}</a>'


def details_html(lines):
    return '<p><b>Предпросмотр</b></p>' + ''.join(f'<p>{esc(x)}</p>' for x in lines or [])


def running_html(done, read, eta=None):
    """Состояние 2: ход."""
    h = f'<p style="font-size:13pt"><b>Прочитано {num(done)} из {num(read)} файлов</b></p>'
    if eta:
        h += f'<p>Осталось ~{max(1, round(eta / 60))} мин.</p>'
    return h + f'<p style="{GRAY_CSS}">{CAN_STOP}</p>'


def stopped_html(stopped, reason, done, read, tail=''):
    """Состояние 3: «Остановлено» (по кнопке) или «Не закончено: причина»."""
    head = (f'<p style="font-size:13pt;color:{ORANGE}"><b>Остановлено</b></p>' if stopped else
            f'<p style="font-size:13pt;color:{RED}"><b>Не закончено: {esc(reason)}</b></p>')
    return (head + f'<p>Прочитано {num(done)} из {num(read)}. Копирование станет возможно, когда хеш будет у всех '
            'нужных файлов.</p>' + (f'<p style="{GRAY_CSS}">{esc(tail)}</p>' if tail and not stopped else ''))


def done_html(n, target):
    """Состояние 4: n - сколько нужных файлов осталось без хеша (повторная проверка)."""
    if not n:
        return (f'<p style="font-size:13pt;color:{GREEN}"><b>✓ Хеш есть у всех файлов, которые пойдут на '
                f'{esc(target)}.</b></p><p>Закройте окно и нажмите «Начать копирование…».</p>')
    return (f'<p style="font-size:13pt;color:{RED}"><b>Без хеша '
            f'{plural(n, "остался", "осталось", "осталось")} {num(n)} '
            f'{plural(n, "нужный файл", "нужных файла", "нужных файлов")} — '
            '<a href="nh-list">Показать</a>. Копирование пока невозможно.</b></p>')


def check_failed_html(text):
    return f'<p style="color:{RED}">Не получилось проверить, у всех ли файлов есть хеш: {esc(text)}</p>'


def refused_html(lines):
    """Состояние 4: база скан не приняла - причины."""
    return (f'<p style="font-size:13pt;color:{RED}"><b>База скан не приняла</b></p>'
            + ''.join(f'<p>{esc(x)}</p>' for x in lines or []))
