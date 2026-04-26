#!/usr/bin/env python3

"""
The `EventBaseBackend` provides backend functionality related to events in general.

There are several subclasses in separate files which provide additional functionality
related to more specific aspects of event management.

This subclasses `EventBackendHelpers`, which provides a collection of internal
low-level helpers which are used here and in the subclasses.

All parts are combined together in the `EventBackend` class via multiple inheritance,
together with a handful of high-level methods, that use functionalities of multiple
backend parts.
"""

import abc
import collections
import copy
import datetime
import decimal
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Protocol, cast

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.backend.common import (
    access,
    affirm_validation as affirm,
    internal,
    singularize,
)
from cdedb.backend.entity_keeper import EntityKeeper
from cdedb.backend.event.lowlevel import EventLowLevelBackend
from cdedb.common import (
    EVENT_SCHEMA_VERSION,
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    RequestState,
    cast_field_entries,
    cast_fields,
    json_serialize,
    make_persona_name,
    normalize_field_entries,
    now,
    unwrap,
)
from cdedb.common.crypt import encrypt_password
from cdedb.common.exceptions import EventIsBalancedError, PrivilegeError
from cdedb.common.fields import (
    EVENT_ROLE_FIELDS,
    PERSONA_EVENT_FIELDS,
    QUESTIONNAIRE_ROW_FIELDS,
    REGISTRATION_FIELDS,
    REGISTRATION_PART_FIELDS,
    REGISTRATION_TRACK_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.privileges import (
    EventPrivileges,
    is_privileged_event as is_privileged,
)
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.filter import datetime_filter
from cdedb.models.common import CdEDataclass
from cdedb.models.core import EventPersona
from cdedb.models.droid import OrgaToken

if TYPE_CHECKING:
    from cdedb.backend.event.registration import ComplexRegistrationFee

# type alias for questionnaire specification.
CdEDBQuestionnaire = dict[const.QuestionnaireUsages, list[CdEDBObject]]


class EventBaseBackend(EventLowLevelBackend):
    def __init__(self) -> None:
        super().__init__()
        # define which keys of log entries will show up in commit messages
        # they are translated to german, since commit messages are always in german
        log_keys = ["Zeitstempel", "Code", "Verantwortlich", "Betroffen", "Erläuterung"]
        self._event_keeper = EntityKeeper(
            self.conf, 'event_keeper', log_keys=log_keys, log_timestamp_key="ctime"
        )

    @access("anonymous")
    def is_locked(self, rs: RequestState, *, event_id: int) -> bool:
        """Helper to determine if an event is locked."""
        event_id = affirm(vtypes.ID, event_id)
        query = "SELECT is_locked FROM event.events WHERE id = %s"
        data = self.query_one(rs, query, (event_id,))
        if data is None:
            raise ValueError(n_("Event does not exist"))
        return data['is_locked'] and not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]

    def assert_lock(self, rs: RequestState, *, event_id: int) -> None:
        """Helper to check locking state of an event.

        This raises an exception in case of the wrong locking state.
        """
        if self.is_locked(rs, event_id=event_id):
            raise RuntimeError(n_("This event is locked."))

    @access("persona")
    def orga_infos(
        self, rs: RequestState, persona_ids: Collection[int]
    ) -> dict[int, set[int]]:
        """List events organized by specific personas."""
        persona_ids = affirm(set[vtypes.ID], persona_ids)
        data = self.sql_select(
            rs,
            "event.orgas",
            ("persona_id", "event_id"),
            persona_ids,
            entity_key="persona_id",
        )
        ret: dict[int, set[int]] = {}
        for anid in persona_ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    @access("persona")
    def caretaker_infos(
        self,
        rs: RequestState,
        persona_ids: Collection[int],
    ) -> dict[int, set[int]]:
        """List events cared for by specific personas."""
        persona_ids = affirm(set[vtypes.ID], persona_ids)
        data = self.sql_select(
            rs,
            "event.caretakers",
            ("persona_id", "event_id"),
            persona_ids,
            entity_key="persona_id",
        )
        ret: dict[int, set[int]] = {}
        for anid in persona_ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    class _CaretakerInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> set[int]: ...

    caretaker_info: _CaretakerInfoProtocol = singularize(
        caretaker_infos, "persona_ids", "persona_id"
    )

    @access("persona")
    def checkin_helper_infos(
        self,
        rs: RequestState,
        persona_ids: Collection[int],
    ) -> dict[int, set[int]]:
        """List events where specific personas are checkin helpers."""
        persona_ids = affirm(set[vtypes.ID], persona_ids)
        data = self.sql_select(
            rs,
            "event.checkin_helpers",
            ("persona_id", "event_id"),
            persona_ids,
            entity_key="persona_id",
        )
        ret: dict[int, set[int]] = {}
        for anid in persona_ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    class _CheckinHelperInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> set[int]: ...

    checkin_helper_info: _CheckinHelperInfoProtocol = singularize(
        checkin_helper_infos, "persona_ids", "persona_id"
    )

    @access("persona")
    def get_event_helpers(self, rs: RequestState) -> set[vtypes.ID]:
        """List all event helpers."""
        data = self.query_all(rs, "SELECT persona_id FROM event.helpers", [])
        return {e['persona_id'] for e in data}

    class _OrgaInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> set[int]: ...

    orga_info: _OrgaInfoProtocol = singularize(orga_infos, "persona_ids", "persona_id")

    @access("event", "auditor")
    def retrieve_log(self, rs: RequestState, log_filter: EventLogFilter) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm(EventLogFilter, log_filter)
        event_ids = log_filter.event_ids()

        if not all(
            is_privileged(rs, EventPrivileges.log_read, event_id=event_id)
            for event_id in event_ids
        ):
            raise PrivilegeError(n_("Not privileged."))

        return self.generic_retrieve_log(rs, log_filter)

    @access("anonymous")
    def list_events(
        self,
        rs: RequestState,
        current: bool | None = None,
        archived: bool | None = None,
    ) -> dict[int, str]:
        """List all events organized via DB.

        :returns: Mapping of event ids to titles.
        """
        subquery = f"""
            SELECT
                e.id, e.registration_start, e.title, e.is_archived, e.is_cancelled,
                MAX(p.part_end) AS event_end
            FROM {models.Event.database_table} AS e
                JOIN {models.EventPart.database_table} AS p ON p.event_id = e.id
            GROUP BY e.id
        """
        query = f"SELECT e.* from ({subquery}) as e"
        constraints = []
        params = {}
        if current is not None:
            if current:
                constraints.append("e.event_end >= now()::date")
                constraints.append("e.is_cancelled = False")
            else:
                constraints.append(
                    "(e.event_end < now()::date OR e.is_cancelled = True)"
                )
        if archived is not None:
            constraints.append("is_archived = %(is_archived)s")
            params["is_archived"] = archived

        if constraints:
            query += " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def get_events(
        self,
        rs: RequestState,
        event_ids: Collection[int],
    ) -> models.CdEDataclassMap[models.Event]:
        event_ids = affirm(set[vtypes.ID], event_ids)
        with Atomizer(rs):
            event_data = {
                e['id']: e
                for e in self.query_all(rs, *models.Event.get_select_query(event_ids))
            }
            part_data = self.query_all(
                rs, *models.EventPart.get_select_query(event_ids)
            )
            all_parts = {e['id']: e['event_id'] for e in part_data}
            part_group_data = self.query_all(
                rs, *models.PartGroup.get_select_query(event_ids)
            )
            track_data = self.query_all(
                rs, *models.CourseTrack.get_select_query(all_parts.keys())
            )
            track_group_data = self.query_all(
                rs, *models.TrackGroup.get_select_query(event_ids)
            )
            fee_data = self.query_all(rs, *models.EventFee.get_select_query(event_ids))
            field_data = self.query_all(
                rs, *models.EventField.get_select_query(event_ids)
            )
            custom_filter_data = self.query_all(
                rs, *models.CustomQueryFilter.get_select_query(event_ids)
            )
        for e in event_data.values():
            e['parts'] = []
            e['part_groups'] = []
            e['tracks'] = []
            e['track_groups'] = []
            e['fees'] = []
            e['fields'] = []
            e['custom_query_filters'] = []
        for p in part_data:
            event_data[p['event_id']]['parts'].append(p)
        for pg in part_group_data:
            event_data[pg['event_id']]['part_groups'].append(pg)
        for t in track_data:
            event_data[all_parts[t['part_id']]]['tracks'].append(t)
        for tg in track_group_data:
            event_data[tg['event_id']]['track_groups'].append(tg)
        for fee in fee_data:
            event_data[fee['event_id']]['fees'].append(fee)
        for field in field_data:
            event_data[field['event_id']]['fields'].append(field)
        for custom_filter in custom_filter_data:
            event_data[custom_filter['event_id']]['custom_query_filters'].append(
                custom_filter
            )
        return models.Event.many_from_database(event_data.values())

    # The annonation for this lives in the lowlevel backend.
    get_event = singularize(get_events, "event_ids", "event_id")

    @access("event")
    def verify_shortname_existence(self, rs: RequestState, shortname: str) -> bool:
        """Return True if the given shortname already exists for some event."""
        shortname = affirm(str, shortname)
        return bool(
            self.query_all(
                rs, "SELECT id FROM event.events WHERE shortname = %s", (shortname,)
            )
        )

    @access("anonymous")
    def get_minor_form_path(self, rs: RequestState, event_id: int) -> Path:
        event_id = affirm(vtypes.ID, event_id)
        return self.minor_form_dir / str(event_id)

    @access("anonymous")
    def has_minor_form(self, rs: RequestState, event_id: int) -> bool:
        event_id = affirm(vtypes.ID, event_id)
        return self.get_minor_form_path(rs, event_id).is_file()

    @access("event")
    def change_minor_form(
        self, rs: RequestState, event_id: int, minor_form: Optional[bytes]
    ) -> DefaultReturnCode:
        """Change or remove an event's minor form.

        Return 1 on successful change, -1 on successful deletion, 0 otherwise."""
        event_id = affirm(vtypes.ID, event_id)
        minor_form = affirm(vtypes.PDFFile | None, minor_form, file_storage=False)
        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Must be orga or admin to change the minor form."))
        path = self.get_minor_form_path(rs, event_id)
        if minor_form is None:
            if path.is_file():
                path.unlink()
                # Since this is not acting on our database, do not demand an atomized
                # context.
                self.event_log(
                    rs, const.EventLogCodes.minor_form_removed, event_id, atomized=False
                )
                return -1
            else:
                return 0
        else:
            with open(path, "wb") as f:
                f.write(minor_form)
            # Since this is not acting on our database, do not demand an atomized
            # context.
            self.event_log(
                rs, const.EventLogCodes.minor_form_updated, event_id, atomized=False
            )
            return 1

    @access("persona")
    def validate_event_persona_ids(
        self, rs: RequestState, persona_ids: Collection[int]
    ) -> None:
        """Validate whether persona_ids are valid for receiving event privileges."""
        if not persona_ids:
            raise ValueError(n_("Must not be empty."))
        if not self.core.verify_ids(rs, persona_ids, is_archived=False):
            raise ValueError(n_("Some of these personas do not exist or are archived."))
        if not self.core.verify_personas(rs, persona_ids, {"event"}):
            raise ValueError(n_("Some of these personas are not event users."))

    @access("event_admin")
    def add_event_helpers(
        self, rs: RequestState, persona_ids: Collection[int]
    ) -> DefaultReturnCode:
        """Add event helpers."""
        persona_ids = affirm(set[vtypes.ID], persona_ids)

        ret = 1
        with Atomizer(rs):
            self.validate_event_persona_ids(rs, persona_ids)
            for anid in xsorted(persona_ids):
                # on conflict do nothing
                r = self.sql_insert(
                    rs, "event.helpers", {'persona_id': anid}, drop_on_conflict=True
                )
                if r:
                    self.event_log(
                        rs,
                        const.EventLogCodes.helper_added,
                        event_id=None,
                        persona_id=anid,
                    )
                ret *= r

        # Update session helper status
        if rs.user.persona_id in persona_ids:
            rs.user.realm_roles['event'].add('event_helper')

        return ret

    @access("event_admin")
    def remove_event_helper(
        self, rs: RequestState, persona_id: int
    ) -> DefaultReturnCode:
        """Remove a single event helper."""
        persona_id = affirm(vtypes.ID, persona_id)
        query = "DELETE FROM event.helpers WHERE persona_id = %s"
        with Atomizer(rs):
            ret = self.query_exec(rs, query, [persona_id])
            if ret:
                self.event_log(
                    rs,
                    const.EventLogCodes.helper_removed,
                    event_id=None,
                    persona_id=persona_id,
                )

            # Update session helper status
            if rs.user.persona_id == persona_id:
                rs.user.realm_roles['event'].remove('event_helper')

        return ret

    def _affirm_event_role_privileges(
        self,
        rs: RequestState,
        event_id: int,
        role: Literal['orga', 'caretaker', 'checkin_helper'],
    ) -> None:
        if role == 'orga':
            if not is_privileged(rs, EventPrivileges.orgas_change, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
        elif role == 'caretaker':
            if not is_privileged(
                rs, EventPrivileges.caretakers_change, event_id=event_id
            ):
                raise PrivilegeError(n_("Not privileged."))
        elif role == 'checkin_helper':
            if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
        else:
            raise RuntimeError(n_("Impossible."))

    @access("event")
    def add_event_roles(
        self,
        rs: RequestState,
        event_id: int,
        persona_ids: Collection[int],
        role: Literal['orga', 'caretaker', 'checkin_helper'],
    ) -> DefaultReturnCode:
        """Add orgas to an event.

        This is basically un-inlined code from `set_event`, but may also be
        called separately.

        Note that this requires different privileges than `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_ids = affirm(set[vtypes.ID], persona_ids)
        self._affirm_event_role_privileges(rs, event_id, role)

        ret = 1
        with Atomizer(rs):
            self.validate_event_persona_ids(rs, persona_ids)

            for anid in xsorted(persona_ids):
                new_orga = {
                    'persona_id': anid,
                    'event_id': event_id,
                }
                # on conflict do nothing
                r = self.sql_insert(
                    rs, f"event.{role}s", new_orga, drop_on_conflict=True
                )
                if r:
                    self.event_log(
                        rs,
                        const.EventLogCodes[role + "_added"],
                        event_id,
                        persona_id=anid,
                    )
                    ret *= r

        # Update session status
        if rs.user.persona_id in persona_ids:
            getattr(rs.user, role).add(event_id)

        return ret

    @access("event")
    def remove_event_role(
        self,
        rs: RequestState,
        event_id: int,
        persona_id: int,
        role: Literal['orga', 'caretaker', 'checkin_helper'],
    ) -> DefaultReturnCode:
        """Remove a single orga of an event.

        Note that this requires different privileges than `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_id = affirm(vtypes.ID, persona_id)
        self._affirm_event_role_privileges(rs, event_id, role)

        query = f"""
            DELETE FROM event.{role}s
            WHERE persona_id = %(persona_id)s AND event_id = %(event_id)s
        """
        params = {"persona_id": persona_id, "event_id": event_id}
        with Atomizer(rs):
            ret = self.query_exec(rs, query, params)
            if ret:
                self.event_log(
                    rs,
                    const.EventLogCodes[role + "_removed"],
                    event_id,
                    persona_id=persona_id,
                )

        # Update session orga status
        if rs.user.persona_id == persona_id:
            getattr(rs.user, role).remove(event_id)

        return ret

    @access("event")
    def list_orga_tokens(self, rs: RequestState, event_id: int) -> dict[int, str]:
        """List all orga tokens belonging to one event.

        :returns: Mapping of token ids to titles.
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.basic_read, event_id=event_id):
            raise PrivilegeError
        data = self.sql_select(
            rs,
            OrgaToken.database_table,
            ("id", "title"),
            (event_id,),
            entity_key="event_id",
        )
        return {e['id']: e['title'] for e in data}

    @access("event")
    def get_orga_tokens(
        self, rs: RequestState, orga_token_ids: Collection[int]
    ) -> dict[int, OrgaToken]:
        """Retrieve information about orga tokens."""
        orga_token_ids = affirm(set[vtypes.ID], orga_token_ids)
        if not orga_token_ids:
            return {}

        with Atomizer(rs):
            ret = OrgaToken.many_from_database(
                self.query_all(
                    rs,
                    *OrgaToken.get_select_query(orga_token_ids, "id"),
                ),
            )

            event_ids = {token.event_id for token in ret.values()}
            if not len(event_ids) == 1:
                raise ValueError(n_("Only orga tokens from one event allowed."))
            if not is_privileged(
                rs, EventPrivileges.basic_read, event_id=unwrap(event_ids)
            ):
                raise PrivilegeError

        return ret

    class _GetOrgaAPITokenProtocol(Protocol):
        def __call__(self, rs: RequestState, orga_token_id: int) -> OrgaToken: ...

    get_orga_token: _GetOrgaAPITokenProtocol = singularize(
        get_orga_tokens, "orga_token_ids", "orga_token_id"
    )

    @access("event")
    def create_orga_token(self, rs: RequestState, data: CdEDBObject) -> tuple[int, str]:
        """Create a new orga token for the given event.

        :returns: A tuple of the new token id and it's secret. The secret is only
            stored as a hash and thus cannot be retrieved again.
        """
        data = affirm(OrgaToken, data, creation=True)

        with Atomizer(rs):
            if not is_privileged(rs, EventPrivileges.token, event_id=data["event_id"]):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(
                    n_("May not create new orga token in offline instance.")
                )

            secret = OrgaToken.create_secret()
            data['secret_hash'] = encrypt_password(secret)
            data['ctime'] = now()

            new_id = self.sql_insert(rs, OrgaToken.database_table, data)
            self.event_log(
                rs,
                const.EventLogCodes.orga_token_created,
                data["event_id"],
                change_note=data["title"],
            )
        return new_id, secret

    @access("event")
    def change_orga_token(
        self, rs: RequestState, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Change some keys of an existing orga token.

        Note that only a small subset of token attributes may be changed.
        """
        data = affirm(OrgaToken, data)

        with Atomizer(rs):
            current = self.get_orga_token(rs, data['id'])
            current_data = current.to_database()

            if not is_privileged(rs, EventPrivileges.token, event_id=current.event_id):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(n_("May not change orga token in offline instance."))

            ret = 1
            if any(data[k] != current_data[k] for k in data):
                ret *= self.sql_update(rs, OrgaToken.database_table, data)

                if 'title' in data and data['title'] != current.title:
                    change_note = f"'{current.title}' -> '{data['title']}'"
                else:
                    change_note = current.title
                self.event_log(
                    rs,
                    const.EventLogCodes.orga_token_changed,
                    current.event_id,
                    change_note=change_note,
                )
        return ret

    @access("event")
    def revoke_orga_token(
        self, rs: RequestState, orga_token_id: int
    ) -> DefaultReturnCode:
        """Revoke an existing orga token and delete its hashed secret."""
        orga_token_id = affirm(vtypes.ID, orga_token_id)

        with Atomizer(rs):
            current = self.get_orga_token(rs, orga_token_id)

            if not is_privileged(rs, EventPrivileges.token, event_id=current.event_id):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(n_("May not revoke orga token in offline instance."))

            if current.rtime:
                raise ValueError(n_("This orga token has already been revoked."))

            data = {
                'id': orga_token_id,
                'secret_hash': None,
                'rtime': now(),
            }
            ret = self.sql_update(rs, OrgaToken.database_table, data)
            self.event_log(
                rs,
                const.EventLogCodes.orga_token_revoked,
                event_id=current.event_id,
                change_note=current.title,
            )

        return ret

    @access("event")
    def delete_orga_token_blockers(
        self, rs: RequestState, orga_token_id: int
    ) -> DeletionBlockers:
        """Determine what keeps an orga  token from being deleted.

        Possible blockers:

        * atime: Block deletion if the token has ever been used.
        * log: Log entries linked to the token.

        Blockers should only be cascaded during event deletion.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        orga_token_id = affirm(vtypes.ID, orga_token_id)
        blockers: DeletionBlockers = {}

        orga_token = self.sql_select_one(
            rs, OrgaToken.database_table, ("atime",), orga_token_id
        )
        if orga_token and orga_token['atime']:
            blockers['atime'] = [True]

        log = self.sql_select(
            rs, "event.log", ("id",), (orga_token_id,), entity_key="droid_id"
        )
        if log:
            blockers['log'] = [e['id'] for e in log]

        return blockers

    @access("event")
    def delete_orga_token(
        self,
        rs: RequestState,
        orga_token_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Delete an orga  token.

        :param cascade: Specify which deletion blockers to cascadingly remove or ignore.
            If None or empty, cascade none.
        """
        orga_token_id = affirm(vtypes.ID, orga_token_id)
        blockers = self.delete_orga_token_blockers(rs, orga_token_id)
        cascade = affirm(set[str], cascade or ()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    'type': "orga token",
                    'block': blockers.keys() - cascade,
                },
            )

        if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
            raise ValueError(n_("May not revoke orga token in offline instance."))

        ret = 1
        with Atomizer(rs):
            orga_token = self.get_orga_token(rs, orga_token_id)

            if not is_privileged(
                rs, EventPrivileges.token, event_id=orga_token.event_id
            ):
                raise PrivilegeError

            if cascade:
                if 'atime' in cascade:
                    update = {
                        'id': orga_token_id,
                        'atime': None,
                    }
                    ret *= self.sql_update(rs, OrgaToken.database_table, update)
                if 'log' in cascade:
                    ret *= self.sql_delete(rs, "event.log", blockers['log'])

                blockers = self.delete_orga_token_blockers(rs, orga_token_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, OrgaToken.database_table, orga_token_id)
                self.event_log(
                    rs,
                    const.EventLogCodes.orga_token_deleted,
                    orga_token.event_id,
                    change_note=orga_token.title,
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {'type': "orga token", 'block': blockers.keys()},
                )

        return ret

    @access("event", "droid_orga")
    def set_event(
        self,
        rs: RequestState,
        event_id: int,
        data: CdEDBObject,
        change_note: Optional[str] = None,
    ) -> DefaultReturnCode:
        """Update some keys of an event organized via DB.

        The syntax for updating the associated data on orgas, parts and
        fields is as follows:

        * If the keys 'parts', or 'fields' are present,
          the associated dict mapping the part, or field ids to
          the respective data sets can contain an arbitrary number of entities,
          absent entities are not modified.

          Any valid entity id that is present has to map to a (partial or
          complete) data set or ``None``. In the first case the entity is
          updated, in the second case it is deleted. Deletion depends on
          the entity being nowhere referenced, otherwise an error is
          raised.

          Any invalid entity id (that is negative integer) has to map to a
          complete data set which will be used to create a new entity.

          The same logic applies to the 'tracks' dicts inside the
          'parts'. Deletion of parts implicitly deletes the dependent
          tracks and fee modifiers.

          Note that due to allowing only subsets of the existing fields,
          fee modifiers, parts and tracks to be given, there are some invalid
          combinations that cannot currently be detected at this point,
          e.g. trying to create a field with a `field_name` that already
          exists for this event. See Issue #1140.
        """
        event_id = affirm(vtypes.ID, event_id)
        ret = 1
        with Atomizer(rs):
            current = self.get_event(rs, event_id)
            data = affirm(models.Event, data, event=current)
            data['id'] = event_id

            if not is_privileged(
                rs,
                EventPrivileges.basic_write | EventPrivileges.free_texts_write,
                event_id=event_id,
            ):
                raise PrivilegeError(n_("Not privileged."))
            self.assert_lock(rs, event_id=event_id)

            edata = {
                k: v for k, v in data.items() if k in models.Event.database_fields()
            }
            # Set top-level event fields.
            if len(edata) > 1:
                ret *= self.sql_update(rs, "event.events", edata)
                self.event_log(
                    rs,
                    const.EventLogCodes.event_changed,
                    data['id'],
                    change_note=change_note,
                )

            if 'orgas' in data:
                ret *= self.add_event_roles(rs, event_id, data['orgas'], 'orga')
            if 'fields' in data:
                ret *= self._set_event_fields(rs, event_id, data['fields'])
            # This also includes taking care of course tracks, since
            # they are linked to a single event part.
            if 'parts' in data:
                # Event begin can have an effect on fees.

                current_fees = None
                if current.is_balanced:
                    current_fees = self._update_registrations_amount_owed(rs, event_id)

                ret *= self._set_event_parts(rs, event_id, data['parts'])

                new_fees = self._update_registrations_amount_owed(rs, event_id)

                if current.is_balanced and (current_fees != new_fees):
                    raise EventIsBalancedError(
                        n_("Event is balanced. Amount owed may no longer change.")
                    )

        return ret

    @access("event_admin")
    def create_event(self, rs: RequestState, data: CdEDBObject) -> DefaultReturnCode:
        """Make a new event organized via DB."""
        data = affirm(models.Event, data, creation=True)
        if not data.get('parts'):
            raise ValueError(n_("At least one event part required."))
        with Atomizer(rs):
            edata = {
                k: v for k, v in data.items() if k in models.Event.database_fields()
            }
            new_id = self.sql_insert(rs, "event.events", edata)
            self.event_log(rs, const.EventLogCodes.event_created, new_id)
            if data.get('orgas'):
                self.add_event_roles(rs, new_id, data['orgas'], 'orga')
            if data.get('caretakers'):
                self.add_event_roles(rs, new_id, data['caretakers'], 'caretaker')
            if 'fields' in data:
                self._set_event_fields(rs, new_id, data['fields'])
            if 'parts' in data:
                self._set_event_parts(rs, new_id, data['parts'])
            lg_data = {"title": data['title']}
            self.create_lodgement_group(rs, new_id, lg_data)
            self.event_keeper_create(rs, new_id)
        return new_id

    @access("event")
    def set_event_free_texts(
        self,
        rs: RequestState,
        event_id: int,
        data: CdEDBObject,
        change_note: Optional[str] = None,
    ) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        data = affirm(
            cast(type[CdEDataclass], models._EventFreetextMixin), data
        )  # absstract model
        with Atomizer(rs):
            if not is_privileged(
                rs, EventPrivileges.free_texts_write, event_id=event_id
            ):
                raise PrivilegeError(n_("Not privileged."))
            if not data:
                return 1
            data['id'] = event_id
            ret = self.sql_update(rs, models.Event.database_table, data)
            self.event_log(
                rs, const.EventLogCodes.event_changed, event_id, change_note=change_note
            )
        return ret

    @access("event")
    def create_lodgement_group(
        self, rs: RequestState, event_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Make a new lodgement group."""
        event_id = affirm(vtypes.ID, event_id)
        data = affirm(models.LodgementGroup, data, creation=True)

        if not is_privileged(rs, EventPrivileges.lodgements_write, event_id):
            raise PrivilegeError(n_("Not privileged to modify lodgement groups."))
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            data["event_id"] = event_id
            new_id = self.sql_insert(rs, models.LodgementGroup.database_table, data)
            self.event_log(
                rs,
                const.EventLogCodes.lodgement_group_created,
                data['event_id'],
                change_note=data['title'],
            )
        return new_id

    @access("event")
    def add_part_group(
        self, rs: RequestState, event_id: int, part_group: CdEDBObject
    ) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)

        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))
        ret = 1

        with Atomizer(rs):
            event = self.get_event(rs, event_id)

            part_group = affirm(
                models.PartGroup, part_group, creation=True, event=event
            )
            part_group['event_id'] = event_id
            part_ids = part_group.pop("part_ids")
            new_id = self.sql_insert(rs, models.PartGroup.database_table, part_group)
            ret *= new_id
            self.event_log(
                rs,
                const.EventLogCodes.part_group_created,
                event_id,
                change_note=part_group['title'],
            )
            inserter = []
            for part_id in part_ids:
                inserter.append({'part_group_id': new_id, 'part_id': part_id})
                change_note = f"{event.parts[part_id].title} -> {part_group['title']}"
                self.event_log(
                    rs,
                    const.EventLogCodes.part_group_link_created,
                    event_id,
                    change_note=change_note,
                )
            if part_ids:
                ret *= self.sql_insert_many(rs, "event.part_group_parts", inserter)

        return ret

    @access("event")
    def change_part_group(
        self, rs: RequestState, part_group_id: int, part_group: CdEDBObject
    ) -> DefaultReturnCode:
        part_group_id = affirm(vtypes.ID, part_group_id)
        part_group["id"] = part_group_id

        ret = 1
        with Atomizer(rs):
            event_id = unwrap(
                self.sql_select_one(
                    rs, models.PartGroup.database_table, ("event_id",), part_group_id
                )
            )
            if event_id is None:
                raise ValueError
            if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            part_group = affirm(models.PartGroup, part_group, event=event)
            current = event.part_groups[part_group["id"]].as_dict()
            if any(part_group[k] != current[k] for k in part_group):
                ret *= self.sql_update(rs, models.PartGroup.database_table, part_group)
                self.event_log(
                    rs,
                    const.EventLogCodes.part_group_changed,
                    event_id,
                    change_note=part_group.get('title', current['title']),
                )

        return ret

    @access("event")
    def delete_part_group(
        self, rs: RequestState, part_group_id: int
    ) -> DefaultReturnCode:
        part_group_id = affirm(vtypes.ID, part_group_id)

        with Atomizer(rs):
            event_id = unwrap(
                self.sql_select_one(
                    rs, models.PartGroup.database_table, ("event_id",), part_group_id
                )
            )
            if event_id is None:
                raise ValueError
            if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
            ret = self._delete_part_group(
                rs, part_group_id=part_group_id, cascade=("part_group_parts",)
            )

        return ret

    @access("event")
    def add_track_group(
        self, rs: RequestState, event_id: int, track_group: CdEDBObject
    ) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)

        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))
        ret = 1

        with Atomizer(rs):
            event = self.get_event(rs, event_id)

            track_group = affirm(
                models.TrackGroup, track_group, creation=True, event=event
            )
            track_group['event_id'] = event_id
            track_ids = track_group.pop("track_ids")
            is_sync = track_group["constraint_type"].is_sync()
            if is_sync and not self.may_create_ccs_group(rs, track_ids):
                raise ValueError(
                    n_(
                        "Cannot create CCS group due to incompatible existing course choices."
                    )
                )
            new_id = self.sql_insert(rs, models.TrackGroup.database_table, track_group)
            ret *= new_id
            self.event_log(
                rs,
                const.EventLogCodes.track_group_created,
                event_id,
                change_note=track_group['title'],
            )
            inserter = []
            for track_id in track_ids:
                inserter.append({'track_group_id': new_id, 'track_id': track_id})
                change_note = (
                    f"{event.tracks[track_id].title} -> {track_group['title']}"
                )
                self.event_log(
                    rs,
                    const.EventLogCodes.track_group_link_created,
                    event_id,
                    change_note=change_note,
                )
            if track_ids:
                ret *= self.sql_insert_many(rs, "event.track_group_tracks", inserter)
            self._track_groups_sanity_check(rs, event_id)

        return ret

    @access("event")
    def change_track_group(
        self, rs: RequestState, track_group_id: int, track_group: CdEDBObject
    ) -> DefaultReturnCode:
        track_group_id = affirm(vtypes.ID, track_group_id)
        track_group["id"] = track_group_id

        ret = 1
        with Atomizer(rs):
            event_id = unwrap(
                self.sql_select_one(
                    rs, models.TrackGroup.database_table, ("event_id",), track_group_id
                )
            )
            if event_id is None:
                raise ValueError
            if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            track_group = affirm(models.TrackGroup, track_group, event=event)
            current = event.track_groups[track_group["id"]].as_dict()
            if any(track_group[k] != current[k] for k in track_group):
                ret *= self.sql_update(
                    rs, models.TrackGroup.database_table, track_group
                )
                self.event_log(
                    rs,
                    const.EventLogCodes.track_group_changed,
                    event_id,
                    change_note=track_group.get('title', current['title']),
                )
            self._track_groups_sanity_check(rs, event_id)

        return ret

    @access("event")
    def delete_track_group(
        self, rs: RequestState, track_group_id: int
    ) -> DefaultReturnCode:
        track_group_id = affirm(vtypes.ID, track_group_id)

        with Atomizer(rs):
            event_id = unwrap(
                self.sql_select_one(
                    rs, models.TrackGroup.database_table, ("event_id",), track_group_id
                )
            )
            if event_id is None:
                raise ValueError
            if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
            ret = self._delete_track_group(
                rs, track_group_id=track_group_id, cascade=("track_group_tracks",)
            )
            self._track_groups_sanity_check(rs, event_id)

        return ret

    def _event_fee_privilege_check(
        self,
        rs: RequestState,
        *,
        event_id: int | None = None,
        fee_id: int | None = None,
    ) -> models.Event:
        """Uninlined code from the event fee methods."""
        self.affirm_atomized_context(rs)

        event_id = affirm(vtypes.ID | None, event_id)
        fee_id = affirm(vtypes.ID | None, fee_id)

        if event_id is None:
            assert fee_id is not None
            event_id = unwrap(
                self.sql_select_one(
                    rs, models.EventFee.database_table, ["event_id"], fee_id
                )
            )
            if not event_id:
                raise ValueError(n_("Event fee does not exist."))

        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged to modify event fees."))

        event = self.get_event(rs, event_id)

        if event.is_balanced:
            raise EventIsBalancedError(
                n_("Event is balanced. May not change fee configuration.")
            )

        return event

    @access("event")
    def create_event_fee(
        self, rs: RequestState, event_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        with Atomizer(rs):
            event = self._event_fee_privilege_check(rs, event_id=event_id)

            quest = self.get_questionnaire(rs, event_id)
            data = affirm(
                models.EventFee,
                data,
                event=event,
                current=None,
                questionnaire=quest,
                creation=True,
            )

            data["event_id"] = event_id
            ret = self.sql_insert(rs, models.EventFee.database_table, data)
            self.event_log(
                rs,
                const.EventLogCodes.event_fee_created,
                event_id,
                change_note=data["title"],
            )

            self._update_registrations_amount_owed(rs, event_id)

        return ret

    @access("event")
    def change_event_fee(
        self, rs: RequestState, fee_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        fee_id = affirm(vtypes.ID, fee_id)

        with Atomizer(rs):
            event = self._event_fee_privilege_check(rs, fee_id=fee_id)
            current_fee = event.fees[fee_id]

            quest = self.get_questionnaire(rs, event.id)
            data = affirm(
                models.EventFee,
                data,
                event=event,
                current=current_fee,
                questionnaire=quest,
            )

            data["id"] = fee_id
            current_fee_data = current_fee.to_database()
            if any(data[k] != current_fee_data[k] for k in data):
                ret = self.sql_update(rs, "event.event_fees", data)
                self.event_log(
                    rs,
                    const.EventLogCodes.event_fee_modified,
                    event.id,
                    change_note=data.get("title", current_fee.title),
                )
            else:
                ret = -1

            self._update_registrations_amount_owed(rs, event.id)

        return ret

    @access("event")
    def delete_event_fee(self, rs: RequestState, fee_id: int) -> DefaultReturnCode:
        fee_id = affirm(vtypes.ID, fee_id)

        with Atomizer(rs):
            event = self._event_fee_privilege_check(rs, fee_id=fee_id)

            current_fee = event.fees[fee_id]
            persona_ids = []
            if current_fee.is_personalized():
                registration_ids = [
                    e["registration_id"]
                    for e in self.sql_select(
                        rs,
                        models.PersonalizedFee.database_table,
                        ["registration_id"],
                        [fee_id],
                        entity_key="fee_id",
                    )
                ]
                persona_ids = [
                    e["persona_id"]
                    for e in self.sql_select(
                        rs,
                        models.Registration.database_table,
                        ["persona_id"],
                        registration_ids,
                    )
                ]
                if len(persona_ids) != len(registration_ids):
                    raise RuntimeError(
                        "Mismatch between registration IDs and persona IDs."
                    )
            ret = self.sql_delete(rs, models.EventFee.database_table, [fee_id])
            for persona_id in xsorted(persona_ids):
                self.event_log(
                    rs,
                    const.EventLogCodes.personalized_fee_amount_deleted,
                    event.id,
                    persona_id,
                    change_note=current_fee.title,
                )
            self.event_log(
                rs,
                const.EventLogCodes.event_fee_deleted,
                event.id,
                change_note=current_fee.title,
            )

            self._update_registrations_amount_owed(rs, event.id)

        return ret

    @abc.abstractmethod
    def _update_registrations_amount_owed(
        self, rs: RequestState, event_id: int
    ) -> dict[int, "ComplexRegistrationFee"]: ...

    @access("event")
    def check_orga_addition_limit(self, rs: RequestState, event_id: int) -> bool:
        """Implement a rate limiting check for orgas adding persons.

        Since adding somebody as participant or orga to an event gives all
        orgas basically full access to their data, we rate limit this
        operation.

        :returns: True if limit has not been reached.
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(
            rs, EventPrivileges.registrations_write, event_id=event_id
        ):
            raise PrivilegeError(n_("Not privileged."))
        if self.is_admin(rs):
            # Admins are exempt
            return True
        query = """
            SELECT COUNT(*) AS num FROM event.log
            WHERE
                event_id = %(event_id)s AND code = %(code)s AND submitted_by != persona_id
                AND ctime >= now() - interval '24 hours'
        """
        params = {
            "event_id": event_id,
            "code": const.EventLogCodes.registration_created,
        }
        num = unwrap(self.query_one(rs, query, params))
        return num < self.conf["ORGA_ADD_LIMIT"]

    @access("event", "droid_quick_partial_export", "droid_orga")
    def get_questionnaire(
        self,
        rs: RequestState,
        event_id: int,
    ) -> models.QuestionnaireContainer:
        """Retrieve the questionnaire rows for a specific event."""
        event_id = affirm(vtypes.ID, event_id)
        event = self.get_event(rs, event_id)
        query = models.QuestionnaireRow.get_select_query([event_id])
        data = self.query_all(rs, *query)
        for row in data:
            row["event"] = event
        return models.QuestionnaireContainer.from_database(data)

    @access("event")
    def set_questionnaire(
        self,
        rs: RequestState,
        event_id: int,
        kind: const.QuestionnaireUsages,
        data: list[CdEDBObject],
    ) -> DefaultReturnCode:
        """Replace the current questionnaire of the given kind for the given event."""
        event_id = affirm(vtypes.ID, event_id)
        kind = affirm(const.QuestionnaireUsages, kind)
        event = self.get_event(rs, event_id)
        data = affirm(
            vtypes.Questionnaire,
            data,
            kind=kind,
            event=event,
            all_questionnaires=self.get_questionnaire(rs, event_id),
        )
        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_lock(rs, event_id=event_id)
        with Atomizer(rs):
            # Always delete everything then recreate.
            query = f"""
                DELETE FROM {models.QuestionnaireRow.database_table}
                WHERE event_id = %(event_id)s and kind = %(kind)s
            """
            params = {"event_id": event_id, "kind": kind}
            self.query_exec(rs, query, params)
            # Otherwise replace rows for all given kinds.
            ret = 1
            for pos, row in enumerate(data):
                new_row = copy.deepcopy(row)
                new_row['pos'] = pos
                new_row['event_id'] = event_id
                new_row['kind'] = kind
                ret *= self.sql_insert(
                    rs, models.QuestionnaireRow.database_table, new_row
                )
            self.event_log(rs, const.EventLogCodes.questionnaire_changed, event_id)
        return ret

    @access("event")
    def balance_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.balance, event_id=event_id):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            event = self.get_event(rs, event_id)
            if event.is_balanced:
                raise ValueError(n_("Event already balanced."))
            update = {
                'id': event_id,
                'is_balanced': True,
            }
            self.event_keeper_commit(
                rs, event_id, "Snapshot vor finanziellem Abschluss."
            )
            ret = self.sql_update(rs, models.Event.database_table, update)
            self.event_log(rs, const.EventLogCodes.event_balanced, event_id)
        return ret

    @access("event")
    def unbalance_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.balance, event_id=event_id):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            event = self.get_event(rs, event_id)
            if not event.is_balanced:
                raise ValueError(n_("Event isn't balanced."))
            update = {
                'id': event_id,
                'is_balanced': False,
            }
            self.event_keeper_commit(
                rs, event_id, "Snapshot vor Aufhebung von finanziellem Abschluss."
            )
            ret = self.sql_update(rs, models.Event.database_table, update)
            self.event_log(rs, const.EventLogCodes.event_unbalanced, event_id)
        return ret

    @access("event")
    def lock_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        """Lock an event."""
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.lock, event_id=event_id):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            update = {
                'id': event_id,
                'is_locked': True,
            }
            self.event_keeper_commit(rs, event_id, "Snapshot vor Lock.")
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_locked, event_id)
        return ret

    @access("event")
    def unlock_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        """Unlock an event."""
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.lock, event_id=event_id):
            raise PrivilegeError
        with Atomizer(rs):
            if not self.is_locked(rs, event_id=event_id):
                raise RuntimeError(n_("Event isn't locked."))
            update = {
                'id': event_id,
                'is_locked': False,
            }
            self.event_keeper_commit(rs, event_id, "Snapshot vor Unlock.")
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_unlocked, event_id)
        return ret

    @access("event")
    def approve_registration(
        self, rs: RequestState, event_id: int
    ) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(
            rs, EventPrivileges.approve_registration, event_id=event_id
        ):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            update = {
                'id': event_id,
                'is_registration_approved': True,
            }
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.registration_approved, event_id)
        return ret

    @access("event")
    def unapprove_registration(
        self, rs: RequestState, event_id: int
    ) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(
            rs, EventPrivileges.approve_registration, event_id=event_id
        ):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            update = {
                'id': event_id,
                'is_registration_approved': False,
            }
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.registration_unapproved, event_id)
        return ret

    @internal
    @access("event")
    def set_event_archived(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.conclude, event_id=event_id):
            raise PrivilegeError
        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            event = self.get_event(rs, event_id)
            if event.is_archived:
                raise ValueError(n_("Event isn't balanced."))
            update = {
                'id': event_id,
                'is_archived': True,
            }
            self.event_keeper_commit(rs, event_id, "Snapshot vor Archivierung.")
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_archived, event_id)
        return ret

    @access("event")
    def export_event(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Export an event for offline usage or after offline usage.

        This provides a more general export functionality which could
        also be used without locking.

        :returns: dict holding all data of the exported event
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.all_read, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Iterable[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        with Atomizer(rs):
            ret: CdEDBObject = {
                'EVENT_SCHEMA_VERSION': EVENT_SCHEMA_VERSION,
                'kind': "full",  # could also be "partial"
                'id': event_id,
                'event.events': list_to_dict(
                    self.sql_select(
                        rs, "event.events", models.Event.database_fields(), (event_id,)
                    )
                ),
                'timestamp': now(),
            }
            # Table name; column to scan; fields to extract
            tables: list[tuple[str, str, tuple[str, ...]]] = [
                models.EventPart.full_export_spec(),
                models.PartGroup.full_export_spec(),
                models.CourseTrack.full_export_spec(),
                models.TrackGroup.full_export_spec(),
                models.Course.full_export_spec("event_id"),
                models.EventField.full_export_spec(),
                models.EventFee.full_export_spec(),
                models.LodgementGroup.full_export_spec(),
                models.Lodgement.full_export_spec("event_id"),
                OrgaToken.full_export_spec("event_id"),
                ('event.part_group_parts', "part_id", ("part_group_id", "part_id")),
                (
                    'event.track_group_tracks',
                    "track_id",
                    ("track_group_id", "track_id"),
                ),
                models.CourseSegment.full_export_spec("track_id"),
                ('event.orgas', "event_id", EVENT_ROLE_FIELDS),
                ('event.caretakers', "event_id", EVENT_ROLE_FIELDS),
                ('event.checkin_helpers', "event_id", EVENT_ROLE_FIELDS),
                ('event.registrations', "event_id", REGISTRATION_FIELDS),
                models.CheckinPeriod.full_export_spec(),
                ('event.registration_parts', "part_id", REGISTRATION_PART_FIELDS),
                ('event.registration_tracks', "track_id", REGISTRATION_TRACK_FIELDS),
                (
                    'event.course_choices',
                    "track_id",
                    ('id', 'registration_id', 'track_id', 'course_id', 'rank'),
                ),
                models.PersonalizedFee.full_export_spec(),
                ('event.questionnaire_rows', "event_id", QUESTIONNAIRE_ROW_FIELDS),
                models.StoredEventQuery.full_export_spec(),
                (
                    'event.log',
                    "event_id",
                    (
                        'id',
                        'ctime',
                        'code',
                        'submitted_by',
                        'event_id',
                        'persona_id',
                        'change_note',
                    ),
                ),
            ]
            personas = set()
            for table, id_name, columns in tables:
                if id_name == "event_id":
                    id_range = {event_id}
                elif id_name == "part_id":
                    id_range = set(ret['event.event_parts'])
                elif id_name == "track_id":
                    id_range = set(ret['event.course_tracks'])
                elif id_name == "registration_id":
                    id_range = set(ret['event.registrations'])
                else:
                    raise RuntimeError(n_("Impossible."))
                if 'id' not in columns:
                    columns += ('id',)
                ret[table] = list_to_dict(
                    self.sql_select(rs, table, columns, id_range, entity_key=id_name)
                )
                # Note the personas present to export them further on
                for e in ret[table].values():
                    if e.get('persona_id'):
                        personas.add(e['persona_id'])
                    if e.get('submitted_by'):  # for log entries
                        personas.add(e['submitted_by'])
            for e in ret[models.EventField.database_table].values():
                if entries := e["entries"]:
                    kind = const.FieldDatatypes(e["kind"])
                    entries = cast_field_entries(entries, kind)
                    entries = normalize_field_entries(entries, kind, coalesce="") or {}
                    e["entries"] = list(map(list, entries.items()))
            ret['core.personas'] = list_to_dict(
                self.sql_select(rs, "core.personas", PERSONA_EVENT_FIELDS, personas)
            )
        return ret

    @access("event", "droid_quick_partial_export", "droid_orga")
    def partial_export_event(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Export an event for third-party applications.

        This provides a consumer-friendly package of event data which can
        later on be reintegrated with the partial import facility.
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.basic_read, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Collection[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        # First gather all the data and give up the database lock afterwards.
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            courses = list_to_dict(
                self.sql_select(
                    rs,
                    'event.courses',
                    models.Course.database_fields(),
                    (event_id,),
                    entity_key='event_id',
                )
            )
            course_segments = self.sql_select(
                rs,
                'event.course_segments',
                ('course_id', 'track_id', 'is_active'),
                courses.keys(),
                entity_key='course_id',
            )
            lodgement_groups = list_to_dict(
                self.sql_select(
                    rs,
                    models.LodgementGroup.database_table,
                    models.LodgementGroup.database_fields(),
                    (event_id,),
                    entity_key='event_id',
                )
            )
            lodgements = list_to_dict(
                self.sql_select(
                    rs,
                    models.Lodgement.database_table,
                    models.Lodgement.database_fields(),
                    (event_id,),
                    entity_key='event_id',
                )
            )
            registrations = self._get_registration_data(rs, event_id)
            registration_parts = self.sql_select(
                rs,
                'event.registration_parts',
                REGISTRATION_PART_FIELDS,
                registrations.keys(),
                entity_key='registration_id',
            )
            registration_tracks = self.sql_select(
                rs,
                'event.registration_tracks',
                REGISTRATION_TRACK_FIELDS,
                registrations.keys(),
                entity_key='registration_id',
            )
            choices = self.sql_select(
                rs,
                "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"),
                registrations.keys(),
                entity_key="registration_id",
            )
            personalized_fees = models.PersonalizedFee.many_from_database(
                self.query_all(
                    rs,
                    *models.PersonalizedFee.get_select_query(registrations.keys()),
                ),
            )
            checkin_periods = self.sql_select(
                rs,
                models.CheckinPeriod.database_table,
                models.CheckinPeriod.database_fields(),
                registrations.keys(),
                entity_key=models.CheckinPeriod.entity_key,
            )
            tokens = list_to_dict(
                self.sql_select(
                    rs,
                    OrgaToken.database_table,
                    OrgaToken.database_fields(),
                    (event_id,),
                    entity_key="event_id",
                )
            )
            questionnaire = self.get_questionnaire(rs, event_id).as_dict()
            persona_ids = tuple(reg['persona_id'] for reg in registrations.values())
            personas = self.core.get_event_users(rs, persona_ids, event_id)

        # Now process all the data.
        # basics
        ret: CdEDBObject = {
            'EVENT_SCHEMA_VERSION': EVENT_SCHEMA_VERSION,
            'kind': "partial",  # could also be "full"
            'id': event_id,
            'timestamp': now(),
        }
        # courses
        lookup: dict[int, dict[int, bool]] = collections.defaultdict(dict)
        for e in course_segments:
            lookup[e['course_id']][e['track_id']] = e['is_active']
        for course_id, course in courses.items():
            del course['id']
            del course['event_id']
            course['segments'] = lookup[course_id]
            course['fields'] = cast_fields(course['fields'], event.fields)
        ret['courses'] = courses
        # lodgement groups
        for lodgement_group in lodgement_groups.values():
            del lodgement_group['id']
            del lodgement_group['event_id']
        ret['lodgement_groups'] = lodgement_groups
        # lodgements
        for lodgement in lodgements.values():
            del lodgement['id']
            del lodgement['event_id']
            lodgement['fields'] = cast_fields(lodgement['fields'], event.fields)
        ret['lodgements'] = lodgements
        # registrations
        part_lookup: dict[int, CdEDBObjectMap]
        part_lookup = collections.defaultdict(dict)
        for e in registration_parts:
            part_lookup[e['registration_id']][e['part_id']] = e
        track_lookup: dict[int, CdEDBObjectMap]
        track_lookup = collections.defaultdict(dict)
        for e in registration_tracks:
            track_lookup[e['registration_id']][e['track_id']] = e
        personalized_fee_lookup: dict[int, dict[int, decimal.Decimal]]
        personalized_fee_lookup = collections.defaultdict(dict)
        for personalized_fee in personalized_fees.values():
            if personalized_fee.amount is not None:
                personalized_fee_lookup[personalized_fee.registration_id][
                    personalized_fee.fee_id
                ] = personalized_fee.amount
        checkin_period_lookup: dict[int, list[CdEDBObject]]
        checkin_period_lookup = collections.defaultdict(list)
        for e in checkin_periods:
            checkin_period_lookup[e['registration_id']].append(e)
        for registration_id, registration in registrations.items():
            del registration['id']
            del registration['event_id']
            # Delete this later.
            # del registration['persona_id']
            del registration['real_persona_id']
            parts = part_lookup[registration_id]
            for part in parts.values():
                part['status'] = const.RegistrationPartStati(part['status'])
                del part['registration_id']
                del part['part_id']
            registration['parts'] = parts
            tracks = track_lookup[registration_id]
            for track_id, track in tracks.items():
                tmp = {
                    e['course_id']: e['rank']
                    for e in choices
                    if (
                        e['registration_id'] == track['registration_id']
                        and e['track_id'] == track_id
                    )
                }
                track['choices'] = xsorted(tmp.keys(), key=tmp.get)
                del track['registration_id']
                del track['track_id']
            registration['tracks'] = tracks
            registration['fields'] = cast_fields(registration['fields'], event.fields)
            registration['personalized_fees'] = {}
            for fee_id, fee_amount in personalized_fee_lookup[registration_id].items():
                registration['personalized_fees'][fee_id] = fee_amount
            registration["amount_owed_by_kind"] = {
                kind.name: amount
                for kind, amount in registration["amount_owed_by_kind"].items()
            }
            registration["amount_owed_by_category"] = {
                category.name: amount
                for category, amount in registration["amount_owed_by_category"].items()
            }
            registration["amount_owed_by_budget"] = {
                budget.name: amount
                for budget, amount in registration["amount_owed_by_budget"].items()
            }
            periods = xsorted(checkin_period_lookup[registration_id])
            for period in periods:
                del period['registration_id']
                del period['id']
            registration['checkin_periods'] = periods
        ret['registrations'] = registrations

        ret['event'] = event.as_dict()

        for token_id, orga_token in tokens.items():
            del orga_token['id']
            del orga_token['event_id']
        ret['event']['orga_tokens'] = tokens

        # now we add additional information that is only auxiliary and
        # does not correspond to changeable entries
        #
        # event
        del ret['event']['id']
        # Delete this later.
        # del ret['event']['orgas']
        del ret['event']['tracks']
        del ret['event']['custom_query_filters']
        ret['event']['fees'] = {
            fee['title']: fee for fee in ret['event']['fees'].values()
        }
        for fee in ret['event']['fees'].values():
            del fee['id']
            del fee['event_id']
            del fee['title']
            del fee['amount_min']
            del fee['amount_max']
        for part in ret['event']['parts'].values():
            del part['event_id']
            del part['part_group_ids']
            for f in ('waitlist_field_id', 'camping_mat_field_id'):
                new_key = f.removesuffix("_id")
                if part[f]:
                    part[new_key] = ret['event']['fields'][part[f]]['field_name']
                else:
                    part[new_key] = None
                del part[f]
            for track in part['tracks'].values():
                del track['track_group_ids']
                for f in ('course_room_field_id',):
                    new_key = f.removesuffix("_id")
                    if track[f]:
                        track[new_key] = ret['event']['fields'][track[f]]['field_name']
                    else:
                        track[new_key] = None
                    del track[f]
        for pg in ret['event']['part_groups'].values():
            del pg['id']
            del pg['event_id']
            pg['constraint_type'] = const.EventPartGroupType(pg['constraint_type'])
            pg['part_ids'] = xsorted(pg['parts'].keys())
            del pg['parts']
        for tg in ret['event']['track_groups'].values():
            del tg['id']
            del tg['event_id']
            tg['constraint_type'] = const.CourseTrackGroupType(tg['constraint_type'])
            tg['track_ids'] = xsorted(tg['tracks'].keys())
            del tg['tracks']
        for f in ('lodge_field_id', 'reimbursement_iban_field_id'):
            new_key = f.removesuffix("_id")
            if ret['event'][f]:
                field = ret['event']['fields'][ret['event'][f]]
                ret['event'][new_key] = field['field_name']
            else:
                ret['event'][new_key] = None
            del ret['event'][f]
        # Fields and questionnaire
        new_fields = {
            field['field_name']: field for field in ret['event']['fields'].values()
        }
        new_questionnaire = {str(usage): rows for usage, rows in questionnaire.items()}
        for usage, rows in new_questionnaire.items():
            for q in rows:
                if q['field_id']:
                    q['field_name'] = event.fields[q['field_id']].field_name
                else:
                    q['field_name'] = None
                del q['pos']
                del q['kind']
                del q['field_id']
        for field in new_fields.values():
            del field['field_name']
            del field['event_id']
            del field['id']
            field["entries"] = normalize_field_entries(
                field["entries"], field["kind"], coalesce=""
            )
        # personas
        for reg_id, registration in ret['registrations'].items():
            persona = personas[registration['persona_id']]
            del registration['persona_id']
            persona['is_orga'] = persona['id'] in ret['event']['orgas']
            for attr in EventPersona.get_status_bits() - {'is_member'}:
                del persona[attr]
            registration['persona'] = persona
        del ret['event']['orgas']
        ret['event']['fields'] = new_fields
        ret['event']['questionnaire'] = new_questionnaire
        if ret['event']['iban']:
            ret['event']['iban'] = ret['event']['iban'].get_iban()
        return ret

    @access("event")
    def questionnaire_import(
        self,
        rs: RequestState,
        event_id: int,
        fields: CdEDBObjectMap,
        questionnaires: dict[const.QuestionnaireUsages, vtypes.Questionnaire],
    ) -> DefaultReturnCode:
        """Special import for custom datafields and questionnaire rows."""
        event_id = affirm(vtypes.ID, event_id)
        # validation of input is delegated to the setters, because it is rather
        # involved and dependent on each other.
        if not is_privileged(rs, EventPrivileges.basic_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_lock(rs, event_id=event_id)

        with Atomizer(rs):
            ret = self.set_event(rs, event_id, {'fields': fields})
            for kind, questionnaire in questionnaires.items():
                ret *= self.set_questionnaire(rs, event_id, kind, questionnaire)
        return ret

    @access("event_admin")
    def event_keeper_create(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Create a new git repository for keeping track of event changes."""
        event_id = affirm(vtypes.ID, event_id)
        self._event_keeper.init(event_id)
        export = self.event_keeper_commit(
            rs, event_id, "Initialer Commit", is_initial=True
        )
        # since is_initial is True, a partial export will always be returned
        assert export is not None
        return export

    @access("event_admin")
    def event_keeper_drop(self, rs: RequestState, event_id: int) -> None:
        """Published version of EntityKeeper.delete.

        :param rs: Required for access check."""
        return self._event_keeper.delete(event_id)

    @access("event")
    def event_keeper_commit(
        self,
        rs: RequestState,
        event_id: int,
        commit_msg: str,
        *,
        after_change: bool = False,
        is_initial: bool = False,
    ) -> Optional[CdEDBObject]:
        """Commit the current state of the event to its git repository.

        In general, there are two scenarios where we want to make a new commit:
        * periodically by a cron job
        * before and after relevant changes

        We divide the three types of commits in those which may be dropped if they are
        empty (periodic commits and commits before a relevant change) and those which
        are taken even if they didn't change anything (after relevant changes).

        :param after_change: Only true for commits taken after a relevant change.
        :param is_initial: Only true for the first commit to the event keeper.
        :returns: The partial export or None. None may only be returned if the commit
            may be dropped.
        """
        event_id = affirm(int, event_id)
        commit_msg = affirm(str, commit_msg)

        may_drop = False if is_initial else not after_change
        with Atomizer(rs):
            logs = self._process_event_keeper_logs(rs, event_id)
            if logs is None and may_drop:
                return None
            export = self.partial_export_event(rs, event_id)
        del export['timestamp']
        author_name = author_email = ""
        if rs.user.persona_id:
            persona = {
                "given_names": rs.user.given_names,
                "family_name": rs.user.family_name,
            }
            author_name = make_persona_name(persona)
            author_email = rs.user.username
        self._event_keeper.commit(
            event_id,
            json_serialize(export, sort_keys=True),
            commit_msg,
            author_name,
            author_email,
            may_drop=may_drop,
            logs=logs,
        )
        return export

    @internal
    def _process_event_keeper_logs(
        self, rs: RequestState, event_id: int
    ) -> Optional[tuple[CdEDBObject, ...]]:
        """Format the log entries since the last commit to make them more readable."""
        with Atomizer(rs):
            timestamp = self._event_keeper.latest_logtime(event_id)
            if timestamp is None:
                return None
            # since retrieve_log compares timestamps inclusive, we need to increase the
            # timestamp to not include log entries from the latest commit.
            timestamp += datetime.timedelta(seconds=1)
            _, entries = self.retrieve_log(
                rs, EventLogFilter(event_id=event_id, ctime_from=timestamp)
            )
            # short circuit if there are no new log entries
            if not entries:
                return None

            # retrieve additional information to pimp up the log entries
            persona_ids = {
                entry['submitted_by'] for entry in entries if entry['submitted_by']
            } | {entry['persona_id'] for entry in entries if entry['persona_id']}
            personas = self.core.get_personas(rs, persona_ids)

        # the name of the fields which will show up in the log are defined
        # during instantiation of the entity keeper.
        for entry in entries:
            entry["Zeitstempel"] = datetime_filter(
                entry["ctime"], formatstr="%Y-%m-%d %H:%M:%S (%Z)"
            )
            # pad the log code column to a fixed width. 31 chars is the current length
            # of our longest log code.
            entry["Code"] = str(const.EventLogCodes(entry["code"]).name).ljust(31)
            if entry["submitted_by"]:
                submitter = personas[entry["submitted_by"]]
                entry["Verantwortlich"] = make_persona_name(submitter)
            if entry["persona_id"]:
                affected = personas[entry["persona_id"]]
                entry["Betroffen"] = make_persona_name(affected)
            entry["Erläuterung"] = entry["change_note"]
        return entries
