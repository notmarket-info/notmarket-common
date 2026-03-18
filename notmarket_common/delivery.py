"""Telegram and Discord delivery with retry and circuit breaker."""

import json
import logging
import re
import time

import requests

from notmarket_common.retry import retry_with_backoff

log = logging.getLogger(__name__)

DISCORD_CONTENT_LIMIT = 2000
TELEGRAM_CAPTION_LIMIT = 950


def mask_token(msg):
    """Mask bot tokens in error messages to prevent leaking secrets in logs."""
    return re.sub(r"(api\.telegram\.org/bot)[^/]+", r"\1***", str(msg))


class CircuitBreaker:
    """Simple circuit breaker for delivery channels.

    Opens after consecutive failures, auto-resets after timeout.

    NOT thread-safe — use one instance per thread or protect with
    an external lock in multi-threaded contexts.
    """

    def __init__(self, threshold=5, timeout_secs=60):
        self._threshold = threshold
        self._timeout_secs = timeout_secs
        self._failure_count = 0
        self._open_since = None

    @property
    def is_open(self):
        if self._open_since and time.monotonic() - self._open_since > self._timeout_secs:
            self._failure_count = 0
            self._open_since = None
        return self._failure_count >= self._threshold

    def record_success(self):
        self._failure_count = 0
        self._open_since = None

    def record_failure(self):
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._open_since = time.monotonic()


_SENTINEL = object()


class TelegramSender:
    """Telegram message sender with retry and circuit breaker.

    Args:
        bot_token: Telegram bot token.
        chat_id: Target chat ID.
        parse_mode: Message parse mode ("HTML" or "Markdown").
        timeout: HTTP request timeout in seconds.
        max_retries: Max retry attempts per request.
        backoff_base: Base delay for exponential backoff.
        circuit_breaker: CircuitBreaker instance, None (create default), or False (disable).
        disable_preview: Whether to disable web page preview.
    """

    def __init__(
        self,
        bot_token,
        chat_id,
        *,
        parse_mode="HTML",
        timeout=8,
        max_retries=2,
        backoff_base=1.0,
        circuit_breaker=_SENTINEL,
        disable_preview=True,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.disable_preview = disable_preview

        if circuit_breaker is _SENTINEL:
            self._breaker = CircuitBreaker()
        elif circuit_breaker is False:
            self._breaker = None
        else:
            self._breaker = circuit_breaker

    @property
    def is_available(self):
        """True if token and chat_id are configured."""
        return bool(self.bot_token) and bool(self.chat_id)

    def _post(self, url, **kwargs):
        """POST with retry and backoff."""
        kwargs.setdefault("timeout", self.timeout)

        def _do_post():
            response = requests.post(url, **kwargs)
            response.raise_for_status()
            return response

        return retry_with_backoff(
            fn=_do_post,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            mask_fn=mask_token,
        )

    def send_message(self, text, *, buttons=None):
        """Send a text message.

        Args:
            text: Message text.
            buttons: Optional list of button rows for inline keyboard.
                     Each row is a list of dicts with "text" and "url" keys.
        """
        if not self.is_available:
            return
        if self._breaker and self._breaker.is_open:
            log.warning("Telegram circuit breaker open, skipping delivery")
            return

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": self.parse_mode,
            }
            if self.disable_preview:
                payload["disable_web_page_preview"] = True
            if buttons:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            self._post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json=payload,
            )
            if self._breaker:
                self._breaker.record_success()
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.error("Telegram delivery error: %s", mask_token(e))

    def send_photo(self, image, *, caption=None, buttons=None):
        """Send a photo with optional caption.

        Args:
            image: Image bytes.
            caption: Optional caption text.
            buttons: Optional inline keyboard rows.
        """
        if not self.is_available:
            return
        if self._breaker and self._breaker.is_open:
            log.warning("Telegram circuit breaker open, skipping delivery")
            return

        try:
            data = {
                "chat_id": self.chat_id,
                "parse_mode": self.parse_mode,
            }
            if caption:
                data["caption"] = caption
            if buttons:
                data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
            self._post(
                f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
                data=data,
                files={"photo": ("signal.png", image)},
            )
            if self._breaker:
                self._breaker.record_success()
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.error("Telegram photo delivery error: %s", mask_token(e))

    def send_video(self, video, *, caption=None):
        """Send a video with optional caption.

        Args:
            video: Video bytes or file-like object.
            caption: Optional caption text.
        """
        if not self.is_available:
            return
        if self._breaker and self._breaker.is_open:
            log.warning("Telegram circuit breaker open, skipping delivery")
            return

        try:
            data = {
                "chat_id": self.chat_id,
                "parse_mode": self.parse_mode,
            }
            if caption:
                data["caption"] = caption
            self._post(
                f"https://api.telegram.org/bot{self.bot_token}/sendVideo",
                data=data,
                files={"video": ("video.mp4", video)},
            )
            if self._breaker:
                self._breaker.record_success()
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.error("Telegram video delivery error: %s", mask_token(e))

    def send(self, text, *, image=None, buttons=None, long_caption=None):
        """High-level send: text with optional image.

        If image is provided and text is shorter than TELEGRAM_CAPTION_LIMIT,
        sends as photo with text as caption. If text is longer, sends photo
        with long_caption, then text as a separate message.

        Args:
            text: Message text.
            image: Optional image bytes.
            buttons: Optional inline keyboard rows.
            long_caption: Fallback caption when text exceeds limit (used with image).
        """
        if not self.is_available:
            return
        if self._breaker and self._breaker.is_open:
            log.warning("Telegram circuit breaker open, skipping delivery")
            return

        try:
            if image:
                caption = text if len(text) < TELEGRAM_CAPTION_LIMIT else long_caption
                data = {
                    "chat_id": self.chat_id,
                    "parse_mode": self.parse_mode,
                }
                if caption:
                    data["caption"] = caption
                if buttons:
                    data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
                self._post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
                    data=data,
                    files={"photo": ("signal.png", image)},
                )
                if len(text) >= TELEGRAM_CAPTION_LIMIT:
                    payload = {
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": self.parse_mode,
                    }
                    if self.disable_preview:
                        payload["disable_web_page_preview"] = True
                    if buttons:
                        payload["reply_markup"] = {"inline_keyboard": buttons}
                    self._post(
                        f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                        json=payload,
                    )
            else:
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": self.parse_mode,
                }
                if self.disable_preview:
                    payload["disable_web_page_preview"] = True
                if buttons:
                    payload["reply_markup"] = {"inline_keyboard": buttons}
                self._post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json=payload,
                )
            if self._breaker:
                self._breaker.record_success()
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.error("Telegram delivery error: %s", mask_token(e))


def _truncate_discord(text, limit=DISCORD_CONTENT_LIMIT):
    """Truncate text to Discord's content limit with ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


class DiscordSender:
    """Discord webhook sender with retry and circuit breaker.

    Args:
        webhook_url: Discord webhook URL.
        timeout: HTTP request timeout in seconds.
        content_limit: Max content length (default 2000).
        max_retries: Max retry attempts per request.
        backoff_base: Base delay for exponential backoff.
        circuit_breaker: CircuitBreaker instance, None (create default), or False (disable).
    """

    def __init__(
        self,
        webhook_url,
        *,
        timeout=8,
        content_limit=DISCORD_CONTENT_LIMIT,
        max_retries=2,
        backoff_base=1.0,
        circuit_breaker=_SENTINEL,
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.content_limit = content_limit
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        if circuit_breaker is _SENTINEL:
            self._breaker = CircuitBreaker()
        elif circuit_breaker is False:
            self._breaker = None
        else:
            self._breaker = circuit_breaker

    @property
    def is_available(self):
        """True if webhook_url is configured."""
        return bool(self.webhook_url)

    def _post(self, url, **kwargs):
        """POST with retry and backoff."""
        kwargs.setdefault("timeout", self.timeout)

        def _do_post():
            response = requests.post(url, **kwargs)
            response.raise_for_status()
            return response

        return retry_with_backoff(
            fn=_do_post,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
        )

    def send(self, text, *, image=None):
        """Send a message to Discord via webhook.

        Args:
            text: Message content (auto-truncated to content_limit).
            image: Optional image bytes to attach.
        """
        if not self.is_available:
            return
        if self._breaker and self._breaker.is_open:
            log.warning("Discord circuit breaker open, skipping delivery")
            return

        try:
            text = _truncate_discord(text, self.content_limit)
            if image:
                self._post(
                    self.webhook_url,
                    data={"content": text},
                    files={"file": ("chart.png", image)},
                )
            else:
                self._post(self.webhook_url, json={"content": text})
            if self._breaker:
                self._breaker.record_success()
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.error("Discord delivery error: %s", e)
