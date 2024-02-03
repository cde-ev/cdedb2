#!/usr/bin/env python3

"""
The `EventLodgementBackend` subclasses the `EventBaseBackend` and provides
functionality for managing lodgements and lodgement groups belonging to an event.
"""
import collections
import dataclasses
from collections.abc import Collection, Iterator
from typing import Any, Optional, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.backend.common import (
    Silencer, access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    read_conditional_write_composer, singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, DefaultReturnCode, DeletionBlockers, PsycoJson,
    RequestState, cast_fields, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import LODGEMENT_FIELDS
from cdedb.common.n_ import n_
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.database.query import DatabaseValue_s


@dataclasses.dataclass(frozen=True)
class LodgementInhabitants:
    """Small helper class to store and add inhabitants of a lodgement."""
    regular: tuple[int, ...] = dataclasses.field(default_factory=tuple)
    camping_mat: tuple[int, ...] = dataclasses.field(default_factory=tuple)

    @property
    def all(self) -> tuple[int, ...]:
        return self.regular + self.camping_mat

    def __add__(self, other: Any) -> "LodgementInhabitants":
        if not isinstance(other, LodgementInhabitants):
            return NotImplemented
        return self.__class__(self.regular + other.regular,
                              self.camping_mat + other.camping_mat)

    def __iter__(self) -> Iterator[tuple[int, ...]]:
        """Enable tuple unpacking."""
        return iter((self.regular, self.camping_mat))


class EventLodgementBackend(EventBaseBackend):  # pylint: disable=abstract-method
    @access("event")
    def list_lodgement_groups(self, rs: RequestState,
                              event_id: int) -> dict[int, str]:
        """List all lodgement groups for an event.

        :returns: dict mapping ids to names
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "event.lodgement_groups", ("id", "title"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

    @access("event")
    def get_lodgement_groups(self, rs: RequestState, group_ids: Collection[int],
                             ) -> CdEDBObjectMap:
        """Retrieve data for some lodgement groups.

        All have to be from the same event.

        For all lodgements belonging to a group, their ids are collected into a set of
        lodgement_ids and their capacities (regular and camping mat) are summed.
        """
        group_ids = affirm_set(vtypes.ID, group_ids)
        with Atomizer(rs):
            query = """
                SELECT
                    lg.id, lg.event_id, lg.title,
                    ARRAY_REMOVE(ARRAY_AGG(l.id), NULL) AS lodgement_ids,
                    COALESCE(SUM(l.regular_capacity), 0) as regular_capacity,
                    COALESCE(SUM(l.camping_mat_capacity), 0) AS camping_mat_capacity
                FROM event.lodgement_groups AS lg
                    LEFT JOIN event.lodgements AS l on lg.id = l.group_id
                WHERE lg.id = ANY(%s)
                GROUP BY lg.id
            """
            data = self.query_all(rs, query, (group_ids,))
            if not data:
                return {}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only lodgement groups from exactly one event allowed!"))
            event_id = unwrap(events)
            if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
                raise PrivilegeError(n_("Not privileged."))
        return {e['id']: e for e in data}

    class _GetLodgementGroupProtocol(Protocol):
        def __call__(self, rs: RequestState, group_id: int) -> CdEDBObject: ...
    get_lodgement_group: _GetLodgementGroupProtocol = singularize(
        get_lodgement_groups, "group_ids", "group_id")

    @access("event")
    def new_get_lodgement_groups(self, rs: RequestState, event_id: int,
                                 ) -> models.CdEDataclassMap[models.LodgementGroup]:
        event_id = affirm(vtypes.ID, event_id)
        with Atomizer(rs):
            group_data = self.query_all(
                rs, *models.LodgementGroup.get_select_query((event_id,)))
        return models.LodgementGroup.many_from_database(group_data)

    @access("event")
    def set_lodgement_group(self, rs: RequestState,
                            data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a lodgement group."""
        data = affirm(vtypes.LodgementGroup, data)
        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_lodgement_groups(rs, (data['id'],)))
            event_id, title = current['event_id'], current['title']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            self.assert_offline_lock(rs, event_id=event_id)

            # Do the actual work:
            ret *= self.sql_update(rs, "event.lodgement_groups", data)
            self.event_log(
                rs, const.EventLogCodes.lodgement_group_changed, event_id,
                change_note=title)

        return ret

    class _RCWLodgementGroupProtocol(Protocol):
        def __call__(self, rs: RequestState, data: CdEDBObject,
                     ) -> DefaultReturnCode: ...
    rcw_lodgement_group: _RCWLodgementGroupProtocol = read_conditional_write_composer(
        get_lodgement_group, set_lodgement_group, id_param_name='group_id')

    @access("event")
    def delete_lodgement_group_blockers(self, rs: RequestState,
                                        group_id: int) -> DeletionBlockers:
        """Determine what keeps a lodgement group from being deleted.

        Possible blockers:

        * lodgements: A lodgement that is part of this lodgement group.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        group_id = affirm(vtypes.ID, group_id)
        blockers = {}

        lodgements = self.sql_select(
            rs, "event.lodgements", ("id",), (group_id,),
            entity_key="group_id")
        if lodgements:
            blockers["lodgements"] = [e["id"] for e in lodgements]

        return blockers

    @access("event")
    def delete_lodgement_group(self, rs: RequestState, group_id: int,
                               cascade: Optional[Collection[str]] = None,
                               ) -> DefaultReturnCode:
        """Delete a lodgement group.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        group_id = affirm(vtypes.ID, group_id)
        blockers = self.delete_lodgement_group_blockers(rs, group_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "lodgement group",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "lodgements" in cascade:
                    with Silencer(rs):
                        lodgement_cascade = ("inhabitants",)
                        for lodgement_id in blockers["lodgements"]:
                            ret *= self.delete_lodgement(
                                rs, lodgement_id, lodgement_cascade)

                blockers = self.delete_lodgement_group_blockers(rs, group_id)

            if not blockers:
                group = self.get_lodgement_group(rs, group_id)
                ret *= self.sql_delete_one(rs, "event.lodgement_groups", group_id)
                self.event_log(rs, const.EventLogCodes.lodgement_group_deleted,
                               event_id=group['event_id'], change_note=group['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement group", "block": blockers.keys()})
        return ret

    @access("event")
    def list_lodgements(self, rs: RequestState, event_id: int, group_id: Optional[int] = None,
                        ) -> dict[int, str]:
        """List all lodgements for an event.

        :param group_id: If given, limit to lodgements in this group.
        :returns: dict mapping ids to names
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        if group_id:
            group_data = self.sql_select_one(
                rs, "event.lodgement_groups", ("event_id", "title"), group_id)
            if not group_data or group_data['event_id'] != event_id:
                raise ValueError(n_("Invalid lodgement group."))
            entities = (group_id,)
            entity_key = 'group_id'
        else:
            entities = (event_id,)
            entity_key = 'event_id'

        data = self.sql_select(rs, "event.lodgements", ("id", "title"),
                               entities=entities, entity_key=entity_key)
        return {e['id']: e['title'] for e in data}

    @access("event")
    def get_lodgements(self, rs: RequestState, lodgement_ids: Collection[int],
                       ) -> CdEDBObjectMap:
        """Retrieve data for some lodgements.

        All have to be from the same event.
        """
        lodgement_ids = affirm_set(vtypes.ID, lodgement_ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.lodgements", LODGEMENT_FIELDS,
                                   lodgement_ids)
            if not data:
                return {}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only lodgements from exactly one event allowed!"))
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event_fields = models.EventField.many_from_database(
                self._get_event_fields(rs, event_id).values())
            ret = {e['id']: e for e in data}
            for lodge in ret.values():
                lodge['fields'] = cast_fields(lodge['fields'], event_fields)
        return {e['id']: e for e in data}

    class _GetLodgementProtocol(Protocol):
        def __call__(self, rs: RequestState, lodgement_id: int) -> CdEDBObject: ...
    get_lodgement: _GetLodgementProtocol = singularize(
        get_lodgements, "lodgement_ids", "lodgement_id")

    @access("event")
    def new_get_lodgements(self, rs: RequestState, lodgement_ids: Collection[int],
                           ) -> models.CdEDataclassMap[models.Lodgement]:
        lodgement_ids = affirm_set(vtypes.ID, lodgement_ids)
        with Atomizer(rs):
            lodgement_data = self.query_all(
                rs, *models.Lodgement.get_select_query(lodgement_ids))
            if not lodgement_data:
                return {}
            events = {e['event_id'] for e in lodgement_data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only lodgements from exactly one event allowed!"))
            event_id = unwrap(events)
            if not self.is_orga(rs, event_id=event_id):
                raise PrivilegeError(n_("Not privileged."))
            group_data = {
                e['id']: e for e in self.query_all(
                    rs, *models.LodgementGroup.get_select_query(
                        [lodge['group_id'] for lodge in lodgement_data], "id"))
            }
            event_fields = self._get_event_fields(rs, event_id)
        return models.Lodgement.many_from_database([
            {
                **lodge,
                'group_data': group_data[lodge['group_id']],
                'event_fields': models.EventField.many_from_database(
                    event_fields.values()),
            }
            for lodge in lodgement_data
        ])

    class _NewGetLodgementProtocol(Protocol):
        def __call__(self, rs: RequestState, lodgement_id: int) -> models.Lodgement: ...
    new_get_lodgement: _NewGetLodgementProtocol = singularize(
        new_get_lodgements, "lodgement_ids", "lodgement_id")

    @access("event")
    def set_lodgement(self, rs: RequestState, data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a lodgement."""
        data = affirm(vtypes.Lodgement, data)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "event.lodgements", ("event_id", "title"), data['id'])
            if current is None:
                raise ValueError(n_("Lodgement does not exist."))
            event_id, title = current['event_id'], current['title']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            self.assert_offline_lock(rs, event_id=event_id)

            # now we get to do the actual work
            ret = 1
            ldata = {k: v for k, v in data.items()
                     if k in LODGEMENT_FIELDS and k != "fields"}
            if len(ldata) > 1:
                ret *= self.sql_update(rs, "event.lodgements", ldata)
            if 'fields' in data:
                # delayed validation since we need more info
                event_fields = self._get_event_fields(rs, event_id)
                fdata = affirm(
                    vtypes.EventAssociatedFields, data['fields'],
                    fields=models.EventField.many_from_database(event_fields.values()),
                    association=const.FieldAssociations.lodgement,
                )

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.lodgements",
                                                    fupdate)
            self.event_log(
                rs, const.EventLogCodes.lodgement_changed, event_id,
                change_note=title)
        return ret

    @access("event")
    def create_lodgement(self, rs: RequestState,
                         data: CdEDBObject) -> DefaultReturnCode:
        """Make a new lodgement."""
        data = affirm(vtypes.Lodgement, data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata,
            fields=models.EventField.many_from_database(event_fields.values()),
            association=const.FieldAssociations.lodgement,
        )
        data['fields'] = PsycoJson(fdata)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "event.lodgements", data)
            self.event_log(
                rs, const.EventLogCodes.lodgement_created, data['event_id'],
                change_note=data['title'])
        return new_id

    @access("event")
    def delete_lodgement_blockers(self, rs: RequestState,
                                  lodgement_id: int) -> DeletionBlockers:
        """Determine what keeps a lodgement from beeing deleted.

        Possible blockers:

        * inhabitants: A registration part that assigns a registration to the
                       lodgement as an inhabitant.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        lodgement_id = affirm(vtypes.ID, lodgement_id)
        blockers = {}

        inhabitants = self.sql_select(
            rs, "event.registration_parts", ("id",), (lodgement_id,),
            entity_key="lodgement_id")
        if inhabitants:
            blockers["inhabitants"] = [e["id"] for e in inhabitants]

        return blockers

    @access("event")
    def delete_lodgement(self, rs: RequestState, lodgement_id: int,
                         cascade: Optional[Collection[str]] = None) -> DefaultReturnCode:
        """Delete a lodgement.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        lodgement_id = affirm(vtypes.ID, lodgement_id)
        lodgement = self.get_lodgement(rs, lodgement_id)
        event_id = lodgement["event_id"]
        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        blockers = self.delete_lodgement_blockers(rs, lodgement_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "lodgement",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "inhabitants" in cascade:
                    query = ("UPDATE event.registration_parts"
                             " SET lodgement_id = NULL"
                             " WHERE id = ANY(%s)")
                    params = (blockers["inhabitants"], )
                    ret *= self.query_exec(rs, query, params)

                blockers = self.delete_lodgement_blockers(rs, lodgement_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.lodgements", lodgement_id)
                self.event_log(rs, const.EventLogCodes.lodgement_deleted,
                               event_id, change_note=lodgement["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement", "block": blockers.keys()})
        return ret

    @access("event")
    def get_grouped_inhabitants(
            self, rs: RequestState, event_id: int,
            lodgement_ids: Optional[Collection[int]] = None,
    ) -> dict[int, dict[int, LodgementInhabitants]]:
        """Group number of inhabitants by lodgement, part and camping mat status."""
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id):
            raise PrivilegeError
        params: list[DatabaseValue_s] = [event_id]
        if lodgement_ids is None:
            condition = "rp.lodgement_id IS NOT NULL"
        else:
            lodgement_ids = affirm_set(vtypes.ID, lodgement_ids)
            condition = "rp.lodgement_id = ANY(%s)"
            params.append(lodgement_ids)
        query = f"""
            SELECT
                lodgement_id, part_id, is_camping_mat AS is_cm,
                COUNT(*) AS num, ARRAY_AGG(rp.registration_id) AS inhabitants
            FROM event.registration_parts AS rp
                JOIN event.event_parts AS ep ON rp.part_id = ep.id
            WHERE ep.event_id = %s AND {condition}
            GROUP BY lodgement_id, part_id, is_camping_mat
        """
        ret: dict[int, dict[int, LodgementInhabitants]]
        ret = collections.defaultdict(
            lambda: collections.defaultdict(LodgementInhabitants))
        for e in self.query_all(rs, query, params):
            if e['is_cm']:
                inhabitants = LodgementInhabitants(camping_mat=tuple(e['inhabitants']))
            else:
                inhabitants = LodgementInhabitants(regular=tuple(e['inhabitants']))
            ret[e['lodgement_id']][e['part_id']] += inhabitants
        return ret

    @access("event")
    def move_lodgements(self, rs: RequestState, group_id: int,
                        target_group_id: Optional[int], delete_group: bool,
                        ) -> DefaultReturnCode:
        """Move lodgements from one group to another or delete them with the group."""
        ret = 1
        with Atomizer(rs):
            group = self.get_lodgement_group(rs, group_id)
            msg = "Snapshot vor Verschieben/Löschen von Unterkünften."
            self.event_keeper_commit(rs, group['event_id'], msg)
            if target_group_id:
                lodgement_ids = self.list_lodgements(rs, group['event_id'], group_id)
                for l_id in xsorted(lodgement_ids):
                    update = {
                        'id': l_id,
                        'group_id': target_group_id,
                    }
                    ret *= self.set_lodgement(rs, update)
            if delete_group:
                cascade = ("lodgements",)
                ret *= self.delete_lodgement_group(rs, group_id, cascade)
            msg = "Verschiebe/Lösche Unterkünfte."
            self.event_keeper_commit(rs, group['event_id'], msg, after_change=True)
        return ret
