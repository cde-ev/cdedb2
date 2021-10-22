#!/usr/bin/env python3

"""Services related to parsing and booking bank transfers for the cde realm.

Everything here requires the "finance_admin" role.
"""

import csv
import datetime
import decimal
import functools
import itertools
import pathlib
import re
from collections import defaultdict
from typing import List, Optional, Sequence, Tuple, cast

from werkzeug import Response
from werkzeug.datastructures import FileStorage

import cdedb.frontend.parse_statement as parse
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, EntitySorter, RequestState, TransactionType, diacritic_patterns,
    get_hash, merge_dicts, n_, xsorted,
)
from cdedb.frontend.cde_base import CdEBaseFrontend
from cdedb.frontend.common import (
    CustomCSVDialect, REQUESTdata, REQUESTfile, TransactionObserver, access,
    check_validation as check, check_validation_optional as check_optional, csv_output,
    inspect_validation as inspect, inspect_validation_optional as inspect_optional,
    make_postal_address, request_extractor,
)


class CdEParseMixin(CdEBaseFrontend):
    @access("finance_admin")
    def parse_statement_form(self, rs: RequestState, data: CdEDBObject = None,
                             params: CdEDBObject = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or {}
        merge_dicts(rs.values, data)
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        event_entries = xsorted(
            [(event['id'], event['title']) for event in events.values()],
            key=lambda e: EntitySorter.event(events[e[0]]), reverse=True)
        params = {
            'params': params or None,
            'data': data,
            'transaction_keys': parse.Transaction.get_request_params(hidden_only=True),
            'ref_sep': parse.REFERENCE_SEPARATOR,
            'TransactionType': parse.TransactionType,
            'event_entries': event_entries,
            'events': events,
        }
        return self.render(rs, "parse/parse_statement", params)

    @staticmethod
    def organize_transaction_data(
        rs: RequestState, transactions: List[parse.Transaction],
        start: Optional[datetime.date], end: Optional[datetime.date],
        timestamp: datetime.datetime
    ) -> Tuple[CdEDBObject, CdEDBObject]:
        """Organize transactions into data and params usable in the form."""

        data = {"{}{}".format(k, t.t_id): v
                for t in transactions
                for k, v in t.to_dict().items()}
        data["count"] = len(transactions)
        data["start"] = start
        data["end"] = end
        data["timestamp"] = timestamp
        params: CdEDBObject = {
            "all": [],
            "has_error": [],
            "has_warning": [],
            "jump_order": {},
            "has_none": [],
            "accounts": defaultdict(int),
            "events": defaultdict(int),
            "memberships": 0,
        }
        prev_jump = None
        for t in transactions:
            params["all"].append(t.t_id)
            if t.errors or t.warnings:
                params["jump_order"][prev_jump] = t.t_id
                params["jump_order"][t.t_id] = None
                prev_jump = t.t_id
                if t.errors:
                    params["has_error"].append(t.t_id)
                else:
                    params["has_warning"].append(t.t_id)
            else:
                params["has_none"].append(t.t_id)
            params["accounts"][t.account] += 1
            if t.event and t.type == TransactionType.EventFee:
                params["events"][t.event['id']] += 1
            if t.type == TransactionType.MembershipFee:
                params["memberships"] += 1
        return data, params

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("statement_file")
    def parse_statement(self, rs: RequestState,
                        statement_file: FileStorage) -> Response:
        """
        Parse the statement into multiple CSV files.

        Every transaction is matched to a TransactionType, as well as to a
        member and an event, if applicable.

        The transaction's reference is searched for DB-IDs.
        If found the associated persona is looked up and their given_names and
        family_name, and variations thereof, are compared to the transaction's
        reference.

        To match to an event, this compares the names of current events, and
        variations thereof, to the transacion's reference.

        Every match to Type, Member and Event is given a ConfidenceLevel, to be
        used on further validation.

        This uses POST because the expected data is too large for GET.
        """
        assert statement_file.filename is not None
        filename = pathlib.Path(statement_file.filename).parts[-1]
        start, end, timestamp = parse.dates_from_filename(filename)
        statement_file = check(rs, vtypes.CSVFile, statement_file, "statement_file")
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)
        assert statement_file is not None
        statementlines = statement_file.splitlines()

        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)

        get_persona = functools.partial(self.coreproxy.get_persona, rs)

        # This does not use the cde csv dialect, but rather the bank's.
        reader = csv.DictReader(statementlines, delimiter=";", quotechar='"')

        transactions = []

        for i, line in enumerate(reversed(list(reader))):
            if not line.keys() <= parse.STATEMENT_CSV_ALL_KEY:
                p = ("statement_file",
                     ValueError(n_("Line %(lineno)s does not have "
                                   "the correct columns."),
                                {'lineno': i + 1}
                                ))
                rs.append_validation_error(p)
                continue
            line["id"] = i  # type: ignore[assignment]
            t = parse.Transaction.from_csv(line)
            t.analyze(events, get_persona)
            t.inspect()

            transactions.append(t)
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)

        data, params = self.organize_transaction_data(
            rs, transactions, start, end, timestamp)

        return self.parse_statement_form(rs, data, params)

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("count", "start", "end", "timestamp", "validate", "event",
                 "membership", "excel", "gnucash", "ignore_warnings")
    def parse_download(self, rs: RequestState, count: int, start: datetime.date,
                       end: Optional[datetime.date],
                       timestamp: datetime.datetime, validate: str = None,
                       event: vtypes.ID = None, membership: str = None,
                       excel: str = None, gnucash: str = None,
                       ignore_warnings: bool = False) -> Response:
        """
        Provide data as CSV-Download with the given filename.

        This uses POST, because the expected filesize is too large for GET.
        """
        rs.ignore_validation_errors()

        get_persona = functools.partial(self.coreproxy.get_persona, rs)
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)

        transactions = []
        for i in range(1, count + 1):
            t_data = request_extractor(rs, parse.Transaction.get_request_params(i))
            t = parse.Transaction(t_data, index=i)
            t.get_data(get_persona=get_persona, events=events)
            t.inspect()
            transactions.append(t)

        data, params = self.organize_transaction_data(
            rs, transactions, start, end, timestamp)

        fields: Sequence[str]
        if validate is not None or params["has_error"] \
                or (params["has_warning"] and not ignore_warnings):
            return self.parse_statement_form(rs, data, params)
        elif membership is not None:
            filename = "Mitgliedsbeiträge"
            transactions = [t for t in transactions
                            if t.type == TransactionType.MembershipFee]
            fields = parse.MEMBERSHIP_EXPORT_FIELDS
            write_header = False
        elif event is not None:
            aux = int(event)
            event_data = self.eventproxy.get_event(rs, aux)
            filename = event_data["shortname"]
            transactions = [t for t in transactions
                            if t.event and t.event['id'] == aux
                            and t.type == TransactionType.EventFee]
            fields = parse.EVENT_EXPORT_FIELDS
            write_header = False
        elif gnucash is not None:
            filename = "gnucash"
            fields = parse.GNUCASH_EXPORT_FIELDS
            write_header = True
        elif excel is not None:
            account = excel
            filename = "transactions_" + account
            transactions = [t for t in transactions
                            if str(t.account) == account]
            fields = parse.EXCEL_EXPORT_FIELDS
            write_header = False
        else:
            rs.notify("error", n_("Unknown action."))
            return self.parse_statement_form(rs, data, params)
        if end is None:
            filename += "_{}.csv".format(start)
        else:
            filename += "_{}_bis_{}.csv".format(start, end)
        csv_data = [t.to_dict() for t in transactions]
        csv_data = csv_output(csv_data, fields, write_header)
        return self.send_csv_file(rs, "text/csv", filename, data=csv_data)

    @access("finance_admin")
    def money_transfers_form(self, rs: RequestState,
                             data: List[CdEDBObject] = None,
                             csvfields: Tuple[str, ...] = None,
                             saldo: decimal.Decimal = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        defaults = {'sendmail': True}
        merge_dicts(rs.values, defaults)
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        return self.render(rs, "parse/money_transfers", {
            'data': data, 'csvfields': csv_position, 'saldo': saldo,
        })

    def examine_money_transfer(self, rs: RequestState, datum: CdEDBObject
                               ) -> CdEDBObject:
        """Check one line specifying a money transfer.

        We test for fitness of the data itself.

        :returns: The processed input datum.
        """
        amount, problems = inspect(
            vtypes.PositiveDecimal, datum['raw']['amount'], argname="amount")
        persona_id, p = inspect(
            vtypes.CdedbID, datum['raw']['persona_id'].strip(),
            argname="persona_id")
        problems.extend(p)
        family_name, p = inspect(
            str, datum['raw']['family_name'], argname="family_name")
        problems.extend(p)
        given_names, p = inspect(
            str, datum['raw']['given_names'], argname="given_names")
        problems.extend(p)
        note, p = inspect_optional(str, datum['raw']['note'], argname="note")
        problems.extend(p)

        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append(('persona_id',
                                 ValueError(
                                     n_("No Member with ID %(p_id)s found."),
                                     {'p_id': persona_id})))
            else:
                if persona['is_archived']:
                    problems.append(('persona_id',
                                     ValueError(n_("Persona is archived."))))
                if not persona['is_cde_realm']:
                    problems.append((
                        'persona_id',
                        ValueError(n_("Persona is not in CdE realm."))))

                if family_name is not None and not re.search(
                    diacritic_patterns(re.escape(family_name)),
                    persona['family_name'],
                    flags=re.IGNORECASE
                ):
                    problems.append(('family_name', ValueError(
                        n_("Family name doesn’t match."))))

                if given_names is not None and not re.search(
                    diacritic_patterns(re.escape(given_names)),
                    persona['given_names'],
                    flags=re.IGNORECASE
                ):
                    problems.append(('given_names', ValueError(
                        n_("Given names don’t match."))))
        datum.update({
            'persona_id': persona_id,
            'amount': amount,
            'note': note,
            'warnings': [],
            'problems': problems,
        })
        return datum

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("transfers_file")
    @REQUESTdata("sendmail", "transfers", "checksum")
    def money_transfers(self, rs: RequestState, sendmail: bool,
                        transfers: Optional[str], checksum: Optional[str],
                        transfers_file: Optional[FileStorage]
                        ) -> Response:
        """Update member balances.

        The additional parameter sendmail modifies the behaviour and can
        be selected by the user.

        The internal parameter checksum is used to guard against data
        corruption and to explicitly signal at what point the data will
        be committed (for the second purpose it works like a boolean).
        """
        transfers_file = check_optional(
            rs, vtypes.CSVFile, transfers_file, "transfers_file")
        if rs.has_validation_errors():
            return self.money_transfers_form(rs)
        if transfers_file and transfers:
            rs.notify("warning", n_("Only one input method allowed."))
            return self.money_transfers_form(rs)
        elif transfers_file:
            rs.values["transfers"] = transfers_file
            transfers = transfers_file
            transferlines = transfers_file.splitlines()
        elif transfers:
            transferlines = transfers.splitlines()
        else:
            rs.notify("error", n_("No input provided."))
            return self.money_transfers_form(rs)
        fields = ('amount', 'persona_id', 'family_name', 'given_names', 'note')
        reader = csv.DictReader(
            transferlines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        for lineno, raw_entry in enumerate(reader):
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno}
            data.append(self.examine_money_transfer(rs, dataset))
        for ds1, ds2 in itertools.combinations(data, 2):
            if ds1['persona_id'] and ds1['persona_id'] == ds2['persona_id']:
                warning = (None, ValueError(
                    n_("More than one transfer for this account "
                       "(lines %(first)s and %(second)s)."),
                    {'first': ds1['lineno'] + 1, 'second': ds2['lineno'] + 1}))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
        if len(data) != len(transferlines):
            rs.append_validation_error(
                ("transfers", ValueError(n_("Lines didn’t match up."))))
        open_issues = any(e['problems'] for e in data)
        saldo = cast(decimal.Decimal,
                     sum(e['amount'] for e in data if e['amount']))
        if rs.has_validation_errors() or not data or open_issues:
            rs.values['checksum'] = None
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)
        current_checksum = get_hash(transfers.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)

        # Here validation is finished
        relevant_keys = {'amount', 'persona_id', 'note'}
        relevant_data = [{k: v for k, v in item.items() if k in relevant_keys}
                         for item in data]
        with TransactionObserver(rs, self, "money_transfers"):
            success, num, new_members = self.cdeproxy.perform_money_transfers(
                rs, relevant_data)
            if success and sendmail:
                for datum in data:
                    persona_ids = tuple(e['persona_id'] for e in data)
                    personas = self.coreproxy.get_cde_users(rs, persona_ids)
                    persona = personas[datum['persona_id']]
                    self.do_mail(rs, "parse/transfer_received",
                                 {'To': (persona['username'],),
                                  'Subject': "Überweisung eingegangen",
                                  },
                                 {'persona': persona,
                                  'address': make_postal_address(rs, persona),
                                  'new_balance': persona['balance']})
        if success:
            rs.notify("success", n_("Committed %(num)s transfers. "
                                    "There were %(new_members)s new members."),
                      {'num': num, 'new_members': new_members})
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line %(num)s."),
                          {'num': num + 1})
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)
