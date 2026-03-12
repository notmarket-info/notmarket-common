"""Retry with exponential backoff and jitter for transient failures."""

import logging
import random
import time

import requests

log = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    requests.ConnectionError,
    requests.Timeout,
    ConnectionError,
    TimeoutError,
    OSError,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 30.0


def retry_with_backoff(
    fn,
    max_retries=None,
    backoff_base=None,
    backoff_max=None,
    retryable_exceptions=None,
    on_retry=None,
    mask_fn=None,
):
    """Execute fn with exponential backoff and jitter on transient failures.

    Args:
        fn: Callable to execute. For HTTP calls, should return a Response object.
        max_retries: Max retry attempts (default 3).
        backoff_base: Base delay in seconds (default 1.0).
        backoff_max: Max delay cap in seconds (default 30.0).
        retryable_exceptions: Tuple of exception types to retry on.
        on_retry: Optional callback(attempt, delay, error) called before each retry.
        mask_fn: Optional callable to mask sensitive data in log messages (e.g. bot tokens).

    Returns:
        The return value of fn on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    if max_retries is None:
        max_retries = DEFAULT_MAX_RETRIES
    if backoff_base is None:
        backoff_base = DEFAULT_BACKOFF_BASE
    if backoff_max is None:
        backoff_max = DEFAULT_BACKOFF_MAX
    if retryable_exceptions is None:
        retryable_exceptions = RETRYABLE_EXCEPTIONS
    if mask_fn is None:
        mask_fn = str

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            result = fn()

            if (
                isinstance(result, requests.Response)
                and result.status_code in RETRYABLE_STATUS_CODES
            ):
                if attempt < max_retries:
                    delay = _calculate_delay(attempt, backoff_base, backoff_max)
                    log.warning(
                        "HTTP %d on attempt %d/%d, retrying in %.1fs",
                        result.status_code,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                    )
                    if on_retry:
                        on_retry(attempt, delay, None)
                    time.sleep(delay)
                    continue
                result.raise_for_status()

            return result

        except retryable_exceptions as e:
            last_error = e
            if attempt < max_retries:
                delay = _calculate_delay(attempt, backoff_base, backoff_max)
                log.warning(
                    "Transient error on attempt %d/%d: %s. Retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    mask_fn(e),
                    delay,
                )
                if on_retry:
                    on_retry(attempt, delay, e)
                time.sleep(delay)
            else:
                log.error(
                    "All %d attempts failed. Last error: %s",
                    max_retries + 1,
                    mask_fn(e),
                )
                raise

    raise last_error  # pragma: no cover — unreachable: loop always returns or raises


def _calculate_delay(attempt, base, max_delay):
    """Exponential backoff with full jitter."""
    delay = min(base * (2**attempt), max_delay)
    return random.uniform(0, delay)
