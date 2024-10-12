from enum import Flag, auto
from typing import Optional

from cdedb.common import RequestState


class EventPrivileges(Flag):
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
    create = auto()
    archive = auto()
    delete = auto()
    admin_only = create | archive | delete
    event_helper = basic_read | courses_read | registrations_stats


def is_privileged_event(rs: RequestState,
                     necessary_privilege: EventPrivileges,
                     event_id: Optional[int] = None) -> bool:
    return (
            "event_admin" in rs.user.roles
            or event_id in rs.user.orga and not (
                necessary_privilege & EventPrivileges.admin_only
            )
            or "event_helper" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege in EventPrivileges.event_helper
            )
            # or "droid_orga" in rs.user.roles and (
            #         sufficient_privilege in OrgaTokenGrants.implied_privileges()
            # )
    )
