from enum import Enum, auto
from typing import AbstractSet, Optional

from cdedb.common import RequestState


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


ComplexEventPrivileges = EventPrivileges | None | AbstractSet[EventPrivileges | None]

# This has only all support, no any support, for the privileges to avoid mistakes.
def may_manage_event(rs: RequestState,
                     necessary_privilege: ComplexEventPrivileges,
                     event_id: Optional[int] = None) -> bool:
    ep = EventPrivileges
    if not isinstance(necessary_privilege, AbstractSet):
        necessary_privilege = {necessary_privilege}

    return ("event_admin" in rs.user.roles
            or event_id in rs.user.orga
            or ("event_helper" in rs.user.roles
                and necessary_privilege <= {
                    ep.basic_read, ep.courses_read, ep.registrations_stats}))
            # or ("droid_orga" in rs.user.roles
            #     and necessary_privilege <= OrgaTokenGrants.implied_privileges()))
