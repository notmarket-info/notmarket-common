"""Shared formatting helpers for notmarket Python services."""

CATEGORY_ICONS = {
    "Crypto": "\U0001fa99",
    "Politics": "\U0001f3db\ufe0f",
    "Sports": "\U0001f3c6",
    "Social Media": "\U0001f4f1",
    "Tech & AI": "\U0001f916",
    "Economy & Finance": "\U0001f4b9",
    "Pop Culture": "\U0001f3ac",
    "Geopolitics": "\U0001f30d",
    "Science & Weather": "\U0001f52c",
}

SEPARATOR = "\u2501" * 12  # ━━━━━━━━━━━━

TELEGRAM_MAX_LEN = 4096
DISCORD_MAX_LEN = 2000


def category_icon(category):
    """Return emoji icon for a super-category."""
    if not category:
        return "\U0001f4cc"
    return CATEGORY_ICONS.get(category, "\U0001f4cc")


def fmt_usd(value, default=None):
    """Format a USD value with K/M suffixes.

    Returns *default* when value is None (None for snapshot, "N/A" for indexer).
    """
    if value is None:
        return default
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def fmt_pct(price):
    """Format a price (0-1) as percentage string."""
    if price is None:
        return "\u2014"
    return f"{float(price) * 100:.0f}%"


def fmt_bold(text, fmt):
    """Format text as bold (HTML or Markdown)."""
    return f"<b>{text}</b>" if fmt == "html" else f"**{text}**"


def fmt_italic(text, fmt):
    """Format text as italic (HTML or Markdown)."""
    return f"<i>{text}</i>" if fmt == "html" else f"*{text}*"


def fmt_link(text, url, fmt):
    """Format a hyperlink (HTML or Markdown). Returns plain text if no URL."""
    if not url:
        return text
    if fmt == "html":
        return f"<a href='{url}'>{text}</a>"
    return f"[{text}]({url})"


def fmt_esc(text, fmt):
    """Escape text for safe embedding in HTML (noop for Markdown)."""
    if not text:
        return ""
    from html import escape as html_escape

    return html_escape(str(text)) if fmt == "html" else str(text)


def event_url(slug):
    """Build a Polymarket event URL from slug."""
    return f"https://polymarket.com/event/{slug}" if slug else ""


def split_message(text, max_len=TELEGRAM_MAX_LEN):
    """Split text into chunks at newline boundaries, each within max_len."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    current_lines = []
    current_len = 0
    for line in text.split("\n"):
        added_len = len(line) + (1 if current_lines else 0)
        if current_lines and current_len + added_len > max_len:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_len = len(line)
        else:
            current_lines.append(line)
            current_len += added_len
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks
