#!/usr/bin/env python3

"""Services for the assembly realm."""

import collections
import datetime
import importlib.metadata
import io
import json
import pathlib
import shutil
import subprocess
import tempfile
import time
import zipapp
from typing import Any, Collection, Dict, List, Optional, Set, Tuple, Union

import werkzeug.exceptions
from schulze_condorcet import pairwise_preference, schulze_evaluate_detailed
from schulze_condorcet.types import Candidate, DetailedResultLevel, VoteString
from schulze_condorcet.util import (
    as_vote_string, as_vote_strings, as_vote_tuple, as_vote_tuples,
)
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
from cdedb.backend.assembly import GroupedBallots
from cdedb.common import (
    ASSEMBLY_BAR_SHORTNAME, CdEDBObject, DefaultReturnCode, RequestState,
    abbreviation_mapper, get_hash, merge_dicts, now, unwrap,
)
from cdedb.common.fields import LOG_FIELDS_COMMON
from cdedb.common.n_ import n_
from cdedb.common.query import QueryScope
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation import (
    ASSEMBLY_COMMON_FIELDS, BALLOT_EXPOSED_FIELDS, PERSONA_FULL_CREATION, filter_none,
)
from cdedb.common.validation.types import CdedbID, Email
from cdedb.filter import keydictsort_filter
from cdedb.frontend.common import (
    AbstractUserFrontend, Attachment, REQUESTdata, REQUESTdatadict, REQUESTfile, access,
    assembly_guard, cdedburl, check_validation as check, drow_name, inspect_validation,
    periodic, process_dynamic_input, request_extractor,
)
from cdedb.models.ml import Mailinglist

#: Magic value to signal abstention during _classical_ voting.
#: This can not occur as a shortname since it contains forbidden characters.
MAGIC_ABSTAIN = Candidate("special: abstain")

ASSEMBLY_BAR_ABBREVIATION = "#"


class AssemblyFrontend(AbstractUserFrontend):
    """Organize congregations and vote on ballots."""
    realm = "assembly"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("assembly")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        assemblies = self.assemblyproxy.list_assemblies(rs, restrictive=True)
        for assembly_id, assembly in assemblies.items():
            assembly['does_attend'] = self.assemblyproxy.does_attend(
                rs, assembly_id=assembly_id)
        attendees_count = {assembly_id: len(
                           self.assemblyproxy.list_attendees(rs, assembly_id))
                           for assembly_id in rs.user.presider}
        return self.render(rs, "index", {'assemblies': assemblies,
                                         'attendees_count': attendees_count})

    @access("core_admin", "assembly_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("core_admin", "assembly_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_CREATION['assembly']))
    def create_user(self, rs: RequestState, data: CdEDBObject) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("core_admin", "assembly_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool) -> Response:
        """Perform search."""
        return self.generic_user_search(
            rs, download, is_search, QueryScope.assembly_user, QueryScope.assembly_user,
            self.assemblyproxy.submit_general_query)

    @access("core_admin", "assembly_admin")
    @REQUESTdata("download", "is_search")
    def full_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        return self.generic_user_search(
            rs, download, is_search,
            QueryScope.all_assembly_users, QueryScope.all_core_users,
            self.assemblyproxy.submit_general_query)

    @access("assembly_admin", "auditor")
    @REQUESTdata(*LOG_FIELDS_COMMON, "assembly_id")
    def view_log(self, rs: RequestState,
                 codes: Collection[const.AssemblyLogCodes],
                 assembly_id: Optional[vtypes.ID], offset: Optional[int],
                 length: Optional[vtypes.PositiveInt], persona_id: Optional[CdedbID],
                 submitted_by: Optional[CdedbID], change_note: Optional[str],
                 time_start: Optional[datetime.datetime],
                 time_stop: Optional[datetime.datetime]) -> Response:
        """View activities."""

        filter_params = {
            'entity_ids': [assembly_id] if assembly_id else [],
            'codes': codes, 'offset': offset, 'length': length,
            'persona_id': persona_id, 'submitted_by': submitted_by,
            'change_note': change_note, 'ctime': (time_start, time_stop),
        }

        all_assemblies = self.assemblyproxy.list_assemblies(rs)
        may_view = lambda id_: self.assemblyproxy.may_assemble(rs, assembly_id=id_)

        return self.generic_view_log(
            rs, filter_params, "assembly.log", "view_log", {
            'may_view': may_view, 'all_assemblies': all_assemblies,
        })

    @access("assembly")
    @assembly_guard
    @REQUESTdata(*LOG_FIELDS_COMMON)
    def view_assembly_log(self, rs: RequestState,
                          codes: Optional[Collection[const.AssemblyLogCodes]],
                          assembly_id: int, offset: Optional[int],
                          length: Optional[vtypes.PositiveInt],
                          persona_id: Optional[CdedbID],
                          submitted_by: Optional[CdedbID],
                          change_note: Optional[str],
                          time_start: Optional[datetime.datetime],
                          time_stop: Optional[datetime.datetime]) -> Response:
        """View activities."""

        filter_params = {
            'entity_ids': [assembly_id],
            'codes': codes, 'offset': offset, 'length': length,
            'persona_id': persona_id, 'submitted_by': submitted_by,
            'change_note': change_note, 'ctime': (time_start, time_stop),
        }

        return self.generic_view_log(
            rs, filter_params, "assembly.log", "view_assembly_log")

    @access("assembly")
    def show_assembly(self, rs: RequestState, assembly_id: int) -> Response:
        """Present an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attachments_version = self.assemblyproxy.get_latest_attachments_version(
            rs, attachment_ids)
        attends = self.assemblyproxy.does_attend(rs, assembly_id=assembly_id)
        presiders = self.coreproxy.get_personas(
            rs, rs.ambience['assembly']['presiders'])

        if self.is_admin(rs):
            conclude_blockers = self.assemblyproxy.conclude_assembly_blockers(
                rs, assembly_id)
            delete_blockers = self.assemblyproxy.delete_assembly_blockers(
                rs, assembly_id)
        else:
            conclude_blockers = {"is_admin": [False]}
            delete_blockers = {"is_admin": [False]}

        params = {
            "attachments": attachments,
            "attachments_version": attachments_version,
            "attends": attends,
            "conclude_blockers": conclude_blockers,
            "delete_blockers": delete_blockers,
            "presiders": presiders,
        }

        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs.ambience['assembly'])
            params['attendee_list_exists'] = self.mlproxy.verify_existence(
                rs, Mailinglist.get_address(ml_data))

        return self.render(rs, "show_assembly", params)

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata("presider_ids")
    def add_presiders(self, rs: RequestState, assembly_id: int,
                      presider_ids: vtypes.CdedbIDList) -> Response:
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        if not self.coreproxy.verify_ids(rs, presider_ids, is_archived=False):
            rs.append_validation_error(("presider_ids", ValueError(n_(
                "Some of these users do not exist or are archived."))))
        elif not self.coreproxy.verify_personas(rs, presider_ids, {"assembly"}):
            rs.append_validation_error(("presider_ids", ValueError(n_(
                "Some of these users are not assembly users."))))
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        code = self.assemblyproxy.add_assembly_presiders(
            rs, assembly_id, presider_ids)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata("presider_id")
    def remove_presider(self, rs: RequestState, assembly_id: int,
                        presider_id: vtypes.ID) -> Response:
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        if presider_id not in rs.ambience['assembly']['presiders']:
            rs.notify("info", n_(
                "This user is not a presider for this assembly."))
            return self.redirect(rs, "assembly/show_assembly")
        code = self.assemblyproxy.remove_assembly_presider(rs, assembly_id, presider_id)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly")
    @assembly_guard
    def change_assembly_form(self, rs: RequestState,
                             assembly_id: int) -> Response:
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        merge_dicts(rs.values, rs.ambience['assembly'])
        return self.render(rs, "configure_assembly")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdatadict(*ASSEMBLY_COMMON_FIELDS)
    @REQUESTdata("presider_address")
    def change_assembly(self, rs: RequestState, assembly_id: int,
                        presider_address: Optional[str], data: Dict[str, Any]
                        ) -> Response:
        """Modify an assembly."""
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        data['id'] = assembly_id
        data['presider_address'] = presider_address
        data = check(rs, vtypes.Assembly, data)
        if rs.has_validation_errors():
            return self.change_assembly_form(rs, assembly_id)
        assert data is not None
        code = self.assemblyproxy.set_assembly(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin")
    def create_assembly_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "configure_assembly")

    @staticmethod
    def _get_mailinglist_setter(assembly: CdEDBObject, presider: bool = False
                                ) -> CdEDBObject:
        # The id is not yet known during creation.
        assembly_id = assembly.get('id')
        if presider:
            descr = ("Bitte wende Dich bei Fragen oder Problemen, die mit dieser"
                     " Versammlung zusammenhängen, über diese Liste an uns.")
            presider_ml_data = {
                'title': f"{assembly['title']} Versammlungsleitung",
                'local_part': f"{assembly['shortname'].lower()}-leitung",
                'domain': const.MailinglistDomain.lists,
                'description': descr,
                'mod_policy': const.ModerationPolicy.unmoderated,
                'attachment_policy': const.AttachmentPolicy.allow,
                'subject_prefix': f"{assembly['shortname']}-leitung",
                'maxsize': ml_type.AssemblyPresiderMailinglist.maxsize_default,
                'is_active': True,
                'assembly_id': assembly_id,
                'notes': None,
                'moderators': assembly['presiders'],
                'ml_type': const.MailinglistTypes.assembly_presider,
            }
            return presider_ml_data
        else:
            descr = ("Dieser Liste kannst Du nur beitreten, indem Du Dich direkt zu"
                     " der [Versammlung anmeldest]({}).")
            attendee_ml_data = {
                'title': assembly['title'],
                'local_part': assembly['shortname'].lower(),
                'domain': const.MailinglistDomain.lists,
                'description': descr,
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'attachment_policy': const.AttachmentPolicy.pdf_only,
                'subject_prefix': assembly['shortname'],
                'maxsize': ml_type.AssemblyAssociatedMailinglist.maxsize_default,
                'is_active': True,
                'assembly_id': assembly_id,
                'notes': None,
                'moderators': assembly['presiders'],
                'ml_type': const.MailinglistTypes.assembly_associated,
            }
            return attendee_ml_data

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata("presider_list")
    def create_assembly_mailinglist(self, rs: RequestState, assembly_id: int,
                                    presider_list: bool) -> Response:
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/show_assembly")
        if not rs.ambience['assembly']['presiders']:
            rs.notify('error',
                      n_("Must have presiders in order to create a mailinglist."))
            return self.redirect(rs, "assembly/show_assembly")

        ml_data = self._get_mailinglist_setter(rs.ambience['assembly'], presider_list)
        ml_address = Mailinglist.get_address(ml_data)
        if not self.mlproxy.verify_existence(rs, ml_address):
            if not presider_list:
                link = cdedburl(rs, "assembly/show_assembly",
                                {'assembly_id': assembly_id})
                ml_data['description'] = ml_data['description'].format(link)
            new_id = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Presider mailinglist created.") if presider_list
                   else n_("Attendee mailinglist created."))
            rs.notify_return_code(new_id, success=msg)
            if new_id and presider_list:
                data = {'id': assembly_id, 'presider_address': ml_address}
                self.assemblyproxy.set_assembly(rs, data)
        else:
            rs.notify("info", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_address})
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict(*ASSEMBLY_COMMON_FIELDS)
    @REQUESTdata("presider_ids", "create_attendee_list", "create_presider_list",
                 "presider_address")
    def create_assembly(self, rs: RequestState, presider_ids: vtypes.CdedbIDList,
                        create_attendee_list: bool, create_presider_list: bool,
                        presider_address: Optional[Email], data: Dict[str, Any]
                        ) -> Response:
        """Make a new assembly."""
        if presider_ids is not None:
            data["presiders"] = presider_ids
        data = check(rs, vtypes.Assembly, data, creation=True)
        if rs.has_validation_errors():
            return self.create_assembly_form(rs)
        assert data is not None
        presider_ml_data = None
        if create_presider_list:
            if presider_address:
                rs.notify("info", n_("Given presider address ignored in favor of"
                                     " newly created mailinglist."))
            presider_ml_data = self._get_mailinglist_setter(data, presider=True)
            presider_address = Mailinglist.get_address(presider_ml_data)
            data["presider_address"] = presider_address
            if self.mlproxy.verify_existence(rs, presider_address):
                presider_ml_data = None
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': presider_address})
        else:
            data["presider_address"] = presider_address
        if presider_ids:
            if not self.coreproxy.verify_ids(rs, presider_ids, is_archived=False):
                rs.append_validation_error(
                    ('presider_ids', ValueError(
                        n_("Some of these users do not exist or are archived."))))
            if not self.coreproxy.verify_personas(rs, presider_ids, {"assembly"}):
                rs.append_validation_error(
                    ('presider_ids', ValueError(
                        n_("Some of these users are not assembly users."))))
        else:
            # We check presider_ml_data here instead of create_presider_list, since
            # the former is falsy if a presider mailinglist already exists.
            if presider_ml_data or create_attendee_list:
                rs.append_validation_error(
                    ('presider_ids', ValueError(
                        n_("Must not be empty in order to create a mailinglist."))))
        if rs.has_validation_errors():
            # as there may be other notifications already, notify errors explicitly
            rs.notify_validation()
            return self.create_assembly_form(rs)
        assert data is not None
        new_id = self.assemblyproxy.create_assembly(rs, data)
        if presider_ml_data:
            presider_ml_data['assembly_id'] = new_id
            code = self.mlproxy.create_mailinglist(rs, presider_ml_data)
            rs.notify_return_code(code, success=n_("Presider mailinglist created."))
        if create_attendee_list:
            attendee_ml_data = self._get_mailinglist_setter(data)
            attendee_address = Mailinglist.get_address(attendee_ml_data)
            if not self.mlproxy.verify_existence(rs, attendee_address):
                link = cdedburl(rs, "assembly/show_assembly", {'assembly_id': new_id})
                descr = attendee_ml_data['description'].format(link)
                attendee_ml_data['description'] = descr
                attendee_ml_data['assembly_id'] = new_id
                code = self.mlproxy.create_mailinglist(rs, attendee_ml_data)
                rs.notify_return_code(code, success=n_("Attendee mailinglist created."))
            else:
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': attendee_address})
        rs.notify_return_code(new_id, success=n_("Assembly created."))
        return self.redirect(rs, "assembly/show_assembly", {'assembly_id': new_id})

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def delete_assembly(self, rs: RequestState, assembly_id: int,
                        ack_delete: bool) -> Response:
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        blockers = self.assemblyproxy.delete_assembly_blockers(rs, assembly_id)
        if "ballot_is_locked" in blockers:
            rs.notify("error", n_("Assemblies with active ballots cannot be deleted."))
            return self.show_assembly(rs, assembly_id)

        # Specify what to cascade
        cascade = {"assembly_is_locked", "attachments", "attendees", "ballots", "log",
                   "mailinglists", "presiders"} & blockers.keys()
        code = self.assemblyproxy.delete_assembly(
            rs, assembly_id, cascade=cascade)

        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/index")

    @access("assembly")
    def list_attachments(self, rs: RequestState, assembly_id: int) -> Response:
        """Render form."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            rs.notify("error", n_("May not access attachments for this assembly."))
            return self.redirect(rs, "assembly/index")
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attachments_versions = self.assemblyproxy.get_attachments_versions(
            rs, attachment_ids)

        def sortkey(att: CdEDBObject) -> Tuple[str, int]:
            """This is an inline function and not in EntitySorter since its only used
            here and needs some extra context."""
            latest_version = attachments_versions[att["id"]][att["latest_version_nr"]]
            return latest_version["title"], att["id"]

        sorted_attachments = {
            att["id"]: att for att in xsorted(attachments.values(), key=sortkey)}
        are_attachment_versions_creatable = \
            self.assemblyproxy.are_attachment_versions_creatable(rs, attachment_ids)
        are_attachment_versions_deletable = \
            self.assemblyproxy.are_attachment_versions_deletable(rs, attachment_ids)
        are_attachments_deletable = {
            attachment_id: (attachment["num_versions"] <= 1
                            and are_attachment_versions_deletable[attachment_id])
            for attachment_id, attachment in attachments.items()}
        return self.render(rs, "list_attachments", {
            "attachments": sorted_attachments,
            "attachments_versions": attachments_versions,
            "are_attachment_versions_creatable": are_attachment_versions_creatable,
            "are_attachment_versions_deletable": are_attachment_versions_deletable,
            "are_attachments_deletable": are_attachments_deletable,
        })

    def process_signup(self, rs: RequestState, assembly_id: int,
                       persona_id: int = None) -> None:
        """Helper to actually perform signup."""
        if persona_id:
            secret = self.assemblyproxy.external_signup(
                rs, assembly_id, persona_id)
        else:
            persona_id = rs.user.persona_id
            secret = self.assemblyproxy.signup(rs, assembly_id)
        persona = self.coreproxy.get_persona(rs, persona_id)
        if secret:
            rs.notify("success", n_("Signed up."))
            subject = f"Teilnahme an {rs.ambience['assembly']['title']}"
            reply_to = (rs.ambience['assembly']['presider_address'] or
                        self.conf["ASSEMBLY_ADMIN_ADDRESS"])
            self.do_mail(
                rs, "signup",
                {'To': (persona['username'],),
                 'Subject': subject,
                 'Reply-To': reply_to},
                {'secret': secret, 'persona': persona})
        else:
            rs.notify("info", n_("Already signed up."))

    @access("member", modi={"POST"})
    def signup(self, rs: RequestState, assembly_id: int) -> Response:
        """Join an assembly."""
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/show_assembly")
        self.process_signup(rs, assembly_id)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("persona_id")
    def external_signup(self, rs: RequestState, assembly_id: int,
                        persona_id: CdedbID) -> Response:
        """Add an external participant to an assembly."""
        if rs.has_validation_errors():
            # Shortcircuit for invalid id
            return self.list_attendees(rs, assembly_id)
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/list_attendees")
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            rs.append_validation_error(
                ('persona_id',
                 ValueError(n_("This user does not exist or is archived."))))
        elif not self.coreproxy.verify_persona(rs, persona_id, {"assembly"}):
            rs.append_validation_error(
                ('persona_id', ValueError(n_("This user is not an assembly user."))))
        elif self.coreproxy.verify_persona(rs, persona_id, {"member"}):
            rs.append_validation_error(
                ('persona_id', ValueError(n_("Members must sign up themselves."))))
        if rs.has_validation_errors():
            return self.list_attendees(rs, assembly_id)
        self.process_signup(rs, assembly_id, persona_id)
        return self.redirect(rs, "assembly/list_attendees")

    def _get_list_attendees_data(self, rs: RequestState,
                                 assembly_id: int) -> Dict[int, Dict[str, Any]]:
        """This lists all attendees of an assembly.

        This is un-inlined to provide a download file too."""
        attendee_ids = self.assemblyproxy.list_attendees(rs, assembly_id)
        attendees = collections.OrderedDict(
            (e['id'], e) for e in xsorted(
                self.coreproxy.get_assembly_users(rs, attendee_ids).values(),
                key=EntitySorter.persona))
        return attendees

    @access("assembly")
    def list_attendees(self, rs: RequestState, assembly_id: int) -> Response:
        """Provide a online list of who is/was present."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        attendees = self._get_list_attendees_data(rs, assembly_id)
        return self.render(rs, "list_attendees", {"attendees": attendees})

    @access("assembly")
    @assembly_guard
    def download_list_attendees(self, rs: RequestState,
                                assembly_id: int) -> Response:
        """Provides a tex-snipped with all attendes of an assembly."""
        attendees = self._get_list_attendees_data(rs, assembly_id)
        if not attendees:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "assembly/list_attendees")
        tex = self.fill_template(
            rs, "tex", "list_attendees", {'attendees': attendees})
        return self.send_file(
            rs, data=tex, inline=False, filename="Anwesenheitsliste-Export.tex")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata("ack_conclude")
    def conclude_assembly(self, rs: RequestState, assembly_id: int,
                          ack_conclude: bool) -> Response:
        """Archive an assembly.

        This purges stored voting secret.
        """
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify("info", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        if not ack_conclude:
            rs.append_validation_error(
                ("ack_conclude", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)

        blockers = self.assemblyproxy.conclude_assembly_blockers(
            rs, assembly_id)
        if "ballot" in blockers:
            rs.notify("error", n_("Unable to conclude assembly with open ballot."))
            return self.show_assembly(rs, assembly_id)

        cascade = {"signup_end"}
        code = self.assemblyproxy.conclude_assembly(rs, assembly_id, cascade)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_assembly")

    def _group_ballots(self, rs: RequestState, assembly_id: int
                       ) -> Optional[GroupedBallots]:
        """Helper to group all ballots of an assembly by status.

        This calls `_update_ballots` to ensure data integrity before
        grouping the ballots. If this performed a state update,
        None will be returned and the calling function should perform
        a redirect to the calling page, so the typical usage looks like:

            if grouped := self._group_ballots(rs, assembly_id):
                done, extended, current, future = grouped
            else:
                return self.redirect(rs, "assembly/dummy_page")

        :returns: None if any ballot updated state, else
            four dicts mapping ballot ids to ballots grouped by status
            in the order done, extended, current, future.
            Every ballot of the assembly is present in exactly one dict.
        """
        # Check for state changes before grouping ballots.
        extended, tallied, _ = self._update_ballots(rs, assembly_id)
        if extended or tallied:
            return None

        return self.assemblyproxy.group_ballots(rs, assembly_id)

    @access("assembly")
    def list_ballots(self, rs: RequestState, assembly_id: int) -> Response:
        """View available ballots for an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        if grouped := self._group_ballots(rs, assembly_id):
            ballots = grouped.all
        else:
            # some ballots updated state
            return self.redirect(rs, "assembly/list_ballots")

        votes = {}
        if self.assemblyproxy.does_attend(rs, assembly_id=assembly_id):
            for ballot_id in ballots:
                votes[ballot_id] = self.assemblyproxy.get_vote(
                    rs, ballot_id, secret=None)

        return self.render(rs, "list_ballots", {
            'ballots': ballots, 'grouped_ballots': grouped, 'votes': votes,
        })

    @access("assembly")
    def ballot_template(self, rs: RequestState, assembly_id: int, ballot_id: int
                        ) -> Response:
        """Offer a choice of appropriate assemblies to create the new ballot.

        If exactly one appropriate assembly exists, skip this page.
        If none exists, show a warning instead.
        """
        assembly_ids = set(self.assemblyproxy.list_assemblies(rs, is_active=True))
        if not self.is_admin(rs):
            assembly_ids &= rs.user.presider
        assemblies = self.assemblyproxy.get_assemblies(rs, assembly_ids)
        assembly_entries = keydictsort_filter(assemblies, EntitySorter.assembly,
                                              reverse=True)
        if not assembly_entries:
            rs.notify("warning", n_("Not presiding over any active assemblies."))
            return self.redirect(rs, "assembly/show_ballot")
        elif len(assembly_entries) == 1:
            return self.redirect(rs, "assembly/create_ballot", {
                'assembly_id': assembly_entries[0][0], 'source_id': ballot_id,
            })
        return self.render(rs, "ballot_template", {
            'assembly_entries': assembly_entries,
        })

    @access("assembly")
    @REQUESTdata("target_assembly_id", "source_id")
    def ballot_template_redirect(self, rs: RequestState, assembly_id: int,
                                 ballot_id: int, target_assembly_id: int,
                                 source_id: int) -> Response:
        """Redirect to the creation page of the chosen target assembly."""
        if rs.has_validation_errors():
            return self.ballot_template(rs, assembly_id, ballot_id)
        return self.redirect(rs, "assembly/create_ballot", {
            'assembly_id': target_assembly_id, 'source_id': source_id,
        })

    @access("assembly")
    @REQUESTdata("source_id", _postpone_validation=True)
    @assembly_guard
    def create_ballot_form(self, rs: RequestState, assembly_id: int,
                           source_id: int = None) -> Response:
        """Render form.

        :param source_id: Can be the ID of an existing ballot, prefilling it's data.
        """
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")

        # Use inspect validation to avoid showing a validation error for this.
        # If the given source ID is not a valid ID at all, simply ignore it.
        if (source_id := inspect_validation(vtypes.ID, source_id)[0]):
            # If the ballot does not exist, get_ballot would throw a key error.
            source_ballot = unwrap(
                self.assemblyproxy.get_ballots(rs, (source_id,)) or None)
            if source_ballot:
                merge_dicts(rs.values, source_ballot)
                # Multiselects work differently from multiple checkboxes, so
                #  merge_dicts does the wrong thing here (setlist).
                rs.values['linked_attachments'] = self.assemblyproxy.list_attachments(
                    rs, ballot_id=source_id)
            # If the ballot does not exist or is not accessible, show a warning instead.
            else:
                rs.notify("warning", rs.gettext("Unknown Ballot."))

        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachment_versions = self.assemblyproxy.get_latest_attachments_version(
            rs, attachment_ids)
        attachment_entries = [(attachment_id, version["title"])
                              for attachment_id, version in attachment_versions.items()]
        selectize_data = [
            {'id': version['attachment_id'], 'name': version['title']}
            for version in xsorted(
                attachment_versions.values(),
                key=EntitySorter.attachment)
        ]

        return self.render(rs, "configure_ballot", {
            'attachment_entries': attachment_entries,
            'selectize_data': selectize_data,
        })

    @access("assembly", modi={"POST"})
    @assembly_guard
    # the linked_attachments must be passed here since we expect a list
    @REQUESTdatadict(*BALLOT_EXPOSED_FIELDS, ("linked_attachments", "[str]"))
    def create_ballot(self, rs: RequestState, assembly_id: int,
                      data: Dict[str, Any]) -> Response:
        """Make a new ballot."""
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        data['assembly_id'] = assembly_id
        data = check(rs, vtypes.Ballot, data, creation=True)
        if rs.has_validation_errors():
            return self.create_ballot_form(rs, assembly_id)
        assert data is not None
        new_id = self.assemblyproxy.create_ballot(rs, data)
        code = self._set_ballot_attachments(rs, new_id, data["linked_attachments"])
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_ballot", {'ballot_id': new_id})

    def _set_ballot_attachments(self, rs: RequestState, ballot_id: int,
                                attachment_ids: Set[Optional[int]]
                                ) -> DefaultReturnCode:
        """Wrapper around `AssemblyBackend.set_ballot_attachments` to filter None.

        We filter None from the id list, so that users are able to unset all attachments
        by selecting only the None option in the form.
        """
        attachment_ids = set(filter(None, attachment_ids))
        return self.assemblyproxy.set_ballot_attachments(rs, ballot_id, attachment_ids)

    @access("assembly")
    def get_attachment(self, rs: RequestState, assembly_id: int,
                       attachment_id: int) -> Response:
        """A wrapper around get_attachment_version to retrieve the current version."""
        attachment = self.assemblyproxy.get_attachment(rs, attachment_id)
        # Access checking is done inside get_attachment_version
        return self.redirect(rs, "assembly/get_attachment_version",
                             params={"version_nr": attachment["latest_version_nr"]})

    @access("assembly")
    @REQUESTdata("version_nr")
    def get_attachment_version(self, rs: RequestState, assembly_id: int,
                               attachment_id: int, version_nr: int) -> Response:
        """Retrieve the content of a given attachment version."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        content = self.assemblyproxy.get_attachment_content(
            rs, attachment_id, version_nr)
        if not content:
            rs.notify("error", n_("File not found."))
            return self.redirect(rs, "assembly/list_attachments")
        return self.send_file(rs, data=content, mimetype="application/pdf",
                              filename=versions[version_nr]['filename'])

    @access("assembly")
    @assembly_guard
    def add_attachment_form(self, rs: RequestState, assembly_id: int) -> Response:
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify('error',
                      n_("Cannot add attachment once the assembly has been locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        return self.render(rs, "add_attachment")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("title", "authors", "filename")
    @REQUESTfile("attachment")
    def add_attachment(self, rs: RequestState, assembly_id: int,
                       attachment: werkzeug.datastructures.FileStorage,
                       title: str, filename: Optional[vtypes.Identifier],
                       authors: Optional[str]) -> Response:
        """Create a new attachment."""
        if not rs.ambience['assembly']['is_active']:
            rs.ignore_validation_errors()
            rs.notify('error',
                      n_("Cannot add attachment once the assembly has been locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        if attachment and not filename:
            assert attachment.filename is not None
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, vtypes.Identifier, tmp, 'filename')
        attachment = check(rs, vtypes.PDFFile, attachment, 'attachment')
        if rs.has_validation_errors():
            return self.add_attachment_form(rs, assembly_id=assembly_id)
        assert attachment is not None
        data: CdEDBObject = {
            "title": title,
            "assembly_id": assembly_id,
            "filename": filename,
            "authors": authors,
        }
        code = self.assemblyproxy.add_attachment(rs, data, attachment)
        rs.notify_return_code(code, success=n_("Attachment added."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("attachment_ack_delete")
    def delete_attachment(self, rs: RequestState, assembly_id: int,
                          attachment_id: int, attachment_ack_delete: bool) -> Response:
        """Delete an attachment."""
        if not attachment_ack_delete:
            rs.append_validation_error(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/list_attachments")

        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment can not be deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        attachment = self.assemblyproxy.get_attachment(rs, attachment_id)
        # This is possible in theory but should not be done to avoid user errors
        if attachment['num_versions'] > 1:
            rs.notify("error", n_("Remove all but the last version before deleting the"
                                  " attachment."))
            return self.redirect(rs, "assembly/list_attachments")

        cascade = {"ballots", "versions"}
        code = self.assemblyproxy.delete_attachment(rs, attachment_id, cascade)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly")
    @assembly_guard
    def add_attachment_version_form(self, rs: RequestState, assembly_id: int,
                                    attachment_id: int) -> Response:
        """Render form."""
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_creatable(rs, attachment_id):
            rs.notify('error',
                      n_("Cannot add attachment version once the assembly has been"
                         " locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        latest_version = self.assemblyproxy.get_latest_attachment_version(
            rs, attachment_id)
        is_deletable = self.assemblyproxy.is_attachment_version_deletable(
            rs, attachment_id)
        return self.render(
            rs, "add_attachment_version", {
                'latest_version': latest_version,
                'is_deletable': is_deletable
            })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("title", "authors", "filename", "ack_creation")
    @REQUESTfile("attachment")
    def add_attachment_version(self, rs: RequestState, assembly_id: int,
                               attachment_id: int,
                               attachment: werkzeug.datastructures.FileStorage,
                               title: str, filename: Optional[vtypes.Identifier],
                               authors: Optional[str],
                               ack_creation: bool = None) -> Response:
        """Create a new version of an existing attachment.

        If this version can not be deleted afterwards, the creation must be confirmed.
        """
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`, which raises a "400 Bad Request" in this case
        if not self.assemblyproxy.is_attachment_version_creatable(rs, attachment_id):
            rs.ignore_validation_errors()
            rs.notify('error',
                      n_("Cannot add attachment version once the assembly has been"
                         " locked."))
            return self.redirect(rs, 'assembly/list_attachments')
        if attachment and not filename:
            assert attachment.filename is not None
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, vtypes.Identifier, tmp, 'filename')
        attachment = check(rs, vtypes.PDFFile, attachment, 'attachment')
        is_deletable = self.assemblyproxy.is_attachment_version_deletable(rs,
                                                                          attachment_id)
        if not is_deletable and not ack_creation:
            rs.append_validation_error(
                ("ack_creation", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.add_attachment_version_form(
                rs, assembly_id=assembly_id, attachment_id=attachment_id)
        assert attachment is not None
        data: CdEDBObject = {
            'title': title,
            'filename': filename,
            'authors': authors,
        }
        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        file_hash = get_hash(attachment)
        if any(v["file_hash"] == file_hash for v in versions.values()):
            # TODO maybe display some kind of warning here?
            # Currently this would mean that you need to reupload the file.
            pass

        data['attachment_id'] = attachment_id
        code = self.assemblyproxy.add_attachment_version(rs, data, attachment)
        rs.notify_return_code(code, success=n_("Attachment added."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("attachment_ack_delete")
    def delete_attachment_version(self, rs: RequestState, assembly_id: int,
                                  attachment_id: int, version_nr: int,
                                  attachment_ack_delete: bool) -> Response:
        """Delete a version of an attachment."""
        if not attachment_ack_delete:
            rs.append_validation_error(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        # the check that the attachment belongs to the assembly is already done in
        # `reconnoitre_ambience`
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/list_attachments")

        if not self.assemblyproxy.is_attachment_version_deletable(rs, attachment_id):
            rs.notify("error", n_("Attachment version can not be deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        # This should not happen. Instead, the last attachment_version_delete button
        # should link directly to delete_attachment
        if rs.ambience["attachment"]['num_versions'] <= 1:
            rs.notify("error", n_("Cannot remove the last remaining"
                                  " version of an attachment."))
            return self.redirect(rs, "assembly/list_attachments")

        versions = self.assemblyproxy.get_attachment_versions(rs, attachment_id)
        if version_nr not in versions:
            rs.notify("error", n_("This version does not exist."))
            return self.redirect(rs, "assembly/list_attachments")
        if versions[version_nr]['dtime']:
            rs.notify("error", n_("This version has already been deleted."))
            return self.redirect(rs, "assembly/list_attachments")

        code = self.assemblyproxy.remove_attachment_version(
            rs, attachment_id, version_nr)
        rs.notify_return_code(code, error=n_("Unknown version."))
        return self.redirect(rs, "assembly/list_attachments")

    @access("assembly", modi={"POST"})
    @REQUESTdata("secret")
    def show_old_vote(self, rs: RequestState, assembly_id: int, ballot_id: int,
                      secret: str) -> Response:
        """Show a vote in a ballot of an old assembly by providing secret."""
        if not rs.ambience["ballot"]["is_tallied"]:
            rs.ignore_validation_errors()
            rs.notify("error", n_("Ballot has not been tallied."))
            return self.redirect(rs, "assembly/show_ballot")
        if rs.has_validation_errors():
            return self.show_ballot_result(rs, assembly_id, ballot_id)
        return self.show_ballot_result(rs, assembly_id, ballot_id, secret.strip())

    @access("assembly")
    def show_ballot(self, rs: RequestState, assembly_id: int, ballot_id: int
                    ) -> Response:
        """Present a ballot.

        This has pretty expansive functionality. It especially checks
        for timeouts and initiates for example tallying.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        # We need to group the ballots for navigation later anyway,
        # and as grouping them updates their state we do it already here
        if grouped := self._group_ballots(rs, assembly_id):
            ballots = grouped.all
        else:
            # some ballots updated state
            return self.redirect(rs, "assembly/show_ballot")

        # get associated attachments
        definitive_versions = self.assemblyproxy.get_definitive_attachments_version(
            rs, ballot_id)
        latest_versions = self.assemblyproxy.get_latest_attachments_version(
            rs, definitive_versions.keys())

        # initial checks done, present the ballot
        ballot = rs.ambience['ballot']
        ballot['vote_count'] = self.assemblyproxy.count_votes(rs, ballot_id)
        result = self.get_online_result(rs, ballot)
        attends = self.assemblyproxy.does_attend(rs, ballot_id=ballot_id)

        vote_dict = self._retrieve_own_vote(rs, ballot, secret=None)
        # convert the own_vote in a shape which can be consumed by the (classical or
        # preferential) vote form
        if ballot['votes']:
            merge_dicts(rs.values, {'vote': vote_dict['own_vote'].split('=')
                                    if vote_dict['own_vote'] else None})
        else:
            merge_dicts(rs.values, {'vote': vote_dict['own_vote']})

        # this is used for the dynamic row candidate table
        current_candidates = {
            drow_name(field_name=key, entity_id=candidate_id): value
            for candidate_id, candidate in ballot['candidates'].items()
            for key, value in candidate.items() if key != 'id'}
        sorted_candidate_ids = [
            e["id"] for e in xsorted(ballot["candidates"].values(),
                                     key=EntitySorter.candidates)]
        merge_dicts(rs.values, current_candidates)

        # now, process the grouped ballots from above for the navigation buttons.
        ballot_list: List[int] = sum((
            xsorted(bdict, key=lambda key: bdict[key]["title"])  # pylint: disable=cell-var-from-loop;
            for bdict in (grouped.upcoming, grouped.running, grouped.concluded)), [])

        i = ballot_list.index(ballot_id)
        length = len(ballot_list)
        prev_ballot = ballots[ballot_list[i-1]] if i > 0 else None
        next_ballot = ballots[ballot_list[i+1]] if i + 1 < length else None

        # Get ids of managed assemblies.
        assembly_ids = set(self.assemblyproxy.list_assemblies(rs, is_active=True))
        if "assembly_presider" not in rs.user.admin_views:
            assembly_ids &= rs.user.presider

        return self.render(rs, "show_ballot", {
            "sorted_candidate_ids": sorted_candidate_ids,
            'latest_versions': latest_versions,
            'definitive_versions': definitive_versions,
            'MAGIC_ABSTAIN': MAGIC_ABSTAIN,
            'ASSEMBLY_BAR_SHORTNAME': ASSEMBLY_BAR_SHORTNAME,
            'attends': attends,
            'result': result,
            'prev_ballot': prev_ballot,
            'next_ballot': next_ballot,
            'managed_assembly_ids': assembly_ids,
            **vote_dict
        })

    @access("assembly")
    def show_ballot_result(self, rs: RequestState, assembly_id: int, ballot_id: int,
                           secret: str = None) -> Response:
        """This shows a more detailed result of a tallied ballot.

        All information provided on this side is constructable from the downloadable
        json result file and the verification scripts.

        However, we provide them also online for the sake of laziness.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/show_ballot_result")

        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        ballot = rs.ambience['ballot']

        # We need to group the ballots for navigation later anyway,
        # and as grouping them updates their state we do it already here
        if grouped := self._group_ballots(rs, assembly_id):
            ballots = grouped.all
        else:
            # some ballots updated state
            return self.redirect(rs, "assembly/show_ballot_result")

        if not ballot['is_tallied']:
            rs.notify("error", n_("Ballot has not been tallied."))
            return self.redirect(rs, "assembly/show_ballot")

        vote_dict = self._retrieve_own_vote(rs, ballot, secret)
        # we may get a validation error from an invalid secret, which will be handled by
        # the user and we may ignore here
        rs.ignore_validation_errors()

        result = self.get_online_result(rs, ballot)
        assert result is not None

        # map the candidate shortnames to their titles
        candidates = {candidate['shortname']: candidate['title']
                      for candidate in ballot['candidates'].values()}
        abbreviations = abbreviation_mapper(xsorted(candidates.keys()))
        if ballot['use_bar']:
            if ballot['votes']:
                candidates[ASSEMBLY_BAR_SHORTNAME] = rs.gettext(
                    "Against all Candidates")
            else:
                candidates[ASSEMBLY_BAR_SHORTNAME] = rs.gettext("Rejection limit")
        # use special symbol for bar abbreviation
        if ballot['use_bar']:
            abbreviations[ASSEMBLY_BAR_SHORTNAME] = ASSEMBLY_BAR_ABBREVIATION

        # all vote string submitted in this ballot
        votes = [vote["vote"] for vote in result["votes"]]
        # calculate the occurrence of each vote
        vote_counts = self.count_equal_votes(votes, classical=bool(ballot['votes']))

        all_candidates = [Candidate(c) for c in candidates]
        if ballot["votes"]:
            all_candidates.append(Candidate(ASSEMBLY_BAR_SHORTNAME))
        # the pairwise preference of all candidates
        # Schulze_condorcet checks if all votes contain exactly the given candidates.
        # Since the pairwise preference does not change if we ignore some candidates
        # afterwards, we simply add the _bar_ here.
        pairwise_pref = pairwise_preference(votes, all_candidates)

        # calculate the hash of the result file
        result_bytes = self.assemblyproxy.get_ballot_result(rs, ballot['id'])
        assert result_bytes is not None
        result_hash = get_hash(result_bytes)

        # show links to next and previous ballots
        # we are only interested in concluded ballots
        ballot_list: List[int] = xsorted(
            grouped.concluded.keys(),
            key=lambda id_: EntitySorter.ballot(grouped.concluded[id_])  # type: ignore[union-attr]
            # Seems like a mypy bug.
        )

        i = ballot_list.index(ballot_id)
        length = len(ballot_list)
        prev_ballot = ballots[ballot_list[i - 1]] if i > 0 else None
        next_ballot = ballots[ballot_list[i + 1]] if i + 1 < length else None

        return self.render(rs, "show_ballot_result", {
            'result': result, 'ASSEMBLY_BAR_SHORTNAME': ASSEMBLY_BAR_SHORTNAME,
            'result_hash': result_hash, 'secret': secret, **vote_dict,
            'vote_counts': vote_counts, 'MAGIC_ABSTAIN': MAGIC_ABSTAIN,
            'BALLOT_TALLY_ADDRESS': self.conf["BALLOT_TALLY_ADDRESS"],
            'BALLOT_TALLY_MAILINGLIST_URL': self.conf["BALLOT_TALLY_MAILINGLIST_URL"],
            'prev_ballot': prev_ballot, 'next_ballot': next_ballot,
            'candidates': candidates, 'abbreviations': abbreviations,
            'pairwise_preference': pairwise_pref,
        })

    @staticmethod
    def count_equal_votes(vote_strings: List[VoteString], classical: bool = False
                          ) -> collections.Counter[VoteString]:
        """This counts how often a specific vote was submitted."""
        # convert the votes into their tuple representation
        vote_tuples = as_vote_tuples(vote_strings)
        if classical:
            # in classical votes, there are at most two pairs of candidates, the
            # first we voted for and the optional second we don't voted for
            # if there is only one pair of candidates, we abstained
            vote_tuples = [((MAGIC_ABSTAIN,),) if len(vote) == 1 else (vote[0],)
                           for vote in vote_tuples]
        # take care that all candidates of the same level of each vote are sorted.
        # otherwise, votes which are semantically the same are counted as different
        votes = [[xsorted(candidates) for candidates in vote] for vote in vote_tuples]
        return collections.Counter(as_vote_strings(votes))

    def _retrieve_own_vote(self, rs: RequestState, ballot: CdEDBObject,
                           secret: str = None) -> CdEDBObject:
        """Helper function to present the own vote

        This handles the personalised information of the current viewer interacting with
        the ballot.

        :return: one of the following strings:
            * your full preference, if the ballot was a preferential vote, otherwise
            * MAGIC_ABSTAIN, if you abstained and the ballot was a classical vote
            * all candidates you voted for, seperated by '=', if the ballot was a
              classical vote
        """
        ballot_id = ballot['id']

        # fetches the vote from the database
        attends = self.assemblyproxy.does_attend(rs, ballot_id=ballot_id)
        has_voted = False
        own_vote = None
        if attends:
            has_voted = self.assemblyproxy.has_voted(rs, ballot_id)
            if has_voted:
                try:
                    own_vote = self.assemblyproxy.get_vote(rs, ballot_id, secret=secret)
                except ValueError:
                    rs.append_validation_error(
                        ("secret", ValueError(n_("Entered invalid secret"))))
                    own_vote = None

        if own_vote and ballot['votes']:
            vote_tuple = as_vote_tuple(own_vote)
            if len(vote_tuple) == 1:
                # abstention
                own_vote = MAGIC_ABSTAIN
            else:
                # select voted options in classical voting
                own_vote = as_vote_string((vote_tuple[0],))

        return {'attends': attends, 'has_voted': has_voted, 'own_vote': own_vote}

    def _update_ballots(self, rs: RequestState, assembly_id: int
                        ) -> Tuple[int, int, int]:
        """Helper to automatically update all ballots of an assembly.

        State updates are necessary for extending and tallying a ballot.
        If this function performs a state update, the calling function should
        redirect to the calling page.

        :returns: how many state changes of which kind were performed
            in order extended, tallied, unchanged
        """
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        extended = tallied = unchanged = 0

        timestamp = now()
        for ballot_id, ballot in ballots.items():
            # check for extension
            if ballot['extended'] is None and timestamp > ballot['vote_end']:
                if self.assemblyproxy.check_voting_period_extension(rs, ballot['id']):
                    extended += 1
                    continue
                else:
                    # we do not need the full updated ballot here, so just update
                    # the relevant piece of information
                    ballot['extended'] = False

            finished = (timestamp > ballot['vote_end']
                        and (not ballot['extended']
                             or timestamp > ballot['vote_extension_end']))
            # check whether we need to initiate tallying
            # tally_ballot returns None if ballot was already tallied
            if finished and (result := self.assemblyproxy.tally_ballot(rs, ballot_id)):
                afile = io.BytesIO(result)
                my_hash = get_hash(result)
                attachment_result: Attachment = {
                    'file': afile,
                    'filename': 'result.json',
                    'mimetype': 'application/json'}
                to = [self.conf["BALLOT_TALLY_ADDRESS"]]
                if rs.ambience['assembly']['presider_address']:
                    to.append(rs.ambience['assembly']['presider_address'])
                reply_to = (rs.ambience['assembly']['presider_address'] or
                            self.conf["ASSEMBLY_ADMIN_ADDRESS"])
                subject = f"Abstimmung '{ballot['title']}' ausgezählt"
                self.do_mail(
                    rs, "ballot_tallied", {
                        'To': to,
                        'Subject': subject,
                        'Reply-To': reply_to
                    },
                    attachments=(attachment_result,),
                    params={'sha': my_hash, 'title': ballot['title']})
                tallied += 1
                continue
            unchanged += 1

        ret = (extended, tallied, unchanged)
        if sum(ret) != len(ballots):
            raise RuntimeError(n_("Impossible."))
        return ret

    def get_online_result(self, rs: RequestState, ballot: Dict[str, Any]
                          ) -> Optional[CdEDBObject]:
        """Helper to get the result information of a tallied ballot."""
        if ballot['is_tallied']:
            ballot_result = self.assemblyproxy.get_ballot_result(rs, ballot['id'])
            assert ballot_result is not None
            result = json.loads(ballot_result)

            preferred: List[Collection[str]] = []
            rejected: List[Collection[str]] = []
            tmp = preferred
            lookup = {e['shortname']: e['id']
                      for e in ballot['candidates'].values()}
            for candidates in as_vote_tuple(result["result"]):
                # Remove bar if present
                level = [lookup[c] for c in candidates if c in lookup]
                if level:
                    tmp.append(level)
                if ASSEMBLY_BAR_SHORTNAME in candidates:
                    tmp = rejected
            result['preferred'] = preferred
            result['rejected'] = rejected

            # vote count for classical vote ballots
            counts: Union[Dict[str, int], List[DetailedResultLevel]]
            if ballot['votes']:
                counts = {e['shortname']: 0 for e in ballot['candidates'].values()}
                if ballot['use_bar']:
                    counts[ASSEMBLY_BAR_SHORTNAME] = 0
                for vote in result['votes']:
                    vote_tuple = as_vote_tuple(vote["vote"])
                    # votes with len 1 are abstentions
                    if len(vote_tuple) > 1:
                        # the first entry contains the candidates voted for
                        for candidate in vote_tuple[0]:
                            counts[candidate] += 1
                result['counts'] = counts
            # vote count for preferential vote ballots
            else:
                votes = [e['vote'] for e in result['votes']]
                candidates = tuple(Candidate(c) for c in result['candidates'])
                if ballot['use_bar']:
                    candidates += (ASSEMBLY_BAR_SHORTNAME,)
                counts = schulze_evaluate_detailed(votes, candidates)

            result['counts'] = counts

            # count abstentions for both voting forms
            abstentions = 0
            for vote in result['votes']:
                if len(as_vote_tuple(vote['vote'])) == 1:
                    abstentions += 1
            result['abstentions'] = abstentions

            # strip the leading _bar_ of the result if it has only technical meanings
            if not result['use_bar']:
                if result['result'].endswith(ASSEMBLY_BAR_SHORTNAME):
                    # remove also the trailing > or =
                    result['result'] = result['result'][:-len(ASSEMBLY_BAR_SHORTNAME)-1]

            return result
        return None

    @periodic("check_tally_ballot", period=1)
    def check_tally_ballot(self, rs: RequestState, store: CdEDBObject
                           ) -> CdEDBObject:
        """Check whether any ballots need to be tallied or extended."""
        tally_count = 0
        extension_count = 0
        assembly_ids = self.assemblyproxy.list_assemblies(rs, is_active=True)
        assemblies = self.assemblyproxy.get_assemblies(rs, assembly_ids)
        for assembly_id, assembly in assemblies.items():
            rs.ambience['assembly'] = assembly
            extended, tallied, _ = self._update_ballots(rs, assembly_id)
            extension_count += extended
            tally_count += tallied
        if extension_count or tally_count:
            self.logger.info(f"Extended {extension_count} and tallied"
                             f" {tally_count} ballots via cron job.")
        return store

    @access("assembly")
    def summary_ballots(self, rs: RequestState, assembly_id: int) -> Response:
        """Give an online summary of all tallied ballots of an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        if not (grouped := self._group_ballots(rs, assembly_id)):
            # some ballots updated state
            return self.redirect(rs, "assembly/summary_ballots")

        result = {k: self.get_online_result(rs, v)
                  for k, v in grouped.concluded.items()}

        config_grouped = self.assemblyproxy.group_ballots_by_config(rs, assembly_id)

        return self.render(rs, "summary_ballots", {
            'grouped_ballots': grouped, 'config_grouped': config_grouped,
            'ASSEMBLY_BAR_SHORTNAME': ASSEMBLY_BAR_SHORTNAME, 'result': result,
        })

    @access("assembly")
    @assembly_guard
    def change_ballot_form(self, rs: RequestState, assembly_id: int,
                           ballot_id: int) -> Response:
        """Render form"""
        if rs.ambience['ballot']['is_locked']:
            rs.notify("warning", n_("Unable to modify active ballot."))
            return self.redirect(rs, "assembly/show_ballot")
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachment_versions = self.assemblyproxy.get_latest_attachments_version(
            rs, attachment_ids)
        attachment_entries = [(attachment_id, version["title"])
                              for attachment_id, version in attachment_versions.items()]
        selectize_data = [
            {'id': version['attachment_id'], 'name': version['title']}
            for version in xsorted(
                attachment_versions.values(),
                key=EntitySorter.attachment)
        ]

        # add the current attachment to the values dict, since they are no part of them
        # by default
        latest_attachments = self.assemblyproxy.list_attachments(
            rs, ballot_id=ballot_id)
        rs.values["linked_attachments"] = list(latest_attachments)
        merge_dicts(rs.values, rs.ambience['ballot'])

        return self.render(rs, "configure_ballot", {
            "attachment_entries": attachment_entries,
            "selectize_data": selectize_data,
        })

    @access("assembly", modi={"POST"})
    @assembly_guard
    # the linked_attachments must be passed here since we expect a list
    @REQUESTdatadict(*BALLOT_EXPOSED_FIELDS, ("linked_attachments", "[str]"))
    def change_ballot(self, rs: RequestState, assembly_id: int,
                      ballot_id: int, data: Dict[str, Any]) -> Response:
        """Modify a ballot."""
        if rs.ambience['ballot']['is_locked']:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Unable to modify active ballot."))
            return self.redirect(rs, "assembly/show_ballot")
        data['id'] = ballot_id
        data = check(rs, vtypes.Ballot, data)
        if rs.has_validation_errors():
            return self.change_ballot_form(rs, assembly_id, ballot_id)
        assert data is not None

        code = self._set_ballot_attachments(rs, ballot_id, data['linked_attachments'])
        code *= self.assemblyproxy.set_ballot(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly")
    @assembly_guard
    def comment_concluded_ballot_form(self, rs: RequestState, assembly_id: int,
                                      ballot_id: int) -> Response:
        if not rs.ambience['ballot']['is_tallied']:
            rs.notify("error", n_("Comments are only allowed for concluded ballots."))
            return self.redirect(rs, "assembly/show_ballot")
        merge_dicts(rs.values, rs.ambience['ballot'])
        return self.render(rs, "comment_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("comment")
    def comment_concluded_ballot(self, rs: RequestState, assembly_id: int,
                                 ballot_id: int, comment: Optional[str]) -> Response:
        if rs.has_validation_errors():
            return self.comment_concluded_ballot_form(rs, assembly_id, ballot_id)
        if not self.assemblyproxy.is_ballot_concluded(rs, ballot_id):
            rs.notify("error", n_("Comments are only allowed for concluded ballots."))
            return self.redirect(rs, "assembly/show_ballot")
        code = self.assemblyproxy.comment_concluded_ballot(rs, ballot_id, comment)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    def ballot_start_voting(self, rs: RequestState, assembly_id: int,
                            ballot_id: int) -> Response:
        """Immediately start voting period of a ballot.
        Only possible in CDEDB_DEV mode."""
        if not self.conf["CDEDB_DEV"]:  # pragma: no cover
            raise RuntimeError(
                n_("Force starting a ballot is only possible in dev mode."))

        bdata = {
            "id": ballot_id,
            # vote begin must be in the future
            "vote_begin": now() + datetime.timedelta(milliseconds=100),
            "vote_end": now() + datetime.timedelta(minutes=1),
            "vote_extension_end":
                None if not rs.ambience['ballot']['vote_extension_end']
                else now() + datetime.timedelta(minutes=1, microseconds=100),
            "abs_quorum": rs.ambience['ballot']['abs_quorum'],
            "rel_quorum": rs.ambience['ballot']['rel_quorum'],
        }

        rs.notify_return_code(self.assemblyproxy.set_ballot(rs, bdata))
        # wait for ballot to be votable
        time.sleep(.1)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("ack_delete")
    def delete_ballot(self, rs: RequestState, assembly_id: int, ballot_id: int,
                      ack_delete: bool) -> Response:
        """Remove a ballot."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)
        blockers = self.assemblyproxy.delete_ballot_blockers(rs, ballot_id)
        if "ballot_is_locked" in blockers:
            rs.notify("error", n_("Unable to remove active ballot."))
            return self.show_ballot(rs, assembly_id, ballot_id)

        # Specify what to cascade
        cascade = {"candidates", "attachments", "voters"} & blockers.keys()
        code = self.assemblyproxy.delete_ballot(rs, ballot_id, cascade=cascade)

        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/list_ballots")

    @access("assembly", modi={"POST"})
    def vote(self, rs: RequestState, assembly_id: int,
             ballot_id: int) -> Response:
        """Decide on the options of a ballot.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not self.assemblyproxy.is_ballot_voting(rs, ballot_id):
            rs.notify("error", n_("Ballot is outside its voting period."))
            return self.redirect(rs, "assembly/show_ballot", {'ballot_id': ballot_id})
        ballot = rs.ambience['ballot']
        # sorting here ensures stable ordering for classical voting below
        candidates = xsorted(
            Candidate(e['shortname']) for e in ballot['candidates'].values())
        vote: Optional[str]
        if ballot['votes']:
            # classical voting
            voted = unwrap(request_extractor(rs, {"vote": Collection[str]}))
            if rs.has_validation_errors():
                return self.show_ballot(rs, assembly_id, ballot_id)
            if voted == (ASSEMBLY_BAR_SHORTNAME,):
                if not ballot['use_bar']:
                    raise ValueError(n_("Option not available."))
                vote = as_vote_string([[ASSEMBLY_BAR_SHORTNAME], candidates])
            elif voted == (MAGIC_ABSTAIN,):
                # When abstaining, the bar is equal to all candidates. This is
                # different from voting *for* all candidates.
                candidates.append(ASSEMBLY_BAR_SHORTNAME)
                vote = as_vote_string([candidates])
            elif ASSEMBLY_BAR_SHORTNAME in voted and len(voted) > 1:
                rs.notify("error", n_("Rejection is exclusive."))
                return self.show_ballot(rs, assembly_id, ballot_id)
            else:
                preferred = [c for c in candidates if c in voted]
                rejected = [c for c in candidates if c not in voted]
                # When voting for certain candidates, they are ranked higher
                # than the bar (to distinguish the vote from abstaining)
                rejected.append(ASSEMBLY_BAR_SHORTNAME)
                # TODO as_vote_string should not take empty lists in account
                if preferred:
                    vote = as_vote_string([preferred, rejected])
                else:
                    vote = as_vote_string([rejected])
        else:
            # preferential voting
            vote = unwrap(request_extractor(rs, {"vote": Optional[str]}))  # type: ignore[dict-item]
            # Empty preferential vote counts as abstaining
            if not vote:
                if ballot['use_bar']:
                    candidates.append(ASSEMBLY_BAR_SHORTNAME)
                vote = as_vote_string([candidates])
        vote = check(rs, vtypes.Vote, vote, "vote", ballot=ballot)
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)
        assert vote is not None
        code = self.assemblyproxy.vote(rs, ballot_id, vote, secret=None)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly")
    def get_result(self, rs: RequestState, assembly_id: int,
                   ballot_id: int) -> Response:
        """Download the tallied stats of a ballot."""
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not (result := self.assemblyproxy.get_ballot_result(rs, ballot_id)):
            rs.notify("warning", n_("Ballot not yet tallied."))
            return self.show_ballot(rs, assembly_id, ballot_id)
        return self.send_file(rs, data=result, inline=False,
                              filename=f"ballot_{ballot_id}_result.json")

    @access("assembly", modi={"POST"})
    @assembly_guard
    def edit_candidates(self, rs: RequestState, assembly_id: int,
                        ballot_id: int) -> Response:
        """Create, edit and delete candidates of a ballot."""

        spec = {
            'shortname': vtypes.ShortnameRestrictiveIdentifier,
            'title': vtypes.LegacyShortname
        }
        existing_candidates = rs.ambience['ballot']['candidates'].keys()
        candidates = process_dynamic_input(
            rs, vtypes.BallotCandidate, existing_candidates, spec)
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)

        shortnames: Set[str] = set()
        for candidate_id, candidate in candidates.items():
            if candidate and candidate['shortname'] in shortnames:
                rs.append_validation_error(
                    (drow_name("shortname", candidate_id),
                     ValueError(n_("Duplicate shortname.")))
                )
            if candidate:
                shortnames.add(candidate['shortname'])
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)

        data = {
            'id': ballot_id,
            'candidates': candidates
        }
        code = self.assemblyproxy.set_ballot(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "assembly/show_ballot")

    def bundle_verify_result_zipapp(self) -> bytes:
        version = importlib.metadata.version("schulze_condorcet")

        with tempfile.TemporaryDirectory() as tmp:
            temp = pathlib.Path(tmp)
            pkg = temp / 'verify_result'
            pkg.mkdir()
            shutil.copy2(self.conf['REPOSITORY_PATH'] / 'static' / 'verify_result.py',
                         pkg / '__main__.py')
            subprocess.run(
                ['python3', '-m', 'pip', 'install',
                 f'schulze_condorcet=={version}', '--target', 'verify_result'],
                cwd=tmp, check=True, stdout=subprocess.DEVNULL)
            shutil.rmtree(pkg / f'schulze_condorcet-{version}.dist-info')
            output = temp / 'verify_result.pyz'
            zipapp.create_archive(pkg, output, interpreter='/usr/bin/env python3')
            with open(output, 'rb') as f:
                return f.read()

    @access("anonymous")
    def download_verify_result_script(self, rs: RequestState) -> Response:
        """Download the script to verify the vote result files."""
        result = self.bundle_verify_result_zipapp()
        return self.send_file(
            rs, data=result, inline=False, filename="verify_result.pyz",
            mimetype="application/x-python")
