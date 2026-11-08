import os
from unittest.mock import patch

from cecli.helpers import browser


def test_is_browser_harness_command_matches_cli_forms():
    assert browser.is_browser_harness_command("browser-harness <<'PY'")
    assert browser.is_browser_harness_command("BU_CDP_URL=x browser-harness --doctor")
    assert browser.is_browser_harness_command("cd /tmp && browser_harness </dev/null")


def test_is_browser_harness_command_rejects_unrelated_commands():
    assert not browser.is_browser_harness_command("echo browser-harness")
    assert not browser.is_browser_harness_command("curl https://example.com/browser-harness")
    assert not browser.is_browser_harness_command("")


def test_get_browser_config_uses_defaults():
    with patch.dict(os.environ, {}, clear=True):
        config = browser.get_browser_config()
        # Resolve the expectation in the same (stripped) environment, since the
        # default profile directory depends on env-provided home directories.
        assert config["user_data_dir"] == browser.default_user_data_dir()

    assert config["cdp_url"] is None
    assert config["port"] == browser.DEFAULT_CDP_PORT
    assert config["launch"] is True
    assert config["headless"] is False


def test_parse_browser_config_accepts_json_and_yaml_strings():
    assert browser.parse_browser_config('{"port": 9333}') == {"port": 9333}
    assert browser.parse_browser_config("port: 9334\nlaunch: false") == {
        "port": 9334,
        "launch": False,
    }
    assert browser.parse_browser_config(None) == {}


def test_get_browser_config_reads_browser_settings():
    config = browser.get_browser_config(
        {
            "cdp_url": "http://127.0.0.1:9333",
            "port": "9333",
            "user_data_dir": "/tmp/cecli-profile",
            "launch_command": "chrome --remote-debugging-port={port}",
            "launch": "false",
            "headless": "true",
            "launch_timeout": "5",
            "harness_timeout": "12",
        }
    )

    assert config["cdp_url"] == "http://127.0.0.1:9333"
    assert config["port"] == 9333
    assert config["user_data_dir"] == "/tmp/cecli-profile"
    assert config["launch"] is False
    assert config["headless"] is True
    assert config["launch_timeout"] == 5.0
    assert config["harness_timeout"] == 12.0


def test_runtime_endpoint_overrides_defaults():
    browser.clear_active_cdp_url()
    try:
        browser.set_active_cdp_url("http://127.0.0.1:9334", 9334)
        with patch("cecli.helpers.browser.cdp_available", return_value=True):
            config = browser.get_browser_config()
            self_url = browser.ensure_cdp_url()

        assert config["cdp_url"] == "http://127.0.0.1:9334"
        assert config["port"] == 9334
        assert self_url == "http://127.0.0.1:9334"
    finally:
        browser.clear_active_cdp_url()


def test_ensure_cdp_url_prefers_explicit_config():
    assert browser.ensure_cdp_url({"cdp_url": "http://127.0.0.1:9444"}) == "http://127.0.0.1:9444"


def test_ensure_cdp_url_reuses_live_environment_endpoint():
    with (
        patch.dict(os.environ, {browser.CDP_URL_ENV: "http://127.0.0.1:9555"}, clear=True),
        patch("cecli.helpers.browser.cdp_available", return_value=True),
    ):
        assert browser.ensure_cdp_url() == "http://127.0.0.1:9555"


def test_ensure_cdp_url_detects_known_port():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("cecli.helpers.browser.cdp_available", side_effect=[False, True]),
    ):
        assert browser.ensure_cdp_url({"launch": False}) == "http://127.0.0.1:9223"


def test_build_launch_command_uses_detected_browser():
    config = browser.get_browser_config({"port": 9333, "user_data_dir": "/tmp/cecli-profile"})

    with patch("cecli.helpers.browser.find_browser_executable", return_value="/usr/bin/chromium"):
        command, use_shell = browser.build_launch_command(config, headless=True)

    assert use_shell is False
    assert command[0] == "/usr/bin/chromium"
    assert "--remote-debugging-port=9333" in command
    assert "--user-data-dir=/tmp/cecli-profile" in command
    assert "--headless=new" in command


def test_build_launch_command_formats_configured_command():
    config = browser.get_browser_config(
        {
            "port": 9333,
            "user_data_dir": "/tmp/cecli-profile",
            "launch_command": "chrome --port={port} --profile={profile_dir} {headless}",
        }
    )

    command, use_shell = browser.build_launch_command(config, headless=True)

    assert use_shell is True
    assert "--port=9333" in command
    assert "--profile=/tmp/cecli-profile" in command
    assert "--headless=new" in command


def test_browser_harness_env_exports_cdp_url():
    with patch("cecli.helpers.browser.ensure_cdp_url", return_value="http://127.0.0.1:9222"):
        env = browser.browser_harness_env({}, headless=True)

    assert env[browser.CDP_URL_ENV] == "http://127.0.0.1:9222"


def test_find_active_cdp_url_prefers_explicit_config():
    assert (
        browser.find_active_cdp_url({"cdp_url": "http://127.0.0.1:9444"}) == "http://127.0.0.1:9444"
    )


def test_find_active_cdp_url_detects_configured_port():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("cecli.helpers.browser.cdp_available", return_value=True),
    ):
        assert (
            browser.find_active_cdp_url({"port": 9333, "user_data_dir": "/tmp/cecli-none"})
            == "http://127.0.0.1:9333"
        )


def test_find_active_cdp_url_scans_default_ports_when_requested():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("cecli.helpers.browser._read_active_port", return_value=None),
        patch("cecli.helpers.browser.cdp_available", side_effect=[False, True]),
    ):
        url = browser.find_active_cdp_url(
            {"port": 9333, "user_data_dir": "/tmp/cecli-none"},
            include_default_ports=True,
        )

    assert url == "http://127.0.0.1:9222"


def test_find_active_cdp_url_returns_none_when_no_browser_runs():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("cecli.helpers.browser.cdp_available", return_value=False),
    ):
        assert browser.find_active_cdp_url({"user_data_dir": "/tmp/cecli-none"}) is None


def test_export_active_cdp_url_sets_environment():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "cecli.helpers.browser.find_active_cdp_url",
            return_value="http://127.0.0.1:9222",
        ),
    ):
        url = browser.export_active_cdp_url({})
        assert os.environ[browser.CDP_URL_ENV] == "http://127.0.0.1:9222"

    assert url == "http://127.0.0.1:9222"


def test_configure_browser_environment_skips_unrelated_commands():
    with (
        patch("cecli.helpers.browser.ensure_cdp_url") as ensure_cdp_url,
        patch("cecli.helpers.browser.find_active_cdp_url", return_value=None),
    ):
        browser.configure_browser_environment({}, command="echo hello")

    ensure_cdp_url.assert_not_called()


def test_configure_browser_environment_injects_active_endpoint():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "cecli.helpers.browser.find_active_cdp_url",
            return_value="http://127.0.0.1:9222",
        ),
    ):
        url = browser.configure_browser_environment({}, command="echo hello")
        assert os.environ[browser.CDP_URL_ENV] == "http://127.0.0.1:9222"

    assert url == "http://127.0.0.1:9222"


def test_browser_automation_context_mentions_heredoc(monkeypatch):
    from types import SimpleNamespace

    from cecli.coders.agent_coder import AgentCoder

    coder = SimpleNamespace(use_enhanced_context=True)
    monkeypatch.setattr(browser, "is_browser_harness_available", lambda: True)

    context = AgentCoder.get_browser_automation_context(coder)

    assert context.startswith('<context name="browser_automation"')
    assert "browser-harness <<'PY'" in context
    assert "BU_CDP_URL" in context


def test_browser_automation_context_requires_harness(monkeypatch):
    from types import SimpleNamespace

    from cecli.coders.agent_coder import AgentCoder

    coder = SimpleNamespace(use_enhanced_context=True)
    monkeypatch.setattr(browser, "is_browser_harness_available", lambda: False)

    assert AgentCoder.get_browser_automation_context(coder) is None


def test_configure_browser_environment_sets_env_for_harness():
    with patch("cecli.helpers.browser.ensure_cdp_url", return_value="http://127.0.0.1:9222"):
        url = browser.configure_browser_environment({}, command="browser-harness <<'PY'")

    assert url == "http://127.0.0.1:9222"
    assert os.environ[browser.CDP_URL_ENV] == "http://127.0.0.1:9222"
