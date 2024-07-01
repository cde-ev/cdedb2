#!/usr/bin/env python3

"""Services for the assembly realm."""

import datetime
import importlib.metadata
import pathlib
import shutil
import subprocess
import tempfile
import zipapp
from typing import Any, Optional

import werkzeug.exceptions
from schulze_condorcet.types import Candidate
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, RequestState, merge_dicts, now
from cdedb.common.n_ import n_
from cdedb.common.query import QueryScope
from cdedb.common.query.log_filter import AssemblyLogFilter
from cdedb.common.validation.types import CdedbID, Email
from cdedb.common.validation.validate import (
    ASSEMBLY_COMMON_FIELDS, PERSONA_FULL_CREATION, filter_none,
)
from cdedb.frontend.common import (
    AbstractUserFrontend, REQUESTdata, REQUESTdatadict, access, assembly_guard,
    cdedburl, check_validation as check,
)
from cdedb.models.ml import (
    AssemblyAssociatedMailinglist, AssemblyPresiderMailinglist, Mailinglist,
)

#: Magic value to signal abstention during _classical_ voting.
#: This can not occur as a shortname since it contains forbidden characters.
MAGIC_ABSTAIN = Candidate("special: abstain")

ASSEMBLY_BAR_ABBREVIATION = "#"


class AssemblyBaseFrontend(AbstractUserFrontend):
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
        return self.render(rs, "base/index", {
            'assemblies': assemblies, 'attendees_count': attendees_count})

    @access("core_admin", "assembly_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return self.render(rs, "base/create_user")

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
            rs, download, is_search, QueryScope.all_assembly_users,
            self.assemblyproxy.submit_general_query)

    @REQUESTdatadict(*AssemblyLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("assembly_admin", "auditor")
    def view_log(self, rs: RequestState, data: CdEDBObject, download: bool) -> Response:
        """View activities."""
        all_assemblies = self.assemblyproxy.list_assemblies(rs)
        may_view = lambda id_: self.assemblyproxy.may_assemble(rs, assembly_id=id_)

        return self.generic_view_log(
            rs, data, AssemblyLogFilter, self.assemblyproxy.retrieve_log,
            download=download, template="base/view_log", template_kwargs={
                'may_view': may_view, 'all_assemblies': all_assemblies,
            },
        )

    @REQUESTdatadict(*AssemblyLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("assembly")
    @assembly_guard
    def view_assembly_log(self, rs: RequestState, assembly_id: int, data: CdEDBObject,
                          download: bool) -> Response:
        """View activities."""
        rs.values['assembly_id'] = data['assembly_id'] = assembly_id
        return self.generic_view_log(
            rs, data, AssemblyLogFilter, self.assemblyproxy.retrieve_log,
            download=download, template="base/view_assembly_log",
        )

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
            ml_data = self._get_mailinglist_setter(rs, rs.ambience['assembly'])
            params['attendee_list_exists'] = self.mlproxy.verify_existence(
                rs, ml_data.address)

        return self.render(rs, "base/show_assembly", params)

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
        return self.render(rs, "base/configure_assembly")

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdatadict(*ASSEMBLY_COMMON_FIELDS)
    @REQUESTdata("presider_address")
    def change_assembly(self, rs: RequestState, assembly_id: int,
                        presider_address: Optional[str], data: dict[str, Any],
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
        return self.render(rs, "base/configure_assembly")

    @staticmethod
    def _get_mailinglist_setter(rs: RequestState, assembly: CdEDBObject,
                                presider: bool = False) -> Mailinglist:
        if presider:
            descr = ("Bitte wende Dich bei Fragen oder Problemen, die mit dieser"
                     " Versammlung zusammenhängen, über diese Liste an uns.")
            presider_ml_data = AssemblyPresiderMailinglist(
                id=vtypes.CreationID(vtypes.ProtoID(-1)),
                title=f"{assembly['title']} Versammlungsleitung",
                local_part=vtypes.EmailLocalPart(
                    f"{assembly['shortname'].lower()}-leitung"),
                domain=const.MailinglistDomain.lists,
                description=descr,
                mod_policy=const.ModerationPolicy.unmoderated,
                attachment_policy=const.AttachmentPolicy.allow,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=f"{assembly['shortname']}-leitung",
                maxsize=AssemblyPresiderMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                assembly_id=assembly['id'],
                notes=None,
                moderators=assembly['presiders'],
                whitelist=set(),
            )
            return presider_ml_data
        else:
            link = cdedburl(rs, "assembly/show_assembly",
                            {'assembly_id': assembly["id"]})
            descr = (f"Dieser Liste kannst Du nur beitreten, indem Du Dich direkt zu"
                     f" der [Versammlung anmeldest]({link}).")
            attendee_ml_data = AssemblyAssociatedMailinglist(
                id=vtypes.CreationID(vtypes.ProtoID(-1)),
                title=assembly["title"],
                local_part=vtypes.EmailLocalPart(assembly['shortname'].lower()),
                domain=const.MailinglistDomain.lists,
                description=descr,
                mod_policy=const.ModerationPolicy.non_subscribers,
                attachment_policy=const.AttachmentPolicy.pdf_only,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=assembly['shortname'],
                maxsize=AssemblyAssociatedMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                assembly_id=assembly["id"],
                notes=None,
                moderators=assembly['presiders'],
                whitelist=set(),
            )
            return attendee_ml_data

    @access("assembly", modi={"POST"})
    @assembly_guard
    @REQUESTdata("presider_list")
    def create_assembly_mailinglist(self, rs: RequestState, assembly_id: int,
                                    presider_list: bool) -> Response:
        if rs.has_validation_errors():
            return self.redirect(rs, "assembly/show_assembly")
        if not rs.ambience['assembly']['presiders']:
            rs.notify('error',
                      n_("Must have presiders in order to create a mailinglist."))
            return self.redirect(rs, "assembly/show_assembly")

        ml_data = self._get_mailinglist_setter(
            rs, rs.ambience['assembly'], presider_list)
        if not self.mlproxy.verify_existence(rs, ml_data.address):
            new_id = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Presider mailinglist created.") if presider_list
                   else n_("Attendee mailinglist created."))
            rs.notify_return_code(new_id, success=msg)
            if new_id and presider_list:
                data = {'id': assembly_id, 'presider_address': ml_data.address}
                self.assemblyproxy.set_assembly(rs, data)
        else:
            rs.notify("info", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_data.address})
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict(*ASSEMBLY_COMMON_FIELDS)
    @REQUESTdata("presider_ids", "create_attendee_list", "create_presider_list",
                 "presider_address")
    def create_assembly(self, rs: RequestState, presider_ids: vtypes.CdedbIDList,
                        create_attendee_list: bool, create_presider_list: bool,
                        presider_address: Optional[Email], data: dict[str, Any],
                        ) -> Response:
        """Make a new assembly."""
        if presider_ids is not None:
            data["presiders"] = presider_ids
        data = check(rs, vtypes.Assembly, data, creation=True)
        if rs.has_validation_errors():
            return self.create_assembly_form(rs)
        assert data is not None

        if not create_presider_list and presider_address:
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
            if create_presider_list or create_attendee_list:
                rs.append_validation_error(
                    ('presider_ids', ValueError(
                        n_("Must not be empty in order to create a mailinglist."))))
        if rs.has_validation_errors():
            # as there may be other notifications already, notify errors explicitly
            rs.notify_validation()
            return self.create_assembly_form(rs)
        assert data is not None
        new_id = self.assemblyproxy.create_assembly(rs, data)
        data["id"] = new_id

        if create_presider_list:
            if presider_address:
                rs.notify("info", n_("Given presider address ignored in favor of"
                                     " newly created mailinglist."))
            presider_ml_data = self._get_mailinglist_setter(rs, data, presider=True)
            if self.mlproxy.verify_existence(rs, presider_ml_data.address):
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': presider_ml_data.address})
            else:
                code = self.mlproxy.create_mailinglist(rs, presider_ml_data)
                rs.notify_return_code(code, success=n_("Presider mailinglist created."))
            code = self.assemblyproxy.set_assembly(
                rs, {"id": new_id, "presider_address": presider_ml_data.address},
                change_note="Mailadresse der Versammlungsleitung gesetzt.")
            rs.notify_return_code(code)
        if create_attendee_list:
            attendee_ml_data = self._get_mailinglist_setter(rs, data)
            if not self.mlproxy.verify_existence(rs, attendee_ml_data.address):
                code = self.mlproxy.create_mailinglist(rs, attendee_ml_data)
                rs.notify_return_code(code, success=n_("Attendee mailinglist created."))
            else:
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': attendee_ml_data.address})
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

    def process_signup(self, rs: RequestState, assembly_id: int,
                       persona_id: Optional[int] = None) -> None:
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
            # This is no actual Reply-To to avoid people leaking their secret.
            contact_address = (rs.ambience['assembly']['presider_address'] or
                               self.conf["ASSEMBLY_ADMIN_ADDRESS"])
            self.do_mail(
                rs, "signup",
                {'From': self.conf["NOREPLY_ADDRESS"],
                 'To': (persona['username'],),
                 'Subject': subject},
                {'secret': secret, 'persona': persona,
                 'contact_address': contact_address})
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

    @access("assembly")
    def list_attendees(self, rs: RequestState, assembly_id: int) -> Response:
        """Provide a online list of who is/was present."""
        if not self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id):  # pragma: no cover
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        attendees = self.assemblyproxy.get_attendees(rs, assembly_id, cutoff=now())
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        if ballots:
            rs.values['cutoff'] = max(b['vote_begin'] for b in ballots.values())
        return self.render(rs, "base/list_attendees", {"attendees": attendees})

    @access("assembly")
    @assembly_guard
    @REQUESTdata("cutoff")
    def download_list_attendees(self, rs: RequestState, assembly_id: int,
                                cutoff: datetime.datetime) -> Response:
        """Provides a tex-snipped with all attendes of an assembly."""
        if rs.has_validation_errors() or not cutoff:
            return self.list_attendees(rs, assembly_id)

        attendees = self.assemblyproxy.get_attendees(rs, assembly_id, cutoff=cutoff)
        if not attendees.all:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "assembly/list_attendees")

        tex = self.fill_template(
            rs, "tex", "list_attendees", {'attendees': attendees})
        return self.send_file(
            rs, data=tex, inline=False,
            filename=f"Anwesenheitsliste ({rs.ambience['assembly']['shortname']}).tex")

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
