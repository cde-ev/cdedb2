#!/usr/bin/env python3

"""Services for the assembly realm."""

import json
import logging
import os

import werkzeug

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access,
    check_validation as check, request_extractor)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input
from cdedb.common import merge_dicts, unwrap, now, ProxyShim
import cdedb.database.constants as const
from cdedb.backend.cde import CdEBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database.connection import Atomizer


#: Magic value to signal abstention during voting. Used during the emulation
#: of classical voting. This can not occur as a moniker since it contains
#: forbidden characters.
MAGIC_ABSTAIN = "special: abstain"
#: Magic value to signal none of the above during voting. Used during the
#: emulation of classical voting. This can not occur as a moniker since it
#: contains forbidden characters.
MAGIC_NONE_OF_THEM = "special: none"

class AssemblyFrontend(AbstractUserFrontend):
    """Organize congregations and vote on ballots."""
    realm = "assembly"
    logger = logging.getLogger(__name__)
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_assembly_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.assemblyproxy = ProxyShim(AssemblyBackend(configpath))
        self.cdeproxy = ProxyShim(CdEBackend(configpath))

    def finalize_session(self, rs, auxilliary=False):
        super().finalize_session(rs, auxilliary=auxilliary)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        """Render start page."""
        assemblies = self.assemblyproxy.list_assemblies(rs)
        return self.render(rs, "index", {'assemblies': assemblies})

    @access("assembly_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
            'cloud_account': False,
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

    @access("anonymous")
    @REQUESTdata(("secret", "str"))
    def genesis_form(self, rs, case_id, secret):
        """Assembly accounts cannot be requested."""
        raise NotImplementedError("Not available in assembly realm.")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict("display_name",)
    def genesis(self, rs, case_id, secret, data):
        """Assembly accounts cannot be requested."""
        raise NotImplementedError("Not available in assembly realm.")

    @access("assembly_admin")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    def user_search(self, rs, CSV, is_search):
        """Perform search."""
        spec = QUERY_SPECS['qview_persona']
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        default_queries = self.conf.DEFAULT_QUERIES['qview_persona']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_persona"
            result = self.assemblyproxy.submit_general_query(rs, query)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("assembly_admin")
    @REQUESTdata(("codes", "[int]"), ("assembly_id", "id_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_log(self, rs, codes, assembly_id, start, stop):
        """View activities."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.assemblyproxy.retrieve_log(rs, codes, assembly_id, start,
                                              stop)
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, personas)
        assemblies = {entry['assembly_id']
                      for entry in log if entry['assembly_id']}
        assemblies = self.assemblyproxy.get_assemblies(rs, assemblies)
        all_assemblies = self.assemblyproxy.list_assemblies(rs)
        return self.render(rs, "view_log", {
            'log': log, 'personas': personas,
            'assemblies': assemblies, 'all_assemblies': all_assemblies})

    @access("assembly")
    def show_assembly(self, rs, assembly_id):
        """Present an assembly."""
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, assembly_id=assembly_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        attends = self.assemblyproxy.does_attend(rs, assembly_id=assembly_id)
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        timestamp = now()
        has_activity = False
        if timestamp < rs.ambience['assembly']['signup_end']:
            has_activity = True
        if any((ballot['extended'] is None
                or timestamp < ballot['vote_end']
                or (ballot['extended']
                    and timestamp < ballot['vote_extension_end']))
               for ballot in ballots.values()):
            has_activity = True
        return self.render(rs, "show_assembly", {
            "attachments": attachments, "attends": attends,
            "has_activity": has_activity})

    @access("assembly_admin")
    def change_assembly_form(self, rs, assembly_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['assembly'])
        return self.render(rs, "change_assembly")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "signup_end", "notes")
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

    @access("assembly", modi={"POST"})
    def signup(self, rs, assembly_id):
        """Join an assembly."""
        if now() > rs.ambience['assembly']['signup_end']:
            rs.notify("warning", "Signup already ended.")
            return self.redirect(rs, "assembly/show_assembly")
        secret = self.assemblyproxy.signup(rs, assembly_id)
        if secret:
            rs.notify("success", "Signed up.")
            attachment = {
                'path': os.path.join(self.conf.REPOSITORY_PATH,
                                     "bin/verify_votes.py"),
                'filename': 'verify_votes.py',
                'mimetype': 'text/plain'}
            self.do_mail(
                rs, "signup",
                {'To': (rs.user.username,),
                 'Subject': 'Signed up for assembly {}'.format(
                     rs.ambience['assembly']['title'])},
                {'secret': secret}, attachments=(attachment,))
        else:
            rs.notify("info", "Already signed up.")
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly")
    def list_attendees(self, rs, assembly_id):
        """Provide a list of who is/was present."""
        attendee_ids = self.assemblyproxy.list_attendees(rs, assembly_id)
        attendees = self.coreproxy.get_assembly_users(rs, attendee_ids)
        return self.render(rs, "list_attendees", {"attendees": attendees})

    @access("assembly_admin", modi={"POST"})
    def conclude_assembly(self, rs, assembly_id):
        """Archive an assembly.

        This purges stored voting secret.
        """
        code = self.assemblyproxy.conclude_assembly(rs, assembly_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_assembly")

    @access("assembly")
    def list_ballots(self, rs, assembly_id):
        """View available ballots for an assembly."""
        ballot_ids = self.assemblyproxy.list_ballots(rs, assembly_id)
        ballots = self.assemblyproxy.get_ballots(rs, ballot_ids)
        return self.render(rs, "list_ballots", {'ballots': ballots})

    @access("assembly_admin")
    def create_ballot_form(self, rs, assembly_id):
        """Render form."""
        if not rs.ambience['assembly']['is_active']:
            rs.notify("warning", "Assembly already concluded.")
            return self.redirect(rs, "assembly/show_assembly")
        return self.render(rs, "create_ballot")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "quorum", "votes", "notes")
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
    ## ballot_id is optional, but comes semantically before attachment_id
    def get_attachment(self, rs, assembly_id, attachment_id, ballot_id=None):
        """Retrieve an attachment."""
        path = os.path.join(self.conf.STORAGE_DIR, "assembly_attachment",
                            str(attachment_id))
        return self.send_file(rs, path=path,
                              filename=rs.ambience['attachment']['filename'])

    @access("assembly_admin")
    @REQUESTdata(("assembly_id", "id_or_None"), ("ballot_id", "id_or_None"))
    def add_attachment_form(self, rs, assembly_id, ballot_id):
        """Render form."""
        if (assembly_id and ballot_id) or (not assembly_id and not ballot_id):
            return werkzeug.exceptions.BadRequest(
                "Exactly one of assembly_id and ballot_id must be provided.")
        if assembly_id:
            ballot = None
            assembly = self.assemblyproxy.get_assembly(rs, assembly_id)
        else:
            ballot = self.assemblyproxy.get_ballot(rs, ballot_id)
            assembly = self.assemblyproxy.get_assembly(rs,
                                                       ballot['assembly_id'])
            if now() > ballot['vote_begin']:
                rs.notify("warning", "Voting has begun.")
                return self.redirect(rs, "assembly/show_ballot", {
                    'assembly_id': ballot['assembly_id'],
                    'ballot_id': ballot_id})
        return self.render(rs, "add_attachment", {
            'assembly': assembly, 'ballot': ballot})

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("assembly_id", "id_or_None"), ("ballot_id", "id_or_None"),
                 ("title", "str"), ("filename", "identifier_or_None"))
    @REQUESTfile("attachment")
    def add_attachment(self, rs, assembly_id, ballot_id, title, filename,
                       attachment):
        """Create a new attachment.

        It can either be associated to an assembly or a ballot.
        """
        if (assembly_id and ballot_id) or (not assembly_id and not ballot_id):
            rs.errors.append(("assembly_id",
                              ValueError("Exactly one must be selected.")))
            rs.errors.append(("ballot_id",
                              ValueError("Exactly one must be selected.")))
        if not filename:
            tmp = os.path.basename(attachment.filename)
            filename = check(rs, "identifier", tmp, 'attachment')
        attachment = check(rs, "pdffile", attachment, 'attachment')
        if rs.errors:
            return self.add_attachment_form(rs, assembly_id=assembly_id,
                                            ballot_id=ballot_id)
        data = {
            'title': title,
            'filename': filename
        }
        if assembly_id:
            data['assembly_id'] = assembly_id
        if ballot_id:
            data['ballot_id'] = ballot_id
        attachment_id = self.assemblyproxy.add_attachment(rs, data)
        path = os.path.join(self.conf.STORAGE_DIR, 'assembly_attachment',
                            str(attachment_id))
        with open(path, 'wb') as f:
            f.write(attachment)
        self.notify_return_code(rs, attachment_id, success="Attachment added.")
        if assembly_id:
            return self.redirect(rs, "assembly/show_assembly",
                                 {'assembly_id': assembly_id})
        else:
            ballot = self.assemblyproxy.get_ballot(rs, ballot_id)
            return self.redirect(rs, "assembly/show_ballot", {
                'assembly_id': ballot['assembly_id'],
                'ballot_id': ballot_id})

    @access("assembly_admin", modi={"POST"})
    ## ballot_id is optional, but comes semantically before attachment_id
    def remove_attachment(self, rs, assembly_id, attachment_id, ballot_id=None):
        """Delete an attachment."""
        with Atomizer(rs):
            code = self.assemblyproxy.remove_attachment(rs, attachment_id)
            self.notify_return_code(rs, code)
            path = os.path.join(self.conf.STORAGE_DIR, 'assembly_attachment',
                                str(attachment_id))
            os.remove(path)
        if ballot_id:
            return self.redirect(rs, "assembly/show_ballot")
        else:
            return self.redirect(rs, "assembly/show_assembly")

    @access("assembly")
    def show_ballot(self, rs, assembly_id, ballot_id):
        """Present a ballot.

        This has pretty expansive functionality. It especially checks
        for timeouts and initiates for example tallying.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        ballot = rs.ambience['ballot']
        attachment_ids = self.assemblyproxy.list_attachments(
            rs, ballot_id=ballot_id)
        attachments = self.assemblyproxy.get_attachments(rs, attachment_ids)
        timestamp = now()
        if (ballot['extended'] is None
                and timestamp > ballot['vote_end']):
            self.assemblyproxy.check_voting_priod_extension(rs, ballot_id)
            return self.redirect(rs, "assembly/show_ballot")
        finished = (
            timestamp > ballot['vote_end']
            and (not ballot['extended']
                 or timestamp > ballot['vote_extension_end']))
        if finished and not ballot['is_tallied']:
            did_tally = self.assemblyproxy.tally_ballot(rs, ballot_id)
            if did_tally:
                attendee_ids = self.assemblyproxy.list_attendees(rs,
                                                                 assembly_id)
                attendees = self.coreproxy.get_assembly_users(rs, attendee_ids)
                mails = tuple(x['username'] for x in attendees.values())
                attachment_script = {
                    'path': os.path.join(self.conf.REPOSITORY_PATH,
                                         "bin/verify_votes.py"),
                    'filename': 'verify_votes.py',
                    'mimetype': 'text/plain'}
                attachment_result = {
                    'path': os.path.join(self.conf.STORAGE_DIR,
                                         "ballot_result", str(ballot_id)),
                    'filename': 'result.json',
                    'mimetype': 'application/json'}
                self.do_mail(
                    rs, "ballot_tallied",
                    {'To': (self.conf.MANAGEMENT_ADDRESS,),
                     'Bcc': mails,
                     'Subject': "Ballot '{}' got tallied".format(
                         ballot['title'])},
                    attachments=(attachment_script, attachment_result,))
            return self.redirect(rs, "assembly/show_ballot")
        ballot['is_voting'] = (
            timestamp > ballot['vote_begin']
            and (timestamp < ballot['vote_end']
                 or (ballot['extended']
                     and timestamp < ballot['vote_extension_end'])))
        result = None
        if ballot['is_tallied']:
            path = os.path.join(self.conf.STORAGE_DIR, 'ballot_result',
                                str(ballot_id))
            with open(path) as f:
                result = json.load(f)
        attends = self.assemblyproxy.does_attend(rs, ballot_id=ballot_id)
        vote = None
        if attends:
            vote = self.assemblyproxy.get_vote(rs, ballot_id, secret=None)
        merge_dicts(rs.values, {'vote': vote})
        split_vote = None
        if vote:
            split_vote = tuple(x.split('=') for x in vote.split('>'))
        if ballot['votes']:
            bar = ballot['candidates'][ballot['bar']]
            if result:
                tiers = tuple(x.split('=') for x in result['result'].split('>'))
                winners = []
                for tier in tiers:
                    winners.extend(tier)
                    if bar['moniker'] in winners:
                        winners.remove(bar['moniker'])
                    if len(winners) >= ballot['votes']:
                        break
                result['winners'] = winners
            if split_vote:
                if len(split_vote) == 1:
                    ## abstention
                    rs.values['vote'] = MAGIC_ABSTAIN
                elif len(split_vote) == 2:
                    ## none of the candidates
                    rs.values['vote'] = MAGIC_NONE_OF_THEM
                else:
                    ## select voted options
                    rs.values.setlist('vote', split_vote[0])
        candidates = {e['moniker']: e
                      for e in ballot['candidates'].values()}
        return self.render(rs, "show_ballot", {
            'attachments': attachments, 'split_vote': split_vote,
            'result': result, 'candidates': candidates, 'attends': attends})

    @access("assembly_admin")
    def change_ballot_form(self, rs, assembly_id, ballot_id):
        """Render form"""
        if now() > rs.ambience['ballot']['vote_begin']:
            rs.notify("warning", "Unable to modify active ballot.")
            return self.redirect(rs, "assembly/show_ballot")
        merge_dicts(rs.values, rs.ambience['ballot'])
        return self.render(rs, "change_ballot")

    @access("assembly_admin", modi={"POST"})
    @REQUESTdatadict("title", "description", "vote_begin", "vote_end",
                     "vote_extension_end", "bar", "quorum", "votes", "notes")
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
    @REQUESTdata(("ack_delete", "bool"))
    def delete_ballot(self, rs, assembly_id, ballot_id, ack_delete):
        """Remove a ballot."""
        if not ack_delete:
            rs.notify("error", "Deletion not confirmed.")
            return self.redirect(rs, "assembly/show_ballot")
        code = self.assemblyproxy.delete_ballot(rs, ballot_id, cascade=True)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/list_ballots")

    @access("assembly", modi={"POST"})
    def vote(self, rs, assembly_id, ballot_id):
        """Decide on the options of a ballot.

        This does a bit of extra work to accomodate the compatability mode
        for classical voting (i.e. with a fixed number of equally weighted
        votes).
        """
        ballot = rs.ambience['ballot']
        if ballot['votes']:
            voted = unwrap(
                request_extractor(rs, (("vote", "[str_or_None]"),)))
            candidates = tuple(e['moniker']
                               for e in ballot['candidates'].values()
                               if e['id'] != ballot['bar'])
            bar = ballot['candidates'][ballot['bar']]
            if voted == (MAGIC_NONE_OF_THEM,):
                vote = "{}>{}".format(bar['moniker'], "=".join(candidates))
            elif voted == (MAGIC_ABSTAIN,):
                vote = "{}={}".format(bar['moniker'], "=".join(candidates))
            else:
                vote = "{}>{}>{}".format(
                    "=".join(voted), bar['moniker'],
                    "=".join(c for c in candidates if c not in voted))
        else:
            vote = unwrap(request_extractor(rs, (("vote", "str"),)))
        vote = check(rs, "vote", vote, "vote", ballot=ballot)
        if rs.errors:
            return self.show_ballot(rs, assembly_id, ballot_id)
        code = self.assemblyproxy.vote(rs, ballot_id, vote, secret=None)
        self.notify_return_code(rs, code)
        return self.show_ballot(rs, assembly_id, ballot_id)

    @access("assembly")
    def get_result(self, rs, assembly_id, ballot_id):
        """Download the tallied stats of a ballot."""
        if not rs.ambience['ballot']['is_tallied']:
            rs.notify("warning", "Ballot not yet tallied.")
            return self.show_ballot(rs, assembly_id, ballot_id)
        path = os.path.join(self.conf.STORAGE_DIR, 'ballot_result',
                            str(ballot_id))
        return self.send_file(rs, path=path, inline=False,
                              filename=self.i18n("result.json", rs.lang))

    @access("assembly_admin", modi={"POST"})
    @REQUESTdata(("moniker", "restrictive_identifier"), ("description", "str"))
    def add_candidate(self, rs, assembly_id, ballot_id, moniker, description):
        """Create a new option for a ballot."""
        monikers = {c['moniker']
                    for c in rs.ambience['ballot']['candidates'].values()}
        if moniker in monikers:
            rs.errors.append(("moniker", ValueError("Duplicate moniker.")))
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
        data = {
            'id': ballot_id,
            'candidates': {
                candidate_id: None
            }
        }
        code = self.assemblyproxy.set_ballot(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "assembly/show_ballot")
