"""Все имена ядра одним модулем - для команд-потребителей (copy_workflow, recovery_plan) и обёртки hashbase.
Пути и соединение отдаются через __getattr__: всегда текущее значение после set_root()."""
from hb_core.paths import *          # noqa: F401,F403
from hb_core.consts import *          # noqa: F401,F403
from hb_core.schema import *          # noqa: F401,F403
from hb_core.util import *          # noqa: F401,F403
from hb_core.report import *          # noqa: F401,F403
from hb_core.sources import *          # noqa: F401,F403
from hb_core.apply_common import *          # noqa: F401,F403
from hb_core.apply_disk import *          # noqa: F401,F403
from hb_core.apply_log import *          # noqa: F401,F403
from hb_core.apply_manual import *          # noqa: F401,F403
from hb_core.apply_partial import *          # noqa: F401,F403
from hb_core.apply_excl import *          # noqa: F401,F403
from hb_core.derived import *          # noqa: F401,F403
from hb_core.builder import *          # noqa: F401,F403
from hb_core.db import *          # noqa: F401,F403
from hb_core.directions import *          # noqa: F401,F403
from hb_core.query import *          # noqa: F401,F403
from hb_core.razbor import *          # noqa: F401,F403
from hb_core.razbor_scope import *          # noqa: F401,F403
from hb_core.short import *          # noqa: F401,F403
from hb_core import paths as _paths, db as _db

_PATHS = {'BASE_DIR', 'EXCLUSIONS', 'SNAP', 'DECISIONS', 'TASKS', 'DB', 'MOVE_TEMPLATE', 'MANUAL', 'TEMPLATE', 'ANSWERS',
          'DIRECTIONS', 'RAZBORY'}


def __getattr__(name):
    if name in _PATHS:
        return getattr(_paths, name)
    if name == '_last':
        return _db._last
    raise AttributeError(name)
