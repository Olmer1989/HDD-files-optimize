"""Соединение с рабочей базой (только здесь живёт _last)."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import sqlite3
import build_pilot as bp
from hb_core import paths
from hb_core.builder import update


_last = None      # последнее открытое соединение: закрывается перед пересборкой, иначе Windows не даст заменить файл


def close_last():
    global _last
    if _last is not None:
        try:
            _last.close()
        except sqlite3.Error:
            pass
        _last = None


def connect():
    global _last
    close_last()
    jobs = bp.find_jobs()
    update(jobs, quiet=True)
    _last = sqlite3.connect(f'file:{paths.DB.as_posix()}?mode=ro', uri=True)
    return _last, jobs
