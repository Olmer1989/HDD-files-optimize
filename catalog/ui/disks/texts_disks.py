"""«Диски и папки»: таблица «Носители» - состояния сканирования (SCAN_RU, scan_text), подпись носителя (disk_cell),
пояснение под заголовком (WHY_TEXT). PySide6 не импортирует (disk_ui сам грузит Qt - шаг Б).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import disk_ui
import service as sv


SCAN_RU = {'complete': 'полное', 'complete_with_inventory_errors': 'полное, есть нечитаемые места',
           'complete_with_unread_files': 'полное, часть файлов не прочитана', 'running': 'не закончено',
           'interrupted': 'прервано, не закончено', 'stopped': 'остановлено, не закончено', 'failed': 'не удалось',
           'error': 'не удалось'}
WHY_TEXT = ('Здесь видно, что лежит на каждом носителе по базе: папки, сколько в них фото, видео и прочего, и какое '
            'решение по ним принято. Отсюда же — открыть папку в Проводнике и пересканировать её.')


def scan_text(r):
    """«08.11.2026 · полное · после полной описи 1 раз пересканированы выбранные папки (2 папки)» (этап 16: вместо
    «частичных: 2» - что это значит; число - сколько раз пересканировали, а не сколько папок)."""
    st = (r.get('status') or '').strip()
    bits = [r.get('scanned') or 'дата неизвестна', SCAN_RU.get(st, disk_ui.status_text(st))]
    if r.get('partial'):
        bits.append(sv.rescans_text(r['partial'], r.get('partial_folders') or 0))
    return ' · '.join(b for b in bits if b and b != '—')


def disk_cell(r):
    """«F: — Монтаж - SN850 — HDD09» / «Видеоархив полный — HDD01» / «HDD61» (метки нет)."""
    return ' — '.join(x for x in (r.get('letter'), disk_ui.disk_name(r), r['disk']) if x)
