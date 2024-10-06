from collections.abc import Iterable
from enum import Enum, auto
from typing import Optional

from cdedb.common import RequestState, n_


class EventPrivileges(Enum):
    basic_read = auto()
    basic_write = auto()
    courses_read = auto()
    courses_write = auto()
    lodgements_read = auto()
    lodgements_write = auto()
    registrations_stats = auto()
    registrations_read = auto()
    registrations_write = auto()
    # send_email = auto()  #: api only? tool suggested recently
    # lifecycle = auto()  #: create, archive, delete. Admin only.


def may_manage_event(rs: RequestState,
                     sufficient_privilege: Optional[EventPrivileges] = None,
                     event_id: Optional[int] = None) -> bool:
    if not event_id:
        if not rs.ambience.get('event'):
            raise RuntimeError(n_("No event context given"))
        event_id = rs.ambience['event'].id
    ep = EventPrivileges
    return ("event_admin" in rs.user.roles
            or event_id in rs.user.orga
            or ("event_helper" in rs.user.roles and sufficient_privilege is not None
                and sufficient_privilege in {ep.basic_read, ep.registrations_stats}))
            # or ("droid_orga" in rs.user.roles
            #     and sufficient_privilege in OrgaTokenGrants.implied_privileges()))


def may_manage_event_all(rs: RequestState,
                         required_privileges: Iterable[EventPrivileges]) -> bool:
    # Incorporating this into may_manage_event would be nice, but a security risk
    # due to our convention for @access being @access_any rather than @access_all.
    return all(may_manage_event(rs, privilege) for privilege in required_privileges)
