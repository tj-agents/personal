import bot_identity as bot
import pytest


def test_setup_dispatch_preserves_explicit_identity_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected: list[tuple[str, str, list[str]]] = []
    setup: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        bot,
        "configure_existing_app",
        lambda app, reviewer, accounts: selected.append((app, reviewer, accounts)),
    )
    monkeypatch.setattr(
        bot, "setup", lambda check, onboard_key: setup.append((check, onboard_key))
    )

    assert (
        bot.main(
            [
                "setup",
                "--onboard",
                "--app",
                "fixture-bot",
                "--reviewer",
                "alex",
                "--account",
                "sample-org",
            ]
        )
        == 0
    )

    assert selected == [("fixture-bot", "alex", ["sample-org"])]
    assert setup == [(False, True)]


def test_token_dispatch_uses_configured_accounts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bot, "required_owners", lambda: ("sample-org",))
    monkeypatch.setattr(bot, "app_record", dict)
    monkeypatch.setattr(
        bot, "installation_token", lambda owner, record: "fixture-token"
    )

    assert bot.main(["token", "--owner", "sample-org"]) == 0
    assert capsys.readouterr().out == "fixture-token\n"

    assert bot.main(["token", "--owner", "unconfigured"]) == 2
    assert "not authorized for that account" in capsys.readouterr().err
