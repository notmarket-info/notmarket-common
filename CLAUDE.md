# CLAUDE.md — notmarket-common

Shared Python package: delivery (Telegram/Discord), retry (exponential backoff), health (HTTP server).

## Module Map

| Module | Pure? | Purpose |
|--------|-------|---------|
| `delivery.py` | Yes | `TelegramSender`, `DiscordSender`, `CircuitBreaker`, `mask_token`, `_truncate_discord` |
| `retry.py` | Yes | `retry_with_backoff` with exponential backoff + jitter, retryable exceptions/status codes |
| `health.py` | No | `start_health_server(port, healthy_fn)` — HTTP `/health` on daemon thread |

## Usage by Services

| Service | Uses |
|---------|------|
| notifier-snapshot | All three modules (re-exports for backward compat) |
| data-indexer | `TelegramSender`, `DiscordSender` (delivery + generate_videos) |
| signal-bot | `TelegramSender`, `start_health_server` |
| monitor-ingest | `TelegramSender` (alerter) |

## Key APIs

```python
# Telegram
sender = TelegramSender(token, chat_id, parse_mode="HTML", timeout=8,
                         max_retries=2, circuit_breaker=None, disable_preview=True)
sender.send_message(text, buttons=None)
sender.send_photo(image, caption=None, buttons=None)
sender.send_video(video, caption=None)
sender.send(text, image=None, buttons=None, long_caption=None)

# Discord
sender = DiscordSender(webhook_url, timeout=8, content_limit=2000,
                        max_retries=2, circuit_breaker=None)
sender.send(text, image=None)

# circuit_breaker: None=create default, False=disable, or pass instance

# Retry
retry_with_backoff(fn, max_retries=3, backoff_base=1.0, backoff_max=30.0,
                    retryable_exceptions=None, on_retry=None, mask_fn=None)

# Health
server = start_health_server(port, healthy_fn=None)  # None = always healthy
```

## Build & Test

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v --tb=short
flake8 notmarket_common/ tests/ --count --select=E9,F63,F7,F82
black --line-length=100 . && isort --profile black .
```

## Testing Conventions

- Tests in `tests/test_<module>.py`
- Naming: `class Test<Component>: def test_action_scenario(self):`
- Mocking: `@patch("notmarket_common.module.dependency")`
- Health tests use live HTTP on port 0 (auto-assign)
