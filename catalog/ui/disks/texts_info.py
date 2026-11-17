"""«Диски и папки»: строка сведений над деревом - «Хеш есть у всех фото и видео» / тревога, «Без хеша: N файлов …»,
ссылка «Показать» (nohash_html); files_word, html_esc. PySide6 не импортирует (n_ru - из overview_page; вынести в
модуль без Qt - шаг Б).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from overview_page import n_ru


def nohash_html(res):
    """Строка над деревом (этап 16): «Хеш есть у всех фото и видео» (или красная тревога) · «Без хеша: N файлов
    (документы, архивы, другие — их тип при сканировании не выбирался)» · ссылка «Показать»."""
    nh = res.get('nohash') or {}
    total, media, zux = nh.get('total', 0), nh.get('media', 0), nh.get('zux', 0)
    head = res.get('hash') or ''
    if not head:
        return ''
    color = '#c62828' if res.get('alarm') else '#2e7d32'
    h = f'<span style="color:{color}"><b>{html_esc(head)}</b></span>'
    other = total - media
    if other:
        h += (f' · Без хеша: <b>{n_ru(other)}</b> {files_word(other)} (документы, архивы, другие — их тип при '
              'сканировании не выбирался)')
    if zux:
        h += f'; из них непроверенных копий (Z/U/X): {n_ru(zux)}'
    if total:
        h += ' · <a href="nohash:" style="color:#1565c0">Показать</a>'
    return h


def files_word(n):
    n10, n100 = (n or 0) % 10, (n or 0) % 100
    return 'файл' if n10 == 1 and n100 != 11 else 'файла' if n10 in (2, 3, 4) and n100 not in (12, 13, 14) else 'файлов'


def html_esc(x):
    import html
    return html.escape(str(x))
