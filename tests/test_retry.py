"""Tests for notmarket_common.retry — exponential backoff with jitter."""

from unittest.mock import MagicMock, patch

import requests

from notmarket_common.retry import retry_with_backoff


class TestRetryWithBackoff:
    @patch("notmarket_common.retry.time.sleep")
    def test_succeeds_on_first_attempt(self, mock_sleep):
        result = retry_with_backoff(lambda: "ok")
        assert result == "ok"
        mock_sleep.assert_not_called()

    @patch("notmarket_common.retry.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.ConnectionError("connection refused")
            return "ok"

        result = retry_with_backoff(flaky, max_retries=3, backoff_base=0.1)
        assert result == "ok"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("notmarket_common.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        def always_fail():
            raise requests.ConnectionError("connection refused")

        try:
            retry_with_backoff(always_fail, max_retries=2, backoff_base=0.1)
            assert False, "Should have raised"
        except requests.ConnectionError:
            pass

        assert mock_sleep.call_count == 2

    @patch("notmarket_common.retry.time.sleep")
    def test_retries_on_timeout(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.Timeout("timeout")
            return "ok"

        result = retry_with_backoff(flaky, max_retries=3, backoff_base=0.1)
        assert result == "ok"

    @patch("notmarket_common.retry.time.sleep")
    def test_does_not_retry_on_non_retryable_error(self, mock_sleep):
        def fail():
            raise ValueError("not retryable")

        try:
            retry_with_backoff(fail, max_retries=3, backoff_base=0.1)
            assert False, "Should have raised"
        except ValueError:
            pass

        mock_sleep.assert_not_called()

    @patch("notmarket_common.retry.time.sleep")
    def test_retries_on_server_error_status(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            resp = MagicMock(spec=requests.Response)
            if call_count < 2:
                resp.status_code = 503
                resp.raise_for_status.side_effect = requests.HTTPError("503")
                return resp
            resp.status_code = 200
            return resp

        result = retry_with_backoff(flaky, max_retries=3, backoff_base=0.1)
        assert result.status_code == 200

    @patch("notmarket_common.retry.time.sleep")
    def test_on_retry_callback(self, mock_sleep):
        callback_calls = []

        def on_retry(attempt, delay, error):
            callback_calls.append(attempt)

        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.ConnectionError("fail")
            return "ok"

        retry_with_backoff(flaky, max_retries=3, backoff_base=0.1, on_retry=on_retry)
        assert callback_calls == [0, 1]

    @patch("notmarket_common.retry.time.sleep")
    def test_backoff_max_caps_delay(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.ConnectionError("fail")
            return "ok"

        retry_with_backoff(flaky, max_retries=3, backoff_base=100.0, backoff_max=0.5)
        for call in mock_sleep.call_args_list:
            delay = call[0][0]
            assert delay <= 0.5

    @patch("notmarket_common.retry.time.sleep")
    def test_all_retries_exhausted_with_retryable_exception(self, mock_sleep):
        def always_fail():
            raise requests.Timeout("timeout")

        try:
            retry_with_backoff(always_fail, max_retries=2, backoff_base=0.01)
            assert False, "Should have raised"
        except requests.Timeout:
            pass

        assert mock_sleep.call_count == 2

    @patch("notmarket_common.retry.time.sleep")
    def test_server_error_on_all_retries_raises(self, mock_sleep):
        def always_503():
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 503
            resp.raise_for_status.side_effect = requests.HTTPError("503 Server Error")
            return resp

        try:
            retry_with_backoff(always_503, max_retries=1, backoff_base=0.01)
            assert False, "Should have raised"
        except requests.HTTPError:
            pass

    @patch("notmarket_common.retry.time.sleep")
    def test_on_retry_callback_for_http_status(self, mock_sleep):
        callback_calls = []

        def on_retry(attempt, delay, error):
            callback_calls.append((attempt, error))

        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            resp = MagicMock(spec=requests.Response)
            if call_count < 2:
                resp.status_code = 500
                return resp
            resp.status_code = 200
            return resp

        retry_with_backoff(flaky, max_retries=3, backoff_base=0.01, on_retry=on_retry)
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == 0
        assert callback_calls[0][1] is None

    @patch("notmarket_common.retry.time.sleep")
    def test_mask_fn_applied_to_error_logs(self, mock_sleep):
        mask_calls = []

        def track_mask(msg):
            mask_calls.append(msg)
            return "MASKED"

        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.ConnectionError("secret-token-123")
            return "ok"

        retry_with_backoff(flaky, max_retries=2, backoff_base=0.01, mask_fn=track_mask)
        assert len(mask_calls) >= 1

    @patch("notmarket_common.retry.time.sleep")
    def test_retries_on_429_rate_limit(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            resp = MagicMock(spec=requests.Response)
            if call_count < 2:
                resp.status_code = 429
                resp.raise_for_status.side_effect = requests.HTTPError("429")
                return resp
            resp.status_code = 200
            return resp

        result = retry_with_backoff(flaky, max_retries=3, backoff_base=0.01)
        assert result.status_code == 200

    @patch("notmarket_common.retry.time.sleep")
    def test_retries_on_os_error(self, mock_sleep):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("network unreachable")
            return "ok"

        result = retry_with_backoff(flaky, max_retries=3, backoff_base=0.01)
        assert result == "ok"

    @patch("notmarket_common.retry.time.sleep")
    def test_zero_retries_fails_immediately(self, mock_sleep):
        def always_fail():
            raise requests.ConnectionError("fail")

        try:
            retry_with_backoff(always_fail, max_retries=0, backoff_base=0.01)
            assert False, "Should have raised"
        except requests.ConnectionError:
            pass

        mock_sleep.assert_not_called()
