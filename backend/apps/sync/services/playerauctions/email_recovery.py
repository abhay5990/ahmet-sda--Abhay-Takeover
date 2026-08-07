"""Secondary Gmail IMAP trigger for PlayerAuctions order recovery.

Emails are never treated as the order source of truth. A matching notification
only identifies the store and PA order ID; the worker then asks the shared PA
relay for the authoritative order payload and sends it through the normal SDA
raw-payload parser and pool-sale reconciliation path.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import timedelta
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses
from typing import Iterable

from django.utils import timezone

from apps.integrations.models import IntegrationAccount, ServiceCredential
from apps.integrations.providers.registry import clear_client_cache
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.enums import ResourceType
from apps.sync.services.registry import build_service

logger = logging.getLogger(__name__)

PA_SENDER = 'noreply@playerauctions.com'
PA_SUBJECT_MARKERS = (
    'you have a new automatic delivery account order',
    'you have a new order',
)
ORDER_ID_PATTERNS = (
    re.compile(r'\border\s*(?:id|number)?\s*[:#]\s*(\d{6,})\b', re.I),
    re.compile(r'[?&](?:orderid|order_id)=(\d{6,})\b', re.I),
)
RECIPIENT_HEADERS = (
    'X-Original-To', 'X-Forwarded-To', 'Delivered-To',
    'X-Envelope-To', 'To', 'Cc',
)
IMAP_CREDENTIAL_SLUG = 'playerauctions-imap-recovery'


@dataclass(frozen=True)
class EmailOrderCandidate:
    order_id: str
    account_slug: str
    message_id: str
    subject: str


def _decode_header(value: str | None) -> str:
    decoded: list[str] = []
    for part, charset in decode_header(value or ''):
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            decoded.append(part)
    return ''.join(decoded)


def _message_text(message: Message) -> str:
    chunks: list[str] = []
    parts: Iterable[Message] = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_maintype() == 'multipart':
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or 'utf-8'
        chunks.append(payload.decode(charset, errors='replace'))
    return '\n'.join(chunks)


def parse_playerauctions_email(
    message: Message,
    recipient_map: dict[str, str],
) -> EmailOrderCandidate | None:
    """Return a mapped PA order candidate, or ``None`` for unrelated mail."""
    sender_header = (message.get('From', '') or '').lower()
    subject = _decode_header(message.get('Subject', '')).strip()
    # Python's permissive email parser can normalize the provider's bracketed
    # display name to just `"No Reply"`; the later relay lookup remains the
    # authoritative verification before anything is written to SDA.
    sender_matches = (
        PA_SENDER in sender_header
        or sender_header.strip().strip('"') == 'no reply'
    )
    if not sender_matches or not any(
        marker in subject.lower() for marker in PA_SUBJECT_MARKERS
    ):
        return None

    recipients: set[str] = set()
    for header in RECIPIENT_HEADERS:
        recipients.update(
            address.lower()
            for _, address in getaddresses(message.get_all(header, []))
            if address
        )
    account_slug = next(
        (recipient_map[address] for address in recipients if address in recipient_map),
        None,
    )
    if not account_slug:
        return None

    text = _message_text(message)
    order_id = next(
        (match.group(1) for pattern in ORDER_ID_PATTERNS for match in pattern.finditer(text)),
        None,
    )
    if not order_id:
        return None

    return EmailOrderCandidate(
        order_id=order_id,
        account_slug=account_slug,
        message_id=message.get('Message-ID', ''),
        subject=subject,
    )


class PlayerAuctionsEmailRecovery:
    """Read bounded PA notifications and recover only orders absent from SDA."""

    def __init__(self) -> None:
        self.recipient_map: dict[str, str] = {}

    def _load_config(self) -> dict | None:
        credential = ServiceCredential.objects.filter(
            slug=IMAP_CREDENTIAL_SLUG,
            is_active=True,
        ).first()
        if credential is None:
            return None
        config = credential.credentials or {}
        self.recipient_map = {
            str(address).lower(): str(slug)
            for address, slug in (config.get('recipient_map') or {}).items()
        }
        if not (
            config.get('email')
            and config.get('app_password')
            and self.recipient_map
        ):
            return None
        return config

    def run(self, *, days: int = 7, limit: int = 100) -> dict[str, int]:
        summary = {
            'examined': 0, 'candidates': 0, 'existing': 0,
            'recovered': 0, 'incomplete': 0, 'failed': 0,
        }
        config = self._load_config()
        if config is None:
            logger.info('pa_email_recovery: skipped because IMAP is not configured')
            return summary

        since = (timezone.now() - timedelta(days=max(1, days))).strftime('%d-%b-%Y')
        client = imaplib.IMAP4_SSL(
            config.get('host', 'imap.gmail.com'),
            int(config.get('port', 993)),
            ssl_context=ssl.create_default_context(),
            timeout=30,
        )
        try:
            client.login(
                config['email'], config['app_password'],
            )
            status, _ = client.select('INBOX', readonly=True)
            if status != 'OK':
                raise RuntimeError('Could not select the IMAP inbox.')
            status, data = client.uid('search', None, 'SINCE', since, 'FROM', PA_SENDER)
            if status != 'OK':
                raise RuntimeError('Could not search PlayerAuctions notification emails.')
            uids = (data[0] or b'').split()[-max(1, limit):]
            for uid in uids:
                candidate = self._candidate_from_uid(client, uid)
                summary['examined'] += 1
                if not candidate:
                    continue
                summary['candidates'] += 1
                outcome = self._recover_candidate(candidate)
                if outcome in summary:
                    summary[outcome] += 1
        finally:
            try:
                client.logout()
            except Exception:
                try:
                    client.shutdown()
                except Exception:
                    pass
        logger.info('pa_email_recovery: %s', summary)
        return summary

    def _candidate_from_uid(
        self, client: imaplib.IMAP4_SSL, uid: bytes,
    ) -> EmailOrderCandidate | None:
        status, data = client.uid('fetch', uid, '(RFC822)')
        if status != 'OK' or not data or not isinstance(data[0], tuple):
            return None
        return parse_playerauctions_email(
            email.message_from_bytes(data[0][1]), self.recipient_map,
        )

    def _recover_candidate(self, candidate: EmailOrderCandidate) -> str:
        from apps.orders.models import Order

        account = IntegrationAccount.objects.select_related('credential', 'group').filter(
            slug=candidate.account_slug,
            provider='playerauctions',
            is_active=True,
            credential__is_active=True,
        ).first()
        if account is None:
            logger.warning('pa_email_recovery: inactive mapped account %s', candidate.account_slug)
            return 'failed'
        if Order.objects.filter(
            integration_account=account, store_order_id=candidate.order_id,
        ).exists():
            return 'existing'

        clear_client_cache()
        try:
            service = build_service(
                ResourceType.ORDERS,
                account.provider,
                credential=account.credential,
                proxy_pool=build_proxy_pool(),
                proxy_group=get_group_name(account),
            )
            outcome = service.recover_order_by_id(account, candidate.order_id)
            if outcome == 'recovered':
                return 'recovered'
            if outcome == 'skipped_incomplete_status':
                return 'incomplete'
            return 'failed'
        except Exception:
            logger.exception(
                'pa_email_recovery: order %s failed for %s',
                candidate.order_id, candidate.account_slug,
            )
            return 'failed'
        finally:
            clear_client_cache()
