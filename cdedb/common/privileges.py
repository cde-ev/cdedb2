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
    # Backend only
    registrations_read_internal = auto()
    # Reading registrations includes reading the associated data (in the frontend)
    registrations_read = courses_read | lodgements_read | registrations_read_internal
    registrations_write = auto()
    log_read = auto()
    # send_email = auto()  #: api only? tool suggested recently
    create = auto()
    archive = auto()
    delete = auto()

    # Shorthands for import / export
    all_read = basic_read | registrations_read | log_read
    entities_write = courses_write | registrations_write | lodgements_write

    # Shorthands for certain roles
    admin_only = create | archive | delete
    event_helper = basic_read | courses_read | registrations_stats | registrations_read_internal
    auditor = basic_read | log_read
    finance_admin = basic_read | registrations_read_internal


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
            # finance_admins are allowed here to book event fees.
            or "finance_admin" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege in EventPrivileges.finance_admin
            )
            or "auditor" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege in EventPrivileges.auditor
            )
            # ml_admins are allowed to do this to be able to manage
            # subscribers of event mailinglists.
            or "ml_admin" in rs.user.roles and (
                necessary_privilege is not None
                and necessary_privilege == EventPrivileges.registrations_read_internal
            )
            # or "droid_orga" in rs.user.roles and (
            #         sufficient_privilege in OrgaTokenGrants.implied_privileges()
            # )
    )
