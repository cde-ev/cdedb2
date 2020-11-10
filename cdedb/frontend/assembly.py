#!/usr/bin/env python3

"""Services for the assembly realm."""

import copy
import json
import pathlib
import collections
import datetime
import time
import io
from typing import (
    Any, Dict, Tuple, Union, Optional, Collection, List, cast, Set
)

import werkzeug.exceptions
from werkzeug import Response

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access, assembly_guard,
    check_validation as check, request_extractor, calculate_db_logparams,
    calculate_loglinks, process_dynamic_input, periodic, cdedburl
)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import Query, QUERY_SPECS, mangle_query_input
from cdedb.common import (
    n_, merge_dicts, unwrap, now, ASSEMBLY_BAR_SHORTNAME, EntitySorter,
    schulze_evaluate, xsorted, RequestState, get_hash, CdEDBObject,
    DefaultReturnCode, CdEDBObjectMap,
)
import cdedb.database.constants as const

#: Magic value to signal abstention during voting. Used during the emulation
#: of classical voting. This can not occur as a shortname since it contains
#: forbidden characters.
MAGIC_ABSTAIN = "special: abstain"


class AssemblyFrontend(AbstractUserFrontend):
    """Organize congregations and vote on ballots."""
    realm = "assembly"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @staticmethod
    def is_ballot_voting(ballot: Dict[str, Any]) -> bool:
        """Determine whether a ballot is open for voting.

        :type ballot: {str: object}
        :rtype: bool
        """
        timestamp = now()
        return (timestamp > ballot['vote_begin']
                and (timestamp < ballot['vote_end']
                     or (ballot['extended']
                         and timestamp < ballot['vote_extension_end'])))

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
    @REQUESTdatadict(
        "given_names", "family_name", "display_name", "notes", "username")
    def create_user(self, rs: RequestState, data: CdEDBObject,
                    ignore_warnings: bool = False) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data, ignore_warnings)

    @access("core_admin", "assembly_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs: RequestState, download: str,
                    is_search: bool) -> Response:
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        query: Optional[Query] = None
        if is_search:
            query = cast(Query, check(rs, "query_input", query_input, "query",
                                      spec=spec, allow_empty=False))
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_assembly_user']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'choices_lists': {}, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = "qview_persona"
            result = self.assemblyproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                return self.send_query_download(
                    rs, result, fields=query.fields_of_interest, kind=download,
                    filename="user_search_result")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("assembly_admin")
    @REQUESTdata(("codes", "[int]"), ("assembly_id", "id_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("change_note", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs: RequestState,
                 codes: Collection[const.AssemblyLogCodes],
                 assembly_id: Optional[int], offset: Optional[int],
                 length: Optional[int], persona_id: Optional[int],
                 submitted_by: Optional[int], change_note: Optional[str],
                 time_start: Optional[datetime.datetime],
                 time_stop: Optional[datetime.datetime]) -> Response:
        """View activities."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.assemblyproxy.retrieve_log(
            rs, codes, assembly_id, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        personas = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, personas)
        assemblies = {entry['assembly_id']
                      for entry in log if entry['assembly_id']}
        assemblies = self.assemblyproxy.get_assemblies(rs, assemblies)
        all_assemblies = self.assemblyproxy.list_assemblies(rs)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'assemblies': assemblies, 'all_assemblies': all_assemblies,
            'loglinks': loglinks})

    @access("assembly")
    @assembly_guard
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("change_note", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_assembly_log(self, rs: RequestState,
                          codes: Optional[Collection[const.AssemblyLogCodes]],
                          assembly_id: Optional[int], offset: Optional[int],
                          length: Optional[int], persona_id: Optional[int],
                          submitted_by: Optional[int],
                          change_note: Optional[str],
                          time_start: Optional[datetime.datetime],
                          time_stop: Optional[datetime.datetime]) -> Response:
        """View activities."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.assemblyproxy.retrieve_log(
            rs, codes, assembly_id, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        personas = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, personas)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_assembly_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'loglinks': loglinks})

    @access("assembly")
    def show_assembly(self, rs: RequestState, assembly_id: int) -> Response:
        """Present an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attachment_histories = self.assemblyproxy.get_attachment_histories(
            rs, attachment_ids)
        attends = self.assemblyproxy.does_attend(rs, assembly_id=assembly_id)
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        presiders = self.coreproxy.get_personas(
            rs, rs.ambience['assembly']['presiders'])

        has_ballot_attachments = False
        ballot_attachments = {}
        for ballot_id in ballot_ids:
            ballot_attachment_ids = self.assemblyproxy.list_attachments(
                rs, ballot_id=ballot_id)
            ballot_attachments[ballot_id] = \
                self.assemblyproxy.get_attachments(
                    rs, ballot_attachment_ids)
            attachment_histories.update(
                self.assemblyproxy.get_attachment_histories(
                    rs, ballot_attachment_ids))
            has_ballot_attachments = has_ballot_attachments or bool(
                ballot_attachment_ids)

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
            "attachment_histories": attachment_histories,
            "attends": attends, "ballots": ballots,
            "ballot_attachments": ballot_attachments,
            "conclude_blockers": conclude_blockers,
            "delete_blockers": delete_blockers,
            "has_ballot_attachments": has_ballot_attachments,
            "presiders": presiders,
        }

        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs.ambience['assembly'])
            params['attendee_list'] = self.mlproxy.verify_existence(
                rs, self.mlproxy.get_full_address(ml_data))

        return self.render(rs, "show_assembly", params)

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("presider_ids", "cdedbid_csv_list"))
    def add_presiders(self, rs: RequestState, assembly_id: int,
                      presider_ids: Collection[int]) -> Response:
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
        presider_ids = set(presider_ids) | rs.ambience['assembly']['presiders']
        code = self.assemblyproxy.set_assembly_presiders(
            rs, assembly_id, presider_ids)
        self.notify_return_code(rs, code, info=n_("Action had no effect."))
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("presider_id", "id"))
    def remove_presider(self, rs: RequestState, assembly_id: int,
                        presider_id: int) -> Response:
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        if presider_id not in rs.ambience['assembly']['presiders']:
            rs.notify("info", n_(
                "This user is not a presider for this assembly."))
            return self.redirect(rs, "assembly/show")
        ids = rs.ambience['assembly']['presiders'] - {presider_id}
        code = self.assemblyproxy.set_assembly_presiders(rs, assembly_id, ids)
        self.notify_return_code(rs, code, info=n_("Action had no effect."))
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
        return self.render(rs, "assembly_data")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdatadict("title", "description", "shortname",
                     "presider_address", "signup_end", "notes")
    def change_assembly(self, rs: RequestState, assembly_id: int,
                        data: Dict[str, Any]) -> Response:
        """Modify an assembly."""
        data['id'] = assembly_id
        data = check(rs, "assembly", data)
        if rs.has_validation_errors():
            return self.change_assembly_form(rs, assembly_id)
        code = self.assemblyproxy.set_assembly(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin")
    def create_assembly_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "assembly_data")

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
                'local_part': f"{assembly['shortname']}-leitung",
                'domain': const.MailinglistDomain.lists,
                'description': descr,
                'mod_policy': const.ModerationPolicy.unmoderated,
                'attachment_policy': const.AttachmentPolicy.allow,
                'subject_prefix': f"{assembly['shortname']}-leitung",
                'maxsize': 8192,
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
                'local_part': assembly['shortname'],
                'domain': const.MailinglistDomain.lists,
                'description': descr,
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'attachment_policy': const.AttachmentPolicy.pdf_only,
                'subject_prefix': assembly['shortname'],
                'maxsize': 1024,
                'is_active': True,
                'assembly_id': assembly_id,
                'notes': None,
                'moderators': assembly['presiders'],
                'ml_type': const.MailinglistTypes.assembly_associated,
            }
            return attendee_ml_data

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("presider_list", "bool"))
    def create_assembly_mailinglist(self, rs: RequestState, assembly_id: int,
                                    presider_list: bool) -> Response:
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/show_assembly")

        ml_data = self._get_mailinglist_setter(rs.ambience['assembly'], presider_list)
        ml_address = self.mlproxy.get_full_address(ml_data)
        if not self.mlproxy.verify_existence(rs, ml_address):
            if not presider_list:
                link = cdedburl(rs, "assembly/show_assembly",
                                {'assembly_id': assembly_id})
                ml_data['description'] = ml_data['description'].format(link)
            new_id = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Presider mailinglist created.") if presider_list
                   else n_("Attendee mailinglist created."))
            self.notify_return_code(rs, new_id, success=msg)
            if new_id and presider_list:
                data = {'id': assembly_id, 'presider_address': ml_address}
                self.assemblyproxy.set_assembly(rs, data)
        else:
            rs.notify("info", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_address})
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "shortname", "signup_end", "notes")
    @REQUESTdata(("presider_ids", "cdedbid_csv_list"),
                 ("create_attendee_list", "bool"), ("create_presider_list", "bool"))
    def create_assembly(self, rs: RequestState, presider_ids: Collection[int],
                        create_attendee_list: bool, create_presider_list: bool,
                        data: Dict[str, Any]) -> Response:
        """Make a new assembly."""
        if presider_ids is not None:
            data["presiders"] = presider_ids
        data = check(rs, "assembly", data, creation=True)
        if rs.has_validation_errors():
            return self.create_assembly_form(rs)
        presider_ml_data = None
        if create_presider_list:
            presider_ml_data = self._get_mailinglist_setter(data, presider=True)
            presider_address = self.mlproxy.get_full_address(presider_ml_data)
            data["presider_address"] = presider_address
            if self.mlproxy.verify_existence(rs, presider_address):
                presider_ml_data = None
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': presider_address})
        data = check(rs, "assembly", data, creation=True)
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
            return self.create_assembly_form(rs)
        new_id = self.assemblyproxy.create_assembly(rs, data)
        if presider_ml_data:
            presider_ml_data['assembly_id'] = new_id
            code = self.mlproxy.create_mailinglist(rs, presider_ml_data)
            self.notify_return_code(
                rs, code, success=n_("Presider mailinglist created."))
        if create_attendee_list:
            attendee_ml_data = self._get_mailinglist_setter(data)
            attendee_address = self.mlproxy.get_full_address(attendee_ml_data)
            if not self.mlproxy.verify_existence(rs, attendee_address):
                link = cdedburl(rs, "assembly/show_assembly", {'assembly_id': new_id})
                descr = attendee_ml_data['description'].format(link)
                attendee_ml_data['description'] = descr
                attendee_ml_data['assembly_id'] = new_id
                code = self.mlproxy.create_mailinglist(rs, attendee_ml_data)
                self.notify_return_code(
                    rs, code, success=n_("Attendee mailinglist created."))
            else:
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': attendee_address})
        self.notify_return_code(rs, new_id, success=n_("Assembly created."))
        return self.redirect(rs, "assembly/show_assembly", {'assembly_id': new_id})

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    def delete_assembly(self, rs: RequestState, assembly_id: int,
                        ack_delete: bool) -> Response:
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        blockers = self.assemblyproxy.delete_assembly_blockers(rs, assembly_id)
        if "vote_begin" in blockers:
            rs.notify("error", n_("Unable to remove active ballot."))
            return self.show_assembly(rs, assembly_id)

        # Specify what to cascade
        cascade = {"ballots", "attendees", "attachments", "log",
                   "mailinglists", "presiders"} & blockers.keys()
        code = self.assemblyproxy.delete_assembly(
            rs, assembly_id, cascade=cascade)

        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/index")

    @access("assembly")
    def list_attachments(self, rs: RequestState, assembly_id: int) -> Response:
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            rs.notify(
                "error", n_("May not access attachments for this assembly."))
            return self.redirect(rs, "assembly/index")
        assembly_attachments = self.assemblyproxy.list_attachments(
                rs, assembly_id=assembly_id)
        count = len(assembly_attachments)
        all_attachments: Dict[Optional[int], CdEDBObjectMap] = {
            None: self.assemblyproxy.get_attachments(
                rs, assembly_attachments)
        }
        attachment_histories: Dict[Optional[int], Dict[int, CdEDBObjectMap]] = {
            None: self.assemblyproxy.get_attachment_histories(
                rs, assembly_attachments)
        }
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        for ballot_id in ballot_ids:
            attachment_ids = self.assemblyproxy.list_attachments(
                rs, ballot_id=ballot_id)
            count += len(attachment_ids)
            all_attachments[ballot_id] = self.assemblyproxy.get_attachments(
                rs, attachment_ids)
            attachment_histories[ballot_id] = (
                self.assemblyproxy.get_attachment_histories(rs, attachment_ids))
        return self.render(rs, "list_attachments", {
            "all_attachments": all_attachments,
            "attachment_histories": attachment_histories,
            "ballots": ballots,
            "count": count,
        })

    def process_signup(self, rs: RequestState, assembly_id: int,
                       persona_id: int = None) -> None:
        """Helper to actually perform signup.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type persona_id: int or None
        :rtype: None
        """
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
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/show_assembly")
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)
        self.process_signup(rs, assembly_id)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("persona_id", "cdedbid"))
    def external_signup(self, rs: RequestState, assembly_id: int,
                        persona_id: int) -> Response:
        """Add an external participant to an assembly."""
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/list_attendees")
        if rs.has_validation_errors():
            # Shortcircuit for invalid id
            return self.list_attendees(rs, assembly_id)
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
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
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
    @REQUESTdata(("ack_conclude", "bool"))
    def conclude_assembly(self, rs: RequestState, assembly_id: int,
                          ack_conclude: bool) -> Response:
        """Archive an assembly.

        This purges stored voting secret.
        """
        if not ack_conclude:
            rs.append_validation_error(
                ("ack_conclude", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_assembly(rs, assembly_id)

        blockers = self.assemblyproxy.conclude_assembly_blockers(
            rs, assembly_id)

        if "ballot" in blockers:
            rs.notify("error",
                      n_("Unable to conclude assembly with open ballot."))
            return self.show_assembly(rs, assembly_id)

        cascade = {"signup_end"}
        code = self.assemblyproxy.conclude_assembly(rs, assembly_id, cascade)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_assembly")

    @staticmethod
    def group_ballots(ballots: Dict[int, Dict[str, Any]]
                      ) -> Tuple[CdEDBObjectMap, CdEDBObjectMap,
                                 CdEDBObjectMap, CdEDBObjectMap]:
        """Helper to group ballots by status.

        :type ballots: {int: str}
        :rtype: tuple({int: str})
        :returns: Four dicts mapping ballot ids to ballots grouped by status
          in the order done, extended, current, future.
        """
        ref = now()

        future = {k: v for k, v in ballots.items()
                  if v['vote_begin'] > ref}
        # `current` also contains ballots which wait for
        # check_voting_priod_extension() being called on them
        current = {k: v for k, v in ballots.items()
                   if (v['vote_begin'] <= ref < v['vote_end']
                       or (v['vote_end'] <= ref and v['extended'] is None))}
        extended = {k: v for k, v in ballots.items()
                    if (v['extended']
                        and v['vote_end'] <= ref < v['vote_extension_end'])}
        done = {k: v for k, v in ballots.items()
                if (v['vote_end'] <= ref
                    and (v['extended'] is False
                         or v['vote_extension_end'] <= ref))}

        if not (len(future) + len(current) + len(extended) + len(done)
                == len(ballots)):
            raise RuntimeError(n_("Grouping ballots by status failed."))

        return done, extended, current, future

    @access("assembly")
    def list_ballots(self, rs: RequestState, assembly_id: int) -> Response:
        """View available ballots for an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)

        # Check for extensions before grouping ballots.
        if any([self._update_ballot_state(rs, ballot)
                for anid, ballot in ballots.items()]):
            return self.redirect(rs, "assembly/list_ballots")

        done, extended, current, future = self.group_ballots(ballots)
        # Currently we don't distinguish between current and extended ballots
        current.update(extended)

        votes = {}
        if self.assemblyproxy.does_attend(rs, assembly_id=assembly_id):
            for ballot_id in ballot_ids:
                votes[ballot_id] = self.assemblyproxy.get_vote(
                    rs, ballot_id, secret=None)

        return self.render(rs, "list_ballots", {
            'ballots': ballots, 'future': future, 'current': current,
            'done': done, 'votes': votes})

    @access("assembly")
    @assembly_guard
    def create_ballot_form(self, rs: RequestState,
                           assembly_id: int) -> Response:
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        return self.render(rs, "create_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "abs_quorum", "rel_quorum", "votes",
                     "notes", "use_bar")
    def create_ballot(self, rs: RequestState, assembly_id: int,
                      data: Dict[str, Any]) -> Response:
        """Make a new ballot."""
        data['assembly_id'] = assembly_id
        data = check(rs, "ballot", data, creation=True)
        if rs.has_validation_errors():
            return self.create_ballot_form(rs, assembly_id)
        new_id = self.assemblyproxy.create_ballot(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "assembly/show_ballot", {
            'ballot_id': new_id})

    @access("assembly")
    # ballot_id is optional, but comes semantically before attachment_id
    def get_attachment(self, rs: RequestState, assembly_id: int,
                       attachment_id: int, ballot_id: int = None,
                       version: int = None) -> Response:
        """Retrieve an attachment. Default to most recent version."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        history = self.assemblyproxy.get_attachment_history(
            rs, attachment_id)
        version = version or self.assemblyproxy.get_current_version(
            rs, attachment_id, include_deleted=False)
        content = self.assemblyproxy.get_attachment_content(
            rs, attachment_id, version)
        if not content:
            rs.notify("error", n_("File not found."))
            if ballot_id:
                return self.redirect(rs, "assembly/show_ballot")
            else:
                return self.redirect(rs, "assembly/show_assembly")
        return self.send_file(rs, data=content, mimetype="application/pdf",
                              filename=history[version]['filename'])

    @access("assembly")
    def show_attachment(self, rs: RequestState, assembly_id: int,
                        attachment_id: int, ballot_id: int = None) -> Response:
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        history = self.assemblyproxy.get_attachment_history(
            rs, attachment_id)
        edit = not self.assemblyproxy.check_attachment_locked(rs, attachment_id)
        return self.render(rs, "show_attachment", {
            'attachment': rs.ambience['attachment'], 'history': history,
            'edit': edit,
        })

    @access("assembly")
    @assembly_guard
    def add_attachment_form(self, rs: RequestState, assembly_id: int,
                            ballot_id: int = None,
                            attachment_id: int = None) -> Response:
        """Render form."""
        if ballot_id and now() > rs.ambience['ballot']['vote_begin']:
            rs.notify("warning", n_("Voting has already begun."))
            return self.redirect(rs, "assembly/show_ballot")
        attachment = None
        history = None
        if attachment_id:
            attachment = rs.ambience['attachment']
            if (attachment['ballot_id'] != ballot_id or
                    (attachment['assembly_id']
                     and attachment['assembly_id'] != assembly_id)):
                rs.notify("error", n_("Invalid attachment specified."))
                if ballot_id:
                    return self.redirect(rs, "assembly/show_ballot")
                else:
                    return self.redirect(rs, "assembly/show_assembly")
            history = self.assemblyproxy.get_attachment_history(
                rs, attachment_id)
        return self.render(
            rs, "add_attachment", {
                'attachment': attachment, 'history': history,
            })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("title", "str"),
                 ("authors", "str_or_None"),
                 ("filename", "identifier_or_None"),)
    @REQUESTfile("attachment")
    # ballot_id and attachment_id come semantically after asssembly_id,
    # but are optional, so need to be at the end.
    def add_attachment(self, rs: RequestState, assembly_id: int,
                       attachment: werkzeug.FileStorage,
                       title: str, filename: Optional[str],
                       authors: Optional[str], ballot_id: int = None,
                       attachment_id: int = None) -> Response:
        """Create a new attachment.

        It can either be associated to an assembly or a ballot.
        """
        if attachment and not filename:
            assert attachment.filename is not None
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, "identifier", tmp, 'filename')
        attachment = cast(bytes, check(rs, "pdffile", attachment, 'attachment'))
        if rs.has_validation_errors():
            return self.add_attachment_form(
                rs, assembly_id=assembly_id, ballot_id=ballot_id,
                attachment_id=attachment_id)
        data: CdEDBObject = {
            'title': title,
            'filename': filename,
            'authors': authors,
        }
        if attachment_id:
            history = self.assemblyproxy.get_attachment_history(
                rs, attachment_id)
            file_hash = get_hash(attachment)
            if any(v["file_hash"] == file_hash for v in history.values()):
                # TODO maybe display some kind of warning here?
                # Currently this would mean that you need to reupload the file.
                pass

            data['attachment_id'] = attachment_id
            code = self.assemblyproxy.add_attachment_version(
                rs, data, attachment)
        else:
            if ballot_id:
                data['ballot_id'] = ballot_id
            else:
                data['assembly_id'] = assembly_id
            code = self.assemblyproxy.add_attachment(rs, data, attachment)
        self.notify_return_code(rs, code, success=n_("Attachment added."))
        return self.redirect(rs, "assembly/show_attachment", {
            'attachment_id': attachment_id if attachment_id else code,
        })

    @access("assembly")
    @assembly_guard
    def change_attachment_link_form(self, rs: RequestState,
                                    assembly_id: int, attachment_id: int,
                                    ballot_id: int = None) -> Response:
        """Change the association of an existing attachment incl. versions."""
        attachment = rs.ambience['attachment']
        if (ballot_id != attachment['ballot_id'] or
                (attachment['assembly_id']
                 and attachment['assembly_id'] != assembly_id)):
            rs.notify("error", n_("Invalid attachment specified."))
            if attachment['ballot_id']:
                return self.redirect(rs, "assembly/show_ballot",
                                     {'ballot_id': attachment['ballot_id']})
            else:
                return self.redirect(rs, "assembly/show_assembly")
        if attachment['ballot_id']:
            ballot = self.assemblyproxy.get_ballot(rs, attachment['ballot_id'])
            if now() > ballot['vote_begin']:
                rs.notify("warning", n_("Voting has already begun."))
                return self.redirect(rs, "assembly/show_ballot")

        history = self.assemblyproxy.get_attachment_history(rs, attachment_id)
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        timestamp = now()
        ballot_entries = [
            (ballot['id'], ballot['title'])
            for ballot in xsorted(ballots.values(), key=EntitySorter.ballot)
            if timestamp < ballot['vote_begin']
        ]
        attachment['new_ballot_id'] = attachment['ballot_id']
        merge_dicts(rs.values, attachment)
        return self.render(rs, "change_attachment_link", params={
            'attachment': attachment, 'history': history,
            'ballot_entries': ballot_entries,
        })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("new_ballot_id", "id_or_None"))
    def change_attachment_link(self, rs: RequestState, assembly_id: int,
                               attachment_id: int, new_ballot_id: Optional[int],
                               ballot_id: int = None) -> Response:
        """Change the association of an existing attachment incl. versions."""
        if rs.has_validation_errors():
            return self.change_attachment_link_form(
                rs, assembly_id, attachment_id)
        attachment = rs.ambience['attachment']
        if (ballot_id != attachment['ballot_id']
                or (attachment['assembly_id']
                    and attachment['assembly_id'] != assembly_id)):
            rs.notify("error", n_("Invalid attachment specified."))
            return self.redirect(rs, "assembly/show_attachment")
        if attachment['ballot_id']:
            ballot = self.assemblyproxy.get_ballot(rs, attachment['ballot_id'])
            if now() > ballot['vote_begin']:
                rs.notify("warning", n_("Voting has already begun."))
                return self.redirect(rs, "assembly/show_ballot")

        data: CdEDBObject = {'id': attachment_id}
        if new_ballot_id:
            ballot = self.assemblyproxy.get_ballot(rs, new_ballot_id)
            if ballot['assembly_id'] != assembly_id:
                rs.append_validation_error(
                    ("new_ballot_id",
                     ValueError(n_("Invalid ballot specified."))))
            if now() > ballot['vote_begin']:
                rs.append_validation_error(
                    ("new_ballot_id",
                     ValueError(n_("Voting has already begun."))))
            if rs.has_validation_errors():
                return self.change_attachment_link_form(
                    rs, assembly_id, attachment_id, ballot_id)
            data["assembly_id"] = None
            data["ballot_id"] = new_ballot_id
        else:
            data["assembly_id"] = assembly_id
            data["ballot_id"] = None
        code = self.assemblyproxy.change_attachment_link(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_attachment", {
            'ballot_id': new_ballot_id,
        })

    @access("assembly")
    @assembly_guard
    # ballot_id comes semantically after assembly_id, but is optional,
    # so needs to be at the end.
    def edit_attachment_version_form(
            self, rs: RequestState, assembly_id: int, attachment_id: int,
            version: int, ballot_id: int = None) -> Response:
        """Change an existing version of an attachment."""
        attachment = rs.ambience['attachment']
        if (attachment['assembly_id']
                and attachment['assembly_id'] != assembly_id):
            rs.notify("error", n_("Invalid attachment specified."))
            if attachment['ballot_id']:
                return self.redirect(rs, "assembly/show_ballot",
                                     {'ballot_id': attachment['ballot_id']})
            else:
                return self.redirect(rs, "assembly/show_assembly")
        if attachment['ballot_id']:
            ballot = self.assemblyproxy.get_ballot(rs, attachment['ballot_id'])
            if now() > ballot['vote_begin']:
                rs.notify("warning", n_("Voting has already begun."))
                return self.redirect(rs, "assembly/show_ballot")
        history = self.assemblyproxy.get_attachment_history(
            rs, attachment_id)
        if version not in history or history[version]['dtime']:
            rs.notify("error", "Invalid version specified.")
            if attachment['ballot_id']:
                return self.redirect(rs, "assembly/show_ballot",
                                     {'ballot_id': attachment['ballot_id']})
            else:
                return self.redirect(rs, "assembly/show_assembly")
        merge_dicts(rs.values, history[version])
        return self.render(rs, "edit_attachment_version", {
            'attachment': attachment,
            'history': history,
            'version': version,
        })

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("title", "str"), ("authors", "str_or_None"),
                 ("filename", "str"))
    def edit_attachment_version(self, rs: RequestState, assembly_id: int,
                                attachment_id: int, version: int, title: str,
                                authors: Optional[str], filename: str,
                                ballot_id: int = None) -> Response:
        """Change an existing version of an attachment."""
        if rs.has_validation_errors():
            return self.change_attachment_link_form(
                rs, assembly_id, attachment_id, version)
        attachment = rs.ambience['attachment']
        if attachment['ballot_id']:
            ballot = self.assemblyproxy.get_ballot(rs, attachment['ballot_id'])
            if now() > ballot['vote_begin']:
                rs.notify("warning", n_("Voting has already begun."))
                return self.redirect(rs, "assembly/show_ballot")
        if (ballot_id != attachment['ballot_id'] or
                (attachment['assembly_id']
                 and attachment['assembly_id'] != assembly_id)):
            rs.notify("error", n_("Invalid attachment specified."))
            if attachment['ballot_id']:
                return self.redirect(rs, "assembly/show_ballot",
                                     {'ballot_id': attachment['ballot_id']})
            else:
                return self.redirect(rs, "assembly/show_assembly")
        history = self.assemblyproxy.get_attachment_history(
            rs, attachment_id)
        if version not in history or history[version]['dtime']:
            rs.notify("error", "Invalid version specified.")
            if attachment['ballot_id']:
                return self.redirect(rs, "assembly/show_ballot",
                                     {'ballot_id': attachment['ballot_id']})
            else:
                return self.redirect(rs, "assembly/show_assembly")

        data = {
            'attachment_id': attachment_id,
            'version': version,
            'title': title,
            'authors': authors,
            'filename': filename,
        }
        code = self.assemblyproxy.change_attachment_version(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_attachment")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("attachment_ack_delete", "bool"))
    # ballot_id is optional, but comes semantically before attachment_id
    def delete_attachment(self, rs: RequestState, assembly_id: int,
                          attachment_id: int, attachment_ack_delete: bool,
                          version: int = None,
                          ballot_id: int = None) -> Response:
        """Delete an attachment."""
        if not attachment_ack_delete:
            rs.append_validation_error(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/show_attachment")
        if version is None:
            cascade = {"versions"}
            code = self.assemblyproxy.delete_attachment(
                rs, attachment_id, cascade)
            self.notify_return_code(rs, code)
            if ballot_id:
                return self.redirect(rs, "assembly/show_ballot")
            else:
                return self.redirect(rs, "assembly/show_assembly")
        else:
            history = self.assemblyproxy.get_attachment_history(
                rs, attachment_id)
            if version not in history:
                rs.notify("error", n_("This version does not exist."))
                return self.redirect(rs, "assembly/show_attachment")
            if history[version]['dtime']:
                rs.notify("error", n_("This version has already been deleted."))
                return self.redirect(rs, "assembly/show_attachment")
            attachment = rs.ambience['attachment']
            if attachment['num_versions'] <= 1:
                rs.notify("error", n_("Cannot remove the last remaining "
                                      "version of an attachment."))
                return self.redirect(rs, "assembly/show_attachment")

            code = self.assemblyproxy.remove_attachment_version(
                rs, attachment_id, version)
            self.notify_return_code(
                rs, code, error=n_("Unknown version."))
            return self.redirect(rs, "assembly/show_attachment")

    @access("assembly", modi={"POST"})
    @REQUESTdata(("secret", "str"))
    def show_old_vote(self, rs: RequestState, assembly_id: int, ballot_id: int,
                      secret: str) -> Response:
        """Show a vote in a ballot of an old assembly by providing secret."""
        if (rs.has_validation_errors() or rs.ambience["assembly"]["is_active"]
                or not rs.ambience["ballot"]["is_tallied"]):
            return self.show_ballot(rs, assembly_id, ballot_id)
        return self.show_ballot(rs, assembly_id, ballot_id, secret.strip())

    @access("assembly")
    def show_ballot(self, rs: RequestState, assembly_id: int, ballot_id: int,
                    secret: str = None) -> Response:
        """Present a ballot.

        This has pretty expansive functionality. It especially checks
        for timeouts and initiates for example tallying.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).

        If a secret is provided, this will fetch the vote belonging to that
        secret.
        """
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        ballot = rs.ambience['ballot']
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, ballot_id=ballot_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attachment_histories = self.assemblyproxy.get_attachment_histories(
            rs, attachment_ids)
        if self._update_ballot_state(rs, ballot):
            return self.redirect(rs, "assembly/show_ballot")

        # initial checks done, present the ballot
        ballot['is_voting'] = self.is_ballot_voting(ballot)
        ballot['vote_count'] = self.assemblyproxy.count_votes(rs, ballot_id)
        result = self.get_online_result(rs, ballot)
        attends = self.assemblyproxy.does_attend(rs, ballot_id=ballot_id)
        has_voted = False
        own_vote = None
        if attends:
            has_voted = self.assemblyproxy.has_voted(rs, ballot_id)
            if has_voted:
                try:
                    own_vote = self.assemblyproxy.get_vote(
                        rs, ballot_id, secret=secret)
                except ValueError:
                    own_vote = None
        merge_dicts(rs.values, {'vote': own_vote})
        split_vote = None
        if own_vote:
            split_vote = tuple(x.split('=') for x in own_vote.split('>'))
        if ballot['votes'] and split_vote:
            if len(split_vote) == 1:
                # abstention
                rs.values['vote'] = MAGIC_ABSTAIN
            else:
                # select voted options
                rs.values.setlist('vote', split_vote[0])

        candidates = {e['shortname']: e
                      for e in ballot['candidates'].values()}
        if ballot['use_bar']:
            candidates[ASSEMBLY_BAR_SHORTNAME] = rs.gettext(
                "bar (options below this are declined)")
        # this is used for the flux candidate table
        current = {
            f"{key}_{candidate_id}": value
            for candidate_id, candidate in ballot['candidates'].items()
            for key, value in candidate.items() if key != 'id'}
        merge_dicts(rs.values, current)

        ballots_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballots_ids)
        done, extended, current, future = self.group_ballots(ballots)

        # Currently we don't distinguish between current and extended ballots
        current.update(extended)
        ballot_list: List[int] = sum((
            xsorted(bdict, key=lambda key: bdict[key]["title"])
            for bdict in (future, current, done)), [])

        i = ballot_list.index(ballot_id)
        length = len(ballot_list)
        prev_ballot = ballots[ballot_list[i-1]] if i > 0 else None
        next_ballot = ballots[ballot_list[i+1]] if i + 1 < length else None

        return self.render(rs, "show_ballot", {
            'attachments': attachments,
            'attachment_histories': attachment_histories,
            'split_vote': split_vote, 'own_vote': own_vote, 'result': result,
            'candidates': candidates, 'attends': attends,
            'ASSEMBLY_BAR_SHORTNAME': ASSEMBLY_BAR_SHORTNAME,
            'prev_ballot': prev_ballot, 'next_ballot': next_ballot,
            'secret': secret, 'has_voted': has_voted,
        })

    def _update_ballot_state(self, rs: RequestState,
                             ballot: Dict[str, Any]) -> DefaultReturnCode:
        """Helper to automatically update a ballots state.

        State updates are necessary for extending and tallying a ballot.
        If this function performs a state update, the calling function should
        redirect to the calling page.

        :returns: 1 if the ballot was tallied, -1 if it was extended,
            0 otherwise.
        """

        timestamp = now()

        # check for extension
        if ballot['extended'] is None and timestamp > ballot['vote_end']:
            self.assemblyproxy.check_voting_period_extension(rs, ballot['id'])
            return -1

        finished = (
                timestamp > ballot['vote_end']
                and (not ballot['extended']
                     or timestamp > ballot['vote_extension_end']))
        # check whether we need to initiate tallying
        if finished and not ballot['is_tallied']:
            result = self.assemblyproxy.tally_ballot(rs, ballot['id'])
            if result:
                afile = io.BytesIO(result)
                my_hash = get_hash(result)
                attachment_result: Dict[str, str] = {
                    'file': afile,  # type: ignore
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
                return 1
        return 0

    def get_online_result(self, rs: RequestState, ballot: Dict[str, Any]
                          ) -> Optional[CdEDBObject]:
        """Helper to get the result information of a tallied ballot."""
        if ballot['is_tallied']:
            ballot_result = self.assemblyproxy.get_ballot_result(rs, ballot['id'])
            assert ballot_result is not None
            result = json.loads(ballot_result)
            tiers = tuple(x.split('=') for x in result['result'].split('>'))
            winners: List[Collection[str]] = []
            losers: List[Collection[str]] = []
            tmp = winners
            lookup = {e['shortname']: e['id']
                      for e in ballot['candidates'].values()}
            for tier in tiers:
                # Remove bar if present
                ntier = tuple(lookup[x] for x in tier if x in lookup)
                if ntier:
                    tmp.append(ntier)
                if ASSEMBLY_BAR_SHORTNAME in tier:
                    tmp = losers
            result['winners'] = winners
            result['losers'] = losers

            # vote count for classical vote ballots
            counts: Union[Dict[str, int],
                          List[Dict[str, Union[int, List[str]]]]]
            if ballot['votes']:
                counts = {e['shortname']: 0
                          for e in ballot['candidates'].values()}
                if ballot['use_bar']:
                    counts[ASSEMBLY_BAR_SHORTNAME] = 0
                for vote in result['votes']:
                    raw = vote['vote']
                    if '>' in raw:
                        selected = raw.split('>')[0].split('=')
                        for s in selected:
                            counts[s] += 1
                result['counts'] = counts
            # vote count for preferential vote ballots
            else:
                votes = [e['vote'] for e in result['votes']]
                candidates = [k for k, v in result['candidates'].items()]
                if ballot['use_bar']:
                    candidates += (ASSEMBLY_BAR_SHORTNAME,)
                condensed, counts = schulze_evaluate(votes, candidates)

            result['counts'] = counts

            # count abstentions for both voting forms
            abstentions = 0
            for vote in result['votes']:
                if '>' not in vote['vote']:
                    abstentions += 1
            result['abstentions'] = abstentions
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
            ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
            ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
            for ballot_id, ballot in ballots.items():
                code = self._update_ballot_state(rs, ballot)
                if code < 0:
                    extension_count += 1
                    ballot = self.assemblyproxy.get_ballot(rs, ballot_id)
                    code = self._update_ballot_state(rs, ballot)
                    if code > 0:
                        tally_count += 1
                elif code > 0:
                    tally_count += 1
        if extension_count or tally_count:
            self.logger.info(f"Extended {extension_count} and tallied"
                             f" {tally_count} ballots via cron job.")
        return store

    @access("assembly")
    def summary_ballots(self, rs: RequestState, assembly_id: int) -> Response:
        """Give an online summary of all tallied ballots of an assembly."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        assembly_ballots = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballot_ids = [k for k, v in assembly_ballots.items()]
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)

        # Check for extensions before grouping ballots.
        if any([self._update_ballot_state(rs, ballot)
                for anid, ballot in ballots.items()]):
            return self.redirect(rs, "assembly/summary_ballots")

        done, extended, current, future = self.group_ballots(ballots)

        result = {k: self.get_online_result(rs, v) for k, v in done.items()}

        return self.render(rs, "summary_ballots", {
            'ballots': done, 'ASSEMBLY_BAR_SHORTNAME': ASSEMBLY_BAR_SHORTNAME,
            'result': result})

    @access("assembly")
    @assembly_guard
    def change_ballot_form(self, rs: RequestState, assembly_id: int,
                           ballot_id: int) -> Response:
        """Render form"""
        if now() > rs.ambience['ballot']['vote_begin']:
            rs.notify("warning", n_("Unable to modify active ballot."))
            return self.redirect(rs, "assembly/show_ballot")
        merge_dicts(rs.values, rs.ambience['ballot'])
        return self.render(rs, "change_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "use_bar", "abs_quorum", "rel_quorum",
                     "votes", "notes")
    def change_ballot(self, rs: RequestState, assembly_id: int,
                      ballot_id: int, data: Dict[str, Any]) -> Response:
        """Modify a ballot."""
        data['id'] = ballot_id
        data = check(rs, "ballot", data)
        if rs.has_validation_errors():
            return self.change_ballot_form(rs, assembly_id, ballot_id)
        code = self.assemblyproxy.set_ballot(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    def ballot_start_voting(self, rs: RequestState, assembly_id: int,
                            ballot_id: int) -> Response:
        """Immediately start voting period of a ballot.
        Only possible in CDEDB_DEV mode."""
        if not self.conf["CDEDB_DEV"]:
            raise RuntimeError(
                n_("Force starting a ballot is only possible in dev mode."))

        bdata = {
            "id": ballot_id,
            "vote_begin": now() + datetime.timedelta(seconds=1),
            "vote_end": now() + datetime.timedelta(minutes=1),
        }

        code = self.assemblyproxy.set_ballot(rs, bdata)
        time.sleep(1)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata(("ack_delete", "bool"))
    def delete_ballot(self, rs: RequestState, assembly_id: int, ballot_id: int,
                      ack_delete: bool) -> Response:
        """Remove a ballot."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)
        blockers = self.assemblyproxy.delete_ballot_blockers(rs, ballot_id)
        if "vote_begin" in blockers:
            rs.notify("error", n_("Unable to remove active ballot."))
            return self.show_ballot(rs, assembly_id, ballot_id)

        # Specify what to cascade
        cascade = {"candidates", "attachments", "voters"} & blockers.keys()
        code = self.assemblyproxy.delete_ballot(rs, ballot_id, cascade=cascade)

        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/list_ballots")

    @access("assembly", modi={"POST"})
    def vote(self, rs: RequestState, assembly_id: int,
             ballot_id: int) -> Response:
        """Decide on the options of a ballot.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        ballot = rs.ambience['ballot']
        candidates = tuple(e['shortname']
                           for e in ballot['candidates'].values())
        if ballot['votes']:
            voted = unwrap(
                request_extractor(rs, (("vote", "[str]"),)))
            if rs.has_validation_errors():
                return self.show_ballot(rs, assembly_id, ballot_id)
            if voted == (ASSEMBLY_BAR_SHORTNAME,):
                if not ballot['use_bar']:
                    raise ValueError(n_("Option not available."))
                vote = "{}>{}".format(
                    ASSEMBLY_BAR_SHORTNAME, "=".join(candidates))
            elif voted == (MAGIC_ABSTAIN,):
                vote = "=".join(candidates)
                # When abstaining, the bar is equal do all candidates. This is
                # different from voting *for* all candidates.
                vote += "={}".format(ASSEMBLY_BAR_SHORTNAME)
            elif ASSEMBLY_BAR_SHORTNAME in voted and len(voted) > 1:
                rs.notify("error", n_("Rejection is exclusive."))
                return self.show_ballot(rs, assembly_id, ballot_id)
            else:
                winners = "=".join(voted)
                losers = "=".join(c for c in candidates if c not in voted)
                # When voting for certain candidates, they are ranked higher
                # than the bar (to distinguish the vote from abstaining)
                if losers:
                    losers += "={}".format(ASSEMBLY_BAR_SHORTNAME)
                else:
                    losers = ASSEMBLY_BAR_SHORTNAME
                if winners and losers:
                    vote = "{}>{}".format(winners, losers)
                else:
                    vote = winners + losers
        else:
            vote = unwrap(request_extractor(rs, (("vote", "str_or_None"),)))
            # Empty preferential vote counts as abstaining
            if not vote:
                vote = "=".join(candidates)
                if ballot['use_bar']:
                    vote += "={}".format(ASSEMBLY_BAR_SHORTNAME)
        vote = check(rs, "vote", vote, "vote", ballot=ballot)
        if rs.has_validation_errors():
            return self.show_ballot(rs, assembly_id, ballot_id)
        code = self.assemblyproxy.vote(rs, ballot_id, vote, secret=None)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly")
    def get_result(self, rs: RequestState, assembly_id: int,
                   ballot_id: int) -> Response:
        """Download the tallied stats of a ballot."""
        if not self.assemblyproxy.may_assemble(rs, ballot_id=ballot_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        result = self.assemblyproxy.get_ballot_result(rs, ballot_id)
        if not rs.ambience['ballot']['is_tallied'] or not result:
            rs.notify("warning", n_("Ballot not yet tallied."))
            return self.show_ballot(rs, assembly_id, ballot_id)
        return self.send_file(rs, data=result, inline=False,
                              filename=f"ballot_{ballot_id}_result.json")

    @access("assembly", modi={"POST"})
    @assembly_guard
    def edit_candidates(self, rs: RequestState, assembly_id: int,
                        ballot_id: int) -> Response:
        """Create, edit and delete candidates of ballot.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type ballot_id: int
        """
        candidates = process_dynamic_input(
            rs, rs.ambience['ballot']['candidates'].keys(),
            {'shortname': "restrictive_identifier", 'title': "str"})

        shortnames: Set[str] = set()
        for candidate_id, candidate in candidates.items():
            if candidate and candidate['shortname'] == ASSEMBLY_BAR_SHORTNAME:
                rs.append_validation_error(
                    (f"shortname_{candidate_id}",
                     ValueError(n_("Mustn’t be the bar shortname.")))
                )
            if candidate and candidate['shortname'] in shortnames:
                rs.append_validation_error(
                    (f"shortname_{candidate_id}",
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
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")
