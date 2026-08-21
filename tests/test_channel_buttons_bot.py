"""Button-spec and allowed-id parsing for the channel buttons bot."""

import pytest

from channel_buttons_bot import parse_allowed_ids, parse_buttons


def test_parse_buttons_single_row():
    markup = parse_buttons("Join -> https://t.me/joinchat/xxx")
    assert len(markup.inline_keyboard) == 1
    assert len(markup.inline_keyboard[0]) == 1
    button = markup.inline_keyboard[0][0]
    assert button.text == "Join"
    assert button.url == "https://t.me/joinchat/xxx"


def test_parse_buttons_multiple_rows_and_columns():
    spec = (
        "Join -> https://t.me/joinchat/xxx\n"
        "Rate -> https://example.com/rate ; Share -> https://example.com/share"
    )
    markup = parse_buttons(spec)
    assert [len(row) for row in markup.inline_keyboard] == [1, 2]
    assert markup.inline_keyboard[1][0].text == "Rate"
    assert markup.inline_keyboard[1][1].text == "Share"


def test_parse_buttons_ignores_blank_lines():
    markup = parse_buttons("\n\nJoin -> https://t.me/joinchat/xxx\n\n")
    assert len(markup.inline_keyboard) == 1


@pytest.mark.parametrize("spec", ["", "   ", "no arrow here", "Label ->"])
def test_parse_buttons_rejects_malformed_spec(spec):
    with pytest.raises(ValueError):
        parse_buttons(spec)


def test_parse_allowed_ids():
    assert parse_allowed_ids("123, 456,789") == {123, 456, 789}


def test_parse_allowed_ids_rejects_empty():
    with pytest.raises(ValueError):
        parse_allowed_ids("")
