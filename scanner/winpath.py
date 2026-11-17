"""Пути Windows для обращения к файлам источника (сканер 1.6.2).

Обычный путь Win32 «чинит» имена: обрезает точку и пробел на конце («a.» -> «a»), а CON, PRN, AUX, NUL,
COM1-9, LPT1-9 (и «CON.jpg») превращает в устройство. Путь с префиксом \\\\?\\ передаётся файловой системе
как есть: такие файлы читаются, и длина пути не ограничена 260 знаками. Здесь же - обратное преобразование
(в описи и журналах путь обычный) и относительный путь строкой (os.path.relpath портит те же имена).
"""
import os
from pathlib import Path, PureWindowsPath

PREFIX = '\\\\?\\'
UNC = PREFIX + 'UNC\\'


def extended(path):
    """Путь -> \\\\?\\-путь. Имена не меняются (точки, пробелы на конце, CON сохраняются); '.' и '..' снимаются
    строкой, без os.path.abspath. Корень диска - '\\\\?\\X:\\' (с чертой: без неё это устройство тома)."""
    s = os.fspath(path)
    if s.startswith(PREFIX):
        return s
    s = s.replace('/', '\\')
    if s.startswith('\\\\.\\'):
        raise ValueError(f'Путь устройства не поддерживается: {s}')
    if s.startswith('\\\\'):                                   # UNC: \\сервер\ресурс\...
        parts = s[2:].split('\\')
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(f'Неполный сетевой путь: {s}')
        head, rest = UNC + parts[0] + '\\' + parts[1], parts[2:]
    else:
        if s[1:2] != ':':                                      # относительный путь - от текущей папки (строкой)
            return extended(os.path.join(os.getcwd(), s))
        if s[2:3] != '\\':
            raise ValueError(f'Путь относительно текущей папки диска не поддерживается: {s}')
        head, rest = PREFIX + s[:2], s[3:].split('\\')
    names = []
    for name in rest:
        if name in ('', '.'):
            continue
        if name == '..':
            if names:
                names.pop()
            continue
        names.append(name)
    return head + '\\' + '\\'.join(names)


def plain(path):
    """\\\\?\\-путь -> обычный (для описи, журналов и сообщений)."""
    s = os.fspath(path)
    if s.startswith(UNC):
        return '\\\\' + s[len(UNC):]
    if s.startswith(PREFIX):
        return s[len(PREFIX):]
    return s


def safe_relative(rel):
    """Путь из описи -> части; абсолютный, с буквой диска, '.', '..' или ':' - ValueError (перенесено из portable)."""
    p = PureWindowsPath(rel)
    if not p.parts or p.is_absolute() or p.drive or any(x in ('.', '..') or ':' in x for x in p.parts):
        raise ValueError('Unsafe relative path')
    return p.parts


def source_path(root, rel):
    """Файл описи на томе root - \\\\?\\-путь (Path) с исходным именем."""
    return Path(extended(root)).joinpath(*safe_relative(rel))


def under(path, root):
    """Путь относительно root - строкой (оба в одном написании, как их склеил обход). Не внутри - ValueError."""
    base = root if root.endswith('\\') else root + '\\'
    if not path.startswith(base) or len(path) == len(base):
        raise ValueError(f'Путь вне корня обхода: {plain(path)}')
    return path[len(base):]
