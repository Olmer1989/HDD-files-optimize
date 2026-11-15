"""Общее оформление носителей в окне: порядок (подключённые сейчас - первыми), названия, цвета, состояние описи.

Используют раздел «Команды» (выбор диска в формах) и раздел «Диски и папки» (таблица носителей).
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont

ON_COLOR, OFF_COLOR = QColor('#1b5e20'), QColor('#8a8a8a')
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


def disk_title(r):
    """Понятное название из описи: «метка тома (марка, объём)»; без метки - модель и объём."""
    parts = [x.strip() for x in (r.get('label') or '').split(' - ') if x.strip()]
    if not parts:
        return ''
    model = parts[0]
    size = parts[1] if len(parts) > 1 and SIZE_RE.match(parts[1]) else ''
    vol = ' - '.join(parts[2:] if size else parts[1:])
    brand = model.split()[0] if model.split() else ''
    brand = brand if (brand.isalpha() or '_' in brand) and not any(ch.isdigit() for ch in brand) else ''
    brief = ' '.join(x for x in (brand, size) if x)
    if vol:
        return f'{vol} ({brief})' if brief else vol
    return ', '.join(x for x in (model, size) if x)


def disk_text(r):
    """«● HDD54 — E: — Исходники (ADATA 2 ТБ)» или «HDD61 — ACASIS EC-7352, 750 ГБ — не подключён»."""
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
