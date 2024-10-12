from enum import Flag, auto
from typing import Optional

from cdedb.common import RequestState


class EventPrivileges(Flag):
    # Generally, this is not adapted in a way to work reliably if you have write, but
    # no read permissions.
    basic_read = auto()
    basic_write = auto()
    courses_read = auto()
    courses_write = auto()
    lodgements_read = auto()
    lodgements_write = auto()
    # Aggregated registration data
    registrations_stats = auto()
    # Who is registered for which parts with which status?
    registrations_read_restricted = auto()
    registrations_read_extended = auto()
    registrations_read = registrations_read_restricted
    registrations_write = auto()
    log_read = auto()
    # send_email = auto()  #: api only? tool suggested recently
    create = auto()
    archive = auto()
    delete = auto()
    # Grouped by privilege
    admin_only = create | archive | delete
    event_helper = basic_read | courses_read | registrations_stats
    auditor = basic_read | log_read
    # Shorthands for import / export
    all_read = basic_read | courses_read | registrations_read | lodgements_read | log_read
    entities_write = courses_write | registrations_write | lodgements_write


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
            or "finance_admin" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege == EventPrivileges.basic_read
            )
            or "auditor" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege in EventPrivileges.auditor
            )
            # or "droid_orga" in rs.user.roles and (
            #         sufficient_privilege in OrgaTokenGrants.implied_privileges()
            # )
    )
