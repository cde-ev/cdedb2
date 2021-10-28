#!/usr/bin/env python3

"""
The `EventLodgementBackend` subclasses the `EventBaseBackend` and provides
functionality for managing lodgements and lodgement groups belonging to an event.
"""

from typing import Collection, Dict, Protocol

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    Silencer, access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    cast_fields, read_conditional_write_composer, singularize,
)
from cdedb.backend.event.event_base import EventBaseBackend
from cdedb.common import (
    LODGEMENT_FIELDS, LODGEMENT_GROUP_FIELDS, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, DeletionBlockers, PrivilegeError, PsycoJson, RequestState, n_,
    unwrap,
)
from cdedb.database.connection import Atomizer


class EventLodgementBackend(EventBaseBackend):
    @access("event")
    def list_lodgement_groups(self, rs: RequestState,
                              event_id: int) -> Dict[int, str]:
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
    def get_lodgement_groups(self, rs: RequestState, group_ids: Collection[int]
                             ) -> CdEDBObjectMap:
        """Retrieve data for some lodgement groups.

        All have to be from the same event.
        """
        group_ids = affirm_set(vtypes.ID, group_ids)
        with Atomizer(rs):
            data = self.sql_select(
                rs, "event.lodgement_groups", LODGEMENT_GROUP_FIELDS, group_ids)
            if not data:
                return {}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only lodgement groups from exactly one event allowed!"))
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
        return {e['id']: e for e in data}

    class _GetLodgementGroupProtocol(Protocol):
        def __call__(self, rs: RequestState, group_id: int) -> CdEDBObject: ...
    get_lodgement_group: _GetLodgementGroupProtocol = singularize(
        get_lodgement_groups, "group_ids", "group_id")

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
        def __call__(self, rs: RequestState, data: CdEDBObject
                     ) -> DefaultReturnCode: ...
    rcw_lodgement_group: _RCWLodgementGroupProtocol = read_conditional_write_composer(
        get_lodgement_group, set_lodgement_group, id_param_name='group_id')

    @access("event")
    def create_lodgement_group(self, rs: RequestState,
                               data: CdEDBObject) -> DefaultReturnCode:
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
                               cascade: Collection[str] = None
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
                        for lodgement_id in blockers["lodgements"]:
                            deletor = {
                                "id": lodgement_id,
                                "group_id": None,
                            }
                            ret *= self.set_lodgement(rs, deletor)

                blockers = self.delete_lodgement_group_blockers(rs, group_id)

            if not blockers:
                group = unwrap(self.get_lodgement_groups(rs, (group_id,)))
                ret *= self.sql_delete_one(
                    rs, "event.lodgement_groups", group_id)
                self.event_log(rs, const.EventLogCodes.lodgement_group_deleted,
                               event_id=group['event_id'],
                               change_note=group['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement group", "block": blockers.keys()})
        return ret

    @access("event")
    def list_lodgements(self, rs: RequestState, event_id: int) -> Dict[int, str]:
        """List all lodgements for an event.

        :returns: dict mapping ids to names
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "event.lodgements", ("id", "title"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

    @access("event")
    def get_lodgements(self, rs: RequestState, lodgement_ids: Collection[int]
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
            event_fields = self._get_event_fields(rs, event_id)
            ret = {e['id']: e for e in data}
            for entry in ret.values():
                entry['fields'] = cast_fields(entry['fields'], event_fields)
        return {e['id']: e for e in data}

    class _GetLodgementProtocol(Protocol):
        def __call__(self, rs: RequestState, lodgement_id: int) -> CdEDBObject: ...
    get_lodgement: _GetLodgementProtocol = singularize(
        get_lodgements, "lodgement_ids", "lodgement_id")

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
                    fields=event_fields,
                    association=const.FieldAssociations.lodgement)

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
            vtypes.EventAssociatedFields, fdata, fields=event_fields,
            association=const.FieldAssociations.lodgement)
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
                         cascade: Collection[str] = None) -> DefaultReturnCode:
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
                    params = (blockers["inhabitants"])
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
