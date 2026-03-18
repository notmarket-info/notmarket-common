"""Shared PostgreSQL connection pool with circuit breaker for Python services."""

import logging
import threading

import psycopg2
import psycopg2.pool

from notmarket_common.delivery import CircuitBreaker
from notmarket_common.retry import retry_with_backoff

log = logging.getLogger(__name__)

# Retryable psycopg2 exceptions (transient errors worth retrying).
PG_RETRYABLE = (
    psycopg2.OperationalError,
    psycopg2.InterfaceError,
    ConnectionError,
    OSError,
)


class DatabasePool:
    """Lazy PostgreSQL connection pool with circuit breaker.

    Wraps psycopg2 connections with:
    - Lazy pool creation (first use)
    - Circuit breaker to avoid hammering a down DB
    - Retry with backoff on transient errors
    - Thread-safe access via lock

    Usage::

        pool = DatabasePool(database_url)
        result = pool.execute_query("SELECT 1")
        rows = pool.execute_fetchall("SELECT * FROM t WHERE id = ANY(%s)", (ids,))
        pool.close()
    """

    def __init__(
        self,
        database_url,
        *,
        minconn=1,
        maxconn=10,
        connect_timeout=5,
        statement_timeout=30000,
        autocommit=True,
        max_retries=2,
        backoff_base=0.5,
        circuit_breaker=None,
    ):
        self._database_url = database_url
        self._minconn = minconn
        self._maxconn = maxconn
        self._connect_timeout = connect_timeout
        self._statement_timeout = statement_timeout
        self._autocommit = autocommit
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._pool = None
        self._lock = threading.Lock()
        self._breaker = circuit_breaker if circuit_breaker is not None else CircuitBreaker()

    def _ensure_pool(self):
        """Create pool lazily on first use. Must be called with lock held."""
        if self._pool is not None and not self._pool.closed:
            return self._pool
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=self._minconn,
            maxconn=self._maxconn,
            dsn=self._database_url,
            connect_timeout=self._connect_timeout,
            options=f"-c statement_timeout={self._statement_timeout}",
        )
        return self._pool

    def _get_conn(self):  # pragma: no cover
        """Get a connection from the pool."""
        with self._lock:
            pool = self._ensure_pool()
        conn = pool.getconn()
        conn.autocommit = self._autocommit
        return conn

    def _return_conn(self, conn):  # pragma: no cover
        """Return a connection to the pool."""
        try:
            with self._lock:
                if self._pool and not self._pool.closed:
                    self._pool.putconn(conn)
        except Exception:
            pass

    @property
    def is_available(self):
        """True if database URL is configured and circuit breaker is closed."""
        if not self._database_url:
            return False
        if self._breaker and self._breaker.is_open:
            return False
        return True

    def execute_fetchall(self, query, params=None):
        """Execute a query and return all rows. Returns [] on failure.

        Retries on transient errors. Records success/failure on circuit breaker.
        """
        if not self.is_available:
            return []

        def _do():
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                rows = cur.fetchall()
                cur.close()
                return rows
            finally:
                self._return_conn(conn)

        try:
            result = retry_with_backoff(
                fn=_do,
                max_retries=self._max_retries,
                backoff_base=self._backoff_base,
                retryable_exceptions=PG_RETRYABLE,
            )
            if self._breaker:
                self._breaker.record_success()
            return result
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.warning("DB query failed (graceful degradation): %s", e)
            return []

    def execute_fetchone(self, query, params=None):
        """Execute a query and return the first row. Returns None on failure."""
        if not self.is_available:
            return None

        def _do():
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                row = cur.fetchone()
                cur.close()
                return row
            finally:
                self._return_conn(conn)

        try:
            result = retry_with_backoff(
                fn=_do,
                max_retries=self._max_retries,
                backoff_base=self._backoff_base,
                retryable_exceptions=PG_RETRYABLE,
            )
            if self._breaker:
                self._breaker.record_success()
            return result
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.warning("DB query failed (graceful degradation): %s", e)
            return None

    def execute(self, query, params=None):
        """Execute a statement (INSERT/UPDATE/DELETE). Returns True on success."""
        if not self.is_available:
            return False

        def _do():
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                cur.close()
                return True
            finally:
                self._return_conn(conn)

        try:
            result = retry_with_backoff(
                fn=_do,
                max_retries=self._max_retries,
                backoff_base=self._backoff_base,
                retryable_exceptions=PG_RETRYABLE,
            )
            if self._breaker:
                self._breaker.record_success()
            return result
        except Exception as e:
            if self._breaker:
                self._breaker.record_failure()
            log.warning("DB execute failed (graceful degradation): %s", e)
            return False

    def close(self):
        """Close the pool and all connections."""
        with self._lock:
            if self._pool is not None:
                try:
                    self._pool.closeall()
                except Exception:
                    pass
                self._pool = None
