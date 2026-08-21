"""Button-spec and allowed-id parsing for the channel buttons bot."""

import json
from pathlib import Path

import pytest

from channel_buttons_bot import load_config, parse_allowed_ids, parse_buttons

ENV_VARS = ("BUTTON_BOT_TOKEN", "ALLOWED_USER_IDS", "CHANNEL_BUTTONS")

GOOD_ENV = {
    "BUTTON_BOT_TOKEN": "123456:ABCDEF",
    "ALLOWED_USER_IDS": "42",
    "CHANNEL_BUTTONS": "Join -> https://t.me/joinchat/xxx",
}


@pytest.fixture
def env(monkeypatch):
    """A clean, valid environment that each test can break one var of."""
    for name, value in GOOD_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


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


def test_parse_allowed_ids_rejects_non_numeric():
    with pytest.raises(ValueError, match="not a numeric user id"):
        parse_allowed_ids("123,@someguy")


def test_load_config_reads_the_environment(env):
    token, allowed, buttons = load_config()
    assert token == "123456:ABCDEF"
    assert allowed == {42}
    assert buttons.inline_keyboard[0][0].text == "Join"


@pytest.mark.parametrize("missing", ENV_VARS)
def test_load_config_names_the_missing_variable(env, missing):
    """A crash-looping Railway service should say which var is wrong."""
    env.delenv(missing)
    with pytest.raises(SystemExit, match=f"{missing} is not set"):
        load_config()


@pytest.mark.parametrize("blank", ENV_VARS)
def test_load_config_treats_blank_as_missing(env, blank):
    env.setenv(blank, "   ")
    with pytest.raises(SystemExit, match=f"{blank} is not set"):
        load_config()


def test_load_config_explains_a_bad_button_spec(env):
    env.setenv("CHANNEL_BUTTONS", "Join https://t.me/nope")
    with pytest.raises(SystemExit, match="CHANNEL_BUTTONS is invalid"):
        load_config()


def test_load_config_explains_a_bad_user_id(env):
    env.setenv("ALLOWED_USER_IDS", "@someguy")
    with pytest.raises(SystemExit, match="ALLOWED_USER_IDS is invalid"):
        load_config()


def test_railway_config_starts_the_right_bot():
    """The second Railway service must not boot the ranking bot by mistake."""
    config = json.loads(Path("railway.buttons.json").read_text())
    assert config["deploy"]["startCommand"] == "python channel_buttons_bot.py"
