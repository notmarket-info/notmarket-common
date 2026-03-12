"""Tests for notmarket_common.delivery — Telegram and Discord senders."""

from unittest.mock import MagicMock, patch

from notmarket_common.delivery import (
    CircuitBreaker,
    DiscordSender,
    TelegramSender,
    _truncate_discord,
    mask_token,
)


def _mock_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# -- mask_token ---------------------------------------------------------------


class TestMaskToken:
    def test_masks_telegram_bot_token(self):
        msg = "Error at https://api.telegram.org/bot123456:ABC-DEF/sendMessage"
        masked = mask_token(msg)
        assert "123456:ABC-DEF" not in masked
        assert "api.telegram.org/bot***" in masked

    def test_no_token_unchanged(self):
        msg = "Simple error message"
        assert mask_token(msg) == msg


# -- CircuitBreaker -----------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(threshold=3)
        assert cb.is_open is False

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(threshold=2)
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_record_success_resets_state(self):
        cb = CircuitBreaker(threshold=2, timeout_secs=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.record_success()
        assert cb.is_open is False
        assert cb._failure_count == 0
        assert cb._open_since is None

    @patch("notmarket_common.delivery.time.monotonic")
    def test_auto_resets_after_timeout(self, mock_time):
        cb = CircuitBreaker(threshold=2, timeout_secs=10)
        mock_time.return_value = 100.0
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        mock_time.return_value = 200.0
        assert cb.is_open is False

    def test_stays_open_within_timeout(self):
        cb = CircuitBreaker(threshold=2, timeout_secs=9999)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True


# -- _truncate_discord --------------------------------------------------------


class TestTruncateDiscord:
    def test_short_text_unchanged(self):
        assert _truncate_discord("hello") == "hello"

    def test_long_text_truncated(self):
        long_text = "x" * 2500
        result = _truncate_discord(long_text)
        assert len(result) == 2000
        assert result.endswith("\u2026")

    def test_exact_limit_unchanged(self):
        text = "x" * 2000
        assert _truncate_discord(text) == text

    def test_custom_limit(self):
        text = "x" * 200
        result = _truncate_discord(text, limit=100)
        assert len(result) == 100


# -- TelegramSender ----------------------------------------------------------


class TestTelegramSender:
    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_posts_to_api(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("test-token", "12345")
        sender.send_message("hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "test-token" in url
        assert "sendMessage" in url

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_html_parse_mode(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send_message("<b>bold</b>")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_markdown_parse_mode(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123", parse_mode="Markdown")
        sender.send_message("**bold**")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "Markdown"

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_disables_preview(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send_message("hello")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["disable_web_page_preview"] is True

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_preview_enabled(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123", disable_preview=False)
        sender.send_message("hello")
        payload = mock_post.call_args.kwargs["json"]
        assert "disable_web_page_preview" not in payload

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_with_buttons(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        buttons = [[{"text": "Open", "url": "https://example.com"}]]
        sender.send_message("hello", buttons=buttons)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["reply_markup"]["inline_keyboard"] == buttons

    def test_send_message_noop_no_token(self):
        sender = TelegramSender("", "123")
        sender.send_message("hello")  # should not raise

    def test_send_message_noop_no_chat_id(self):
        sender = TelegramSender("tok", "")
        sender.send_message("hello")  # should not raise

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_error_does_not_raise(self, mock_post):
        mock_post.side_effect = Exception("network error")
        sender = TelegramSender("tok", "123", max_retries=0)
        sender.send_message("hello")  # should not raise

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_error_increments_breaker(self, mock_post):
        mock_post.side_effect = Exception("network error")
        breaker = CircuitBreaker(threshold=2)
        sender = TelegramSender("tok", "123", max_retries=0, circuit_breaker=breaker)
        sender.send_message("hello")
        assert breaker._failure_count == 1

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_success_resets_breaker(self, mock_post):
        mock_post.return_value = _mock_response()
        breaker = CircuitBreaker(threshold=5)
        breaker.record_failure()
        breaker.record_failure()
        sender = TelegramSender("tok", "123", circuit_breaker=breaker)
        sender.send_message("hello")
        assert breaker._failure_count == 0

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_skips_when_breaker_open(self, mock_post):
        breaker = CircuitBreaker(threshold=1)
        breaker.record_failure()
        sender = TelegramSender("tok", "123", circuit_breaker=breaker)
        sender.send_message("hello")
        mock_post.assert_not_called()

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_no_breaker(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123", circuit_breaker=False)
        sender.send_message("hello")
        mock_post.assert_called_once()

    @patch("notmarket_common.delivery.requests.post")
    def test_send_message_no_breaker_error_does_not_raise(self, mock_post):
        mock_post.side_effect = Exception("fail")
        sender = TelegramSender("tok", "123", circuit_breaker=False, max_retries=0)
        sender.send_message("hello")  # should not raise


# -- TelegramSender.send_photo ------------------------------------------------


class TestTelegramSendPhoto:
    @patch("notmarket_common.delivery.requests.post")
    def test_send_photo_posts_to_api(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send_photo(b"png-bytes", caption="my photo")
        url = mock_post.call_args[0][0]
        assert "sendPhoto" in url
        assert "files" in mock_post.call_args.kwargs

    @patch("notmarket_common.delivery.requests.post")
    def test_send_photo_with_buttons(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        buttons = [[{"text": "Click", "url": "https://example.com"}]]
        sender.send_photo(b"png-bytes", caption="photo", buttons=buttons)
        data = mock_post.call_args.kwargs["data"]
        assert "reply_markup" in data

    @patch("notmarket_common.delivery.requests.post")
    def test_send_photo_skips_when_breaker_open(self, mock_post):
        breaker = CircuitBreaker(threshold=1)
        breaker.record_failure()
        sender = TelegramSender("tok", "123", circuit_breaker=breaker)
        sender.send_photo(b"png-bytes")
        mock_post.assert_not_called()

    def test_send_photo_noop_no_credentials(self):
        sender = TelegramSender("", "")
        sender.send_photo(b"png-bytes")  # should not raise

    @patch("notmarket_common.delivery.requests.post")
    def test_send_photo_error_does_not_raise(self, mock_post):
        mock_post.side_effect = Exception("fail")
        sender = TelegramSender("tok", "123", max_retries=0)
        sender.send_photo(b"png-bytes")  # should not raise


# -- TelegramSender.send (high-level) ----------------------------------------


class TestTelegramSend:
    @patch("notmarket_common.delivery.requests.post")
    def test_send_text_only(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send("hello")
        assert mock_post.call_count == 1
        url = mock_post.call_args[0][0]
        assert "sendMessage" in url

    @patch("notmarket_common.delivery.requests.post")
    def test_send_with_image_short_text(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send("short text", image=b"png-bytes")
        assert mock_post.call_count == 1
        url = mock_post.call_args[0][0]
        assert "sendPhoto" in url

    @patch("notmarket_common.delivery.requests.post")
    def test_send_with_image_long_text_splits(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        long_text = "x" * 1000
        sender.send(long_text, image=b"png-bytes", long_caption="Summary")
        assert mock_post.call_count == 2
        first_url = mock_post.call_args_list[0][0][0]
        assert "sendPhoto" in first_url
        second_url = mock_post.call_args_list[1][0][0]
        assert "sendMessage" in second_url

    @patch("notmarket_common.delivery.requests.post")
    def test_send_with_image_long_text_uses_long_caption(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        long_text = "x" * 1000
        sender.send(long_text, image=b"png-bytes", long_caption="Short summary")
        photo_data = mock_post.call_args_list[0].kwargs["data"]
        assert photo_data["caption"] == "Short summary"

    @patch("notmarket_common.delivery.requests.post")
    def test_send_text_only_disables_preview(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send("hello")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["disable_web_page_preview"] is True

    @patch("notmarket_common.delivery.requests.post")
    def test_send_long_text_followup_disables_preview(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        sender.send("x" * 1000, image=b"png-bytes")
        followup_payload = mock_post.call_args_list[1].kwargs["json"]
        assert followup_payload["disable_web_page_preview"] is True

    @patch("notmarket_common.delivery.requests.post")
    def test_send_with_buttons(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = TelegramSender("tok", "123")
        buttons = [[{"text": "Open", "url": "https://example.com"}]]
        sender.send("hello", buttons=buttons)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["reply_markup"]["inline_keyboard"] == buttons

    @patch("notmarket_common.delivery.requests.post")
    def test_send_skips_when_breaker_open(self, mock_post):
        breaker = CircuitBreaker(threshold=1)
        breaker.record_failure()
        sender = TelegramSender("tok", "123", circuit_breaker=breaker)
        sender.send("hello")
        mock_post.assert_not_called()

    def test_send_noop_no_token(self):
        sender = TelegramSender("", "123")
        sender.send("hello")

    @patch("notmarket_common.delivery.requests.post")
    def test_send_error_does_not_raise(self, mock_post):
        mock_post.side_effect = Exception("fail")
        sender = TelegramSender("tok", "123", max_retries=0)
        sender.send("hello")  # should not raise


# -- TelegramSender.is_available ----------------------------------------------


class TestTelegramIsAvailable:
    def test_available_when_configured(self):
        sender = TelegramSender("tok", "123")
        assert sender.is_available is True

    def test_unavailable_no_token(self):
        sender = TelegramSender("", "123")
        assert sender.is_available is False

    def test_unavailable_no_chat_id(self):
        sender = TelegramSender("tok", "")
        assert sender.is_available is False


# -- DiscordSender ------------------------------------------------------------


class TestDiscordSender:
    @patch("notmarket_common.delivery.requests.post")
    def test_send_text_only(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        sender.send("hello")
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["content"] == "hello"

    @patch("notmarket_common.delivery.requests.post")
    def test_send_with_image(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        sender.send("hello", image=b"png-bytes")
        assert "files" in mock_post.call_args.kwargs

    def test_send_noop_no_webhook(self):
        sender = DiscordSender("")
        sender.send("hello")  # should not raise

    @patch("notmarket_common.delivery.requests.post")
    def test_send_error_does_not_raise(self, mock_post):
        mock_post.side_effect = Exception("network error")
        sender = DiscordSender("https://discord.com/api/webhooks/test", max_retries=0)
        sender.send("hello")  # should not raise

    @patch("notmarket_common.delivery.requests.post")
    def test_send_truncates_long_content_text_only(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        sender.send("x" * 2500)
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["content"]) <= 2000

    @patch("notmarket_common.delivery.requests.post")
    def test_send_truncates_long_content_with_image(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        sender.send("x" * 2500, image=b"png-bytes")
        data = mock_post.call_args.kwargs["data"]
        assert len(data["content"]) <= 2000

    @patch("notmarket_common.delivery.requests.post")
    def test_send_preserves_short_content(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        sender.send("hello")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["content"] == "hello"

    @patch("notmarket_common.delivery.requests.post")
    def test_send_skips_when_breaker_open(self, mock_post):
        breaker = CircuitBreaker(threshold=1)
        breaker.record_failure()
        sender = DiscordSender("https://discord.com/api/webhooks/test", circuit_breaker=breaker)
        sender.send("hello")
        mock_post.assert_not_called()

    @patch("notmarket_common.delivery.requests.post")
    def test_send_error_increments_breaker(self, mock_post):
        mock_post.side_effect = Exception("fail")
        breaker = CircuitBreaker(threshold=5)
        sender = DiscordSender(
            "https://discord.com/api/webhooks/test", circuit_breaker=breaker, max_retries=0
        )
        sender.send("hello")
        assert breaker._failure_count == 1

    @patch("notmarket_common.delivery.requests.post")
    def test_send_success_resets_breaker(self, mock_post):
        mock_post.return_value = _mock_response()
        breaker = CircuitBreaker(threshold=5)
        breaker.record_failure()
        breaker.record_failure()
        sender = DiscordSender(
            "https://discord.com/api/webhooks/test", circuit_breaker=breaker
        )
        sender.send("hello")
        assert breaker._failure_count == 0

    @patch("notmarket_common.delivery.requests.post")
    def test_send_no_breaker(self, mock_post):
        mock_post.return_value = _mock_response()
        sender = DiscordSender(
            "https://discord.com/api/webhooks/test", circuit_breaker=False
        )
        sender.send("hello")
        mock_post.assert_called_once()


# -- DiscordSender.is_available -----------------------------------------------


class TestDiscordIsAvailable:
    def test_available_when_configured(self):
        sender = DiscordSender("https://discord.com/api/webhooks/test")
        assert sender.is_available is True

    def test_unavailable_no_webhook(self):
        sender = DiscordSender("")
        assert sender.is_available is False
