import collections
import dataclasses
import datetime
import decimal
from collections.abc import Callable
from typing import Optional

import cdedb.models.core as models_core
import cdedb.models.event as models_event
from cdedb.common import CdEDBObject, RequestState, n_
from cdedb.config import Config

_CONF = Config()


@dataclasses.dataclass
class MoneyTransferMember:
    persona: models_core.CdEPersona
    amount: decimal.Decimal
    date: datetime.date


@dataclasses.dataclass
class MoneyTransferEvent:
    persona: models_core.CorePersona
    amount: decimal.Decimal
    date: datetime.date
    registration: CdEDBObject


@dataclasses.dataclass
class MoneyTransfersResult:
    success: bool = True
    index: int = -1

    membership_fees: list[MoneyTransferMember] = dataclasses.field(default_factory=list)
    event_fees: dict[int, list[MoneyTransferEvent]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(list)
    )
    event_reimbursements: dict[int, list[MoneyTransferEvent]] = dataclasses.field(
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
        do_mail: Callable[..., Optional[str]],
        events: models_event.CdEDataclassMap[models_event.Event],
    ) -> None:
        # Import here to avoid cyclic imports.
        from cdedb.frontend.common import Headers  # noqa: PLC0415

        if send_individual_notifications:
            for member_transfer in self.membership_fees:
                headers: Headers = {
                    'Subject': "Überweisung eingegangen – Guthaben zu gering!"
                    if member_transfer.persona.balance < _CONF["MEMBERSHIP_FEE"]
                    else "Mitgliedsbeitrag eingegangen",
                    'To': [member_transfer.persona.username],
                }
                do_mail(
                    rs,
                    'parse/transfer_received',
                    headers,
                    {
                        'persona': member_transfer.persona,
                        'address': member_transfer.persona.get_postal_address(rs),
                        'transfer': member_transfer,
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
                    headers['To'] = [transfer.persona.username]
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
                    headers['To'] = [transfer.persona.username]
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
                    'Subject': "Erstattungen für Eure Veranstaltung durchgeführt.",
                    'Prefix': "",
                }
                do_mail(
                    rs,
                    "parse/event_reimbursements_booked",
                    headers,
                    {'num': len(reimbursements), 'event': event},
                )
