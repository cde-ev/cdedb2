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
from typing import Any, Collection, Dict, Iterable, List, Optional, Protocol, Set, Tuple

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import (
    Silencer, access, affirm_dataclass, affirm_set_validation as affirm_set,
    affirm_validation as affirm, affirm_validation_optional as affirm_optional,
    cast_fields, encrypt_password, internal, singularize,
)
from cdedb.backend.entity_keeper import EntityKeeper
from cdedb.backend.event.lowlevel import EventLowLevelBackend
from cdedb.common import (
    EVENT_SCHEMA_VERSION, CdEDBLog, CdEDBObject, CdEDBObjectMap, CdEDBOptionalMap,
    DefaultReturnCode, DeletionBlockers, RequestState, glue, json_serialize,
    make_persona_name, now, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import (
    COURSE_FIELDS, COURSE_SEGMENT_FIELDS, COURSE_TRACK_FIELDS, EVENT_FEE_FIELDS,
    EVENT_FIELDS, EVENT_PART_FIELDS, FIELD_DEFINITION_FIELDS, LODGEMENT_FIELDS,
    LODGEMENT_GROUP_FIELDS, PART_GROUP_FIELDS, PERSONA_EVENT_FIELDS,
    PERSONA_STATUS_FIELDS, QUESTIONNAIRE_ROW_FIELDS, REGISTRATION_FIELDS,
    REGISTRATION_PART_FIELDS, REGISTRATION_TRACK_FIELDS, STORED_EVENT_QUERY_FIELDS,
    TRACK_GROUP_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.common.sorting import mixed_existence_sorter, xsorted
from cdedb.database.connection import Atomizer
from cdedb.filter import datetime_filter
from cdedb.models.droid import OrgaToken
from cdedb.models.event import CustomQueryFilter

# type alias for questionnaire specification.
CdEDBQuestionnaire = Dict[const.QuestionnaireUsages, List[CdEDBObject]]


class EventBaseBackend(EventLowLevelBackend):
    def __init__(self) -> None:
        super().__init__()
        # define which keys of log entries will show up in commit messages
        # they are translated to german, since commit messages are always in german
        log_keys = ["Zeitstempel", "Code", "Verantwortlich", "Betroffen", "Erläuterung"]
        self._event_keeper = EntityKeeper(
            self.conf, 'event_keeper', log_keys=log_keys, log_timestamp_key="ctime")

    @access("event")
    def is_offline_locked(self, rs: RequestState, *, event_id: int = None,
                          course_id: int = None) -> bool:
        """Helper to determine if an event or course is locked for offline
        usage.

        Exactly one of the inputs has to be provided.
        """
        if event_id is not None and course_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        elif event_id is not None:
            anid = affirm(vtypes.ID, event_id)
            query = "SELECT offline_lock FROM event.events WHERE id = %s"
        elif course_id is not None:
            anid = affirm(vtypes.ID, course_id)
            query = glue(
                "SELECT offline_lock FROM event.events AS e",
                "LEFT OUTER JOIN event.courses AS c ON c.event_id = e.id",
                "WHERE c.id = %s")
        else:  # event_id is None and course_id is None:
            raise ValueError(n_("No input specified."))

        data = self.query_one(rs, query, (anid,))
        if data is None:
            raise ValueError(n_("Event does not exist"))
        return data['offline_lock']

    def assert_offline_lock(self, rs: RequestState, *, event_id: int = None,
                            course_id: int = None) -> None:
        """Helper to check locking state of an event or course.

        This raises an exception in case of the wrong locking state. Exactly
        one of the inputs has to be provided.
        """
        # the following does the argument checking
        is_locked = self.is_offline_locked(rs, event_id=event_id,
                                           course_id=course_id)
        if is_locked != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            raise RuntimeError(n_("Event offline lock error."))

    @access("persona")
    def orga_infos(self, rs: RequestState, persona_ids: Collection[int]
                   ) -> Dict[int, Set[int]]:
        """List events organized by specific personas."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        data = self.sql_select(rs, "event.orgas", ("persona_id", "event_id"),
                               persona_ids, entity_key="persona_id")
        ret = {}
        for anid in persona_ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    class _OrgaInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> Set[int]: ...
    orga_info: _OrgaInfoProtocol = singularize(orga_infos, "persona_ids", "persona_id")

    @access("event", "auditor")
    def retrieve_log(self, rs: RequestState, log_filter: EventLogFilter) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(EventLogFilter, log_filter)
        event_ids = log_filter.event_ids()

        if self.is_admin(rs) or "auditor" in rs.user.roles:
            pass
        elif not event_ids:
            raise PrivilegeError(n_("Must be admin to access global log."))
        elif all(self.is_orga(rs, event_id=event_id) for event_id in event_ids):
            pass
        else:
            raise PrivilegeError(n_("Not privileged."))

        return self.generic_retrieve_log(rs, log_filter)

    @access("anonymous")
    def list_events(self, rs: RequestState, visible: bool = None,
                       current: bool = None,
                       archived: bool = None) -> Dict[int, str]:
        """List all events organized via DB.

        :returns: Mapping of event ids to titles.
        """
        subquery = glue(
            "SELECT e.id, e.registration_start, e.title, e.is_visible,",
            "e.is_archived, e.is_cancelled, MAX(p.part_end) AS event_end",
            "FROM event.events AS e JOIN event.event_parts AS p",
            "ON p.event_id = e.id",
            "GROUP BY e.id")
        query = "SELECT e.* from ({}) as e".format(subquery)
        constraints = []
        params = []
        if visible is not None:
            constraints.append("is_visible = %s")
            params.append(visible)
        if current is not None:
            if current:
                constraints.append("e.event_end > now()")
                constraints.append("e.is_cancelled = False")
            else:
                constraints.append(
                    "(e.event_end <= now() OR e.is_cancelled = True)")
        if archived is not None:
            constraints.append("is_archived = %s")
            params.append(archived)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def get_events(self, rs: RequestState, event_ids: Collection[int]
                   ) -> CdEDBObjectMap:
        """Retrieve data for some events organized via DB.

        This queries quite a lot of additional tables since there is quite
        some data attached to such an event. Namely we have additional data on:

        * parts,
        * part_groups,
        * orgas,
        * fields.

        The tracks are inside the parts entry. This allows to create tracks
        during event creation.

        Furthermore we have the following derived keys:

        * tracks,
        * begin,
        * end,
        * is_open.
        """
        event_ids = affirm_set(vtypes.ID, event_ids)
        with Atomizer(rs):
            event_data = self.sql_select(rs, "event.events", EVENT_FIELDS, event_ids)
            ret = {e['id']: e for e in event_data}
            for anid in event_ids:
                ret[anid]['orgas'] = set()
                ret[anid]['parts'] = {}
                ret[anid]['tracks'] = {}
                ret[anid]['part_groups'] = {}
                ret[anid]['track_groups'] = {}
                ret[anid]['fees'] = {}
            part_data = self.sql_select(
                rs, "event.event_parts", EVENT_PART_FIELDS,
                event_ids, entity_key="event_id")
            all_parts = {e['id']: e['event_id'] for e in part_data}
            part_group_data = self.sql_select(
                rs, "event.part_groups", PART_GROUP_FIELDS,
                event_ids, entity_key="event_id")
            part_group_part_data = self.sql_select(
                rs, "event.part_group_parts", ("part_group_id", "part_id"),
                all_parts.keys(), entity_key="part_id")
            track_data = self.sql_select(
                rs, "event.course_tracks", COURSE_TRACK_FIELDS,
                all_parts.keys(), entity_key="part_id")
            all_tracks = {e['id']: all_parts[e['part_id']] for e in track_data}
            track_group_data = self.sql_select(
                rs, "event.track_groups", TRACK_GROUP_FIELDS,
                event_ids, entity_key="event_id")
            track_group_track_data = self.sql_select(
                rs, "event.track_group_tracks", ("track_group_id", "track_id"),
                all_tracks.keys(), entity_key="track_id")
            fee_data = self.sql_select(
                rs, "event.event_fees", EVENT_FEE_FIELDS, event_ids,
                entity_key="event_id")
            orga_data = self.sql_select(
                rs, "event.orgas", ("persona_id", "event_id"), event_ids,
                entity_key="event_id")
            event_fields_data = self._get_events_fields(rs, event_ids)
            custom_filters_data = self.sql_select(
                rs, CustomQueryFilter.database_table,
                CustomQueryFilter.database_fields(),
                entities=event_ids, entity_key='event_id')
            for d in orga_data:
                ret[d['event_id']]['orgas'].add(d['persona_id'])
            for d in part_data:
                d['tracks'] = {}
                d['part_groups'] = {}
                ret[d['event_id']]['parts'][d['id']] = d
            for d in part_group_data:
                d['part_ids'] = set()
                d['constraint_type'] = const.EventPartGroupType(d['constraint_type'])
                ret[d['event_id']]['part_groups'][d['id']] = d
            for d in part_group_part_data:
                event_id = all_parts[d['part_id']]
                part_group = ret[event_id]['part_groups'][d['part_group_id']]
                part_group['part_ids'].add(d['part_id'])
                part = ret[event_id]['parts'][d['part_id']]
                part['part_groups'][d['part_group_id']] = part_group
            for d in track_data:
                d['track_groups'] = {}
                event_id = all_tracks[d['id']]
                ret[event_id]['tracks'][d['id']] = d
                ret[event_id]['parts'][d['part_id']]['tracks'][d['id']] = d
            for d in track_group_data:
                d['track_ids'] = set()
                d['constraint_type'] = const.CourseTrackGroupType(d['constraint_type'])
                ret[d['event_id']]['track_groups'][d['id']] = d
            for d in track_group_track_data:
                event_id = all_tracks[d['track_id']]
                track_group = ret[event_id]['track_groups'][d['track_group_id']]
                track_group['track_ids'].add(d['track_id'])
                track = ret[event_id]['tracks'][d['track_id']]
                track['track_groups'][d['track_group_id']] = track_group
            for d in fee_data:
                ret[d['event_id']]['fees'][d['id']] = d
            for event_id, fields in event_fields_data.items():
                ret[event_id]['fields'] = fields
            for anid in event_ids:
                ret[anid]['custom_query_filters'] = {}
            for d in custom_filters_data:
                ret[d['event_id']]['custom_query_filters'][
                    d['id']] = CustomQueryFilter.from_database(d)
        for anid in event_ids:
            reference_time = now()
            ret[anid]['begin'] = min((p['part_begin']
                                      for p in ret[anid]['parts'].values()))
            ret[anid]['end'] = max((p['part_end']
                                    for p in ret[anid]['parts'].values()))
            ret[anid]['is_open'] = (
                    ret[anid]['registration_start']
                    and ret[anid]['registration_start'] <= reference_time
                    and (ret[anid]['registration_hard_limit'] is None
                         or ret[anid]['registration_hard_limit'] >= reference_time))
        return ret

    class _GetEventProtocol(Protocol):
        def __call__(self, rs: RequestState, event_id: int) -> CdEDBObject: ...
    get_event: _GetEventProtocol = singularize(get_events, "event_ids", "event_id")

    @access("event")
    def change_minor_form(self, rs: RequestState, event_id: int,
                          minor_form: Optional[bytes]) -> DefaultReturnCode:
        """Change or remove an event's minor form.

        Return 1 on successful change, -1 on successful deletion, 0 otherwise."""
        event_id = affirm(vtypes.ID, event_id)
        minor_form = affirm_optional(
            vtypes.PDFFile, minor_form, file_storage=False)
        if not (self.is_orga(rs, event_id=event_id) or self.is_admin(rs)):
            raise PrivilegeError(n_("Must be orga or admin to change the"
                                    " minor form."))
        path = self.minor_form_dir / str(event_id)
        if minor_form is None:
            if path.exists():
                path.unlink()
                # Since this is not acting on our database, do not demand an atomized
                # context.
                self.event_log(rs, const.EventLogCodes.minor_form_removed, event_id,
                               atomized=False)
                return -1
            else:
                return 0
        else:
            with open(path, "wb") as f:
                f.write(minor_form)
            # Since this is not acting on our database, do not demand an atomized
            # context.
            self.event_log(rs, const.EventLogCodes.minor_form_updated, event_id,
                           atomized=False)
            return 1

    @access("event")
    def get_minor_form(self, rs: RequestState,
                       event_id: int) -> Optional[bytes]:
        """Retrieve the minor form for an event.

        Returns None if no minor form exists for the given event."""
        event_id = affirm(vtypes.ID, event_id)
        # TODO accesscheck?
        path = self.minor_form_dir / str(event_id)
        ret = None
        if path.exists():
            with open(path, "rb") as f:
                ret = f.read()
        return ret

    @internal
    @access("event")
    def set_event_archived(self, rs: RequestState, data: CdEDBObject) -> None:
        """Wrapper around ``set_event()`` for archiving an event.

        This exists to emit the correct log message. It delegates
        everything else (like validation) to the wrapped method.
        """
        with Atomizer(rs):
            with Silencer(rs):
                self.set_event(rs, data)
            self.event_log(rs, const.EventLogCodes.event_archived,
                           data['id'])

    @access("event_admin")
    def add_event_orgas(self, rs: RequestState, event_id: int,
                        persona_ids: Collection[int]) -> DefaultReturnCode:
        """Add orgas to an event.

        This is basically un-inlined code from `set_event`, but may also be
        called separately.

        Note that this is only available to admins in contrast to `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        ret = 1
        with Atomizer(rs):
            if not self.core.verify_ids(rs, persona_ids, is_archived=False):
                raise ValueError(n_(
                    "Some of these orgas do not exist or are archived."))
            if not self.core.verify_personas(rs, persona_ids, {"event"}):
                raise ValueError(n_("Some of these orgas are not event users."))
            self.assert_offline_lock(rs, event_id=event_id)

            for anid in xsorted(persona_ids):
                new_orga = {
                    'persona_id': anid,
                    'event_id': event_id,
                }
                # on conflict do nothing
                r = self.sql_insert(rs, "event.orgas", new_orga, drop_on_conflict=True)
                if r:
                    self.event_log(rs, const.EventLogCodes.orga_added, event_id,
                                   persona_id=anid)
                ret *= r
        return ret

    @access("event_admin")
    def remove_event_orga(self, rs: RequestState, event_id: int,
                          persona_id: int) -> DefaultReturnCode:
        """Remove a single orga of an event.

        Note that this is only available to admins in contrast to `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_id = affirm(vtypes.ID, persona_id)
        self.assert_offline_lock(rs, event_id=event_id)

        query = ("DELETE FROM event.orgas"
                 " WHERE persona_id = %s AND event_id = %s")
        with Atomizer(rs):
            ret = self.query_exec(rs, query, (persona_id, event_id))
            if ret:
                self.event_log(rs, const.EventLogCodes.orga_removed,
                               event_id, persona_id=persona_id)
        return ret

    @access("event")
    def list_orga_tokens(self, rs: RequestState, event_id: int) -> dict[int, str]:
        """List all orga tokens belonging to one event.

        :returns: Mapping of token ids to titles.
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id):
            raise PrivilegeError
        data = self.sql_select(rs, OrgaToken.database_table, ("id", "title",),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

    @access("event")
    def get_orga_tokens(self, rs: RequestState, orga_token_ids: Collection[int]
                        ) -> dict[int, OrgaToken]:
        """Retrieve information about orga tokens."""
        orga_token_ids = affirm_set(vtypes.ID, orga_token_ids)
        if not orga_token_ids:
            return {}

        with Atomizer(rs):
            data = self.sql_select(
                rs, OrgaToken.database_table, OrgaToken.database_fields(),
                orga_token_ids)

            event_ids = {e['event_id'] for e in data}
            if not len(event_ids) == 1:
                raise ValueError(n_("Only orga tokens from one event allowed."))
            if not self.is_orga(rs, event_id=unwrap(event_ids)):
                raise PrivilegeError

            ret: dict[int, OrgaToken] = {}
            for e in data:
                ret[e['id']] = OrgaToken(
                    id=e['id'],
                    event_id=e['event_id'],
                    title=e['title'],
                    notes=e['notes'],
                    ctime=e['ctime'],
                    etime=e['etime'],
                    rtime=e['rtime'],
                    atime=e['atime'],
                )
        return ret

    class _GetOrgaAPITokenProtocol(Protocol):
        def __call__(self, rs: RequestState, orga_token_id: int) -> OrgaToken: ...
    get_orga_token: _GetOrgaAPITokenProtocol = singularize(
        get_orga_tokens, "orga_token_ids", "orga_token_id")

    @access("event")
    def create_orga_token(self, rs: RequestState, data: OrgaToken
                          ) -> tuple[int, str]:
        """Create a new orga token for the given event.

        :returns: A tuple of the new token id and it's secret. The secret is only
            stored as a hash and thus cannot be retrieved again.
        """
        data = affirm_dataclass(OrgaToken, data, creation=True)

        with Atomizer(rs):
            if not self.is_orga(rs, event_id=data.event_id):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(n_(
                    "May not create new orga token in offline instance."))

            secret = OrgaToken.create_secret()
            tdata = data.to_database()
            tdata['secret_hash'] = encrypt_password(secret)
            # Expiration time is not set automatically.
            tdata['etime'] = data.etime

            new_id = self.sql_insert(rs, OrgaToken.database_table, tdata)
            self.event_log(rs, const.EventLogCodes.orga_token_created,
                           data.event_id, change_note=data.title)
        return new_id, secret

    @access("event")
    def change_orga_token(self, rs: RequestState, data: CdEDBObject
                          ) -> DefaultReturnCode:
        """Change some keys of an existing orga token.

        Note that only a small subset of token attributes may be changed.
        """
        data = affirm(vtypes.OrgaToken, data)

        with Atomizer(rs):
            current = self.get_orga_token(rs, data['id'])
            current_data = current.to_database()

            if not self.is_orga(rs, event_id=current.event_id):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(n_(
                    "May not change orga token in offline instance."))

            ret = 1
            if any(data[k] != current_data[k] for k in data):
                ret *= self.sql_update(rs, OrgaToken.database_table, data)

                if 'title' in data and data['title'] != current.title:
                    change_note = f"'{current.title}' -> '{data['title']}'"
                else:
                    change_note = current.title
                self.event_log(
                    rs, const.EventLogCodes.orga_token_changed, current.event_id,
                    change_note=change_note)
        return ret

    @access("event")
    def revoke_orga_token(self, rs: RequestState, orga_token_id: int
                          ) -> DefaultReturnCode:
        """Revoke an existing orga token and delete its hashed secret."""
        orga_token_id = affirm(vtypes.ID, orga_token_id)

        with Atomizer(rs):
            current = self.get_orga_token(rs, orga_token_id)

            if not self.is_orga(rs, event_id=current.event_id):
                raise PrivilegeError

            if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
                raise ValueError(n_(
                    "May not revoke orga token in offline instance."))

            if current.rtime:
                raise ValueError(n_("This orga token has already been revoked."))

            data = {
                'id': orga_token_id,
                'secret_hash': None,
                'rtime': now(),
            }
            ret = self.sql_update(rs, OrgaToken.database_table, data)
            self.event_log(rs, const.EventLogCodes.orga_token_revoked,
                           event_id=current.event_id, change_note=current.title)

        return ret

    @access("event")
    def delete_orga_token_blockers(self, rs: RequestState, orga_token_id: int
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
            rs, OrgaToken.database_table, ("atime",), orga_token_id)
        if orga_token and orga_token['atime']:
            blockers['atime'] = [True]

        log = self.sql_select(
            rs, "event.log", ("id",), (orga_token_id,), entity_key="droid_id")
        if log:
            blockers['log'] = [e['id'] for e in log]

        return blockers

    @access("event")
    def delete_orga_token(self, rs: RequestState, orga_token_id: int,
                          cascade: Collection[str] = None) -> DefaultReturnCode:
        """Delete an orga  token.

        :param cascade: Specify which deletion blockers to cascadingly remove or ignore.
            If None or empty, cascade none.
        """
        orga_token_id = affirm(vtypes.ID, orga_token_id)
        blockers = self.delete_orga_token_blockers(rs, orga_token_id)
        cascade = affirm_set(str, cascade or ()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 'type': "orga token",
                                 'block': blockers.keys() - cascade,
                             })

        if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
            raise ValueError(n_(
                "May not revoke orga token in offline instance."))

        ret = 1
        with Atomizer(rs):
            orga_token = self.get_orga_token(rs, orga_token_id)

            if not self.is_orga(rs, event_id=orga_token.event_id):
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
                ret *= self.sql_delete_one(
                    rs, OrgaToken.database_table, orga_token_id)
                self.event_log(rs, const.EventLogCodes.orga_token_deleted,
                               orga_token.event_id, change_note=orga_token.title)
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {'type': "orga token", 'block': blockers.keys()})

        return ret

    @access("event", "droid_orga")
    def set_event(self, rs: RequestState, data: CdEDBObject,
                  change_note: str = None) -> DefaultReturnCode:
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
        data = affirm(vtypes.Event, data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])

        ret = 1
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            # Set top-level event fields.
            if len(edata) > 1:
                # Do additional validation for these references to custom datafields.
                indirect_fields = set(
                    edata[f] for f in ("lodge_field", "camping_mat_field",
                                       "course_room_field") if f in edata
                )
                if indirect_fields:
                    indirect_data = {e['id']: e for e in self.sql_select(
                        rs, "event.field_definitions",
                        ("id", "event_id", "kind", "association"), indirect_fields)}
                    if edata.get('lodge_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "lodge_field",
                            indirect_data[edata['lodge_field']])
                    if edata.get('camping_mat_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "camping_mat_field",
                            indirect_data[edata['camping_mat_field']])
                    if edata.get('course_room_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "course_room_field",
                            indirect_data[edata['course_room_field']])
                ret *= self.sql_update(rs, "event.events", edata)
                self.event_log(rs, const.EventLogCodes.event_changed,
                               data['id'], change_note=change_note)

            if 'orgas' in data:
                ret *= self.add_event_orgas(rs, data['id'], data['orgas'])
            if 'fields' in data:
                ret *= self._set_event_fields(rs, data['id'], data['fields'])
            # This also includes taking care of course tracks and fee modifiers, since
            # they are each linked to a single event part.
            if 'parts' in data:
                ret *= self._set_event_parts(rs, data['id'], data['parts'])

        return ret

    @access("event_admin")
    def create_event(self, rs: RequestState,
                     data: CdEDBObject) -> DefaultReturnCode:
        """Make a new event organized via DB."""
        data = affirm(vtypes.Event, data, creation=True)
        if not data.get('parts'):
            raise ValueError(n_("At least one event part required."))
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            new_id = self.sql_insert(rs, "event.events", edata)
            self.event_log(rs, const.EventLogCodes.event_created, new_id)
            update_data = {aspect: data[aspect]
                           for aspect in ('parts', 'orgas', 'fields')
                           if aspect in data}
            if update_data:
                update_data['id'] = new_id
                self.set_event(rs, update_data)
            # lg_data: vtypes.LodgementGroup
            if groups := data.get('lodgement_groups'):
                for creation_id in mixed_existence_sorter(groups):
                    lg_data = groups[creation_id]
                    lg_data['event_id'] = new_id
                    self.create_lodgement_group(rs, lg_data)
            else:
                lg_data = vtypes.LodgementGroup({
                    'title': data['title'],
                    'event_id': new_id,
                })
                self.create_lodgement_group(rs, lg_data)
            if fees := data.get('fees'):
                self.set_event_fees(rs, new_id, fees)
            self.event_keeper_create(rs, new_id)
        return new_id

    @access("event")
    def create_lodgement_group(self, rs: RequestState,
                               data: vtypes.LodgementGroup) -> DefaultReturnCode:
        """Make a new lodgement group."""
        data = affirm(vtypes.LodgementGroup, data, creation=True)

        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "event.lodgement_groups", data)
            self.event_log(
                rs, const.EventLogCodes.lodgement_group_created,
                data['event_id'], change_note=data['title'])
        return new_id

    @access("event")
    def set_part_groups(self, rs: RequestState, event_id: int,
                        part_groups: CdEDBOptionalMap) -> DefaultReturnCode:
        """Create, delete and/or update part groups for one event."""
        event_id = affirm(vtypes.ID, event_id)
        part_groups = affirm(vtypes.EventPartGroupSetter, part_groups)

        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))
        ret = 1
        if not part_groups:
            return ret

        with Atomizer(rs):
            parts = {e['id']: e for e in self.sql_select(
                rs, "event.event_parts", EVENT_PART_FIELDS, (event_id,),
                entity_key="event_id")}

            existing_part_groups = {unwrap(e) for e in self.sql_select(
                rs, "event.part_groups", ("id",), (event_id,), entity_key="event_id")}
            new_part_groups = {x for x in part_groups if x < 0}
            updated_part_groups = {
                x for x in part_groups if x > 0 and part_groups[x] is not None}
            deleted_part_groups = {
                x for x in part_groups if x > 0 and part_groups[x] is None}

            if not (updated_part_groups | deleted_part_groups) <= existing_part_groups:
                raise ValueError(n_("Unknown part group."))

            # Defer unique constraints until end of transaction to avoid errors when
            # updating multiple groups at once or deleting and recreating them.
            self.sql_defer_constraints(
                rs, "event.part_groups_event_id_shortname_key",
                "event.part_groups_event_id_title_key",
                "event.part_group_parts_part_id_part_group_id_key")

            # new
            for x in mixed_existence_sorter(new_part_groups):
                new_part_group = part_groups[x]
                assert new_part_group is not None
                new_part_group['event_id'] = event_id
                part_ids = affirm_set(vtypes.ID, new_part_group.pop('part_ids'))
                new_id = self.sql_insert(rs, "event.part_groups", new_part_group)
                ret *= new_id
                self.event_log(
                    rs, const.EventLogCodes.part_group_created, event_id,
                    change_note=new_part_group['title'])
                if part_ids:
                    if not part_ids <= parts.keys():
                        raise ValueError(n_("Unknown part for the given event."))
                    ret *= self._set_part_group_parts(
                        rs, event_id, part_group_id=new_id, part_ids=part_ids,
                        parts=parts, part_group_title=new_part_group['title'])

            # updated
            if updated_part_groups:
                current_part_group_data = {e['id']: e for e in self.sql_select(
                    rs, "event.part_groups", PART_GROUP_FIELDS, updated_part_groups)}
                for x in mixed_existence_sorter(updated_part_groups):
                    updated = part_groups[x]
                    assert updated is not None
                    updated['id'] = x
                    # Changing the constraint type is not allowed.
                    new_ct = updated.pop('contraint_type', None)
                    old_ct = current_part_group_data[x]['constraint_type']
                    if new_ct and new_ct != old_ct:
                        raise ValueError(n_("May not change constraint type."))
                    part_ids = updated.pop('part_ids', None)
                    title = updated.get('title', current_part_group_data[x]['title'])
                    if any(updated[k] != current_part_group_data[x][k]
                           for k in updated):
                        ret *= self.sql_update(rs, "event.part_groups", updated)
                        self.event_log(
                            rs, const.EventLogCodes.part_group_changed, event_id,
                            change_note=title)
                    if part_ids is not None:
                        part_ids = affirm_set(vtypes.ID, part_ids)
                        if not part_ids <= parts.keys():
                            raise ValueError(n_("Unknown part for the given event."))
                        ret *= self._set_part_group_parts(
                            rs, event_id, part_group_id=x, part_ids=part_ids,
                            parts=parts, part_group_title=title)

            if deleted_part_groups:
                cascade = ("part_group_parts",)
                for x in mixed_existence_sorter(deleted_part_groups):
                    ret *= self._delete_part_group(rs, part_group_id=x, cascade=cascade)

        return ret

    @access("event")
    def set_track_groups(self, rs: RequestState, event_id: int,
                         track_groups: CdEDBOptionalMap) -> DefaultReturnCode:
        """Create, delete and/or update track groups for one event."""
        event_id = affirm(vtypes.ID, event_id)
        track_groups = affirm(vtypes.EventTrackGroupSetter, track_groups)

        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))

        ret = 1
        if not track_groups:
            return ret

        with Atomizer(rs):
            parts = {e['id']: e for e in self.sql_select(
                rs, "event.event_parts", EVENT_PART_FIELDS, (event_id,),
                entity_key="event_id")}
            tracks = {e['id']: e for e in self.sql_select(
                rs, "event.course_tracks", COURSE_TRACK_FIELDS, parts.keys(),
                entity_key="part_id")}

            existing_track_groups = {unwrap(e) for e in self.sql_select(
                rs, "event.track_groups", ("id",), (event_id,), entity_key="event_id")}
            new_track_groups = {x for x in track_groups if x < 0}
            updated_track_groups = {
                x for x in track_groups if x > 0 and track_groups[x] is not None}
            deleted_track_groups = {
                x for x in track_groups if x > 0 and track_groups[x] is None}

            tmp = updated_track_groups | deleted_track_groups
            if not tmp <= existing_track_groups:
                raise ValueError(n_("Unknown track group."))

            # Defer unique constraints until end of transaction.
            self.sql_defer_constraints(
                rs, "event.track_groups_event_id_shortname_key",
                "event.track_groups_event_id_title_key",
                "event.track_group_tracks_track_id_track_group_id_key",
            )

            # new
            for x in mixed_existence_sorter(new_track_groups):
                new_track_group = track_groups[x]
                assert new_track_group is not None
                new_track_group['event_id'] = event_id
                track_ids = affirm_set(vtypes.ID, new_track_group.pop('track_ids'))
                new_id = self.sql_insert(rs, "event.track_groups", new_track_group)
                ret *= new_id
                self.event_log(
                    rs, const.EventLogCodes.track_group_created, event_id,
                    change_note=new_track_group['title'])
                if track_ids:
                    if not track_ids <= tracks.keys():
                        raise ValueError(n_("Unknown track for the given event."))
                    ret *= self._set_track_group_tracks(
                        rs, event_id, track_group_id=new_id, track_ids=track_ids,
                        tracks=tracks, track_group_title=new_track_group['title'],
                        constraint_type=new_track_group['constraint_type'])

            # updated
            if updated_track_groups:
                current_track_group_data = {e['id']: e for e in self.sql_select(
                    rs, "event.track_groups", TRACK_GROUP_FIELDS, updated_track_groups)}
                for x in mixed_existence_sorter(updated_track_groups):
                    current = current_track_group_data[x]
                    updated = track_groups[x]
                    assert updated is not None
                    updated['id'] = x
                    # Changing constraint type is not allowed.
                    new_ct = updated.pop('contraint_type', None)
                    old_ct = current_track_group_data[x]['constraint_type']
                    if new_ct and new_ct != old_ct:
                        raise ValueError(n_("May not change constraint type."))
                    track_ids = updated.pop('track_ids', None)
                    title = updated.get('title', current_track_group_data[x]['title'])
                    if any(updated[k] != current_track_group_data[x][k]
                           for k in updated):
                        ret *= self.sql_update(rs, "event.track_groups", updated)
                        self.event_log(
                            rs, const.EventLogCodes.track_group_changed, event_id,
                            change_note=title)
                    if track_ids is not None:
                        track_ids = affirm_set(vtypes.ID, track_ids)
                        if not track_ids <= tracks.keys():
                            raise ValueError(n_("Unknown track for the given event."))
                        ret *= self._set_track_group_tracks(
                            rs, event_id, track_group_id=x, track_ids=track_ids,
                            tracks=tracks, track_group_title=title,
                            constraint_type=const.CourseTrackGroupType(
                                current['constraint_type']))

            if deleted_track_groups:
                cascade = ("track_group_tracks",)
                for x in mixed_existence_sorter(deleted_track_groups):
                    ret *= self._delete_track_group(
                        rs, track_group_id=x, cascade=cascade)

            self._track_groups_sanity_check(rs, event_id)

        return ret

    @access("event")
    def set_event_fees(self, rs: RequestState, event_id: int, fees: CdEDBOptionalMap
                       ) -> DefaultReturnCode:
        """Create, delete and/or update fees for one event."""
        event_id = affirm(vtypes.ID, event_id)

        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))

        ret = 1
        if not fees:
            return ret

        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            questionnaire = self.get_questionnaire(rs, event_id)
            fees = affirm(vtypes.EventFeeSetter, fees, event=event,
                          questionnaire=questionnaire)

            existing_fees = {unwrap(e) for e in self.sql_select(
                rs, "event.event_fees", ("id",), (event_id,), entity_key="event_id")}
            new_fees = {x for x in fees if x < 0}
            updated_fees = {x for x in fees if x > 0 and fees[x] is not None}
            deleted_fees = {x for x in fees if x > 0 and fees[x] is None}
            if not updated_fees | deleted_fees <= existing_fees:
                raise ValueError(n_("Non-existing event fee specified."))

            if updated_fees or deleted_fees:
                current_fee_data = {e['id']: e for e in self.sql_select(
                    rs, "event.event_fees", EVENT_FEE_FIELDS,
                    updated_fees | deleted_fees)}

                if deleted_fees:
                    ret *= self.sql_delete(rs, "event.event_fees", deleted_fees)
                    for x in mixed_existence_sorter(deleted_fees):
                        current = current_fee_data[x]
                        self.event_log(rs, const.EventLogCodes.fee_modifier_deleted,
                                       event_id, change_note=current['title'])

                for x in mixed_existence_sorter(updated_fees):
                    updated_fee = copy.deepcopy(fees[x])
                    assert updated_fee is not None
                    updated_fee['id'] = x
                    current = current_fee_data[x]
                    if any(updated_fee[k] != current[k] for k in updated_fee):
                        ret *= self.sql_update(rs, "event.event_fees", updated_fee)
                        self.event_log(rs, const.EventLogCodes.fee_modifier_changed,
                                       event_id, change_note=current['title'])

            for x in mixed_existence_sorter(new_fees):
                new_fee = copy.deepcopy(fees[x])
                assert new_fee is not None
                new_fee['event_id'] = event_id
                ret *= self.sql_insert(rs, "event.event_fees", new_fee)
                self.event_log(rs, const.EventLogCodes.fee_modifier_created, event_id,
                               change_note=new_fee['title'])

            self._update_registrations_amount_owed(rs, event_id)

        return ret

    @abc.abstractmethod
    def _update_registrations_amount_owed(self, rs: RequestState, event_id: int
                                          ) -> DefaultReturnCode: ...

    @access("event")
    def check_orga_addition_limit(self, rs: RequestState,
                                  event_id: int) -> bool:
        """Implement a rate limiting check for orgas adding persons.

        Since adding somebody as participant or orga to an event gives all
        orgas basically full access to their data, we rate limit this
        operation.

        :returns: True if limit has not been reached.
        """
        event_id = affirm(vtypes.ID, event_id)
        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        if self.is_admin(rs):
            # Admins are exempt
            return True
        query = ("SELECT COUNT(*) AS num FROM event.log"
                 " WHERE event_id = %s AND code = %s "
                 " AND submitted_by != persona_id "
                 " AND ctime >= now() - interval '24 hours'")
        params = (event_id, const.EventLogCodes.registration_created)
        num = unwrap(self.query_one(rs, query, params))
        return num < self.conf["ORGA_ADD_LIMIT"]

    @access("event", "droid_quick_partial_export", "droid_orga")
    def get_questionnaire(self, rs: RequestState, event_id: int,
                          kinds: Collection[const.QuestionnaireUsages] = None
                          ) -> CdEDBQuestionnaire:
        """Retrieve the questionnaire rows for a specific event.

        Rows are seperated by kind. Specifying a kinds will get you only rows
        of those kinds, otherwise you get them all.
        """
        event_id = affirm(vtypes.ID, event_id)
        kinds = kinds or []
        affirm_set(const.QuestionnaireUsages, kinds)
        columns = ', '.join(k for k in QUESTIONNAIRE_ROW_FIELDS if k != 'event_id')
        query = f"SELECT {columns} FROM event.questionnaire_rows"
        constraints = ["event_id = %s"]
        params: List[Any] = [event_id]
        if kinds:
            constraints.append("kind = ANY(%s)")
            params.append(kinds)
        query += " WHERE " + " AND ".join(c for c in constraints)
        d = self.query_all(rs, query, params)
        for row in d:
            row['kind'] = const.QuestionnaireUsages(row['kind'])
        ret = {
            k: xsorted([e for e in d if e['kind'] == k], key=lambda x: x['pos'])
            for k in kinds or const.QuestionnaireUsages
        }
        return ret

    @access("event")
    def set_questionnaire(self, rs: RequestState, event_id: int,
                          data: Optional[CdEDBQuestionnaire]) -> DefaultReturnCode:
        """Replace current questionnaire rows for a specific event, by kind.

        This superseeds the current questionnaire for all given kinds.
        Kinds that are not present in data, will not be touched.

        To delete all questionnaire rows, you can specify data as None.
        """
        event_id = affirm(vtypes.ID, event_id)
        event = self.get_event(rs, event_id)
        fees_by_field = self.get_event_fees_per_entity(rs, event_id).fields
        if data is not None:
            current = self.get_questionnaire(rs, event_id)
            current.update(data)
            # FIXME what is the correct type here?
            data = affirm(vtypes.Questionnaire, current,  # type: ignore[assignment]
                          field_definitions=event['fields'],
                          fees_by_field=fees_by_field)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        with Atomizer(rs):
            ret = 1
            # Allow deletion of enitre questionnaire by specifying None.
            if data is None:
                self.sql_delete(rs, "event.questionnaire_rows", (event_id,),
                                entity_key="event_id")
                return 1
            # Otherwise replace rows for all given kinds.
            for kind, rows in data.items():
                query = ("DELETE FROM event.questionnaire_rows"
                         " WHERE event_id = %s AND kind = %s")
                params = (event_id, kind)
                self.query_exec(rs, query, params)
                for pos, row in enumerate(rows):
                    new_row = copy.deepcopy(row)
                    new_row['pos'] = pos
                    new_row['event_id'] = event_id
                    new_row['kind'] = kind
                    ret *= self.sql_insert(
                        rs, "event.questionnaire_rows", new_row)
            self.event_log(
                rs, const.EventLogCodes.questionnaire_changed, event_id)
        return ret

    @access("event")
    def lock_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        """Lock an event for offline usage."""
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        # An event in the main instance is considered as locked if offline_lock
        # is true, in the offline instance it is the other way around
        update = {
            'id': event_id,
            'offline_lock': not self.conf["CDEDB_OFFLINE_DEPLOYMENT"],
        }
        with Atomizer(rs):
            self.event_keeper_commit(rs, event_id, "Snapshot vor Offline-Lock.")
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_locked, event_id)
        return ret

    @access("event")
    def export_event(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Export an event for offline usage or after offline usage.

        This provides a more general export functionality which could
        also be used without locking.

        :returns: dict holding all data of the exported event
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Iterable[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        with Atomizer(rs):
            ret: CdEDBObject = {
                'EVENT_SCHEMA_VERSION': EVENT_SCHEMA_VERSION,
                'kind': "full",  # could also be "partial"
                'id': event_id,
                'event.events': list_to_dict(self.sql_select(
                    rs, "event.events", EVENT_FIELDS, (event_id,))),
                'timestamp': now(),
            }
            # Table name; column to scan; fields to extract
            tables: List[Tuple[str, str, Tuple[str, ...]]] = [
                ('event.event_parts', "event_id", EVENT_PART_FIELDS),
                ('event.part_groups', "event_id", PART_GROUP_FIELDS),
                ('event.part_group_parts', "part_id", ("part_group_id", "part_id")),
                ('event.course_tracks', "part_id", COURSE_TRACK_FIELDS),
                ('event.track_groups', "event_id", TRACK_GROUP_FIELDS),
                ('event.track_group_tracks', "track_id", (
                    "track_group_id", "track_id")),
                ('event.courses', "event_id", COURSE_FIELDS),
                ('event.course_segments', "track_id", COURSE_SEGMENT_FIELDS),
                ('event.orgas', "event_id", ('id', 'persona_id', 'event_id',)),
                ('event.field_definitions', "event_id", FIELD_DEFINITION_FIELDS),
                ('event.event_fees', "event_id", EVENT_FEE_FIELDS),
                ('event.lodgement_groups', "event_id", LODGEMENT_GROUP_FIELDS),
                ('event.lodgements', "event_id", LODGEMENT_FIELDS),
                ('event.registrations', "event_id", REGISTRATION_FIELDS),
                ('event.registration_parts', "part_id", REGISTRATION_PART_FIELDS),
                ('event.registration_tracks', "track_id", REGISTRATION_TRACK_FIELDS),
                ('event.course_choices', "track_id", (
                    'id', 'registration_id', 'track_id', 'course_id', 'rank',)),
                (OrgaToken.database_table, "event_id", tuple(
                    OrgaToken.database_fields())),
                ('event.questionnaire_rows', "event_id", QUESTIONNAIRE_ROW_FIELDS),
                ('event.stored_queries', "event_id", STORED_EVENT_QUERY_FIELDS),
                ('event.log', "event_id", (
                    'id', 'ctime', 'code', 'submitted_by', 'event_id',
                    'persona_id', 'change_note')),
            ]
            personas = set()
            for table, id_name, columns in tables:
                if id_name == "event_id":
                    id_range = {event_id}
                elif id_name == "part_id":
                    id_range = set(ret['event.event_parts'])
                elif id_name == "track_id":
                    id_range = set(ret['event.course_tracks'])
                else:
                    raise RuntimeError(n_("Impossible."))
                if 'id' not in columns:
                    columns += ('id',)
                ret[table] = list_to_dict(self.sql_select(
                    rs, table, columns, id_range, entity_key=id_name))
                # Note the personas present to export them further on
                for e in ret[table].values():
                    if e.get('persona_id'):
                        personas.add(e['persona_id'])
                    if e.get('submitted_by'):  # for log entries
                        personas.add(e['submitted_by'])
            ret['core.personas'] = list_to_dict(self.sql_select(
                rs, "core.personas", PERSONA_EVENT_FIELDS, personas))
        return ret

    @access("event", "droid_quick_partial_export", "droid_orga")
    def partial_export_event(self, rs: RequestState,
                             event_id: int) -> CdEDBObject:
        """Export an event for third-party applications.

        This provides a consumer-friendly package of event data which can
        later on be reintegrated with the partial import facility.
        """
        event_id = affirm(vtypes.ID, event_id)
        access_ok = (
            (self.conf["CDEDB_OFFLINE_DEPLOYMENT"]  # this grants access for
             and "droid_quick_partial_export" in rs.user.roles)  # the droid
            or self.is_orga(rs, event_id=event_id)
            or self.is_admin(rs))
        if not access_ok:
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Collection[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        # First gather all the data and give up the database lock afterwards.
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            courses = list_to_dict(self.sql_select(
                rs, 'event.courses', COURSE_FIELDS, (event_id,),
                entity_key='event_id'))
            course_segments = self.sql_select(
                rs, 'event.course_segments',
                ('course_id', 'track_id', 'is_active'), courses.keys(),
                entity_key='course_id')
            lodgement_groups = list_to_dict(self.sql_select(
                rs, 'event.lodgement_groups', LODGEMENT_GROUP_FIELDS,
                (event_id,), entity_key='event_id'))
            lodgements = list_to_dict(self.sql_select(
                rs, 'event.lodgements', LODGEMENT_FIELDS, (event_id,),
                entity_key='event_id'))
            registrations = self._get_registration_data(rs, event_id)
            registration_parts = self.sql_select(
                rs, 'event.registration_parts',
                REGISTRATION_PART_FIELDS, registrations.keys(),
                entity_key='registration_id')
            registration_tracks = self.sql_select(
                rs, 'event.registration_tracks',
                REGISTRATION_TRACK_FIELDS, registrations.keys(),
                entity_key='registration_id')
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"),
                registrations.keys(), entity_key="registration_id")
            tokens = list_to_dict(self.sql_select(
                rs, OrgaToken.database_table, OrgaToken.database_fields(),
                (event_id,), entity_key="event_id"))
            questionnaire = self.get_questionnaire(rs, event_id)
            persona_ids = tuple(reg['persona_id']
                                for reg in registrations.values())
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
        lookup: Dict[int, Dict[int, bool]] = collections.defaultdict(dict)
        for e in course_segments:
            lookup[e['course_id']][e['track_id']] = e['is_active']
        for course_id, course in courses.items():
            del course['id']
            del course['event_id']
            course['segments'] = lookup[course_id]
            course['fields'] = cast_fields(
                course['fields'], event['fields'])
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
            lodgement['fields'] = cast_fields(lodgement['fields'],
                                              event['fields'])
        ret['lodgements'] = lodgements
        # registrations
        part_lookup: Dict[int, Dict[int, CdEDBObject]]
        part_lookup = collections.defaultdict(dict)
        for e in registration_parts:
            part_lookup[e['registration_id']][e['part_id']] = e
        track_lookup: Dict[int, Dict[int, CdEDBObject]]
        track_lookup = collections.defaultdict(dict)
        for e in registration_tracks:
            track_lookup[e['registration_id']][e['track_id']] = e
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
                tmp = {e['course_id']: e['rank'] for e in choices
                       if (e['registration_id'] == track['registration_id']
                           and e['track_id'] == track_id)}
                track['choices'] = xsorted(tmp.keys(), key=tmp.get)
                del track['registration_id']
                del track['track_id']
            registration['tracks'] = tracks
            registration['fields'] = cast_fields(registration['fields'],
                                                 event['fields'])
        ret['registrations'] = registrations

        for token_id, orga_token in tokens.items():
            del orga_token['id']
            del orga_token['event_id']
        event['orga_tokens'] = tokens

        # now we add additional information that is only auxillary and
        # does not correspond to changeable entries
        #
        # event
        del event['id']
        del event['begin']
        del event['end']
        del event['is_open']
        # Delete this later.
        # del event['orgas']
        del event['tracks']
        event['fees'] = {
            fee['title']: fee for fee in event['fees'].values()}
        for fee in event['fees'].values():
            del fee['id']
            del fee['event_id']
            del fee['title']
        for part in event['parts'].values():
            del part['id']
            del part['event_id']
            del part['part_groups']
            for f in ('waitlist_field',):
                if part[f]:
                    part[f] = event['fields'][part[f]]['field_name']
            for track in part['tracks'].values():
                del track['id']
                del track['part_id']
                del track['track_groups']
        for pg in event['part_groups'].values():
            del pg['id']
            del pg['event_id']
            pg['constraint_type'] = const.EventPartGroupType(pg['constraint_type'])
            pg['part_ids'] = xsorted(pg['part_ids'])
        for tg in event['track_groups'].values():
            del tg['id']
            del tg['event_id']
            tg['constraint_type'] = const.CourseTrackGroupType(tg['constraint_type'])
            tg['track_ids'] = xsorted(tg['track_ids'])
        for f in ('lodge_field', 'camping_mat_field', 'course_room_field'):
            if event[f]:
                event[f] = event['fields'][event[f]]['field_name']
        # Fields and questionnaire
        new_fields = {
            field['field_name']: field
            for field in event['fields'].values()
        }
        new_questionnaire = {
            str(usage): rows
            for usage, rows in questionnaire.items()
        }
        for usage, rows in new_questionnaire.items():
            for q in rows:
                if q['field_id']:
                    q['field_name'] = event['fields'][q['field_id']]['field_name']
                else:
                    q['field_name'] = None
                del q['pos']
                del q['kind']
                del q['field_id']
        for field in new_fields.values():
            del field['field_name']
            del field['event_id']
            del field['id']
        # personas
        for reg_id, registration in ret['registrations'].items():
            persona = personas[registration['persona_id']]
            del registration['persona_id']
            persona['is_orga'] = persona['id'] in event['orgas']
            for attr in set(PERSONA_STATUS_FIELDS) - {'is_member'}:
                del persona[attr]
            registration['persona'] = persona
        del event['orgas']
        event['fields'] = new_fields
        event['questionnaire'] = new_questionnaire
        ret['event'] = event
        return ret

    @access("event")
    def questionnaire_import(self, rs: RequestState, event_id: int,
                             fields: CdEDBObjectMap, questionnaire: CdEDBQuestionnaire,
                             ) -> DefaultReturnCode:
        """Special import for custom datafields and questionnaire rows."""
        event_id = affirm(vtypes.ID, event_id)
        # validation of input is delegated to the setters, because it is rather
        # involved and dependent on each other.
        # Do not allow special use of `set_questionnaire` for deleting everything.
        if questionnaire is None:
            raise ValueError(n_(
                "Cannot use questionnaire import to delete questionnaire."))
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        with Atomizer(rs):
            ret = self.set_event(rs, {'id': event_id, 'fields': fields})
            ret *= self.set_questionnaire(rs, event_id, questionnaire)
        return ret

    @access("event_admin")
    def event_keeper_create(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Create a new git repository for keeping track of event changes."""
        event_id = affirm(vtypes.ID, event_id)
        self._event_keeper.init(event_id)
        export = self.event_keeper_commit(rs, event_id, "Initialer Commit",
                                          is_initial=True)
        # since is_initial is True, a partial export will always be returned
        assert export is not None
        return export

    @access("event_admin")
    def event_keeper_drop(self, rs: RequestState, event_id: int) -> None:
        """Published version of EntityKeeper.delete.

        :param rs: Required for access check."""
        return self._event_keeper.delete(event_id)

    @access("event")
    def event_keeper_commit(self, rs: RequestState, event_id: int, commit_msg: str, *,
                            after_change: bool = False, is_initial: bool = False
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
            persona = {"display_name": rs.user.display_name,
                       "given_names": rs.user.given_names,
                       "family_name": rs.user.family_name}
            author_name = make_persona_name(persona)
            author_email = rs.user.username
        self._event_keeper.commit(
            event_id, json_serialize(export), commit_msg, author_name, author_email,
            may_drop=may_drop, logs=logs)
        return export

    @internal
    def _process_event_keeper_logs(self, rs: RequestState,
                                   event_id: int) -> Optional[Tuple[CdEDBObject, ...]]:
        """Format the log entries since the last commit to make them more readable."""
        with Atomizer(rs):
            timestamp = self._event_keeper.latest_logtime(event_id)
            if timestamp is None:
                return None
            # since retrieve_log compares timestamps inclusive, we need to increase the
            # timestamp to not include log entries from the latest commit.
            timestamp += datetime.timedelta(seconds=1)
            _, entries = self.retrieve_log(
                rs, EventLogFilter(event_id=event_id, ctime_from=timestamp))
            # short circuit if there are no new log entries
            if not entries:
                return None

            # retrieve additional information to pimp up the log entries
            persona_ids = (
                {entry['submitted_by'] for entry in entries if entry['submitted_by']}
                | {entry['persona_id'] for entry in entries if entry['persona_id']})
            personas = self.core.get_personas(rs, persona_ids)

        # the name of the fields which will show up in the log are defined
        # during instantiation of the entity keeper.
        for entry in entries:
            entry["Zeitstempel"] = datetime_filter(
                entry["ctime"], formatstr="%Y-%m-%d %H:%M:%S (%Z)")
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
