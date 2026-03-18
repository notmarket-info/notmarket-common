"""Tests for notmarket_common.db module."""

from unittest.mock import MagicMock, patch

from notmarket_common.db import DatabasePool


class TestDatabasePoolAvailability:
    def test_not_available_without_url(self):
        pool = DatabasePool("")
        assert pool.is_available is False

    def test_available_with_url(self):
        pool = DatabasePool("postgres://localhost/test")
        assert pool.is_available is True

    def test_not_available_when_breaker_open(self):
        pool = DatabasePool("postgres://localhost/test")
        pool._breaker._failure_count = 100
        pool._breaker._open_since = 999999999999.0
        assert pool.is_available is False

    def test_returns_empty_when_not_available(self):
        pool = DatabasePool("")
        assert pool.execute_fetchall("SELECT 1") == []
        assert pool.execute_fetchone("SELECT 1") is None
        assert pool.execute("SELECT 1") is False


class TestDatabasePoolClose:
    def test_close_without_pool(self):
        pool = DatabasePool("postgres://localhost/test")
        pool.close()  # should not raise

    def test_close_with_pool(self):
        pool = DatabasePool("postgres://localhost/test")
        mock_pool = MagicMock()
        pool._pool = mock_pool
        pool.close()
        mock_pool.closeall.assert_called_once()
        assert pool._pool is None

    def test_close_ignores_exception(self):
        pool = DatabasePool("postgres://localhost/test")
        mock_pool = MagicMock()
        mock_pool.closeall.side_effect = Exception("boom")
        pool._pool = mock_pool
        pool.close()  # should not raise
        assert pool._pool is None


class TestDatabasePoolExecute:
    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_fetchall_success(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.return_value = [("row1",), ("row2",)]
        result = pool.execute_fetchall("SELECT 1")
        assert result == [("row1",), ("row2",)]
        mock_retry.assert_called_once()

    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_fetchall_failure_returns_empty(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.side_effect = ConnectionError("boom")
        result = pool.execute_fetchall("SELECT 1")
        assert result == []
        assert pool._breaker._failure_count == 1

    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_fetchone_success(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.return_value = ("row1",)
        result = pool.execute_fetchone("SELECT 1")
        assert result == ("row1",)

    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_fetchone_failure_returns_none(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.side_effect = OSError("boom")
        result = pool.execute_fetchone("SELECT 1")
        assert result is None

    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_success(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.return_value = True
        assert pool.execute("INSERT INTO t VALUES (1)") is True

    @patch("notmarket_common.db.retry_with_backoff")
    def test_execute_failure_returns_false(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.side_effect = ConnectionError("boom")
        assert pool.execute("INSERT INTO t VALUES (1)") is False

    @patch("notmarket_common.db.retry_with_backoff")
    def test_circuit_breaker_records_success(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        pool._breaker._failure_count = 2
        mock_retry.return_value = [("ok",)]
        pool.execute_fetchall("SELECT 1")
        assert pool._breaker._failure_count == 0

    @patch("notmarket_common.db.retry_with_backoff")
    def test_circuit_breaker_records_failure(self, mock_retry):
        pool = DatabasePool("postgres://localhost/test")
        mock_retry.side_effect = ConnectionError("boom")
        pool.execute_fetchall("SELECT 1")
        pool.execute_fetchall("SELECT 1")
        assert pool._breaker._failure_count == 2


class TestEnsurePool:
    @patch("notmarket_common.db.psycopg2.pool.ThreadedConnectionPool")
    def test_creates_pool_lazily(self, mock_tpc):
        pool = DatabasePool("postgres://localhost/test", statement_timeout=5000)
        assert pool._pool is None
        with pool._lock:
            pool._ensure_pool()
        mock_tpc.assert_called_once()
        assert pool._pool is not None

    @patch("notmarket_common.db.psycopg2.pool.ThreadedConnectionPool")
    def test_reuses_existing_pool(self, mock_tpc):
        pool = DatabasePool("postgres://localhost/test")
        mock_existing = MagicMock()
        mock_existing.closed = False
        pool._pool = mock_existing
        with pool._lock:
            result = pool._ensure_pool()
        assert result is mock_existing
        mock_tpc.assert_not_called()
