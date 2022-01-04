from cdedb.backend.core.base import CoreBaseBackend
from cdedb.backend.core.genesis import CoreGenesisBackend


class CoreBackend(CoreGenesisBackend, CoreBaseBackend):
    pass
