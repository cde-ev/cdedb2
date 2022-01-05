from cdedb.backend.core.base import CoreBaseBackend
from cdedb.backend.core.genesis import CoreGenesisBackend

"""The core backend provides services which are common for all users.

The user roles which are most relevant are:
* `anonymous`: For non-logged-in users (actually logged-in users too).
* `persona`: For logged-in users regardless of the users realms.
"""


class CoreBackend(CoreGenesisBackend, CoreBaseBackend):
    pass
