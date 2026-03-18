"""Tests for notmarket_common.formatting module."""

from notmarket_common.formatting import (
    CATEGORY_ICONS,
    SEPARATOR,
    category_icon,
    event_url,
    fmt_bold,
    fmt_esc,
    fmt_italic,
    fmt_link,
    fmt_pct,
    fmt_usd,
    split_message,
)


# -- fmt_usd ---------------------------------------------------------------


class TestFmtUsd:
    def test_millions(self):
        assert fmt_usd(1_500_000) == "$1.5M"

    def test_thousands(self):
        assert fmt_usd(50_100) == "$50.1K"

    def test_small(self):
        assert fmt_usd(500) == "$500"

    def test_none_default(self):
        assert fmt_usd(None) is None

    def test_none_custom_default(self):
        assert fmt_usd(None, default="N/A") == "N/A"

    def test_boundary_million(self):
        assert fmt_usd(1_000_000) == "$1.0M"

    def test_boundary_thousand(self):
        assert fmt_usd(1_000) == "$1.0K"


# -- category_icon ----------------------------------------------------------


class TestCategoryIcon:
    def test_known_category(self):
        assert category_icon("Crypto") == "\U0001fa99"

    def test_unknown_category(self):
        assert category_icon("Unknown") == "\U0001f4cc"

    def test_none_category(self):
        assert category_icon(None) == "\U0001f4cc"

    def test_empty_category(self):
        assert category_icon("") == "\U0001f4cc"


# -- fmt_pct ----------------------------------------------------------------


class TestFmtPct:
    def test_half(self):
        assert fmt_pct(0.5) == "50%"

    def test_none(self):
        assert fmt_pct(None) == "\u2014"

    def test_one(self):
        assert fmt_pct(1.0) == "100%"


# -- fmt_bold / fmt_italic --------------------------------------------------


class TestFmtBold:
    def test_html(self):
        assert fmt_bold("hi", "html") == "<b>hi</b>"

    def test_markdown(self):
        assert fmt_bold("hi", "markdown") == "**hi**"


class TestFmtItalic:
    def test_html(self):
        assert fmt_italic("hi", "html") == "<i>hi</i>"

    def test_markdown(self):
        assert fmt_italic("hi", "markdown") == "*hi*"


# -- fmt_link ---------------------------------------------------------------


class TestFmtLink:
    def test_html(self):
        assert fmt_link("click", "https://x.com", "html") == "<a href='https://x.com'>click</a>"

    def test_markdown(self):
        assert fmt_link("click", "https://x.com", "markdown") == "[click](https://x.com)"

    def test_no_url(self):
        assert fmt_link("click", "", "html") == "click"


# -- fmt_esc ----------------------------------------------------------------


class TestFmtEsc:
    def test_html_escapes(self):
        assert fmt_esc("<b>hi</b>", "html") == "&lt;b&gt;hi&lt;/b&gt;"

    def test_markdown_noop(self):
        assert fmt_esc("<b>hi</b>", "markdown") == "<b>hi</b>"

    def test_empty(self):
        assert fmt_esc("", "html") == ""

    def test_none(self):
        assert fmt_esc(None, "html") == ""


# -- event_url --------------------------------------------------------------


class TestEventUrl:
    def test_normal(self):
        assert event_url("test-slug") == "https://polymarket.com/event/test-slug"

    def test_empty(self):
        assert event_url("") == ""


# -- split_message ----------------------------------------------------------


class TestSplitMessage:
    def test_short_message(self):
        assert split_message("hello", 100) == ["hello"]

    def test_splits_at_newlines(self):
        text = "line1\nline2\nline3"
        chunks = split_message(text, 12)
        assert len(chunks) == 2
        assert chunks[0] == "line1\nline2"
        assert chunks[1] == "line3"

    def test_single_long_line(self):
        text = "a" * 200
        chunks = split_message(text, 100)
        assert len(chunks) == 1
        assert chunks[0] == text


# -- constants --------------------------------------------------------------


class TestConstants:
    def test_separator_length(self):
        assert len(SEPARATOR) == 12

    def test_category_icons_has_all(self):
        expected = {
            "Crypto", "Politics", "Sports", "Social Media",
            "Tech & AI", "Economy & Finance", "Pop Culture",
            "Geopolitics", "Science & Weather",
        }
        assert set(CATEGORY_ICONS.keys()) == expected
