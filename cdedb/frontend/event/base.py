#!/usr/bin/env python3

"""
The `EventBaseFrontend` provides some basic frontend functionality for the event realm.

This implements the `AbstractUserFrontend` and overrides the `AbstractFrontend.render`
method to do some event specific preparation before rendering templates.

This offers both a global and a event-specific event log.

In addition the `EventBaseFrontend` provides a few helper methods that are used across
multiple of its subclasses.

The base aswell as all its subclasses (the event frontend mixins) combine together to
become the full `EventFrontend` in this modules `__init__.py`.
"""

import abc
import functools
import operator
import typing
from collections import OrderedDict
from collections.abc import Callable, Collection
from typing import Any, cast

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models_core
import cdedb.models.event as models
import cdedb.models.event.constraint_violations as models_cv
from cdedb.backend.event.lodgement import LodgementInhabitants
from cdedb.common import (
    EVENT_SCHEMA_VERSION,
    CdEDBObject,
    CdEDBObjectMap,
    Notification,
    RequestState,
    get_mandatory_form_fields,
    merge_dicts,
    unwrap,
)
from cdedb.common.i18n import get_localized_country_codes
from cdedb.common.n_ import n_
from cdedb.common.privileges import (
    EventPrivileges,
    is_event_access_limited,
    is_privileged_event,
)
from cdedb.common.query import QueryScope
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.common.sorting import EntitySorter, KeyFunction, Sortkey, xsorted
from cdedb.common.validation.validate import PERSONA_FULL_CREATION, filter_none
from cdedb.filter import enum_entries_filter, keydictsort_filter
from cdedb.frontend.common import (
    AbstractUserFrontend,
    REQUESTdata,
    REQUESTdatadict,
    access,
    periodic,
    request_extractor,
)
from cdedb.frontend.event.lodgement_wishes import detect_lodgement_wishes
from cdedb.models.common import CdEDataclassMap


class CourseChoiceParams(typing.TypedDict):
    courses: models.CourseMap
    courses_per_track: dict[int, set[int]]
    all_courses_per_track: dict[int, set[int]]
    courses_per_track_group: dict[int, set[int]]
    all_courses_per_track_group: dict[int, set[int]]
    simple_tracks: set[int]
    choice_objects: list[models.CourseChoiceObject]
    sync_track_groups: dict[int, models.SyncTrackGroup]
    track_group_map: dict[int, int | None]
    ccos_per_part: dict[int, list[str]]
    parts_per_track_group_per_course: dict[vtypes.CourseID, dict[int, set[vtypes.ID]]]


class ParticipantListData(typing.TypedDict):
    registrations: models.RegistrationMap
    ordered: list[vtypes.RegistrationID]
    reg_counts: dict[int | None, int]
    personas: CdEDataclassMap[models_core.EventPersona]
    courses: models.CourseMap
    parts: CdEDataclassMap[models.EventPart]


class UserLodgementWishes(typing.TypedDict):
    field: models.EventField | None
    wished_personas: list[models_core.EventPersona]
    problems: list[Notification]


class ConstraintViolationsData(typing.TypedDict):
    violations: models_cv.ViolationList
    all_registrations: models.RegistrationMap
    registrations: models.RegistrationMap
    personas: CdEDataclassMap[models_core.EventPersona]
    all_courses: models.CourseMap
    courses: models.CourseMap
    choice_stats: models.ChoiceStats
    attendee_stats: models.AttendeeStats
    all_lodgements: models.LodgementMap
    lodgements: models.LodgementMap
    involved_inhabitants: dict[vtypes.LodgementID, dict[int, LodgementInhabitants]]
    uninvolved_inhabitants: dict[vtypes.LodgementID, dict[int, LodgementInhabitants]]


def event_guard[F: Callable[..., Any]](
    *required_privileges: EventPrivileges,
) -> Callable[[F], F]:
    """
    This decorator checks the users privilege regarding the contextual event,
    taken from rs.ambience['event'].

    Can take any number of privileges, any of which is sufficient.
    Multiple privileges can be combined to instead require the user to have all
    of these privileges.

    This also blocks the use of write privileges if the event is locked.
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(
            obj: "EventBaseFrontend", rs: RequestState, *args: Any, **kwargs: Any
        ) -> Any:
            if not obj.is_privileged(
                rs, *required_privileges, event_id=rs.ambience['event'].id
            ):
                if obj.is_locked(rs.ambience['event']):
                    raise werkzeug.exceptions.Forbidden(n_("This event is locked."))
                raise werkzeug.exceptions.Forbidden(
                    n_("This page can only be accessed by orgas.")
                )
            return fun(obj, rs, *args, **kwargs)

        new_fun.event_required_privileges = required_privileges  # type: ignore[attr-defined]

        return cast(F, new_fun)

    return wrap


def event_associated_fields_extractor(
    rs: RequestState,
    event: models.Event,
    association: const.FieldAssociations,
    field_ids: Collection[int] | None = None,
    *,
    filter_params: (
        Callable[[vtypes.MutableTypeMapping], vtypes.MutableTypeMapping] | None
    ) = None,
    suffix: str = "",
) -> CdEDBObject:
    """
    Given an event, extract inputs for all event fields of the given association.

    :param field_ids: Used to limit the extracted fields based on their id.
    :param filter_params: Used to limit the extracted fields via a callable that
        takes the fields params and returns a narrowed down set of params.
        This is utilized by the "multiedit" to limit the extracted fields based
        on additional user input.
    """
    fields = [
        field
        for field in event.fields.values()
        if field.association == association
        and (field_ids is None or field.id in field_ids)
    ]
    field_params = {
        f"{field.request_name}{suffix}": field.get_validator() for field in fields
    }
    if filter_params:
        field_params = filter_params(field_params)
    raw_fields = request_extractor(rs, field_params)
    return {
        field.field_name: raw_fields.get(f"{field.request_name}{suffix}")
        for field in fields
        if f"{field.request_name}{suffix}" in field_params
    }


def event_associated_fields_multi_extractor(
    rs: RequestState,
    event: models.Event,
    association: const.FieldAssociations,
    entity_ids: Collection[int],
    field_id: int | None = None,
) -> CdEDBObjectMap:
    """Extract fields multiple times, denoted by suffixed in form of the given ids."""
    return {
        entity_id: event_associated_fields_extractor(
            rs,
            event,
            association,
            {field_id} if field_id else None,
            suffix=str(entity_id),
        )
        for entity_id in entity_ids
    }


def event_associated_fields_to_request(
    event: models.Event, entity: models.Course | models.Lodgement | CdEDBObject
) -> CdEDBObject:
    """
    Given an entity, prepare the associated field data to be put into a form.

    This is the inverse of `event_associated_fields_extractor`.
    """
    fields = lambda e: e.fields if hasattr(e, 'fields') else e.get('fields', {})
    return {
        field.request_name: fields(entity)[field.field_name]
        for field in event.fields.values()
        if field.field_name in fields(entity)
    }


def event_associated_fields_to_request_multi(
    event: models.Event,
    entities: (
        dict[vtypes.ID, CdEDBObject]
        | models.CdEDataclassMap[models.Course | models.Lodgement]
    ),
) -> list[CdEDBObject]:
    """
    Given a list of entities, prepare all of their fields to be put into a single form.

    This is relized by suffixing the id.
    This is the inverse of `event_associated_fields_multi_extractor`.
    """
    return [
        {
            f"{k}{entity_id}": v
            for k, v in event_associated_fields_to_request(event, entity).items()
        }
        for entity_id, entity in entities.items()
    ]


class EventBaseFrontend(AbstractUserFrontend):
    """Provide the base for event frontend mixins."""

    realm = "event"

    def render(
        self,
        rs: RequestState,
        templatename: str,
        params: CdEDBObject | None = None,
        mandatory_fields: Collection[str] | None = None,
    ) -> Response:
        def is_privileged(
            required_privilege: EventPrivileges = EventPrivileges.basic_read,
            *,
            event_id: vtypes.EventID | None = None,
        ) -> bool:
            return self.is_privileged(rs, required_privilege, event_id=event_id)

        def is_privileged_for(
            endpoint: str,
            *,
            event_id: vtypes.EventID | None = None,
            admin_view_to_consider: str | None = "event_orga",
        ) -> bool:
            endpoint = endpoint.removeprefix(f"{self.realm}/")
            privileges = getattr(getattr(self, endpoint), "event_required_privileges")

            if event_id is None and 'event' in rs.ambience:
                event_id = rs.ambience['event'].id

            is_privileged = self.is_privileged(rs, *privileges, event_id=event_id)
            if (
                event_id in rs.user.orga | rs.user.caretaker | rs.user.checkin_helper
                or admin_view_to_consider is None
                or admin_view_to_consider not in rs.user.available_admin_views
            ):
                return is_privileged
            return is_privileged and admin_view_to_consider in rs.user.admin_views

        if 'event' in rs.ambience:
            event_id = rs.ambience['event'].id
            orga_view = (
                event_id in rs.user.orga | rs.user.caretaker | rs.user.checkin_helper
                or 'event_orga' in rs.user.admin_views
            )
            access_is_limited = orga_view and is_event_access_limited(event_id)
        else:
            orga_view = None
            access_is_limited = None

        params = params or {}
        if 'event' in rs.ambience:
            params['is_locked'] = self.is_locked(rs.ambience['event'])
            if rs.user.persona_id and "event" in rs.user.roles:
                reg_list = self.eventproxy.list_registrations(
                    rs, rs.ambience['event'].id, rs.user.persona_id
                )
                params['is_registered'] = bool(reg_list)
                params['is_participant'] = False
                if params['is_registered']:
                    registration = self.eventproxy.get_registration(
                        rs, unwrap(reg_list.keys())
                    )
                    if any(
                        part['status'] == const.RegistrationPartStati.participant
                        for part in registration['parts'].values()
                    ):
                        params['is_participant'] = True
                    params["is_instructor"] = rs.ambience["event"].tracks and any(
                        rt["course_instructor"]
                        for rt in registration['tracks'].values()
                    )

        all_events = self.eventproxy.get_events(rs, self.eventproxy.list_events(rs))
        event_options = [
            {
                'title': event.title,
                'shortname': event.shortname,
                'id': event.id,
            }
            for event in xsorted(all_events.values(), reverse=True)
        ]
        params['all_events'] = all_events
        params['event_options'] = event_options

        params['is_privileged'] = is_privileged
        params['is_privileged_for'] = is_privileged_for
        params['orga_view'] = orga_view
        params['access_is_limited'] = access_is_limited

        params['ViolationFormat'] = models_cv.ViolationFormat
        params["EVENT_ADMIN_ADDRESS"] = self.conf["EVENT_ADMIN_ADDRESS"]

        return super().render(
            rs, templatename, params=params, mandatory_fields=mandatory_fields
        )

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def is_privileged(
        self,
        rs: RequestState,
        *required_privileges: EventPrivileges,
        event_id: vtypes.EventID | None = None,
    ) -> bool:
        """
        Check the users privilege regarding the contextual event, given via event_id or
        taken from rs.ambience['event'].

        Can take any number of privileges, any of which is sufficient.
        Multiple privileges can be combined to instead require the user to have all
        of these privileges.

        Returns False if the operation is blocked by the event being locked, regardless
        of whether the user has sufficient privileges.
        """
        if not event_id:
            if not rs.ambience.get('event'):
                raise RuntimeError(n_("No event context given"))
            event_id = rs.ambience['event'].id
        if event := rs.ambience.get('event'):
            is_locked = event.is_locked
        else:
            is_locked = self.eventproxy.is_locked(rs, event_id=event_id)

        # Only block access if all given privileges are writing.
        if is_locked and all(
            required_privilege & EventPrivileges.all_write
            for required_privilege in required_privileges
        ):
            return False
        return any(
            is_privileged_event(rs, required_privilege, event_id)
            for required_privilege in required_privileges
        )

    def is_locked(self, event: models.Event) -> bool:
        """Shorthand to determine locking state of an event."""
        return event.is_locked and not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]

    @access("core_admin", "event_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return self.render(
            rs,
            "user/create_user",
            {},
            get_mandatory_form_fields(filter_none(PERSONA_FULL_CREATION['event'])),
        )

    @access("core_admin", "event_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_CREATION['event']))
    def create_user(self, rs: RequestState, data: CdEDBObject) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("core_admin", "event_admin")
    @REQUESTdata("download", "is_search")
    def user_search(
        self, rs: RequestState, download: str | None, is_search: bool
    ) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices: dict[str, OrderedDict[Any, str]] = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))
            ),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext,
                )
            ),
            'country': OrderedDict(get_localized_country_codes(rs)),
        }
        return self.generic_user_search(
            rs,
            download,
            is_search,
            QueryScope.all_event_users,
            self.eventproxy.submit_general_query,
            choices=choices,
        )

    @access("event")
    @REQUESTdata("part_id", "sortkey", "reverse")
    def participant_list(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        part_id: vtypes.ID | None = None,
        sortkey: str | None = "persona",
        reverse: bool = False,
    ) -> Response:
        """List participants of an event"""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not self.is_privileged(rs, EventPrivileges.participant_list):
            assert rs.user.persona_id is not None
            if not self.eventproxy.check_registration_status(
                rs,
                rs.user.persona_id,
                event_id,
                {const.RegistrationPartStati.participant},
            ):
                rs.notify('warning', n_("You do not participate at this event."))
                return self.redirect(rs, "event/show_event")
            reg_list = self.eventproxy.list_registrations(
                rs, event_id, rs.user.persona_id
            )
            registration = self.eventproxy.get_registration(rs, unwrap(reg_list.keys()))
            list_consent = registration['list_consent']
        else:
            list_consent = True
        EP = EventPrivileges
        if not self.is_privileged(rs, EP.registrations_read, EP.checkin):
            if not rs.ambience['event'].is_participant_list_visible:
                rs.notify("error", n_("Participant list not published yet."))
                return self.redirect(rs, "event/show_event")

        if part_id:
            part_ids: Collection[int] = [part_id]
        else:
            part_ids = rs.ambience['event'].parts.keys()

        if len(rs.ambience['event'].parts) == 1:
            part_id = unwrap(rs.ambience['event'].parts).id
        return self.render(
            rs,
            "base/participant_list",
            {
                'part_id': part_id,
                'list_consent': list_consent,
                'last_sortkey': sortkey,
                'last_reverse': reverse,
                **self._get_participant_list_data(
                    rs,
                    event_id,
                    part_ids,
                    include_total_count=True,
                    sort_by=sortkey or "persona",
                    reverse=reverse,
                ),
            },
        )

    def _get_participant_list_data(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        part_ids: Collection[int] = (),
        orga_list: bool = False,
        include_total_count: bool = False,
        sort_by: str = "persona",
        reverse: bool = False,
    ) -> ParticipantListData:
        """This provides data for download and online participant list.

        It filters out the participants which have not given list_consent.

        This is un-inlined so download_participant_list can use this
        as well."""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_participants(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        reg_counts = self.eventproxy.get_num_registrations_by_part(
            rs,
            event_id,
            (const.RegistrationPartStati.participant,),
            include_total=include_total_count,
        )

        if not part_ids:
            part_ids = rs.ambience['event'].parts.keys()
        if any(anid not in rs.ambience['event'].parts for anid in part_ids):
            raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
        if orga_list and not self.is_privileged(rs, EventPrivileges.registrations_read):
            raise PermissionError
        parts = {anid: rs.ambience['event'].parts[anid] for anid in part_ids}

        def check(reg: CdEDBObject) -> bool:
            if not reg['list_consent'] and not orga_list:
                return False
            participant = const.RegistrationPartStati.participant
            return any(
                reg['parts'][part_id]['status'] == participant for part_id in parts
            )

        registrations = {
            reg_id: reg for reg_id, reg in registrations.items() if check(reg)
        }
        persona_ids = tuple(e['persona_id'] for e in registrations.values())
        personas = self.coreproxy.get_event_users(rs, persona_ids, event_id)

        all_sorters: dict[str, KeyFunction] = {
            "given_names": EntitySorter.make_persona_sorter(family_name_first=False),
            "family_name": EntitySorter.make_persona_sorter(family_name_first=True),
            "email": EntitySorter.email,
            "address": EntitySorter.make_address_sorter(
                rs.gettext, self.conf["DEFAULT_COUNTRY"]
            ),
            # "course": use dataclass sorting,
            # the default sorting is, in contrast to EntitySorter.persona, by forename
            "persona": EntitySorter.make_persona_sorter(family_name_first=False),
        }

        def get_sortkey(anid: vtypes.RegistrationID) -> Sortkey:
            sortkey: Sortkey = tuple()
            registration = registrations[anid]
            persona = personas[registration['persona_id']].as_dict()
            if sort_by == "course":
                if not len(part_ids) == 1:
                    raise werkzeug.exceptions.BadRequest(
                        n_("Only one part id allowed.")
                    )
                part_id = unwrap(part_ids)
                for track in parts[part_id].tracks.values():
                    if course_id := registration['tracks'][track.id]['course_id']:
                        sortkey += courses[course_id].get_sortkey()
                    else:
                        sortkey += ("0", "", "")
            else:
                sorter = all_sorters.get(sort_by, all_sorters["persona"])
                sortkey += sorter(persona)
            sortkey += all_sorters["persona"](persona)
            return sortkey

        ordered = xsorted(registrations.keys(), reverse=reverse, key=get_sortkey)
        return ParticipantListData(
            courses=courses,
            registrations=registrations,
            personas=personas,
            ordered=ordered,
            parts=parts,
            reg_counts=reg_counts,
        )

    def _get_user_lodgement_wishes(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> UserLodgementWishes | None:
        assert rs.user.persona_id is not None
        if not (
            rs.ambience['event'].is_participant_list_visible
            and rs.ambience['event'].lodge_field
            and self.eventproxy.check_registration_status(
                rs,
                rs.user.persona_id,
                event_id,
                [const.RegistrationPartStati.participant],
            )
        ):
            return None

        registration_id = unwrap(
            self.eventproxy.list_registrations(rs, event_id, rs.user.persona_id).keys()
        )
        registration = self.eventproxy.get_registration(rs, registration_id)
        wished_personas: list[models_core.EventPersona]
        problems: list[Notification]
        if registration['list_consent']:
            data = self._get_participant_list_data(rs, event_id)
            wishes, problems = detect_lodgement_wishes(
                data['registrations'],
                data['personas'],
                rs.ambience['event'],
                restrict_part_id=None,
                restrict_registration_id=registration_id,
                check_edges=False,
            )
            # Ordered list of wished personas
            wished_personas = xsorted([
                data['personas'][data['registrations'][wish.wished]['persona_id']]
                for wish in wishes
            ])
        else:
            msg = n_(
                "You can not access the Participant List as you have not agreed to"
                " have your own data sent to other participants before the event."
            )
            wished_personas = []
            problems = [("error", msg, {})]
        return UserLodgementWishes(
            field=rs.ambience['event'].lodge_field,
            wished_personas=wished_personas,
            problems=problems,
        )

    @access("event")
    def participant_info(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Display the `participant_info`, accessible only to participants."""
        if not self.is_privileged(rs, EventPrivileges.basic_read):
            assert rs.user.persona_id is not None
            if not self.eventproxy.check_registration_status(
                rs,
                rs.user.persona_id,
                event_id,
                {const.RegistrationPartStati.participant},
            ):
                rs.notify('warning', n_("You do not participate at this event."))
                return self.redirect(rs, "event/show_event")
        return self.render(rs, "base/participant_info")

    def extract_questionnaire_fields(
        self, rs: RequestState, kind: const.QuestionnaireUsages
    ) -> CdEDBObject:
        """Extract questionnaire inputs."""
        questionnaire = self.eventproxy.get_all_questionnaires(
            rs, rs.ambience["event"].id
        )[kind]
        field_ids = {
            entry.field_id for entry in questionnaire.field_rows if not entry.readonly
        }
        return event_associated_fields_extractor(
            rs, rs.ambience["event"], const.FieldAssociations.registration, field_ids
        )

    @staticmethod
    def calculate_groups(
        entity_ids: Collection[int],
        event: models.Event,
        registrations: models.RegistrationMap,
        key: str,
        personas: CdEDBObjectMap | None = None,
        instructors: bool = True,
        only_present: bool = True,
        only_involved: bool = True,
    ) -> dict[tuple[int, int], list[vtypes.RegistrationID]]:
        """Determine inhabitants/attendees of lodgements/courses.

        This has to take care only to select registrations which are
        actually present (and not cancelled or such).

        :param key: one of lodgement_id or course_id, signalling what to do
        :param personas: If provided this is used to sort the resulting
          lists by name, so that the can be displayed sorted.
        :param instructors: Include instructors of courses. No effect for
          lodgements.
        :param only_present: Exclude personas which are not present at the event in the
          specified event part.
        :param only_involved: Exclude personas which are not involved in specified event
          part at all.
        """
        tracks = event.tracks
        if key == "course_id":
            aspect = 'tracks'
        elif key == "lodgement_id":
            aspect = 'parts'
        else:
            raise ValueError(n_("Invalid key. Expected 'course_id' or 'lodgement_id"))

        def _check_belonging(
            entity_id: int, sub_id: int, reg_id: vtypes.RegistrationID
        ) -> bool:
            """The actual check, un-inlined."""
            instance: CdEDBObject = registrations[reg_id][aspect][sub_id]
            if aspect == 'parts':
                part: CdEDBObject = instance
            elif aspect == 'tracks':
                part = registrations[reg_id]['parts'][tracks[sub_id].part_id]
                # TODO remove when migrating lodgements to dataclasses here
                if isinstance(instance, models.EventDataclass):
                    instance = instance.as_dict()
            else:
                raise RuntimeError("impossible.")
            ret = (
                instance[key] == entity_id
                and (part['status'].is_present() or not only_present)
                and (part['status'].is_involved() or not only_involved)
            )
            if (
                ret
                and key == "course_id"
                and not instructors
                and instance['course_instructor'] == entity_id
            ):
                ret = False
            return ret

        if personas is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]
            )
        if aspect == 'tracks':
            sub_ids: Collection[int] = tracks.keys()
        elif aspect == 'parts':
            sub_ids = event.parts.keys()
        else:
            raise RuntimeError(n_("Impossible."))
        return {
            (entity_id, sub_id): xsorted(
                (
                    registration_id
                    for registration_id in registrations
                    if _check_belonging(entity_id, sub_id, registration_id)
                ),
                key=sorter,
            )
            for entity_id in entity_ids
            for sub_id in sub_ids
        }

    @abc.abstractmethod
    def get_course_choice_params(
        self, rs: RequestState, event_id: vtypes.EventID, orga: bool = True
    ) -> CourseChoiceParams: ...

    @abc.abstractmethod
    def get_course_stats(
        self,
        rs: RequestState,
        *,
        event: models.Event,
        registrations: models.RegistrationMap,
        course_ids: Collection[vtypes.CourseID] | None = None,
    ) -> tuple[models.ChoiceStats, models.AttendeeStats]: ...

    def get_constraint_violations(
        self,
        rs: RequestState,
        event: models.Event,
        *,
        registration_id: vtypes.RegistrationID | None = vtypes.RegistrationID(
            vtypes.ID(-1)
        ),
        course_id: vtypes.CourseID | None = vtypes.CourseID(vtypes.ID(-1)),
        lodgement_id: int | None = -1,
    ) -> ConstraintViolationsData:
        """
        Check for violations.

        :param registration_id: Can be a single id to only consider that registrations.
            Can also be `-1` to check no registrations at all. Alternatively this can
            be `None` in order to check all existing registrations.
        :param course_id: Same as `registration_id`.
        :return: A collection of data pertaining to the constraint violations.
        """
        # Retrieve registrations.
        all_registrations = self.eventproxy.get_registrations(
            rs, self.eventproxy.list_registrations(rs, event.id)
        )
        if registration_id is None:
            registrations: models.RegistrationMap = all_registrations
        elif registration_id < 0:
            registrations = {}
        else:
            registrations = self.eventproxy.get_registrations(rs, (registration_id,))
        personas = self.coreproxy.get_event_users(
            rs,
            [reg['persona_id'] for reg in all_registrations.values()],
            event_id=event.id,
        )
        registrations = dict(
            keydictsort_filter(
                registrations,
                lambda reg: EntitySorter.persona(personas[reg['persona_id']].as_dict()),
            )
        )

        # Retrieve courses.
        all_courses = self.eventproxy.get_courses(
            rs, self.eventproxy.list_courses(rs, event.id), _event=event
        )
        if course_id is None:
            courses: models.CourseMap = all_courses
        elif course_id < 0:
            courses = {}
        else:
            courses = self.eventproxy.get_courses(rs, [course_id], _event=event)

        choice_stats: models.ChoiceStats
        attendee_stats: models.AttendeeStats
        choice_stats, attendee_stats = self.get_course_stats(
            rs, event=event, registrations=all_registrations, course_ids=courses
        )

        # Retrieve lodgements.
        all_lodgements = self.eventproxy.new_get_lodgements(
            rs, self.eventproxy.list_lodgements(rs, event.id), _event=event
        )
        if lodgement_id is None:
            lodgements: models.LodgementMap = all_lodgements
        elif lodgement_id < 0:
            lodgements = {}
        else:
            lodgements = self.eventproxy.new_get_lodgements(
                rs, [lodgement_id], _event=event
            )

        involved_inhabitants = self.eventproxy.get_grouped_inhabitants(
            rs, event.id, involved=True, _registrations=all_registrations
        )
        uninvolved_inhabitants = self.eventproxy.get_grouped_inhabitants(
            rs, event.id, involved=False, _registrations=all_registrations
        )

        violations = models_cv.ViolationAux(
            event=event,
            registrations=registrations,
            personas=personas,
            all_courses=all_courses,
            courses=courses,
            all_lodgements=all_lodgements,
            lodgements=lodgements,
            attendee_data=attendee_stats,
            choices_data=choice_stats,
            involved_inhabitants_data=involved_inhabitants,
            uninvolved_inhabitants_data=uninvolved_inhabitants,
        ).evaluate_all()

        return ConstraintViolationsData(
            violations=violations,
            all_registrations=all_registrations,
            registrations=registrations,
            personas=personas,
            all_courses=all_courses,
            courses=courses,
            choice_stats=choice_stats,
            attendee_stats=attendee_stats,
            all_lodgements=all_lodgements,
            lodgements=lodgements,
            involved_inhabitants=involved_inhabitants,
            uninvolved_inhabitants=uninvolved_inhabitants,
        )

    @access("event")
    # TODO Be more thoughtful here, considering the constraint violations rework
    @event_guard(EventPrivileges.all_read)
    @REQUESTdata("min_severity", "violation_kind", _omit_missing=True)
    def constraint_violations(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        min_severity: models_cv.ViolationSeverity = models_cv.ViolationSeverity.INFO,
        violation_kind: models_cv.ViolationKind | None = None,
    ) -> Response:
        rs.ignore_validation_errors()
        return self.render(
            rs,
            "base/constraint_violations",
            {
                'min_severity': min_severity or models_cv.ViolationSeverity.INFO,  # type: ignore[unreachable]
                'violation_kind': violation_kind,
                **self.get_constraint_violations(
                    rs,
                    rs.ambience['event'],
                    registration_id=None,
                    course_id=None,
                    lodgement_id=None,
                ),
            },
        )

    @access("event.event_helper", "event_admin", "finance_admin")
    @REQUESTdata(
        "event_ids",
        "violation_classes",
        "is_archived",
        "is_balanced",
        "is_concluded",
        "min_severity",
        "violation_kind",
        _omit_missing=True,
    )
    def constraint_violations_summary(
        self,
        rs: RequestState,
        event_ids: set[int] | None = None,
        violation_classes: list[str] | None = None,
        is_archived: int = -1,
        is_balanced: int = -1,
        is_concluded: int = -1,
        min_severity: models_cv.ViolationSeverity = models_cv.ViolationSeverity.INFO,
        violation_kind: models_cv.ViolationKind | None = None,
    ) -> Response:
        rs.ignore_validation_errors()

        is_archived_ = bool(is_archived) if is_archived != -1 else None
        is_balanced_ = bool(is_balanced) if is_balanced != -1 else None
        is_concluded_ = bool(is_concluded) if is_concluded != -1 else None
        event_ids = set(event_ids or [])
        min_severity = min_severity or models_cv.ViolationSeverity.INFO  # type: ignore[unreachable]

        all_event_ids = self.eventproxy.list_events(rs)
        all_events = self.eventproxy.get_events(rs, all_event_ids)
        event_options = [
            {
                'title': event.title,
                'shortname': event.shortname,
                'id': event.id,
            }
            for event in xsorted(all_events.values(), reverse=True)
        ]

        violations = models_cv.ViolationList()
        for event in all_events.values():
            violations.extend(
                self.get_constraint_violations(
                    rs,
                    event,
                    registration_id=None,
                    course_id=None,
                    lodgement_id=None,
                )['violations'],
            )
        violations.sort()

        return self.render(
            rs,
            "base/constraint_violations_summary",
            {
                'violations': violations,
                'all_events': all_events,
                'event_options': event_options,
                'event_ids': event_ids,
                'is_archived': is_archived_,
                'is_balanced': is_balanced_,
                'is_concluded': is_concluded_,
                'min_severity': min_severity,
                'violation_kind': violation_kind,
            },
        )

    @REQUESTdatadict(*EventLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("event_admin", "finance_admin", "auditor")
    def view_log(self, rs: RequestState, data: CdEDBObject, download: bool) -> Response:
        """View activities concerning events organized via DB."""
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        if self.is_admin(rs):
            registration_map = self.eventproxy.get_registration_map(rs, event_ids)
        else:
            registration_map = {}  # pyrefly: ignore[implicit-any-empty-container]
        return self.generic_view_log(
            rs,
            data,
            EventLogFilter,
            self.eventproxy.retrieve_log,
            download=download,
            template="base/view_log",
            template_kwargs={
                'all_events': events,
                'registration_map': registration_map,
            },
        )

    @REQUESTdatadict(*EventLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("event")
    @event_guard(EventPrivileges.log_read)
    def view_event_log(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        data: CdEDBObject,
        download: bool,
    ) -> Response:
        """View activities concerning one event organized via DB."""
        rs.values['event_id'] = data['event_id'] = event_id
        registration_map = self.eventproxy.get_registration_map(rs, (event_id,))
        return self.generic_view_log(
            rs,
            data,
            EventLogFilter,
            self.eventproxy.retrieve_log,
            download=download,
            template="base/view_event_log",
            template_kwargs={
                'registration_map': registration_map,
            },
        )

    @staticmethod
    def _get_camping_mat_field_names(
        event: models.Event,
    ) -> dict[int, vtypes.RestrictiveIdentifier | None]:
        field_names: dict[int, vtypes.RestrictiveIdentifier | None] = {}
        for part_id, part in event.parts.items():
            if f := part.camping_mat_field:
                field_names[part_id] = f.field_name
            else:
                field_names[part_id] = None
        return field_names

    @periodic("event_keeper", 2)
    def event_keeper(self, rs: RequestState, state: CdEDBObject) -> CdEDBObject:
        """Regularly backup any event that got changed.

        :param state: Keeps track of the event schema version to do an extra commit if
            it is outdated.
        """
        if not state:
            state = {
                'EVENT_SCHEMA_VERSION': None,
            }
        # TODO this can be dropped once this got deployed
        if "events" in state:
            del state["events"]
        event_ids = self.eventproxy.list_events(rs, archived=False)
        if state.get("EVENT_SCHEMA_VERSION") != list(EVENT_SCHEMA_VERSION):
            self.logger.info(
                "Event schema version changed, creating new commit for every event."
            )
            for event_id in event_ids:
                self.eventproxy.event_keeper_commit(
                    rs, event_id, "Ändere Veranstaltungs-Schema.", after_change=True
                )
            state['EVENT_SCHEMA_VERSION'] = EVENT_SCHEMA_VERSION

        commit_msg = "Regelmäßiger Snapshot"
        for event_id in event_ids:
            self.eventproxy.event_keeper_commit(rs, event_id, commit_msg)

        return state
