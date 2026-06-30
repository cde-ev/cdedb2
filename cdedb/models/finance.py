import collections
import dataclasses
import datetime
import decimal
from collections.abc import Callable

import cdedb.models.event as models_event
from cdedb.common import CdEDBObject, RequestState, n_
from cdedb.config import Config

_CONF = Config()


@dataclasses.dataclass
class MoneyTransfer:
    persona: CdEDBObject
    amount: decimal.Decimal
    date: datetime.date

    registration: CdEDBObject | None = None


@dataclasses.dataclass
class MoneyTransfersResult:
    success: bool = True
    index: int = -1

    membership_fees: list[MoneyTransfer] = dataclasses.field(default_factory=list)
    event_fees: dict[int, list[MoneyTransfer]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(list)
    )
    event_reimbursements: dict[int, list[MoneyTransfer]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(list)
    )

    new_members: int = 0

    def __bool__(self) -> bool:
        return self.success

    def send_notifications(
        self,
        rs: RequestState,
        *,
        send_individual_notifications: bool,
        by_orga: bool,
        do_mail: Callable[..., str | None],
        events: models_event.CdEDataclassMap[models_event.Event],
    ) -> None:
        # Import here to avoid cyclic imports.
        from cdedb.frontend.common import Headers, make_postal_address  # noqa: PLC0415

        if send_individual_notifications:
            for transfer in self.membership_fees:
                p = transfer.persona
                if p['balance'] < _CONF["MEMBERSHIP_FEE"]:
                    subject = "Überweisung eingegangen – Guthaben zu gering!"
                else:
                    subject = "Mitgliedsbeitrag eingegangen"
                headers: Headers = {
                    'Subject': subject,
                    'To': [transfer.persona['username']],
                }
                do_mail(
                    rs,
                    'parse/transfer_received',
                    headers,
                    {
                        'persona': transfer.persona,
                        'address': make_postal_address(rs, transfer.persona),
                        'transfer': transfer,
                        'fee': _CONF['MEMBERSHIP_FEE'],
                    },
                )

        if self.membership_fees:
            rs.notify(
                "success",
                n_(
                    "Booked %(num)s membership fees."
                    " There were %(new_members)s new members."
                ),
                {
                    'num': len(self.membership_fees),
                    'new_members': self.new_members,
                },
            )

        for event_id, booked_transfers in self.event_fees.items():
            event = events[event_id]

            if by_orga:
                to = [event.orga_address, _CONF['EVENT_FINANCE_ADMIN_ADDRESS']]
                reply_to = event.orga_address or _CONF['EVENT_FINANCE_ADMIN_ADDRESS']
            else:
                to = [event.orga_address]
                reply_to = _CONF['FINANCE_ADMIN_ADDRESS']

            rs.notify(
                "success",
                n_("Booked %(num)s event fees for %(event)s."),
                {'num': len(booked_transfers), 'event': event.title},
            )
            headers = {
                'Reply-To': reply_to,
                'Subject': f"Überweisung für {event.title} eingetroffen",
            }
            if send_individual_notifications:
                for transfer in booked_transfers:
                    headers['To'] = [transfer.persona['username']]
                    do_mail(
                        rs,
                        'parse/event_transfer_received',
                        headers,
                        {'transfer': transfer, 'event': event},
                    )
            if any(to):
                headers = {
                    'To': to,
                    'Reply-To': reply_to,
                    'Subject': "Neue Überweisungen für Eure Veranstaltung",
                    'Prefix': "",
                }
                do_mail(
                    rs,
                    "parse/event_transfers_booked",
                    headers,
                    {'num': len(booked_transfers), 'event': event},
                )

        for event_id, reimbursements in self.event_reimbursements.items():
            event = events[event_id]

            if by_orga:
                to = [event.orga_address, _CONF['EVENT_FINANCE_ADMIN_ADDRESS']]
                reply_to = _CONF['EVENT_FINANCE_ADMIN_ADDRESS']
            else:
                to = [event.orga_address]
                reply_to = _CONF['FINANCE_ADMIN_ADDRESS']

            rs.notify(
                "success",
                n_("Booked %(num)s reimbursements for %(event)s."),
                {'num': len(reimbursements), 'event': event.title},
            )
            headers = {
                'Reply-To': reply_to,
                'Subject': f"Erstattung für {event.title} ausgeführt",
            }
            if send_individual_notifications:
                for transfer in reimbursements:
                    headers['To'] = [transfer.persona['username']]
                    do_mail(
                        rs,
                        'parse/event_reimbursement_booked',
                        headers,
                        {
                            'transfer': transfer,
                            'event': event,
                            'finance_admin_address': _CONF['FINANCE_ADMIN_ADDRESS'],
                        },
                    )
            if any(to):
                headers = {
                    'To': to,
                    'Reply-To': reply_to,
                    'Subject': "Erstattungen für Eure Veranstaltung durchgeführt",
                    'Prefix': "",
                }
                do_mail(
                    rs,
                    "parse/event_reimbursements_booked",
                    headers,
                    {'num': len(reimbursements), 'event': event},
                )
