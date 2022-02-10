#!/usr/bin/env python3

"""
The `CdEBaseBackend` provides backend functionality for management of (former) members.

There are a few subclasses in separate files which provide addtional functionality
for more specific aspects of member management.

All parts are combined together in the `CdEBackend` class via multiple inheritance,
together with a handful of high-level methods that use functionalities of multiple
backend parts.
"""

import copy
import datetime
import decimal
from collections import OrderedDict
from typing import Collection, List, Optional, Tuple

import psycopg2.extensions

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    AbstractBackend, access, affirm_array_validation as affirm_array,
    affirm_validation as affirm,
)
from cdedb.backend.past_event import PastEventBackend
from cdedb.common import (
    PARSE_OUTPUT_DATEFORMAT, CdEDBLog, CdEDBObject, DefaultReturnCode, LineResolutions,
    PathLike, PrivilegeError, QuotaException, RequestState, glue, implying_realms,
    make_proxy, n_, unwrap,
)
from cdedb.database.connection import Atomizer
from cdedb.filter import money_filter
from cdedb.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.validation import PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS, is_optional


class CdEBaseBackend(AbstractBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)
        self.pastevent = make_proxy(PastEventBackend(configpath), internal=True)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def cde_log(self, rs: RequestState, code: const.CdeLogCodes,
                persona_id: int = None, change_note: str = None
                ) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "cde.log", data)

    @access("cde_admin", "auditor")
    def retrieve_cde_log(self, rs: RequestState,
                         codes: Collection[const.CdeLogCodes] = None,
                         offset: int = None, length: int = None,
                         persona_id: int = None, submitted_by: int = None,
                         change_note: str = None,
                         time_start: datetime.datetime = None,
                         time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        return self.generic_retrieve_log(
            rs, const.CdeLogCodes, "persona", "cde.log", codes=codes,
            offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)

    @access("core_admin", "cde_admin", "auditor")
    def retrieve_finance_log(self, rs: RequestState,
                             codes: Collection[const.FinanceLogCodes] = None,
                             offset: int = None, length: int = None,
                             persona_id: int = None, submitted_by: int = None,
                             change_note: str = None,
                             time_start: datetime.datetime = None,
                             time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get financial activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        additional_columns = ["delta", "new_balance", "members", "total"]
        return self.generic_retrieve_log(
            rs, const.FinanceLogCodes, "persona", "cde.finance_log",
            codes=codes, offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, additional_columns=additional_columns,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    @access("finance_admin")
    def perform_money_transfers(self, rs: RequestState, data: List[CdEDBObject]
                                ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Resolve all money transfer entries.

        :returns: A bool indicating success and:
            * In case of success:
                * The number of recorded transactions
                * The number of new members.
            * In case of error:
                * The index of the erronous line or None
                    if a DB-serialization error occurred.
                * None
        """
        data = affirm_array(vtypes.MoneyTransferEntry, data)
        index = 0
        note_template = ("Guthabenänderung um {amount} auf {new_balance} "
                         "(Überwiesen am {date})")
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                memberships_gained = 0
                persona_ids = tuple(e['persona_id'] for e in data)
                personas = self.core.get_total_personas(rs, persona_ids)
                for index, datum in enumerate(data):
                    assert isinstance(datum['amount'], decimal.Decimal)
                    new_balance = (personas[datum['persona_id']]['balance']
                                   + datum['amount'])
                    note = datum['note']
                    if note:
                        try:
                            date = datetime.datetime.strptime(
                                note, PARSE_OUTPUT_DATEFORMAT)
                        except ValueError:
                            pass
                        else:
                            # This is the default case and makes it pretty
                            note = note_template.format(
                                amount=money_filter(datum['amount']),
                                new_balance=money_filter(new_balance),
                                date=date.strftime(PARSE_OUTPUT_DATEFORMAT))
                    count += self.core.change_persona_balance(
                        rs, datum['persona_id'], new_balance,
                        const.FinanceLogCodes.increase_balance,
                        change_note=note)
                    if new_balance >= self.conf["MEMBERSHIP_FEE"]:
                        code = self.core.change_membership_easy_mode(
                            rs, datum['persona_id'], is_member=True)
                        memberships_gained += bool(code)
                    # Remember the changed balance in case of multiple transfers.
                    personas[datum['persona_id']]['balance'] = new_balance
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None, None
        except Exception:  # pragma: no cover
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index, None
        return True, count, memberships_gained

    @access("cde")
    def current_period(self, rs: RequestState) -> int:
        """Check for the current semester."""
        query = "SELECT MAX(id) FROM cde.org_period"
        ret = unwrap(self.query_one(rs, query, tuple()))
        if not ret:
            raise ValueError(n_("No period exists."))
        return ret

    @access("member", "cde_admin")
    def get_member_stats(self, rs: RequestState
                         ) -> Tuple[CdEDBObject, CdEDBObject, CdEDBObject]:
        """Retrieve some generic statistics about members."""
        # Simple stats first.
        query = """SELECT
            num_members, num_of_searchable, num_of_trial, num_of_printed_expuls,
            num_ex_members, num_all
        FROM
            (
                SELECT COUNT(*) AS num_members
                FROM core.personas
                WHERE is_member = True
            ) AS member_count,
            (
                SELECT COUNT(*) AS num_of_searchable
                FROM core.personas
                WHERE is_member = True AND is_searchable = True
            ) AS searchable_count,
            (
                SELECT COUNT(*) AS num_of_trial
                FROM core.personas
                WHERE is_member = True AND trial_member = True
            ) AS trial_count,
            (
                SELECT COUNT(*) AS num_of_printed_expuls
                FROM core.personas
                WHERE is_member = True and paper_expuls = True
            ) AS printed_expuls_count,
            (
                SELECT COUNT(*) AS num_ex_members
                FROM core.personas
                WHERE is_cde_realm = True AND is_member = False
            ) AS ex_member_count,
            (
                SELECT COUNT(*) AS num_all
                FROM core.personas
            ) AS all_count
        """
        data = self.query_one(rs, query, ())
        assert data is not None

        simple_stats = OrderedDict((k, data[k]) for k in (
            n_("num_members"), n_("num_of_searchable"), n_("num_of_trial"),
            n_("num_of_printed_expuls"), n_("num_ex_members"), n_("num_all")))

        # TODO: improve this type annotation with a new mypy version.
        def query_stats(select: str, condition: str, order: str, limit: int = 0
                        ) -> OrderedDict:  # type: ignore
            query = (f"SELECT COUNT(*) AS num, {select} AS datum"
                     f" FROM core.personas"
                     f" WHERE is_member = True AND {condition} IS NOT NULL"
                     f" GROUP BY datum HAVING COUNT(*) > {limit} ORDER BY {order}")
            data = self.query_all(rs, query, ())
            return OrderedDict((e['datum'], e['num']) for e in data)

        # Members by locations.
        other_stats: CdEDBObject = {
            n_("members_by_country"): query_stats(
                select="country",
                condition="location",
                order="num DESC, datum ASC"),
            n_("members_by_city"): query_stats(
                select="location",
                condition="location",
                order="num DESC, datum ASC",
                limit=9),
        }

        # Members by date.
        year_stats: CdEDBObject = {
            n_("members_by_birthday"): query_stats(
                select="EXTRACT(year FROM birthday)::integer",
                condition="birthday",
                order="datum ASC"),
        }

        # Members by first event.
        query = """SELECT
            COUNT(*) AS num, EXTRACT(year FROM min_tempus.t)::integer AS datum
        FROM
            (
                SELECT persona.id, MIN(pevents.tempus) as t
                FROM
                    (
                        SELECT id FROM core.personas
                        WHERE is_member = TRUE
                    ) as persona
                    LEFT OUTER JOIN (
                        SELECT DISTINCT persona_id, pevent_id
                        FROM past_event.participants
                    ) AS participants ON persona.id = participants.persona_id
                    LEFT OUTER JOIN (
                        SELECT id, tempus
                        FROM past_event.events
                    ) AS pevents ON participants.pevent_id = pevents.id
                WHERE
                    pevents.id IS NOT NULL
                GROUP BY
                    persona.id
            ) AS min_tempus
        GROUP BY
            datum
        ORDER BY
            -- num DESC,
            datum ASC
        """
        year_stats[n_("members_by_first_event")] = OrderedDict(
            (e['datum'], e['num']) for e in self.query_all(rs, query, ()))

        # Unique event attendees per year:
        query = """SELECT
            COUNT(DISTINCT persona_id) AS num,
            EXTRACT(year FROM events.tempus)::integer AS datum
        FROM
            (
                past_event.institutions
                LEFT OUTER JOIN (
                    SELECT id, institution, tempus FROM past_event.events
                ) AS events ON events.institution = institutions.id
                LEFT OUTER JOIN (
                    SELECT persona_id, pevent_id FROM past_event.participants
                ) AS participants ON participants.pevent_id = events.id
            )
        WHERE
            shortname = 'CdE'
        GROUP BY
            datum
        ORDER BY
            datum ASC
        """
        year_stats[n_("unique_participants_per_year")] = dict(
            (e['datum'], e['num']) for e in self.query_all(rs, query, ()))

        return simple_stats, other_stats, year_stats

    def _perform_one_batch_admission(self, rs: RequestState, datum: CdEDBObject,
                                     trial_membership: bool, consent: bool
                                     ) -> Optional[bool]:
        """Uninlined code from perform_batch_admission().

        :returns: None if nothing happened. True if a new member account was created or
            membership was granted to an existing (non-member) account. False if
            (trial-)membership was renewed for an existing (already member) account.
        """
        # Require an Atomizer.
        self.affirm_atomized_context(rs)

        batch_fields = (
            'family_name', 'given_names', 'display_name', 'title', 'name_supplement',
            'birth_name', 'gender', 'address_supplement', 'address',
            'postal_code', 'location', 'country', 'telephone',
            'mobile', 'birthday')  # email omitted as it is handled separately
        if datum['resolution'] == LineResolutions.skip:
            return None
        elif datum['resolution'] == LineResolutions.create:
            new_persona = copy.deepcopy(datum['persona'])
            new_persona.update({
                'is_member': True,
                'trial_member': trial_membership,
                'paper_expuls': True,
                'is_searchable': consent,
            })
            persona_id = self.core.create_persona(rs, new_persona)
            ret = True
        elif datum['resolution'].is_modification():
            ret = False
            persona_id = datum['doppelganger_id']
            current = self.core.get_persona(rs, persona_id)
            if current['is_archived']:
                if current['is_purged']:
                    raise RuntimeError(n_("Cannot restore purged account."))
                self.core.dearchive_persona(
                    rs, persona_id, datum['persona']['username'])
                current['username'] = datum['persona']['username']
            if datum['update_username']:
                if current['username'] != datum['persona']['username']:
                    self.core.change_username(
                        rs, persona_id, datum['persona']['username'], password=None)
            if not current['is_cde_realm']:
                # Promote to cde realm dependent on current realm
                promotion: CdEDBObject = {
                    field: None for field in CDE_TRANSITION_FIELDS}
                # The ream independent upgrades of the persona. They are applied at last
                # to prevent unintentional overrides
                upgrades = {
                    'is_cde_realm': True,
                    'is_event_realm': True,
                    'is_assembly_realm': True,
                    'is_ml_realm': True,
                    'decided_search': False,
                    'trial_member': False,
                    'paper_expuls': True,
                    'bub_search': False,
                    'id': persona_id,
                }
                # This applies a part of the newly imported data necessary for realm
                # transition. The remaining data will be updated later.
                mandatory_fields = {
                    field for field, validator in CDE_TRANSITION_FIELDS.items()
                    if field not in upgrades and not is_optional(validator)
                }
                assert mandatory_fields <= set(batch_fields)
                # It is pure incident that only event users have additional (optional)
                # data they share with cde users and which must be honoured during realm
                # transition. This may be changed if a new user tier is introduced.
                if not current['is_event_realm']:
                    if not datum['resolution'].do_update():
                        raise RuntimeError(n_("Need extra data."))
                    for field in mandatory_fields:
                        promotion[field] = datum['persona'][field]
                else:
                    current = self.core.get_event_user(rs, persona_id)
                    # take care that we do not override existent data
                    current_fields = {
                        field for field in CDE_TRANSITION_FIELDS
                        if current.get(field) is not None
                    }
                    for field in current_fields:
                        promotion[field] = current[field]
                    for field in mandatory_fields:
                        if promotion[field] is None:
                            promotion[field] = datum['persona'][field]
                # apply the actual changes
                promotion.update(upgrades)
                self.core.change_persona_realms(
                    rs, promotion, change_note="Datenübernahme nach Massenaufnahme")
            if datum['resolution'].do_trial():
                code = self.core.change_membership_easy_mode(
                    rs, datum['doppelganger_id'], is_member=True)
                # This will be true if the user was not a member before.
                ret = bool(code)
                update = {
                    'id': datum['doppelganger_id'],
                    'trial_member': True,
                }
                self.core.change_persona(
                    rs, update, may_wait=False,
                    change_note="Probemitgliedschaft erneuert.")
            if datum['resolution'].do_update():
                update = {'id': datum['doppelganger_id']}
                for field in batch_fields:
                    update[field] = datum['persona'][field]
                self.core.change_persona(
                    rs, update, may_wait=True, force_review=True,
                    change_note="Import aktualisierter Daten.")
        else:
            raise RuntimeError(n_("Impossible."))
        if datum['pevent_id'] and persona_id:
            self.pastevent.add_participant(
                rs, datum['pevent_id'], datum['pcourse_id'], persona_id,
                is_instructor=datum['is_instructor'], is_orga=datum['is_orga'])
        return ret

    @access("cde_admin")
    def perform_batch_admission(self, rs: RequestState, data: List[CdEDBObject],
                                trial_membership: bool, consent: bool
                                ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Atomized call to recruit new members.

        The frontend wants to do this in its entirety or not at all, so this
        needs to be in atomized context.

        :returns: A tuple consisting of a bool and two optional integers.:
            A boolean signalling success.
            If the operation was successful:
                An integer signalling the number of newly created accounts.
                An integer signalling the number of modified/renewed accounts.
            If the operation was not successful:
                If a TransactionRollbackError occrured:
                    Both integer parameters are None.
                Otherwise:
                    The index where the error occured.
                    The second parameter is None.
        """
        data = affirm_array(vtypes.BatchAdmissionEntry, data)
        trial_membership = affirm(bool, trial_membership)
        consent = affirm(bool, consent)
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count_new = count_renewed = 0
                for index, datum in enumerate(data, start=1):
                    account_created = self._perform_one_batch_admission(
                        rs, datum, trial_membership, consent)
                    if account_created is None:
                        pass
                    elif account_created:
                        count_new += 1
                    else:
                        count_renewed += 1
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None, None
        except Exception:  # pragma: no cover
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during batch creation",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index, None
        return True, count_new, count_renewed

    @access("searchable", "core_admin", "cde_admin")
    def submit_general_query(self, rs: RequestState,
                             query: Query) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        if query.scope == QueryScope.cde_member:
            if self.core.check_quota(rs, num=1):
                raise QuotaException(n_("Too many queries."))
            query.constraints.append(("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(("is_member", QueryOperators.equal, True))
            query.constraints.append(("is_searchable", QueryOperators.equal, True))
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.spec['is_cde_realm'] = QuerySpecEntry("bool", "")
            query.spec['is_member'] = QuerySpecEntry("bool", "")
            query.spec['is_searchable'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
        elif query.scope in {QueryScope.cde_user, QueryScope.archived_past_event_user}:
            if not {'core_admin', 'cde_admin'} & rs.user.roles:
                raise PrivilegeError(n_("Admin only."))
            query.constraints.append(("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(
                ("is_archived", QueryOperators.equal,
                 query.scope == QueryScope.archived_past_event_user))
            query.spec['is_cde_realm'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('cde'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = QuerySpecEntry("bool", "")
        elif query.scope == QueryScope.past_event_user:
            if not self.is_admin(rs):
                raise PrivilegeError(n_("Admin only."))
            query.constraints.append(("is_event_realm", QueryOperators.equal, True))
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.spec['is_event_realm'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)
