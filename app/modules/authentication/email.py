"""Pluggable email delivery. Real providers implement `EmailSender`."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LoggingEmailSender:
    """Default stub: logs the recipient and subject only (never the body/token)."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("email stub: to=%s subject=%s", to, subject)


@dataclass
class InMemoryEmailSender:
    """Collects messages; intended for tests."""

    outbox: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append((to, subject, body))


_sender: EmailSender = LoggingEmailSender()


def get_email_sender() -> EmailSender:
    return _sender
