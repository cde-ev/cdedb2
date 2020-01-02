#!/usr/bin/env python3

"""Services for the assembly realm."""

import copy
import hashlib
import json
import pathlib
import collections
import datetime
import time

import werkzeug.exceptions

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access, csv_output,
    check_validation as check, request_extractor, query_result_to_json)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input
from cdedb.common import (
    n_, merge_dicts, unwrap, now, ProxyShim,
    ASSEMBLY_BAR_MONIKER, EntitySorter)
from cdedb.backend.cde import CdEBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database.connection import Atomizer

#: Magic value to signal abstention during voting. Used during the emulation
#: of classical voting. This can not occur as a moniker since it contains
#: forbidden characters.
MAGIC_ABSTAIN = "special: abstain"


class AssemblyFrontend(AbstractUserFrontend):
    """Organize congregations and vote on ballots."""
    realm = "assembly"
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_assembly_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.assemblyproxy = ProxyShim(AssemblyBackend(configpath))
        self.cdeproxy = ProxyShim(CdEBackend(configpath))

    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def is_ballot_voting(ballot):
        """Determine whether a ballot is open for voting.

        :type ballot: {str: object}
        :rtype: bool
        """
        timestamp = now()
        return (timestamp > ballot['vote_begin']
                and (timestamp < ballot['vote_end']
                     or (ballot['extended']
                         and timestamp < ballot['vote_extension_end'])))

    def may_assemble(self, rs, *, assembly_id=None, ballot_id=None):
        """Helper to check authorization.

        The deal is that members may access anything and assembly users
        may access any assembly in which they are participating. This
        especially allows people who have "cde", but not "member" in
        their roles, to access only those assemblies they participated
        in.

        Exactly one of the two id parameters has to be provided

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type ballot_id: int
        :rtype: bool
        """
        if "member" in rs.user.roles:
            return True
        return self.assemblyproxy.does_attend(
            rs, assembly_id=assembly_id, ballot_id=ballot_id)

    @access("assembly")
    def index(self, rs):
        """Render start page."""
        assemblies = self.assemblyproxy.list_assemblies(rs)
        return self.render(rs, "index", {'assemblies': assemblies})

    @access("assembly_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict(
        "given_names", "family_name", "display_name", "notes", "username")
    def create_user(self, rs, data):
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("assembly_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs, download, is_search):
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        default_queries = self.conf.DEFAULT_QUERIES['qview_assembly_user']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'choices_lists': {}, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_persona"
            result = self.assemblyproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                if download == "csv":
                    csv_data = csv_output(result, fields)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="user_search_result.csv")
                elif download == "json":
                    json_data = query_result_to_json(result, fields)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="user_search_result.json")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("assembly_admin")
    @REQUESTdata(("codes", "[int]"), ("assembly_id", "id_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs, codes, assembly_id, start, stop, persona_id,
                 submitted_by, additional_info, time_start, time_stop):
        """View activities."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.assemblyproxy.retrieve_log(
            rs, codes, assembly_id, start, stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
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
        return self.render(rs, "view_log", {
            'log': log, 'personas': personas,
            'assemblies': assemblies, 'all_assemblies': all_assemblies})

    @access("assembly_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_assembly_log(self, rs, codes, assembly_id, start, stop, persona_id,
                 submitted_by, additional_info, time_start, time_stop):
        """View activities."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.assemblyproxy.retrieve_log(
            rs, codes, assembly_id, start, stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        personas = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_assembly_log", {
            'log': log, 'personas': personas})

    @access("assembly")
    def show_assembly(self, rs, assembly_id):
        """Present an assembly."""
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attends = self.assemblyproxy.does_attend(rs, assembly_id=assembly_id)
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)

        has_ballot_attachments = False
        ballot_attachments = {}
        for ballot_id in ballot_ids:
            ballot_attachment_ids = self.assemblyproxy.list_attachments(
                rs, ballot_id=ballot_id)
            ballot_attachments[ballot_id] = self.assemblyproxy.get_attachments(
                rs, ballot_attachment_ids)
            has_ballot_attachments = has_ballot_attachments or bool(
                ballot_attachment_ids)

        if self.is_admin(rs):
            conclude_blockers = self.assemblyproxy.conclude_assembly_blockers(
                rs, assembly_id)
            delete_blockers = self.assemblyproxy.delete_assembly_blockers(
                rs, assembly_id)
        else:
            conclude_blockers = {"is_admin": False}
            delete_blockers = {"is_admin": False}

        return self.render(rs, "show_assembly", {
            "attachments": attachments, "attends": attends, "ballots": ballots,
            "delete_blockers": delete_blockers,
            "conclude_blockers": conclude_blockers,
            "ballot_attachments": ballot_attachments,
            "has_ballot_attachments": has_ballot_attachments})

    @access("assembly_admin")
    def change_assembly_form(self, rs, assembly_id):
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        merge_dicts(rs.values, rs.ambience['assembly'])
        return self.render(rs, "change_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "mail_address", "signup_end",
                     "notes")
    def change_assembly(self, rs, assembly_id, data):
        """Modify an assembly."""
        data['id'] = assembly_id
        data = check(rs, "assembly", data)
        if rs.errors:
            return self.change_assembly_form(rs, assembly_id)
        code = self.assemblyproxy.set_assembly(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin")
    def create_assembly_form(self, rs):
        """Render form."""
        return self.render(rs, "create_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "signup_end", "notes")
    def create_assembly(self, rs, data):
        """Make a new assembly."""
        data = check(rs, "assembly", data, creation=True)
        if rs.errors:
            return self.create_assembly_form(rs)
        new_id = self.assemblyproxy.create_assembly(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "assembly/show_assembly", {
            'assembly_id': new_id})

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    def delete_assembly(self, rs, assembly_id, ack_delete):
        if not ack_delete:
            rs.errors.append(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_assembly(rs, assembly_id)
        blockers = self.assemblyproxy.delete_assembly_blockers(rs, assembly_id)
        if "vote_begin" in blockers:
            rs.notify("error",
                      ValueError(n_("Unable to remove active ballot.")))
            return self.show_assembly(rs, assembly_id)

        # Specify what to cascade
        cascade = {"ballots", "attendees", "attachments", "log",
                   "mailinglists"} & blockers.keys()
        code = self.assemblyproxy.delete_assembly(
            rs, assembly_id, cascade=cascade)

        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/index")

    def process_signup(self, rs, assembly_id, persona_id=None):
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
            subject = "[CdE] Teilnahme an {}".format(
                rs.ambience['assembly']['title'])
            reply_to = (rs.ambience['assembly']['mail_address'] or
                        self.conf.ASSEMBLY_ADMIN_ADDRESS)
            self.do_mail(
                rs, "signup",
                {'To': (persona['username'],),
                 'Subject': subject,
                 'Reply-To': reply_to},
                {'secret': secret, 'persona': persona})
        else:
            rs.notify("info", n_("Already signed up."))

    @access("member", modi={"POST"})
    def signup(self, rs, assembly_id):
        """Join an assembly."""
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/show_assembly")
        if rs.errors:
            return self.show_assembly(rs, assembly_id)
        self.process_signup(rs, assembly_id)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "cdedbid"))
    def external_signup(self, rs, assembly_id, persona_id):
        """Add an external participant to an assembly."""
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", n_("Signup already ended."))
            return self.redirect(rs, "assembly/list_attendees")
        if rs.errors:
            return self.list_attendees(rs, assembly_id)
        self.process_signup(rs, assembly_id, persona_id)
        return self.redirect(rs, "assembly/list_attendees")

    @access("assembly")
    def list_attendees(self, rs, assembly_id):
        """Provide a list of who is/was present."""
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        attendee_ids = self.assemblyproxy.list_attendees(rs, assembly_id)
        attendees = collections.OrderedDict(
            (e['id'], e) for e in sorted(
                self.coreproxy.get_assembly_users(rs, attendee_ids).values(),
                key=EntitySorter.persona))
        return self.render(rs, "list_attendees", {"attendees": attendees})

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("ack_conclude", "bool"))
    def conclude_assembly(self, rs, assembly_id, ack_conclude):
        """Archive an assembly.

        This purges stored voting secret.
        """
        if not ack_conclude:
            rs.errors.append(
                ("ack_conclude", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_assembly(rs, assembly_id)

        blockers = self.assemblyproxy.conclude_assembly_blockers(
            rs, assembly_id)

        if "ballot" in blockers:
            rs.notify("error",
                      ValueError(n_("Unable to conclude assembly with "
                                    "open ballot.")))
            return self.show_assembly(rs, assembly_id)

        cascade = {"signup_end"}
        code = self.assemblyproxy.conclude_assembly(rs, assembly_id, cascade)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_assembly")

    @staticmethod
    def group_ballots(ballots):
        """Helper to group ballots by status.

        :type ballots: {int: str}
        :rtype: tuple({int: str})
        :returns: Four dicts mapping ballot ids to ballots grouped by status 
          in the order done, extended, current, future.
        """
        ref = now()

        future = {k: v for k, v in ballots.items()
                  if v['vote_begin'] > ref}
        current = {k: v for k, v in ballots.items()
                   if v['vote_begin'] <= ref < v['vote_end']}
        extended = {k: v for k, v in ballots.items()
                    if (v['extended']
                        and v['vote_end'] <= ref < v['vote_extension_end'])}
        done = {k: v for k, v in ballots.items()
                if (v['vote_end'] <= ref
                    and (v['extended'] is False
                         or v['vote_extension_end'] <= ref))}

        assert (len(ballots) == len(future) + len(current) +
                len(extended) + len(done))

        return done, extended, current, future

    @access("assembly")
    def list_ballots(self, rs, assembly_id):
        """View available ballots for an assembly."""
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)

        # Check for extensions before grouping ballots.
        ref = now()
        update = False
        for ballot_id, ballot in ballots.items():
            if ballot['extended'] is None and ref > ballot['vote_end']:
                self.assemblyproxy.check_voting_priod_extension(rs, ballot_id)
                update = True
        if update:
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

    @access("assembly_admin")
    def create_ballot_form(self, rs, assembly_id):
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", n_("Assembly already concluded."))
            return self.redirect(rs, "assembly/show_assembly")
        return self.render(rs, "create_ballot")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "quorum", "votes", "notes",
                     "use_bar")
    def create_ballot(self, rs, assembly_id, data):
        """Make a new ballot."""
        data['assembly_id'] = assembly_id
        data = check(rs, "ballot", data, creation=True)
        if rs.errors:
            return self.create_ballot_form(rs, assembly_id)
        new_id = self.assemblyproxy.create_ballot(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "assembly/show_ballot", {
            'ballot_id': new_id})

    @access("assembly")
    # ballot_id is optional, but comes semantically before attachment_id
    def get_attachment(self, rs, assembly_id, attachment_id, ballot_id=None):
        """Retrieve an attachment."""
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        path = (self.conf.STORAGE_DIR / "assembly_attachment"
                / str(attachment_id))
        return self.send_file(rs, path=path, mimetype="application/pdf",
                              filename=rs.ambience['attachment']['filename'])

    @access("assembly_admin")
    def add_attachment_form(self, rs, assembly_id, ballot_id=None):
        """Render form."""
        if ballot_id and now() > rs.ambience['ballot']['vote_begin']:
            rs.notify("warning", n_("Voting has already begun."))
            return self.redirect(rs, "assembly/show_ballot")
        return self.render(rs, "add_attachment")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("title", "str"), ("filename", "identifier_or_None"))
    @REQUESTfile("attachment")
    # ballot_id is optional, but comes semantically after assembly_id
    def add_attachment(self, rs, assembly_id, title, filename,
                       attachment, ballot_id=None):
        """Create a new attachment.

        It can either be associated to an assembly or a ballot.
        """
        if attachment and not filename:
            tmp = pathlib.Path(attachment.filename).parts[-1]
            filename = check(rs, "identifier", tmp, 'filename')
        attachment = check(rs, "pdffile", attachment, 'attachment')
        if rs.errors:
            return self.add_attachment_form(rs, assembly_id=assembly_id,
                                            ballot_id=ballot_id)
        data = {
            'title': title,
            'filename': filename
        }
        if ballot_id:
            data['ballot_id'] = ballot_id
        else:
            data['assembly_id'] = assembly_id
        attachment_id = self.assemblyproxy.add_attachment(rs, data, attachment)
        self.notify_return_code(rs, attachment_id,
                                success=n_("Attachment added."))
        if ballot_id:
            return self.redirect(rs, "assembly/show_ballot")
        else:
            return self.redirect(rs, "assembly/show_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("attachment_ack_delete", "bool"))
    # ballot_id is optional, but comes semantically before attachment_id
    def remove_attachment(self, rs, assembly_id, attachment_id,
                          attachment_ack_delete, ballot_id=None):
        """Delete an attachment."""
        if not attachment_ack_delete:
            rs.errors.append(
                ("attachment_ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            if ballot_id:
                return self.show_ballot(rs, assembly_id, ballot_id)
            else:
                return self.show_assembly(rs, assembly_id)
        with Atomizer(rs):
            code = self.assemblyproxy.remove_attachment(rs, attachment_id)
            self.notify_return_code(rs, code)
        if ballot_id:
            return self.redirect(rs, "assembly/show_ballot")
        else:
            return self.redirect(rs, "assembly/show_assembly")

    @access("assembly", modi={"POST"})
    @REQUESTdata(("secret", "str"))
    def show_old_vote(self, rs, assembly_id, ballot_id, secret):
        """Show a vote in a ballot of an old assembly by providing secret."""
        if (rs.ambience["assembly"]["is_active"] or
                not rs.ambience["ballot"]["is_tallied"] or rs.errors):
            return self.show_ballot(rs, assembly_id, ballot_id)
        return self.show_ballot(rs, assembly_id, ballot_id, secret.strip())

    @access("assembly")
    def show_ballot(self, rs, assembly_id, ballot_id, secret=None):
        """Present a ballot.

        This has pretty expansive functionality. It especially checks
        for timeouts and initiates for example tallying.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).

        If a secret is provided, this will fetch the vote beloging to that
        secret.
        """
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        ballot = rs.ambience['ballot']
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, ballot_id=ballot_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        timestamp = now()
        # check whether we need to initiate extension
        if (ballot['extended'] is None
                and timestamp > ballot['vote_end']):
            self.assemblyproxy.check_voting_priod_extension(rs, ballot_id)
            return self.redirect(rs, "assembly/show_ballot")
        finished = (
                timestamp > ballot['vote_end']
                and (not ballot['extended']
                     or timestamp > ballot['vote_extension_end']))
        # check whether we need to initiate tallying
        if finished and not ballot['is_tallied']:
            did_tally = self.assemblyproxy.tally_ballot(rs, ballot_id)
            if did_tally:
                path = self.conf.STORAGE_DIR / "ballot_result" / str(ballot_id)
                attachment_result = {
                    'path': path,
                    'filename': 'result.json',
                    'mimetype': 'application/json'}
                to = [self.conf.BALLOT_TALLY_ADDRESS]
                if rs.ambience['assembly']['mail_address']:
                    to.append(rs.ambience['assembly']['mail_address'])
                subject = "Abstimmung '{}' ausgezählt".format(ballot['title'])
                hasher = hashlib.sha512()
                with open(path, 'rb') as resultfile:
                    hasher.update(resultfile.read())
                self.do_mail(
                    rs, "ballot_tallied", {'To': to, 'Subject': subject},
                    attachments=(attachment_result,),
                    params={'sha': hasher.hexdigest()})
            return self.redirect(rs, "assembly/show_ballot")
        # initial checks done, present the ballot
        ballot['is_voting'] = self.is_ballot_voting(ballot)
        result = None
        if ballot['is_tallied']:
            path = self.conf.STORAGE_DIR / 'ballot_result' / str(ballot_id)
            with open(path) as f:
                result = json.load(f)
            tiers = tuple(x.split('=') for x in result['result'].split('>'))
            winners = []
            losers = []
            tmp = winners
            lookup = {e['moniker']: e['id']
                      for e in ballot['candidates'].values()}
            for tier in tiers:
                # Remove bar if present
                ntier = tuple(lookup[x] for x in tier if x in lookup)
                if ntier:
                    tmp.append(ntier)
                if ASSEMBLY_BAR_MONIKER in tier:
                    tmp = losers
            result['winners'] = winners
            result['losers'] = losers
            result['counts'] = None  # Will be used for classical voting
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
        if ballot['votes']:
            if split_vote:
                if len(split_vote) == 1:
                    # abstention
                    rs.values['vote'] = MAGIC_ABSTAIN
                else:
                    # select voted options
                    rs.values.setlist('vote', split_vote[0])
            if result:
                counts = {e['moniker']: 0
                          for e in ballot['candidates'].values()}
                for v in result['votes']:
                    raw = v['vote']
                    if '>' in raw:
                        selected = raw.split('>')[0].split('=')
                        for s in selected:
                            if s in counts:
                                counts[s] += 1
                result['counts'] = counts
        candidates = {e['moniker']: e
                      for e in ballot['candidates'].values()}
        if ballot['use_bar']:
            candidates[ASSEMBLY_BAR_MONIKER] = rs.gettext(
                "bar (options below this are declined)")

        ballots_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballots_ids)
        done, extended, current, future = self.group_ballots(ballots)

        # Currently we don't distinguish between current and extended ballots
        current.update(extended)
        ballot_list = sum((sorted(bdict, key=lambda key: bdict[key]["title"])
                           for bdict in (done, current, future)), [])

        i = ballot_list.index(ballot_id)
        l = len(ballot_list)
        prev_ballot = ballots[ballot_list[i-1]] if i > 0 else None
        next_ballot = ballots[ballot_list[i+1]] if i + 1 < l else None

        return self.render(rs, "show_ballot", {
            'attachments': attachments, 'split_vote': split_vote,
            'own_vote': own_vote, 'result': result, 'candidates': candidates,
            'attends': attends, 'ASSEMBLY_BAR_MONIKER': ASSEMBLY_BAR_MONIKER,
            'prev_ballot': prev_ballot, 'next_ballot': next_ballot,
            'secret': secret, 'has_voted': has_voted,
        })

    @access("assembly_admin")
    def change_ballot_form(self, rs, assembly_id, ballot_id):
        """Render form"""
        if now() > rs.ambience['ballot']['vote_begin']:
            rs.notify("warning", n_("Unable to modify active ballot."))
            return self.redirect(rs, "assembly/show_ballot")
        merge_dicts(rs.values, rs.ambience['ballot'])
        return self.render(rs, "change_ballot")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "use_bar", "quorum", "votes",
                     "notes")
    def change_ballot(self, rs, assembly_id, ballot_id, data):
        """Modify a ballot."""
        data['id'] = ballot_id
        data = check(rs, "ballot", data)
        if rs.errors:
            return self.change_ballot_form(rs, assembly_id, ballot_id)
        code = self.assemblyproxy.set_ballot(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly_admin", modi={"POST"})
    def ballot_start_voting(self, rs, assembly_id, ballot_id):
        """Immediately start voting period of a ballot.
        Only possible in CDEDB_DEV mode."""
        if not self.conf.CDEDB_DEV:
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

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    def delete_ballot(self, rs, assembly_id, ballot_id, ack_delete):
        """Remove a ballot."""
        if not ack_delete:
            rs.errors.append(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_ballot(rs, assembly_id, ballot_id)
        blockers = self.assemblyproxy.delete_ballot_blockers(rs, ballot_id)
        if "vote_begin" in blockers:
            rs.notify("error",
                      ValueError(n_("Unable to remove active ballot.")))
            return self.show_ballot(rs, assembly_id, ballot_id)

        # Specify what to cascade
        cascade = {"candidates", "attachments", "voters"} & blockers.keys()
        code = self.assemblyproxy.delete_ballot(rs, ballot_id, cascade=cascade)

        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/list_ballots")

    @access("assembly", modi={"POST"})
    def vote(self, rs, assembly_id, ballot_id):
        """Decide on the options of a ballot.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        ballot = rs.ambience['ballot']
        candidates = tuple(e['moniker']
                           for e in ballot['candidates'].values())
        if ballot['votes']:
            voted = unwrap(
                request_extractor(rs, (("vote", "[str]"),)))
            if rs.errors:
                return self.show_ballot(rs, assembly_id, ballot_id)
            if voted == (ASSEMBLY_BAR_MONIKER,):
                if not ballot['use_bar']:
                    raise ValueError(n_("Option not available."))
                vote = "{}>{}".format(
                    ASSEMBLY_BAR_MONIKER, "=".join(candidates))
            elif voted == (MAGIC_ABSTAIN,):
                vote = "=".join(candidates)
                # When abstaining, the bar is equal do all candidates. This is
                # different from voting *for* all candidates.
                vote += "={}".format(ASSEMBLY_BAR_MONIKER)
            elif ASSEMBLY_BAR_MONIKER in voted and len(voted) > 1:
                rs.notify("error", n_("Rejection is exclusive."))
                return self.show_ballot(rs, assembly_id, ballot_id)
            else:
                winners = "=".join(voted)
                losers = "=".join(c for c in candidates if c not in voted)
                # When voting for certain candidates, they are ranked higher
                # than the bar (to distinguish the vote from abstaining)
                if losers:
                    losers += "={}".format(ASSEMBLY_BAR_MONIKER)
                else:
                    losers = ASSEMBLY_BAR_MONIKER
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
                    vote += "={}".format(ASSEMBLY_BAR_MONIKER)
        vote = check(rs, "vote", vote, "vote", ballot=ballot)
        if rs.errors:
            return self.show_ballot(rs, assembly_id, ballot_id)
        code = self.assemblyproxy.vote(rs, ballot_id, vote, secret=None)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly")
    def get_result(self, rs, assembly_id, ballot_id):
        """Download the tallied stats of a ballot."""
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not rs.ambience['ballot']['is_tallied']:
            rs.notify("warning", n_("Ballot not yet tallied."))
            return self.show_ballot(rs, assembly_id, ballot_id)
        path = self.conf.STORAGE_DIR / 'ballot_result' / str(ballot_id)
        return self.send_file(rs, path=path, inline=False,
                              filename="ballot_{}_result.json".format(ballot_id))

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("moniker", "restrictive_identifier"), ("description", "str"))
    def add_candidate(self, rs, assembly_id, ballot_id, moniker, description):
        """Create a new option for a ballot."""
        monikers = {c['moniker']
                    for c in rs.ambience['ballot']['candidates'].values()}
        if moniker in monikers:
            rs.errors.append(("moniker", ValueError(n_("Duplicate moniker."))))
        if moniker == ASSEMBLY_BAR_MONIKER:
            rs.errors.append(
                ("moniker", ValueError(n_("Mustn’t be the bar moniker."))))
        if rs.errors:
            return self.show_ballot(rs, assembly_id, ballot_id)
        data = {
            'id': ballot_id,
            'candidates': {
                -1: {
                    'moniker': moniker,
                    'description': description,
                }
            }
        }
        code = self.assemblyproxy.set_ballot(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")

    @access("assembly_admin", modi={"POST"})
    def remove_candidate(self, rs, assembly_id, ballot_id, candidate_id):
        """Delete an option from a ballot."""
        if rs.errors:
            return self.show_ballot(rs, assembly_id, ballot_id)
        data = {
            'id': ballot_id,
            'candidates': {
                candidate_id: None
            }
        }
        code = self.assemblyproxy.set_ballot(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")
