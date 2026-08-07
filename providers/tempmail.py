"""Temporary mailbox client for catchmail.io.

No API key required — just pick a random address and poll for messages.
"""
from __future__ import annotations

import re
import random
import time

import httpx

from config import Config

_OTP_PATTERN = re.compile(r"\b(\d{6})\b")


class TempMailError(Exception):
    """Raised when no OTP arrives in time or the mailbox API fails."""


def generate_email(domain: str = "random") -> str:
    """Generate a random disposable address with realistic names."""
    if domain == "random":
        domain = random.choice(["catchmail.io", "mailistry.com", "zeppost.com"])
        
    first_names = [
        "james", "mary", "john", "patricia", "robert", "jennifer", "michael", "linda", 
        "william", "elizabeth", "david", "barbara", "richard", "susan", "joseph", "jessica", 
        "thomas", "sarah", "charles", "karen", "christopher", "nancy", "daniel", "lisa"
    ]
    last_names = [
        "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis", 
        "rodriguez", "martinez", "hernandez", "lopez", "gonzalez", "wilson", "anderson", 
        "thomas", "taylor", "moore", "jackson", "martin", "lee", "perez", "thompson", "white"
    ]
    
    first = random.choice(first_names)
    last = random.choice(last_names)
    number = random.randint(10, 9999)
    
    return f"{first}.{last}{number}@{domain}"


async def fetch_messages(email: str, *, timeout: int = 30) -> list[dict[str, object]]:
    """Return the message list for a mailbox, or [] on any API failure."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            "https://api.catchmail.io/api/v1/mailbox",
            params={"address": email},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        if isinstance(data, list):
            return data  # type: ignore[return-value]
        if isinstance(data, dict):
            for key in ("messages", "emails", "data", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value  # type: ignore[return-value]
        return []


async def read_message(message_id: str, email: str, *, timeout: int = 30) -> dict[str, object]:
    """Fetch a single message body (needed to find the OTP)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"https://api.catchmail.io/api/v1/message/{message_id}",
            params={"mailbox": email},
        )
        if resp.status_code >= 400:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}


def extract_otp(full_message: dict[str, object]) -> str | None:
    """Pull the 6-digit code from the email body only.

    The mailbox list headers (id, date, size) contain their own 6-digit runs
    (e.g. the message-id timestamp) that would cause false matches — the OTP
    lives in the message's body, never anywhere else.
    """
    body = full_message.get("body")
    if not isinstance(body, dict):
        return None
    for key in ("text", "html"):
        value = body.get(key)
        if isinstance(value, str):
            match = _OTP_PATTERN.search(value)
            if match:
                return match.group(1)
    return None


async def wait_for_otp(email: str, cfg: Config) -> str:
    """Poll catchmail.io until a 6-digit OTP arrives or the timeout elapses.

    Returns the code, or raises TempMailError.
    """
    deadline = time.monotonic() + cfg.verify_poll_timeout
    while True:
        messages = await fetch_messages(email, timeout=cfg.request_timeout)
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id") or msg.get("_id") or msg.get("message_id")
            if msg_id is None:
                continue
            full = await read_message(str(msg_id), email, timeout=cfg.request_timeout)
            code = extract_otp(full)
            if code:
                return code

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TempMailError(f"No OTP received for {email} within {cfg.verify_poll_timeout}s")
        await _sleep(min(cfg.verify_poll_interval, remaining))


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(max(0.1, seconds))
