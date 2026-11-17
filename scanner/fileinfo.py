"""Сведения о файле через один дескриптор Windows (вынесено из rescan в 1.6.2; путь - через \\\\?\\, winpath).

Размер, даты, ChangeTime, номер файла NTFS - без чтения содержимого. rescan по-прежнему отдаёт file_info и Busy.
"""
import ctypes
from ctypes import wintypes

from winpath import extended

EPOCH_DIFF = 116444736000000000             # FILETIME (100 нс с 1601) -> Unix


class _BHFI(ctypes.Structure):
    _fields_ = [('attrs', wintypes.DWORD), ('c', wintypes.FILETIME), ('a', wintypes.FILETIME), ('w', wintypes.FILETIME),
                ('vsn', wintypes.DWORD), ('size_hi', wintypes.DWORD), ('size_lo', wintypes.DWORD),
                ('links', wintypes.DWORD), ('idx_hi', wintypes.DWORD), ('idx_lo', wintypes.DWORD)]


class _FBI(ctypes.Structure):
    _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong), ('write', ctypes.c_longlong),
                ('change', ctypes.c_longlong), ('attrs', wintypes.DWORD)]


_K32 = None


def _k32():
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE]
        k.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        _K32 = k
    return _K32


class Busy(OSError):
    """Файл открыт другой программой на запись: подтвердить его неизменность сейчас нельзя."""


def file_info(path, exclusive=False):
    """Размер, mtime, время создания, ChangeTime, номер файла NTFS, атрибуты, ссылок - через ОДИН дескриптор.
    Содержимое не читается. exclusive=True - открыть так, чтобы никто не мог писать в файл, пока он открыт
    (если пишет уже сейчас - Busy)."""
    k = _k32()
    access = 0x80000000 if exclusive else 0x80          # GENERIC_READ (данные не читаются) / FILE_READ_ATTRIBUTES
    share = 0x1 if exclusive else 0x7                    # только чтение / чтение, запись, удаление
    h = k.CreateFileW(extended(path), access, share, None, 3, 0x02000000 | 0x00200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        code = ctypes.get_last_error()
        if code in (32, 33):
            raise Busy(code, 'файл занят другой программой', str(path))
        raise ctypes.WinError(code)
    try:
        b, f = _BHFI(), _FBI()
        if not k.GetFileInformationByHandle(h, ctypes.byref(b)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k.GetFileInformationByHandleEx(h, 0, ctypes.byref(f), ctypes.sizeof(f)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(h)

    def ns(ft):
        return (ft - EPOCH_DIFF) * 100 if ft else 0
    return dict(size=(b.size_hi << 32) | b.size_lo, mtime_ns=ns(f.write), ctime_ns=ns(f.creation), change_ns=ns(f.change),
                file_id=str((b.idx_hi << 32) | b.idx_lo), attrs=f.attrs, links=b.links)
