#!/usr/bin/env python3

"""Services related to parsing and booking bank transfers for the cde realm.

Everything here requires the "finance_admin" role.
"""

import csv
import datetime
import decimal
import itertools
import pathlib
from collections import defaultdict
from collections.abc import Sequence
from typing import Optional

from werkzeug import Response
from werkzeug.datastructures import FileStorage

import cdedb.common.validation.types as vtypes
import cdedb.frontend.cde.parse_statement as parse
import cdedb.models.event as models_event
from cdedb.common import (
    Accounts, CdEDBObject, Error, RequestState, TransactionType, get_hash, merge_dicts,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.sorting import xsorted
from cdedb.filter import money_filter
from cdedb.frontend.cde.base import CdEBaseFrontend
from cdedb.frontend.common import (
    CustomCSVDialect, Headers, REQUESTdata, REQUESTfile, TransactionObserver, access,
    check_validation as check, check_validation_optional as check_optional, csv_output,
    inspect_validation as inspect, make_postal_address, request_extractor,
)


class CdEParseMixin(CdEBaseFrontend):
    @access("finance_admin")
    def parse_statement_form(self, rs: RequestState, data: Optional[CdEDBObject] = None,
                             params: Optional[CdEDBObject] = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or {}
        merge_dicts(rs.values, data)
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        event_entries = xsorted(
            [(event.id, event.title) for event in events.values()],
            key=lambda e: events[e[0]], reverse=True)
        event_options = [
            {
                'title': event.title,
                'shortname': event.shortname,
                'id': event.id,
            }
            for event in xsorted(events.values(), reverse=True)
        ]
        params = {
            'params': params or None,
            'data': data,
            'transaction_keys': parse.Transaction.get_request_params(hidden_only=True),
            'TransactionType': parse.TransactionType,
            'event_entries': event_entries, 'event_options': event_options,
            'events': events,
        }
        return self.render(rs, "parse/parse_statement", params)

    def organize_transaction_data(
        self, rs: RequestState, transactions: list[parse.Transaction],
        date: datetime.date,
    ) -> tuple[CdEDBObject, CdEDBObject]:
        """Organize transactions into data and params usable in the form."""

        data = {f"{k}{t.t_id}": v
                for t in transactions
                for k, v in t.to_dict().items()}
        data["count"] = len(transactions)
        data["date"] = date
        params: CdEDBObject = {
            "all": [],
            "has_error": [],
            "has_warning": [],
            "jump_order": {},
            "has_none": [],
            "accounts": defaultdict(int),
            "events": defaultdict(int),
            "memberships": 0,
            "registration_ids": {},
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
            if t.event and t.persona:
                reg_id = self.eventproxy.get_registration_id(
                    rs, persona_id=t.persona['id'], event_id=t.event.id)
                params["registration_ids"][(t.persona['id'], t.event.id)] = reg_id
            params["accounts"][t.account] += 1
            if t.event and t.type == TransactionType.EventFee:
                params["events"][t.event.id] += 1
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
        date = parse.date_from_filename(filename)
        statement_file = check(rs, vtypes.CSVFile, statement_file, "statement_file")
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)
        assert statement_file is not None
        statementlines = statement_file.splitlines()

        # This does not use the cde csv dialect, but rather the bank's.
        reader = csv.DictReader(statementlines, delimiter=";", quotechar='"')

        transactions = []

        ALL_KEYS = parse.StatementCSVKeys.all_keys()

        for i, line in enumerate(reversed(list(reader))):
            if not line.keys() <= ALL_KEYS:
                p = ("statement_file",
                     ValueError(n_("Line %(lineno)s does not have "
                                   "the correct columns."),
                                {'lineno': i + 1},
                                ))
                rs.append_validation_error(p)
                continue
            line["id"] = i
            t = parse.Transaction.from_csv(line)
            t.parse(rs, self.coreproxy, self.eventproxy)
            t.validate(rs, self.coreproxy, self.eventproxy)

            transactions.append(t)
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)

        data, params = self.organize_transaction_data(rs, transactions, date)

        return self.parse_statement_form(rs, data, params)

    @access("finance_admin", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata("count", "date", "validate", "event", "membership", "excel",
                 "ignore_warnings")
    def parse_download(self, rs: RequestState, count: int, date: datetime.date,
                       validate: Optional[str] = None,
                       event: Optional[vtypes.ID] = None,
                       membership: Optional[str] = None, excel: Optional[str] = None,
                       ignore_warnings: bool = False,
                       ) -> Response:
        """
        Provide data as CSV-Download with the given filename.

        This uses POST, because the expected filesize is too large for GET.
        """
        rs.ignore_validation_errors()

        transactions = []
        for i in range(1, count + 1):
            t_data = request_extractor(rs, parse.Transaction.get_request_params(i))
            t = parse.Transaction(t_data, index=i)
            t.validate(rs, self.coreproxy, self.eventproxy)
            transactions.append(t)

        data, params = self.organize_transaction_data(rs, transactions, date)

        fields: Sequence[str]
        if validate is not None or params["has_error"] \
                or (params["has_warning"] and not ignore_warnings):
            return self.parse_statement_form(rs, data, params)
        elif excel is not None:
            account, _ = inspect(Accounts, excel)
            if not account:
                rs.notify("error", n_("Unknown account."))
                return self.parse_statement_form(rs, data, params)
            filename = f"transactions_{account.display_str()}"
            transactions = [t for t in transactions if t.account == account]
            fields = parse.ExportFields.excel
            if account == Accounts.Festgeld:
                fields = parse.ExportFields.festgeld
            write_header = False
        else:
            filename = "DB-Import"
            transactions = [
                t for t in transactions
                if t.type in {
                    TransactionType.MembershipFee,
                    TransactionType.EventFee,
                }
            ]
            fields = parse.ExportFields.db_import
            write_header = False
        filename += f"_{date}.csv"
        csv_data = [t.to_dict() for t in transactions]
        csv_data = csv_output(csv_data, fields, write_header,
                              tzinfo=self.conf['DEFAULT_TIMEZONE'])
        return self.send_csv_file(rs, "text/csv", filename, data=csv_data)

    @access("finance_admin")
    def money_transfers_form(self, rs: RequestState,
                             data: Optional[list[CdEDBObject]] = None,
                             csvfields: Optional[tuple[str, ...]] = None,
                             saldos: Optional[dict[int, decimal.Decimal]] = None,
                             ) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        events = self.eventproxy.get_events(rs, self.eventproxy.list_events(rs))
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        return self.render(rs, "parse/money_transfers", {
            'data': data, 'csvfields': csv_position, 'saldos': saldos, 'events': events,
        })

    @staticmethod
    def parse_amount(amount_str: str) -> tuple[Optional[decimal.Decimal], list[Error]]:
        try:
            amount = parse.parse_amount(amount_str)
        except parse.ParseAmountError:
            return None, [('amount', ValueError(n_("Invalid input for amount.")))]
        else:
            return amount, []

    def examine_money_transfer(self, rs: RequestState, datum: CdEDBObject, *,
                               events_by_shortname: dict[str, models_event.Event],
                               amounts_paid: dict[int, decimal.Decimal],
                               ) -> CdEDBObject:
        """Check one line specifying a money transfer.

        We test for fitness of the data itself.

        :returns: The processed input datum.
        """
        raw = datum['raw']
        problems, infos = [], []

        category, p = inspect(
            vtypes.Identifier, raw['category_old'], argname="category")
        problems.extend(p)
        persona = None
        registration = None
        event = None

        date, p = inspect(
            datetime.date, raw['transaction_date'], argname="date")
        problems.extend(p)

        amount, p = self.parse_amount(raw['amount_german'])
        problems.extend(p)

        persona_id, p = inspect(
            vtypes.CdedbID, datum['raw']['cdedbid'].strip(), argname="persona_id")
        problems.extend(p)

        family_name, p = inspect(
            str, datum['raw']['family_name'], argname="family_name")
        problems.extend(p)

        given_names, p = inspect(
            str, datum['raw']['given_names'], argname="given_names")
        problems.extend(p)

        if category is None:
            problems.append(('category', ValueError(n_("Invalid category."))))
            type_ = TransactionType.Unknown
        elif category == TransactionType.MembershipFee.old():
            type_ = TransactionType.MembershipFee
            if amount is not None and amount <= 0:
                problems.append((
                    'amount',
                    ValueError(n_("Must be greater than zero.")),
                ))
        elif event := events_by_shortname.get(category):
            type_ = TransactionType.EventFee
            if amount is not None and amount == 0:
                problems.append(('amount', ValueError(n_("Must not be zero."))))
        else:
            problems.append(('category', ValueError(n_("Unknown event."))))
            type_ = TransactionType.Unknown

        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append((
                    'persona_id',
                    ValueError(n_("No Member with ID %(p_id)s found."),
                               {'p_id': persona_id}),
                ))
            else:
                if persona['is_archived']:
                    problems.append(
                        ('persona_id', ValueError(n_("Persona is archived."))))
                if type_ == TransactionType.MembershipFee:
                    if not persona['is_cde_realm']:
                        problems.append((
                            'persona_id',
                            ValueError(n_("Persona is not in CdE realm.")),
                        ))
                elif type_ == TransactionType.EventFee:
                    if not persona['is_event_realm']:
                        problems.append((
                            'persona_id',
                            ValueError(n_("Persona is not in event realm.")),
                        ))
                    assert event is not None
                    registration_ids = self.eventproxy.list_registrations(
                        rs, event.id, persona_id)
                    if not registration_ids:
                        problems.append((
                            'persona_id',
                            ValueError(n_("Persona is not registerd for this event.")),
                        ))
                    elif amount:
                        registration = self.eventproxy.get_registration(
                            rs, unwrap(registration_ids.keys()))
                        if registration['id'] in amounts_paid:
                            amount_paid = amounts_paid[registration['id']]
                        else:
                            amount_paid = registration['amount_paid']
                        total = amount_paid + amount
                        fee = registration['amount_owed']

                        if (registration['ctime']
                                and date < registration['ctime'].date()):
                            infos.append((
                                'date',
                                ValueError(n_(
                                    "Payment date before registration.")),
                            ))

                        params = {
                            'total': money_filter(total, lang=rs.lang),
                            'expected': money_filter(fee, lang=rs.lang),
                        }
                        if total < fee:
                            infos.append((
                                'amount',
                                ValueError(
                                    n_("Not enough money. %(total)s < %(expected)s"),
                                    params,
                                ),
                            ))
                        elif total > fee:
                            infos.append((
                                'amount',
                                ValueError(
                                    n_("Too much money. %(total)s > %(expected)s"),
                                    params,
                                ),
                            ))
                        amounts_paid[registration['id']] = total

                if family_name != persona['family_name']:
                    problems.append((
                        'family_name', ValueError(n_("Family name doesn’t match.")),
                    ))

                if given_names != persona['given_names']:
                    problems.append((
                        'given_names', ValueError(n_("Given names don’t match.")),
                    ))

        datum.update({
            'category': category,
            'persona': persona,
            'persona_id': persona['id'] if persona else None,
            'event': event,
            'event_id': event.id if event else None,
            'registration_id': registration['id'] if registration else None,
            'amount': amount,
            'date': date,
            'problems': problems,
            'infos': infos,
        })
        return datum

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("transfers_file")
    @REQUESTdata("send_notifications", "transfers", "checksum")
    def money_transfers(self, rs: RequestState, send_notifications: bool,
                        transfers: Optional[str], checksum: Optional[str],
                        transfers_file: Optional[FileStorage],
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

        events = self.eventproxy.get_events(rs, self.eventproxy.list_events(rs))
        events_by_shortname = {event.shortname: event for event in events.values()}
        fields = parse.ExportFields.db_import
        reader = csv.DictReader(
            transferlines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        amounts_paid: dict[int, decimal.Decimal] = {}
        for lineno, raw_entry in enumerate(reader):
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno}
            data.append(
                self.examine_money_transfer(
                    rs, dataset, events_by_shortname=events_by_shortname,
                    amounts_paid=amounts_paid,
                ),
            )
        for ds1, ds2 in itertools.combinations(data, 2):
            if (ds1['persona_id'], ds1['category']) == (
                    ds2['persona_id'], ds2['category']):
                if ds1['persona_id']:
                    info = (
                        None,
                        ValueError(
                            n_("More than one transfer for this account"
                               " (lines %(first)s and %(second)s)."),
                            {'first': ds1['lineno'] + 1, 'second': ds2['lineno'] + 1}),
                    )
                    ds1['infos'].append(info)
                    ds2['infos'].append(info)

        if len(data) != len(transferlines):
            rs.append_validation_error(
                ("transfers", ValueError(n_("Lines didn’t match up."))))

        open_issues = any(e['problems'] for e in data)
        saldos: dict[int, decimal.Decimal] = defaultdict(decimal.Decimal)
        for datum in data:
            if datum['amount'] is None:
                continue
            saldos[datum['event_id'] or 0] += datum['amount']
            saldos[-1] += datum['amount']

        if rs.has_validation_errors() or not data or open_issues:
            rs.values['checksum'] = None
            return self.money_transfers_form(
                rs, data=data, csvfields=fields, saldos=saldos)

        current_checksum = get_hash(transfers.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.money_transfers_form(
                rs, data=data, csvfields=fields, saldos=saldos)

        # Here validation is finished
        transfers = [
            {
                'persona_id': datum['persona_id'],
                'registration_id': datum['registration_id'],
                'amount': datum['amount'],
                'date': datum['date'],
            }
            for datum in data
        ]
        with TransactionObserver(rs, self, "money_transfers"):
            if result := self.cdeproxy.book_money_transfers(rs, transfers):
                if send_notifications:
                    for transfer in result.membership_fees:
                        p = transfer.persona
                        headers: Headers = {
                            'Subject':
                                "Überweisung eingegangen – Guthaben zu gering!"
                                if p['balance'] < self.conf["MEMBERSHIP_FEE"] else
                                "Mitgliedsbeitrag eingegangen",
                            'To': (transfer.persona['username'],),
                        }
                        self.do_mail(
                            rs, 'parse/transfer_received', headers,
                            {
                                'persona': transfer.persona,
                                'address': make_postal_address(rs, transfer.persona),
                                'fee': self.conf['MEMBERSHIP_FEE'],
                            },
                        )
                    if result.membership_fees:
                        rs.notify(
                            "success",
                            n_("Booked %(num)s membership fees."
                               " There were %(new_members)s new members."),
                            {
                                'num': len(result.membership_fees),
                                'new_members': result.new_members,
                            },
                        )
                        # TODO: Also send overview to finance admins?
                    for event_id, booked_transfers in result.event_fees.items():
                        event = events[event_id]
                        rs.notify(
                            "success",
                            n_("Booked %(num)s event fees for %(event)s"),
                            {'num': len(booked_transfers), 'event': event.title},
                        )
                        headers = {
                            'Reply-To':
                                event.orga_address
                                or self.conf['FINANCE_ADMIN_ADDRESS'],
                            'Subject': f"Überweisung für {event.title} eingetroffen",
                        }
                        for transfer in booked_transfers:
                            headers['To'] = (transfer.persona['username'],)
                            self.do_mail(
                                rs, 'parse/event_transfer_received', headers,
                                {'transfer': transfer, 'event': event})
                        if event.orga_address:
                            # TODO: Also send this to finance admins?
                            headers = {
                                'To': (event.orga_address,),
                                'Reply-To': self.conf['FINANCE_ADMIN_ADDRESS'],
                                'Subject': "Neue Überweisungen für Eure Veranstaltung",
                                'Prefix': "",
                            }
                            self.do_mail(
                                rs, "parse/transfers_booked", headers,
                                {'num': len(booked_transfers)})
                    for event_id, reimbursements in result.event_reimbursements.items():
                        event = events[event_id]
                        rs.notify(
                            "success",
                            n_("Booked %(num)s reimbursements for %(event)s"),
                            {'num': len(reimbursements), 'event': event.title},
                        )
                        if event.orga_address:
                            # TODO: Also send this to finance admins?
                            headers = {
                                'To': (event.orga_address,),
                                'Reply-To': self.conf['FINANCE_ADMIN_ADDRESS'],
                                'Subject':
                                    "Erstattungen für Eure Veranstaltung durchgeführt.",
                                'Prefix': "",
                            }
                            self.do_mail(
                                rs, "parse/reimbursements_booked", headers,
                                {'num': len(reimbursements)})

                return self.redirect(rs, "cde/index")
            else:
                if result.index < 0:
                    rs.notify("warning", n_("DB serialization error."))
                else:
                    rs.notify(
                        "error",
                        n_("Unexpected error on line %(num)s."),
                        {'num': result.index + 1},
                    )
            return self.money_transfers_form(
                rs, data=data, csvfields=fields, saldos=saldos)
