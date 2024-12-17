"""Central facility for more fine-grained privilege checks per realm."""
from enum import Flag, auto

from cdedb.common import RequestState, User


class EventPrivileges(Flag):
    """Representation of fine-grained event privileges.

    This diffrentiates four areas (the "large" entities lodgement, course, registration
    and the basic event information) and allows to award read and write permissions for
    each individually.
    For reading registrations, this is somewhat more involved: There are privileges for
    * accessing registrations in the backend, with now comprehensive frontend access
    * accessing aggregated registration data, lacking personal data
    * accessing all registration data in the frontend includes the references to
      lodgements and courses, which is why it automatically contains them.
      and
    Also, there are some shorthands or special cases handled separately.
    Generally, this is not adapted in a way to work reliably if you have write, but
    no read permissions, and the frontend might have slight malfunctions for novel
    privilege combinations."""
    basic_read = auto()
    basic_write = auto()
    free_texts_write = auto()
    courses_read = auto()
    courses_write = auto()
    lodgements_read = auto()
    lodgements_write = auto()
    # Aggregated registration data
    registrations_stats = auto()
    # Backend only
    registrations_read_internal = auto()
    # Reading registrations includes reading the associated data (in the frontend)
    _registrations_read_dummy = auto()
    registrations_read = (_registrations_read_dummy | courses_read | lodgements_read
                          | registrations_read_internal)
    registrations_write = auto()
    log_read = auto()
    # send_email = auto()  #: api only? tool suggested recently
    # create = auto()
    conclude = auto()

    # Shorthands for import / export
    all_read = basic_read | registrations_read | log_read
    entities_write = courses_write | registrations_write | lodgements_write
    all_write = basic_write | entities_write


def is_privileged_event(rs: RequestState, required_privilege: EventPrivileges,
                        event_id: int) -> bool:

    return is_privileged_event_user(rs.user, required_privilege, event_id)


def is_privileged_event_user(user: User, required_privilege: EventPrivileges,
                             event_id: int) -> bool:
    """Check whether `user` has `required_privilege` relative to a given `event_id`.

    This also encodes which permission each (generalized) role is supposed to have
    access to. This only needs the `user`, which allows it to be easily referred to
    from templates.
    """
    EP = EventPrivileges
    orga_privileges = ~EP.conclude
    event_helper_privileges = (EP.basic_read | EP.courses_read | EP.lodgements_read |
                               EP.registrations_stats | EP.registrations_read_internal)
    auditor_privileges = EP.basic_read | EP.log_read
    finance_admin_privileges = EP.basic_read | EP.registrations_read_internal

    return (
        "event_admin" in user.roles
        or event_id in user.orga and required_privilege in orga_privileges
        # Due to use in ml realm, users without event realm might come across this
        or ("event_helper" in user.realm_roles.get('event', {})
            and required_privilege in event_helper_privileges)
        # finance_admins are allowed here to book event fees.
        or ("finance_admin" in user.roles
            and required_privilege in finance_admin_privileges)
        or "auditor" in user.roles and required_privilege in auditor_privileges
        # ml_admins are allowed to do this to be able to manage
        # subscribers of event mailinglists.
        or ("ml_admin" in user.roles
            and required_privilege == EP.registrations_read_internal
        )
        or ("droid_quick_partial_export" in user.roles
            and required_privilege in EP.basic_read | EP.registrations_read)
        # or ("droid_orga" in user.roles
        #     and required_privilege in OrgaTokenGrants.implied_privileges())
        # )
    )
