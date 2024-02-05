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
import dataclasses
import datetime
import decimal
from collections import OrderedDict
from typing import Optional, Union

import psycopg2.extensions

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import (
    AbstractBackend, access, affirm_array_validation as affirm_array, affirm_dataclass,
    affirm_validation as affirm,
)
from cdedb.backend.past_event import PastEventBackend
from cdedb.common import (
    PARSE_OUTPUT_DATEFORMAT, CdEDBLog, CdEDBObject, DefaultReturnCode, LineResolutions,
    RequestState, glue, make_proxy, unwrap,
)
from cdedb.common.exceptions import PrivilegeError, QuotaException
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.common.query.log_filter import CdELogFilter, FinanceLogFilter
from cdedb.common.roles import implying_realms
from cdedb.common.validation.validate import (
    PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS, is_optional,
)
from cdedb.database.connection import Atomizer
from cdedb.filter import money_filter


@dataclasses.dataclass
class BatchAdmissionStats:
    # New accounts created via batch admission
    new_accounts: set[int]
    # Existing accounts which were granted trial membership
    new_members: set[int]
    # Existing accounts which were only modified
    modified_accounts: set[int]

    def add(self, persona_id: int, resolution: LineResolutions) -> None:
        """Add a persona to the right stat set, depending on the chosen resolution."""
        if resolution == LineResolutions.skip:
            pass
        elif resolution == LineResolutions.create:
            self.new_accounts.add(persona_id)
        elif resolution.do_trial():
            self.new_members.add(persona_id)
        elif resolution.do_update():
            self.modified_accounts.add(persona_id)
        else:
            raise RuntimeError(n_("Impossible"))


class CdEBaseBackend(AbstractBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"

    def __init__(self) -> None:
        super().__init__()
        self.pastevent = make_proxy(PastEventBackend(), internal=True)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def cde_log(self, rs: RequestState, code: const.CdeLogCodes,
                persona_id: Optional[int] = None, change_note: Optional[str] = None,
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
    def retrieve_cde_log(self, rs: RequestState, log_filter: CdELogFilter) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(CdELogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @access("core_admin", "cde_admin", "auditor")
    def retrieve_finance_log(self, rs: RequestState, log_filter: FinanceLogFilter,
                             ) -> CdEDBLog:
        """Get financial activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(FinanceLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @access("finance_admin")
    def perform_money_transfers(self, rs: RequestState, data: list[CdEDBObject],
                                ) -> tuple[bool, Optional[int], Optional[int]]:
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
                    date = None
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
                        change_note=note, transaction_date=date)
                    if (new_balance >= self.conf["MEMBERSHIP_FEE"]
                            and not personas[datum['persona_id']]['is_member']):
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
    def get_member_stats(self, rs: RequestState,
                         ) -> tuple[CdEDBObject, CdEDBObject, CdEDBObject]:
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

        def query_stats(select: str, condition: str, order: str, limit: int = 0,
                        ) -> OrderedDict[str, int]:
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

        # Users/Members by first event.
        query = """SELECT
            COUNT(*) AS num, EXTRACT(year FROM min_tempus.t)::integer AS datum
        FROM
            (
                SELECT persona.id, MIN(pevents.tempus) as t
                FROM
                    (
                        SELECT id FROM core.personas
                        {}
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
            (e['datum'], e['num'])
            for e in self.query_all(rs, query.format("WHERE is_member = TRUE"), ()))
        year_stats[n_("users_by_first_event")] = OrderedDict(
            (e['datum'], e['num'])
            for e in self.query_all(rs, query.format(""), ()))

        # Unique event attendees per year:
        query = """SELECT
            COUNT(DISTINCT persona_id) AS num,
            EXTRACT(year FROM events.tempus)::integer AS datum
        FROM
            (
                past_event.events
                LEFT OUTER JOIN (
                    SELECT persona_id, pevent_id FROM past_event.participants
                ) AS participants ON participants.pevent_id = events.id
            )
        WHERE
            institution = %s
        GROUP BY
            datum
        ORDER BY
            datum ASC
        """
        year_stats[n_("unique_participants_per_year")] = dict(
            (e['datum'], e['num']) for e in
            self.query_all(rs, query, [const.PastInstitutions.main_insitution()]))

        return simple_stats, other_stats, year_stats

    def _perform_one_batch_admission(self, rs: RequestState, datum: CdEDBObject,
                                     trial_membership: bool, consent: bool,
                                     ) -> Optional[int]:
        """Uninlined code from perform_batch_admission().

        :returns: The affected persona_id, or None if the entry was skipped.
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
            # We set membership separately to ensure correct logging.
            new_persona.update({
                'is_member': False,
                'trial_member': False,
                'paper_expuls': True,
                'donation': decimal.Decimal(0),
                'is_searchable': consent,
            })
            persona_id = self.core.create_persona(rs, new_persona)
            self.core.change_membership_easy_mode(
                rs, persona_id, is_member=True, trial_member=trial_membership)
        elif datum['resolution'].is_modification():
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
                # The realm independent upgrades of the persona.
                # They are applied last to prevent unintentional overrides.
                upgrades = {
                    'is_cde_realm': True,
                    'is_event_realm': True,
                    'is_assembly_realm': True,
                    'is_ml_realm': True,
                    'decided_search': False,
                    'trial_member': False,
                    'paper_expuls': True,
                    'donation': decimal.Decimal(0),
                    'bub_search': False,
                    'pronouns_nametag': False,
                    'pronouns_profile': False,
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
                if current['is_member']:
                    raise RuntimeError(n_("May not grant trial membership to member."))
                self.core.change_membership_easy_mode(
                    rs, datum['doppelganger_id'], is_member=True, trial_member=True)
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
        return persona_id

    @access("cde_admin")
    def perform_batch_admission(
            self, rs: RequestState, data: list[CdEDBObject], trial_membership: bool,
            consent: bool,
    ) -> tuple[bool, Optional[Union[BatchAdmissionStats, int]]]:
        """Atomized call to recruit new members.

        The frontend wants to do this in its entirety or not at all, so this
        needs to be in atomized context.

        :returns: A tuple consisting of a bool and an optional second argument.:
            A boolean signalling success.
            If the operation was successful:
                The second argument is an instance of BatchAdmissionStats.
            If the operation was not successful:
                If a TransactionRollbackError occurred:
                    The second argument is None
                Otherwise:
                    The second argument is an int, the index where the error occurred.
        """
        data = affirm_array(vtypes.BatchAdmissionEntry, data)
        trial_membership = affirm(bool, trial_membership)
        consent = affirm(bool, consent)
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                stats = BatchAdmissionStats(set(), set(), set())
                for index, datum in enumerate(data, start=1):
                    persona_id = self._perform_one_batch_admission(
                        rs, datum, trial_membership, consent)
                    if persona_id is None:
                        continue
                    stats.add(persona_id, datum['resolution'])
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None
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
            return False, index  # pylint: disable=used-before-assignment
        return True, stats

    @access("searchable", "core_admin", "cde_admin")
    def submit_general_query(self, rs: RequestState, query: Query,
                             aggregate: bool = False) -> tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        aggregate = affirm(bool, aggregate)
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
        elif query.scope in {
            QueryScope.cde_user,
            QueryScope.past_event_user,
            QueryScope.all_cde_users,
        }:
            if not {'core_admin', 'cde_admin'} & rs.user.roles:
                raise PrivilegeError(n_("Admin only."))

            # Potentially restrict to non-archived users.
            if not query.scope.includes_archived:
                query.constraints.append(("is_archived", QueryOperators.equal, False))
                query.spec["is_archived"] = QuerySpecEntry("bool", "")

            if query.scope == QueryScope.past_event_user:
                # Restrict to event users (or higher).
                query.constraints.append(("is_event_realm", QueryOperators.equal, True))
                query.spec['is_event_realm'] = QuerySpecEntry("bool", "")
            else:
                # Restrict to exactly cde users (not higher).
                query.constraints.append(("is_cde_realm", QueryOperators.equal, True))
                query.spec['is_cde_realm'] = QuerySpecEntry("bool", "")
                for realm in implying_realms('cde'):
                    query.constraints.append(
                        (f"is_{realm}_realm", QueryOperators.equal, False))
                    query.spec[f"is_{realm}_realm"] = QuerySpecEntry("bool", "")
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query, aggregate=aggregate)
