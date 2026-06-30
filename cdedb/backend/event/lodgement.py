#!/usr/bin/env python3

"""
The `EventLodgementBackend` subclasses the `EventBaseBackend` and provides
functionality for managing lodgements and lodgement groups belonging to an event.
"""

import abc
import collections
import dataclasses
from collections.abc import Collection, Iterator
from functools import cached_property
from typing import Any, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.backend.common import (
    Silencer,
    access,
    affirm_validation as affirm,
    singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    PsycoJson,
    RequestState,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.privileges import (
    EventPrivileges,
    is_privileged_event as is_privileged,
)
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.database.query import DatabaseValue_s


@dataclasses.dataclass(frozen=True)
class LodgementInhabitants:
    """Small helper class to store and add inhabitants of a lodgement."""

    regular: list[CdEDBObject] = dataclasses.field(default_factory=list)
    camping_mat: list[CdEDBObject] = dataclasses.field(default_factory=list)

    @cached_property
    def all(self) -> list[CdEDBObject]:
        return self.regular + self.camping_mat

    def __add__(self, other: Any) -> "LodgementInhabitants":
        if not isinstance(other, LodgementInhabitants):
            return NotImplemented
        return self.__class__(
            self.regular + other.regular, self.camping_mat + other.camping_mat
        )

    def __iter__(self) -> Iterator[list[CdEDBObject]]:
        """Enable tuple unpacking."""
        return iter((self.regular, self.camping_mat))


class EventLodgementBackend(EventBaseBackend, abc.ABC):
    def _get_event_id_from_group_id(self, rs: RequestState, group_id: int) -> int:
        q = f"SELECT event_id FROM {models.LodgementGroup.database_table} WHERE id = %s"
        event_id = unwrap(self.query_one(rs, q, [group_id]))
        if event_id is None:
            raise KeyError(
                "Unknown lodgement group: %(group_id)s", {"group_id": group_id}
            )
        return event_id

    @access("event")
    def get_lodgement_groups(
        self, rs: RequestState, event_id: int
    ) -> models.CdEDataclassMap[models.LodgementGroup]:
        event_id = affirm(vtypes.ID, event_id)
        with Atomizer(rs):
            group_data = self.query_all(
                rs, *models.LodgementGroup.get_select_query((event_id,))
            )
        return models.LodgementGroup.many_from_database(group_data)

    @access("event")
    def set_lodgement_group(
        self, rs: RequestState, group_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Update some keys of a lodgement group."""
        group_id = affirm(vtypes.ID, group_id)
        data = affirm(models.LodgementGroup, data)
        data['id'] = group_id
        ret = 1
        with Atomizer(rs):
            event_id = self._get_event_id_from_group_id(rs, group_id)
            if not is_privileged(
                rs, EventPrivileges.lodgements_write, event_id=event_id
            ):
                raise PrivilegeError(n_("Not privileged to modify lodgement groups."))
            self.assert_lock(rs, event_id=event_id)
            current = self.get_lodgement_groups(rs, event_id)[group_id]

            # Do the actual work:
            if data != current.as_dict():
                ret *= self.sql_update(rs, models.LodgementGroup.database_table, data)
                self.event_log(
                    rs,
                    const.EventLogCodes.lodgement_group_changed,
                    event_id,
                    change_note=data.get("title") or current.title,
                )

        return ret

    @access("event")
    def delete_lodgement_group_blockers(
        self, rs: RequestState, group_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a lodgement group from being deleted.

        Possible blockers:

        * lodgements: A lodgement that is part of this lodgement group.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        group_id = affirm(vtypes.ID, group_id)
        blockers = {}

        lodgements = self.sql_select(
            rs,
            models.Lodgement.database_table,
            ("id",),
            (group_id,),
            entity_key="group_id",
        )
        if lodgements:
            blockers["lodgements"] = [e["id"] for e in lodgements]

        return blockers

    @access("event")
    def delete_lodgement_group(
        self, rs: RequestState, group_id: int, cascade: Collection[str] | None = None
    ) -> DefaultReturnCode:
        """Delete a lodgement group.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        group_id = affirm(vtypes.ID, group_id)
        event_id = self._get_event_id_from_group_id(rs, group_id)
        if not is_privileged(rs, EventPrivileges.lodgements_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged to modify lodgement groups."))

        blockers = self.delete_lodgement_group_blockers(rs, group_id)
        if not cascade:
            cascade = set()
        cascade = affirm(set[str], cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "lodgement group",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "lodgements" in cascade:
                    with Silencer(rs):
                        lodgement_cascade = ("inhabitants",)
                        for lodgement_id in blockers["lodgements"]:
                            ret *= self.delete_lodgement(
                                rs, lodgement_id, lodgement_cascade
                            )

                blockers = self.delete_lodgement_group_blockers(rs, group_id)

            if not blockers:
                group = self.get_lodgement_groups(rs, event_id)[group_id]
                ret *= self.sql_delete_one(rs, "event.lodgement_groups", group_id)
                self.event_log(
                    rs,
                    const.EventLogCodes.lodgement_group_deleted,
                    event_id=event_id,
                    change_note=group.title,
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement group", "block": blockers.keys()},
                )
        return ret

    @access("event")
    def list_lodgements(
        self, rs: RequestState, event_id: int, group_id: int | None = None
    ) -> dict[int, str]:
        """List all lodgements for an event.

        :param group_id: If given, limit to lodgements in this group.
        :returns: dict mapping ids to names
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(rs, EventPrivileges.lodgements_read, event_id=event_id):
            raise PrivilegeError(n_("Not privileged."))
        if group_id:
            group_data = self.sql_select_one(
                rs, "event.lodgement_groups", ("event_id", "title"), group_id
            )
            if not group_data or group_data['event_id'] != event_id:
                raise ValueError(n_("Invalid lodgement group."))
            entities = (group_id,)
            entity_key = 'group_id'
        else:
            entities = (event_id,)
            entity_key = 'event_id'

        data = self.sql_select(
            rs,
            "event.lodgements",
            ("id", "title"),
            entities=entities,
            entity_key=entity_key,
        )
        return {e['id']: e['title'] for e in data}

    @access("event")
    def new_get_lodgements(
        self,
        rs: RequestState,
        lodgement_ids: Collection[int],
        *,
        _event: models.Event | None = None,
    ) -> models.CdEDataclassMap[models.Lodgement]:
        lodgement_ids = affirm(set[vtypes.ID], lodgement_ids)
        with Atomizer(rs):
            lodgement_data = self.query_all(
                rs, *models.Lodgement.get_select_query(lodgement_ids)
            )
            if not lodgement_data:
                return {}
            events = {e['event_id'] for e in lodgement_data}
            if len(events) > 1:
                raise ValueError(n_("Only lodgements from exactly one event allowed!"))
            event_id = unwrap(events)
            if not is_privileged(
                rs, EventPrivileges.lodgements_read, event_id=event_id
            ):
                raise PrivilegeError(n_("Not privileged."))
            groups = self.get_lodgement_groups(rs, event_id)
            if _event:
                event = _event
            else:
                event = self.get_event(rs, event_id)
        return models.Lodgement.many_from_database([
            {
                **lodge,
                'group': groups[lodge['group_id']],
                'event': event,
            }
            for lodge in lodgement_data
        ])

    class _NewGetLodgementProtocol(Protocol):
        def __call__(self, rs: RequestState, lodgement_id: int) -> models.Lodgement: ...

    new_get_lodgement: _NewGetLodgementProtocol = singularize(
        new_get_lodgements, "lodgement_ids", "lodgement_id"
    )

    @access("event")
    def set_lodgement(
        self, rs: RequestState, lodgement_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Update some keys of a lodgement."""
        lodgement_id = affirm(vtypes.ID, lodgement_id)
        with Atomizer(rs):
            current = self.new_get_lodgement(rs, lodgement_id)
            groups = self.get_lodgement_groups(rs, current.event_id)
            data = affirm(models.Lodgement, data, event=current.event, groups=groups)
            if not is_privileged(
                rs, EventPrivileges.lodgements_write, event_id=current.event_id
            ):
                raise PrivilegeError(n_("Not privileged to modify lodgements."))
            self.assert_lock(rs, event_id=current.event_id)

            # now we get to do the actual work
            ret = 1
            changed = False
            current_dict = current.as_dict()
            lodgement_fields = set(models.Lodgement.database_fields()) - {"fields"}
            changed_data = {
                k: v
                for k, v in data.items()
                if k in lodgement_fields and v != current_dict[k]
            }
            if changed_data:
                changed_data["id"] = current.id
                ret *= self.sql_update(
                    rs, models.Lodgement.database_table, changed_data
                )
                changed = True

            if 'fields' in data:
                # delayed validation since we need more info
                fdata = affirm(
                    vtypes.EventAssociatedFields,
                    data['fields'],
                    event=current.event,
                    association=const.FieldAssociations.lodgement,
                )
                fdata = {
                    k: v
                    for k, v in fdata.items()
                    if k not in current.fields or v != current.fields[k]
                }
                if fdata:
                    fupdate = {"id": current.id, "fields": fdata}
                    ret *= self.sql_json_inplace_update(
                        rs, models.Lodgement.database_table, fupdate
                    )
                    changed = True

            if changed:
                if not data.get("title") or data["title"] == current.title:
                    change_note = current.title
                else:
                    change_note = f"{current.title} -> {data['title']}"
                self.event_log(
                    rs,
                    const.EventLogCodes.lodgement_changed,
                    current.event_id,
                    change_note=change_note,
                )

        return ret

    @access("event")
    def create_lodgement(
        self, rs: RequestState, event_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Make a new lodgement."""
        event_id = affirm(vtypes.ID, event_id)

        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            groups = self.get_lodgement_groups(rs, event_id)
            data = affirm(
                models.Lodgement, data, event=event, groups=groups, creation=True
            )
            self.assert_lock(rs, event_id=event_id)
            if not is_privileged(rs, EventPrivileges.lodgements_write, event_id):
                raise PrivilegeError(n_("Not privileged to modify lodgements."))

            data["fields"] = PsycoJson(data.get("fields", {}))
            data["event_id"] = event_id
            new_id = self.sql_insert(rs, models.Lodgement.database_table, data)
            self.event_log(
                rs,
                const.EventLogCodes.lodgement_created,
                event_id,
                change_note=data['title'],
            )
        return new_id

    @access("event")
    def delete_lodgement_blockers(
        self, rs: RequestState, lodgement_id: int
    ) -> DeletionBlockers:
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
            rs,
            "event.registration_parts",
            ("id",),
            (lodgement_id,),
            entity_key="lodgement_id",
        )
        if inhabitants:
            blockers["inhabitants"] = [e["id"] for e in inhabitants]

        return blockers

    @access("event")
    def delete_lodgement(
        self,
        rs: RequestState,
        lodgement_id: int,
        cascade: Collection[str] | None = None,
    ) -> DefaultReturnCode:
        """Delete a lodgement.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        lodgement_id = affirm(vtypes.ID, lodgement_id)
        lodgement = self.new_get_lodgement(rs, lodgement_id)
        event_id = lodgement.event_id
        if not is_privileged(rs, EventPrivileges.lodgements_write, event_id=event_id):
            raise PrivilegeError(n_("Not privileged to modify lodgements."))
        self.assert_lock(rs, event_id=event_id)

        blockers = self.delete_lodgement_blockers(rs, lodgement_id)
        if not cascade:
            cascade = set()
        cascade = affirm(set[str], cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "lodgement",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "inhabitants" in cascade:
                    query = """
                        UPDATE event.registration_parts
                        SET lodgement_id = NULL
                        WHERE id = ANY(%s)
                    """
                    params = (blockers["inhabitants"],)
                    ret *= self.query_exec(rs, query, params)

                blockers = self.delete_lodgement_blockers(rs, lodgement_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, models.Lodgement.database_table, lodgement_id
                )
                self.event_log(
                    rs,
                    const.EventLogCodes.lodgement_deleted,
                    event_id,
                    change_note=lodgement.title,
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement", "block": blockers.keys()},
                )
        return ret

    @access("event")
    def get_grouped_inhabitants(
        self,
        rs: RequestState,
        event_id: int,
        lodgement_ids: Collection[int] | None = None,
        involved: bool | None = None,
        _registrations: CdEDBObjectMap | None = None,
    ) -> dict[int, dict[int, LodgementInhabitants]]:
        """Group number of inhabitants by lodgement, part and camping mat status."""
        event_id = affirm(vtypes.ID, event_id)
        involved = affirm(bool | None, involved)
        _registrations = affirm(CdEDBObjectMap | None, _registrations)

        if not is_privileged(
            rs,
            EventPrivileges.lodgements_read | EventPrivileges.registrations_stats,
            event_id=event_id,
        ):
            raise PrivilegeError

        params: list[DatabaseValue_s] = [event_id]
        if lodgement_ids is None:
            condition = "rp.lodgement_id IS NOT NULL"
        else:
            lodgement_ids = affirm(set[vtypes.ID], lodgement_ids)
            condition = "rp.lodgement_id = ANY(%s)"
            params.append(lodgement_ids)
        if involved is not None:
            params.append(const.RegistrationPartStati.involved_states())
            if involved:
                condition += " AND rp.status = ANY(%s)"
            else:
                condition += " AND NOT(rp.status = ANY(%s))"

        if _registrations is None:
            # Retrieve all registrations.
            query = f"""
                SELECT registration_id
                FROM event.registration_parts rp
                    JOIN event.event_parts ep ON rp.part_id = ep.id
                WHERE ep.event_id = %s AND {condition}
            """
            registration_ids = {
                e['registration_id'] for e in self.query_all(rs, query, params)
            }
            registrations = self.get_registrations(rs, registration_ids)  # type: ignore[attr-defined]
        else:
            registrations = _registrations

        # Add personas to allow for simple display and sorting later
        personas = self.core.get_personas(
            rs, [reg['persona_id'] for reg in registrations.values()]
        )
        for reg in registrations.values():
            reg['persona'] = personas[reg['persona_id']]

        # Retrieve grouped registration ids.
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
            lambda: collections.defaultdict(LodgementInhabitants)
        )
        for e in self.query_all(rs, query, params):
            if e['is_cm']:
                inhabitants = LodgementInhabitants(
                    camping_mat=[registrations[reg_id] for reg_id in e['inhabitants']],
                )
            else:
                inhabitants = LodgementInhabitants(
                    regular=[registrations[reg_id] for reg_id in e['inhabitants']],
                )
            ret[e['lodgement_id']][e['part_id']] += inhabitants
        return ret

    @access("event")
    def move_lodgements(
        self,
        rs: RequestState,
        group_id: int,
        target_group_id: int | None,
        delete_group: bool,
    ) -> DefaultReturnCode:
        """Move lodgements from one group to another or delete them with the group."""
        ret = 1
        with Atomizer(rs):
            event_id = self._get_event_id_from_group_id(rs, group_id)
            msg = "Snapshot vor Verschieben/Löschen von Unterkünften."
            self.event_keeper_commit(rs, event_id, msg)
            if target_group_id:
                lodgement_ids = self.list_lodgements(rs, event_id, group_id)
                for l_id in xsorted(lodgement_ids):
                    update = {'group_id': target_group_id}
                    ret *= self.set_lodgement(rs, l_id, update)
            if delete_group:
                cascade = ("lodgements",)
                ret *= self.delete_lodgement_group(rs, group_id, cascade)
            msg = "Verschiebe/Lösche Unterkünfte."
            self.event_keeper_commit(rs, event_id, msg, after_change=True)
        return ret
