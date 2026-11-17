"""Общее оформление носителей в окне: порядок (подключённые сейчас - первыми), названия, цвета, состояние описи.

Используют раздел «Команды» (выбор диска в формах) и раздел «Диски и папки» (таблица носителей).
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont

TASKS_PAGE = 'Задания на копирование'     # имя раздела окна (меню слева); переходы - open_page(TASKS_PAGE)
ON_COLOR, OFF_COLOR = QColor('#1b5e20'), QColor('#8a8a8a')
# Диски направлений (этап 5, 15.11.2026): назначенный направлению диск - оранжевый, это важнее «подключён»
# (подключённость видна ещё жирным шрифтом, значком «●» и буквой); неподключённый назначенный - бледно-оранжевый.
ASSIGNED_ON, ASSIGNED_OFF = '#e65100', '#e8a46a'     # в диалоге: диск уже у другого направления
SIZE_RE = re.compile(r'^\d[\d,.]*\s*\S+$')

STATUS_RU = {'complete': 'полная',
             'complete_with_inventory_errors': 'полная, есть нечитаемые места',
             'complete_with_unread_files': 'полная, часть файлов не прочитана',
             'running': 'не закончена',
             'interrupted': 'прервана, не закончена',
             'stopped': 'остановлена, не закончена',
             'failed': 'не удалась',
             'error': 'не удалась'}


def as_row(r):
    return r if isinstance(r, dict) else {'disk': str(r), 'label': '', 'letter': ''}


def disk_key(d):
    m = re.match(r'(\D*)(\d*)', d)
    return (0 if m.group(1) == 'HDD' else 1, m.group(1), int(m.group(2) or 0), d)     # диски, потом флешки


def disk_name(r):
    """Название диска для окна - ТОЛЬКО метка тома (16.11.2026, решение владельца): модель и док-станция («JMicron 6 ТБ»,
    «WD 2 ТБ») - устройство подключения, в следующий раз будет другим, поэтому не показываются нигде.
    Подпись в базе: «модель - объём - метка» (sv.disks() уже убрал номер HDD; метка сама может содержать « - »);
    если номер не убран - он отбрасывается. Второе поле не похоже на объём - метка всё после модели. Метки нет - ''."""
    parts = [x.strip() for x in (r.get('label') or '').split(' - ') if x.strip()]
    if parts and r.get('disk') and parts[0] == r.get('disk'):
        parts = parts[1:]
    name = ''
    if len(parts) >= 2:
        name = ' - '.join(parts[2:] if SIZE_RE.match(parts[1]) else parts[1:])
    return name or kind_word(r.get('disk', ''))


def kind_word(disk):
    """Метки тома нет (16.11.2026, решение владельца): «Флешка» у Flash…, «Накопитель» у остальных (HDD…)."""
    if not disk:
        return ''
    return 'Флешка' if str(disk).lower().startswith('flash') else 'Накопитель'


disk_title = disk_name          # прежнее имя: все места окна получают подпись без модели


def disk_place(r):
    """«I: My Book» (подключён) / «My Book» (не подключён) / номер диска, если метки нет."""
    r = as_row(r)
    name = disk_name(r) or r.get('disk', '')
    return f'{r["letter"]} {name}' if r.get('letter') else name


def disk_text(r):
    """«● HDD54 — E: — Исходники» или «HDD61 — не подключён» (метки тома нет)."""
    r = as_row(r)
    name = disk_title(r)
    if r.get('letter'):
        return ' — '.join(x for x in (f'● {r["disk"]}', r['letter'], name) if x)
    return ' — '.join(x for x in (r['disk'], name, 'не подключён') if x)


def split_disks(rows):
    """(подключённые сейчас, остальные), каждые по номеру носителя: диски HDD раньше флешек."""
    rows = [as_row(r) for r in rows]
    on = sorted((r for r in rows if r.get('letter')), key=lambda r: disk_key(r['disk']))
    off = sorted((r for r in rows if not r.get('letter')), key=lambda r: disk_key(r['disk']))
    return on, off


def ordered(rows):
    """Один список: подключённые сейчас, затем остальные HDD по номеру, флешки в конце."""
    on, off = split_disks(rows)
    return on + off


def status_text(status):
    """Состояние описи словами владельца; неизвестное значение - как есть."""
    s = (status or '').strip()
    if not s:
        return '—'
    return STATUS_RU.get(s, s.replace('_', ' '))


def style_item(set_data, connected):
    """Подключённый - жирным и зелёным, отключённый - серым (для пунктов списка, дерева и галочек)."""
    if connected:
        f = QFont()
        f.setBold(True)
        set_data(Qt.FontRole, f)
        set_data(Qt.ForegroundRole, QBrush(ON_COLOR))
    else:
        set_data(Qt.ForegroundRole, QBrush(OFF_COLOR))


def disk_color(connected, assigned):
    """Цвет диска в списках направлений: оранжевый - назначен направлению (бледный - не подключён), зелёный -
    подключён и свободен, серый - не подключён и свободен. -> (цвет '#rrggbb', жирный)."""
    if assigned:
        return (ASSIGNED_ON, True) if connected else (ASSIGNED_OFF, False)
    return (ON_COLOR.name(), True) if connected else (OFF_COLOR.name(), False)


# Таблица направлений (второй круг, 16.11.2026): диски направлений - зелёные; оранжевые - только у направлений,
# отмеченных галочкой «Пишем команды»; неподключённые - бледнее (и подпись «не подключён» в тексте диска).
DIR_ON, DIR_OFF = '#1b5e20', '#7fb582'
# Список дисков диалога «Новое направление» / «Назначить диск»: строка с галочкой - голубой фон «выбран сейчас».
SELECTED_BG = '#bbdefb'


def dir_disk_color(connected, writing):
    """Цвет диска в колонке «Диски» таблицы направлений. -> (цвет '#rrggbb', жирный)."""
    if writing:
        return (ASSIGNED_ON, True) if connected else (ASSIGNED_OFF, False)
    return (DIR_ON, True) if connected else (DIR_OFF, False)


def style_disk(set_data, connected, assigned):
    """То же для пункта списка (QListWidgetItem.setData)."""
    color, bold = disk_color(connected, assigned)
    f = QFont()
    f.setBold(bold)
    set_data(Qt.FontRole, f)
    set_data(Qt.ForegroundRole, QBrush(QColor(color)))


def tb_text(b):
    """Объём диска «как на наклейке» - десятичные ТБ: 16 000 900 165 632 байт -> «16 ТБ», 2 ТБ -> «2 ТБ», 500 ГБ."""
    if not b:
        return ''
    if b >= 1e12:
        v = b / 1e12
        return f'{v:.0f} ТБ' if v >= 9.95 or abs(v - round(v)) < 0.05 else f'{v:.1f} ТБ'.replace('.', ',')
    return f'{b / 1e9:.0f} ГБ'
