"""Подмена имени service в тестах (шаг А разбивки service.py на пакет, 17.11.2026; docs/СТРУКТУРА_ПРОГРАММЫ.md).

Функции пакета зовут друг друга по именам своих подмодулей (read_disks.disks зовёт read_disks.volumes): подмена
только sv.X на такие вызовы не действует. sv_patch('X', …) подменяет X в пакете И в каждом подмодуле, где имя X
связано с тем же объектом, - одним и тем же объектом подмены; так подмена действует, как прежде в одном service.py:
и на вызовы из окна (sv.X), и на вызовы изнутри пакета. Подменять имена service в тестах - только так
(test_service_layers.test_tests_patch_service_through_helper).

    with sv_patch('volumes', return_value={}) as m: …          как mock.patch.object(sv, 'volumes', …)
    p = sv_patch('toc_check', toc); p.start(); …; p.stop()
    with sv_patch_multiple(disks=…, generation=…): …            как mock.patch.multiple(sv, …)
    with sv_patch_multiple(ro=mock.DEFAULT) as mocks: mocks['ro'] …   словарь созданных подмен (только DEFAULT)
    with sv_patch('NEW', 1, create=True): …                     имени нет - создаётся в пакете, на выходе убирается
    with sv_patch('ro', a): with sv_patch('ro', b): …           вложенная подмена того же имени - поверх внешней
                                                                 во всех тех же местах, откат в обратном порядке
Один и тот же объект sv_patch запускать второй раз, не остановив, нельзя - RuntimeError (у mock это молча
подменило бы дважды и сломало откат).
"""
import contextlib
import importlib
import pkgutil
from unittest import mock

import service as sv


def submodules():
    """Все подмодули пакета service (загружаются, если ещё не загружены)."""
    return [importlib.import_module(f'{sv.__name__}.{m.name}') for m in pkgutil.iter_modules(sv.__path__)]


def bindings(name):
    """Модули, где имя связано с тем же объектом, что sv.<имя>: сам пакет первым. Под тем же именем другой объект -
    ошибка (подмена разошлась бы с прежним поведением)."""
    if not hasattr(sv, name):
        return [sv]                       # имени нет нигде: только пакет (без create=True - AttributeError, как у mock)
    obj = getattr(sv, name)
    out = [sv]
    for m in submodules():
        if name in vars(m):
            if vars(m)[name] is not obj:
                raise AssertionError(f'{m.__name__}.{name} - не тот объект, что service.{name}')
            out.append(m)
    return out


class sv_patch:
    """Как mock.patch.object(sv, name, new, **kw), но во всех модулях пакета, где имя связано (см. bindings)."""

    def __init__(self, name, new=mock.DEFAULT, **kw):
        self.name, self.new, self.kw = name, new, kw
        self._stack = None

    def start(self):
        if self._stack is not None:
            raise RuntimeError(f'sv_patch({self.name!r}) уже запущен')
        if not hasattr(sv, self.name) and not self.kw.get('create'):
            raise AttributeError(f'service.{self.name}: такого имени нет (нужен create=True)')
        mods = bindings(self.name)                   # при вложенной подмене - те же места: везде внешняя подмена
        stack = contextlib.ExitStack()
        try:
            repl = stack.enter_context(mock.patch.object(mods[0], self.name, self.new, **self.kw))
            for m in mods[1:]:
                stack.enter_context(mock.patch.object(m, self.name, repl))
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        return repl

    def stop(self):
        stack, self._stack = self._stack, None
        if stack is not None:
            stack.close()

    __enter__ = start

    def __exit__(self, *exc):
        self.stop()
        return False


class sv_patch_multiple:
    """Как mock.patch.multiple(sv, create=False, **kw): каждое имя - через sv_patch; start / with отдают словарь
    {имя: подмена} для имён со значением mock.DEFAULT (как mock.patch.multiple)."""

    def __init__(self, create=False, **kw):
        self.parts = [sv_patch(k, v, **({'create': True} if create else {})) for k, v in kw.items()]
        self._stack = None

    def start(self):
        if self._stack is not None:
            raise RuntimeError('sv_patch_multiple уже запущен')
        stack = contextlib.ExitStack()
        made = {}
        try:
            for p in self.parts:
                repl = stack.enter_context(p)
                if p.new is mock.DEFAULT:
                    made[p.name] = repl
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        return made

    def stop(self):
        stack, self._stack = self._stack, None
        if stack is not None:
            stack.close()

    __enter__ = start

    def __exit__(self, *exc):
        self.stop()
        return False
