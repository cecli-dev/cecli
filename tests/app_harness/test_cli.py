"""Tests for the ``app-harness`` command surface and exit codes."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import cli  # noqa: E402
from tests.app_harness.conftest import DIALOG_WINDOW, PNG_BYTES  # noqa: E402


def test_wsl_hint_only_inside_wsl():
    hint = cli.runtime.wsl_hint("6.18.58.1-microsoft-standard-WSL2")

    assert "WSL detected" in hint
    assert "powershell.exe" in hint
    assert cli.runtime.wsl_hint("6.8.0-45-generic") == ""


def test_state_human_output(fake_bridge, capsys):
    code = cli.main(["state"])
    out = capsys.readouterr().out

    assert code == 0
    assert "platform: linux" in out
    assert "backend: fake" in out
    assert "capabilities: windows, snapshot, actions" in out


def test_windows_table(fake_bridge, capsys):
    code = cli.main(["windows"])
    out = capsys.readouterr().out

    assert code == 0
    assert "HANDLE" in out
    assert "Excel - Book1" in out
    assert "0x1234" in out


def test_snapshot_tree_and_truncation(fake_bridge, capsys):
    code = cli.main(["snapshot", "--window", "Excel", "--format", "lines"])
    out = capsys.readouterr().out

    assert code == 0
    assert '[2] Button "Save"' in out
    assert "sensitive" in out
    assert "truncated:" in out
    assert "99" in out


def test_snapshot_json_truncated_flag(fake_bridge, capsys):
    code = cli.main(["--json", "snapshot", "--window", "Excel"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["truncated"] is True
    assert payload["total_elements"] == 99
    assert payload["elements"][2]["name"] == "Save"


def test_snapshot_defaults_to_toon(fake_bridge, capsys):
    code = cli.main(["snapshot", "--window", "Excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert (
        "elements[4]{id,parent,depth,control_type,name,value,enabled,offscreen,"
        "sensitive,bounds,center,scroll}:" in out
    )
    assert any(line.startswith("elements[4]{") for line in out.splitlines())
    assert "Button,Save" in out
    assert "bounds{" not in out
    assert not out.lstrip().startswith("{")


def test_snapshot_verbose_keeps_every_field(fake_bridge, capsys):
    code = cli.main(["snapshot", "--window", "Excel", "--verbose"])
    out = capsys.readouterr().out

    assert code == 0
    assert "runtime_id" in out
    assert "bounds" in out
    assert "patterns" in out
    assert "path" in out


def test_snapshot_format_json_matches_the_json_flag(fake_bridge, capsys):
    code = cli.main(["snapshot", "--window", "Excel", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["elements"][2]["name"] == "Save"
    assert "bounds" in payload["elements"][2]


def test_click_sends_target(fake_bridge):
    code = cli.main(["click", "--window", "Excel", "--name", "Save"])

    assert code == 0
    assert fake_bridge.action_requests[0]["target"] == {"name": "Save"}


def test_click_by_point(fake_bridge):
    code = cli.main(["click", "--window", "Excel", "--x", "10", "--y", "20"])

    assert code == 0
    assert fake_bridge.action_requests[0]["args"]["point"] == {"x": 10, "y": 20}


def test_scroll_to_sends_percentages(fake_bridge):
    code = cli.main(
        ["scroll-to", "--window", "Excel", "--name", "Editor", "--vertical-percent", "50"]
    )

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == "scroll_to"
    assert request["args"]["vertical_percent"] == 50.0
    assert request["args"].get("horizontal_percent") is None


def test_scroll_to_requires_a_percentage(fake_bridge, capsys):
    code = cli.main(["scroll-to", "--window", "Excel", "--name", "Editor"])

    assert code == 2
    assert "vertical-percent" in capsys.readouterr().err


def test_scroll_to_rejects_out_of_range(fake_bridge, capsys):
    code = cli.main(["scroll-to", "--window", "Excel", "--vertical-percent", "150"])

    assert code == 2
    assert "between 0 and 100" in capsys.readouterr().err


def test_get_value_prints_value(fake_bridge, capsys):
    code = cli.main(["get-value", "--window", "Excel", "--automation-id", "A1"])
    out = capsys.readouterr().out

    assert code == 0
    assert "hello" in out


def test_uncertain_action_exits_three(fake_bridge, capsys):
    fake_bridge.action_mode = "uncertain"

    code = cli.main(["invoke", "--window", "Excel", "--name", "Save"])
    out = capsys.readouterr().out

    assert code == 3
    assert "uncertain" in out


def test_unverified_action_exits_three(fake_bridge):
    fake_bridge.action_mode = "unverified"

    code = cli.main(["invoke", "--window", "Excel", "--name", "Save"])

    assert code == 3


def test_backend_refusal_exits_two(fake_bridge, capsys):
    fake_bridge.action_mode = "refuse"

    code = cli.main(["invoke", "--window", "Excel", "--name", "Save"])
    err = capsys.readouterr().err

    assert code == 2
    assert "error: control is disabled" in err


def test_refused_before_send_exits_two(fake_bridge, capsys):
    code = cli.main(["invoke", "--window", "Excel"])
    err = capsys.readouterr().err

    assert code == 2
    assert "missing element selector" in err
    assert fake_bridge.requests == []


def test_missing_window_exits_two(fake_bridge):
    code = cli.main(["snapshot"])

    assert code == 2
    assert fake_bridge.requests == []


def test_missing_bridge_exits_four(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    code = cli.main(["state"])
    err = capsys.readouterr().err

    assert code == 4
    assert "error:" in err
    assert "ce-underscore" in err


def test_missing_bridge_json_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    code = cli.main(["--json", "state"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 4
    assert payload["ok"] is False
    assert payload["error"]["type"] == "bridge_unavailable"


def test_screenshot_writes_png(fake_bridge, tmp_path, capsys):
    out_path = tmp_path / "shot.png"

    code = cli.main(["screenshot", "--window", "Excel", "--out", str(out_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert out_path.read_bytes() == PNG_BYTES
    assert str(out_path) in out


def test_activate_subcommand(fake_bridge, capsys):
    code = cli.main(["activate", "--window", "Excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert fake_bridge.action_requests[0]["action"] == "activate"
    assert "activate" in out


def test_doctor_human_output(fake_bridge, capsys):
    code = cli.main(["doctor"])
    out = capsys.readouterr().out

    assert code == 0
    assert "accessibility: granted" in out
    assert "FAIL  screen_capture" in out


def test_json_state_output(fake_bridge, capsys):
    code = cli.main(["--json", "state"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["platform"] == "linux"
    assert payload["protocol_version"] == "0.1.0"


def test_unknown_subcommand_exits_two():
    with pytest.raises(SystemExit) as info:
        cli.main(["frobnicate"])

    assert info.value.code == 2


def test_script_mode_chains_calls_through_one_client(fake_bridge, monkeypatch, capsys):
    script = (
        'found = snapshot(window="Excel")\n'
        "print(found.summary)\n"
        'invoke(window="Excel", name="Save")\n'
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(script))
    created = []
    real_make_client = cli.runtime.make_client

    def counting_make_client(args):
        created.append(True)
        return real_make_client(args)

    monkeypatch.setattr(cli.runtime, "make_client", counting_make_client)

    code = cli.main([])
    out = capsys.readouterr().out

    assert code == 0
    assert len(created) == 1
    assert fake_bridge.paths() == ["/api/app/snapshot", "/api/app/action"]
    assert "Excel - Book1: 4/99 elements (truncated)" in out


def test_script_mode_smoke_from_stdin(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(len(windows()))\n"))

    code = cli.main([])
    out = capsys.readouterr().out

    assert code == 0
    assert out.strip() == "1"


def test_script_mode_uncertain_returns_three(fake_bridge, monkeypatch):
    fake_bridge.action_mode = "uncertain"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('invoke(window="Excel", name="Save")\n'),
    )

    assert cli.main([]) == 3


def test_version_mismatch_exits_four(fake_bridge, capsys):
    fake_bridge.write_bridge("9.9.9")

    code = cli.main(["state"])
    err = capsys.readouterr().err

    assert code == 4
    assert "version" in err
    assert "ce-underscore" in err


def test_ensure_bridge_without_binary_exits_four(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("CECLI_CE_UNDERSCORE", "/nonexistent/ce-underscore")

    code = cli.main(["--ensure-bridge", "state"])
    err = capsys.readouterr().err

    assert code == 4
    assert "ce-underscore" in err


def test_json_flag_after_subcommand(fake_bridge, capsys):
    code = cli.main(["state", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["backend"] == "fake"


def test_script_subcommand_runs_a_file(fake_bridge, tmp_path, capsys):
    script = tmp_path / "probe.py"
    script.write_text("print(len(windows()))\n", encoding="utf-8")

    code = cli.main(["script", str(script)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out.isdigit()


def test_script_exposes_activate(fake_bridge, tmp_path, capsys):
    script = tmp_path / "raise.py"
    script.write_text('print(activate("Excel").delivered)\n', encoding="utf-8")
    code = cli.main(["--window", "Excel", "script", str(script)])
    captured = capsys.readouterr()
    out = captured.out.strip()

    assert code == 0, captured.err
    assert out == "True"
    assert fake_bridge.action_requests[0]["action"] == "activate"


def test_bare_script_path_runs_script_mode(fake_bridge, tmp_path, capsys):
    script = tmp_path / "probe.py"
    script.write_text("print(len(windows()))\n", encoding="utf-8")

    code = cli.main(["--window", "Excel", str(script)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out.isdigit()


def test_bare_dash_reads_a_script_from_stdin(fake_bridge, monkeypatch, capsys):
    stdin = io.StringIO("print(len(windows()))\n")
    monkeypatch.setattr(stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(sys, "stdin", stdin)

    code = cli.main(["--window", "Excel", "-"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out.isdigit()


def test_script_without_input_prints_help(monkeypatch, capsys):
    stdin = io.StringIO("")
    monkeypatch.setattr(stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys, "stdin", stdin)

    code = cli.main([])
    err = capsys.readouterr().err

    assert code == 2
    assert "usage: app-harness" in err


def test_script_missing_file_is_refused(fake_bridge, tmp_path, capsys):
    code = cli.main(["script", str(tmp_path / "absent.py")])
    err = capsys.readouterr().err

    assert code == 2
    assert "cannot read" in err


def test_help_prints_capabilities(fake_bridge, capsys):
    code = cli.main(["help"])
    out = capsys.readouterr().out

    assert code == 0
    assert "backend: fake" in out
    assert "invoke" in out
    assert "snapshot" in out


def test_snapshot_sends_exclude_roles(fake_bridge, capsys):
    code = cli.main(["snapshot", "--window", "Excel", "--exclude-role", "Menu"])

    assert code == 0

    snapshots = [
        request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"
    ]

    assert snapshots[-1]["body"]["exclude_roles"] == ["Menu"]


def test_find_defaults_to_toon(fake_bridge, capsys):
    code = cli.main(["find", "--window", "Excel", "Edit"])
    out = capsys.readouterr().out

    assert code == 0
    assert "matches: 2" in out
    assert "elements[2]{id,control_type,name,value,path}:" in out
    assert "Address" in out
    assert "Password" in out


def test_find_json_includes_id_name_value_and_path(fake_bridge, capsys):
    code = cli.main(["--json", "find", "--window", "Excel", "Button"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["selector"] == "Button"
    assert payload["matches"] == 1
    assert payload["elements"] == [
        {
            "id": 2,
            "control_type": "Button",
            "name": "Save",
            "value": None,
            "path": None,
        }
    ]


def test_find_limit_truncates_output_but_not_the_count(fake_bridge, capsys):
    code = cli.main(["--json", "find", "--window", "Excel", "Edit", "--limit", "1"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["matches"] == 2
    assert [element["id"] for element in payload["elements"]] == [1]


def test_find_without_a_window_exits_two(fake_bridge):
    code = cli.main(["find", "Button"])

    assert code == 2
    assert fake_bridge.requests == []


def test_find_rejects_a_bad_selector_before_snapshot(fake_bridge, capsys):
    code = cli.main(["find", "--window", "Excel", "Button["])
    err = capsys.readouterr().err

    assert code == 2
    assert "invalid selector" in err
    assert fake_bridge.requests == []


def test_script_exposes_find_and_wait_for(fake_bridge, monkeypatch, capsys):
    script = 'print([element.id for element in find("Edit")])\n' 'print(wait_for("Button").id)\n'
    monkeypatch.setattr(sys, "stdin", io.StringIO(script))

    code = cli.main(["--window", "Excel"])
    out = capsys.readouterr().out.split()

    assert code == 0
    assert out == ["[1,", "3]", "2"]


def test_find_uses_the_server_route(fake_bridge, capsys):
    code = cli.main(["--json", "find", "--window", "Excel", "Button"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["truncated"] is False
    assert fake_bridge.paths() == ["/api/app/find"]
    assert fake_bridge.requests[-1]["body"]["match"] == {"roles": ["Button"]}


def test_cell_at_prints_the_resolved_cell(fake_bridge, capsys):
    code = cli.main(["cell-at", "--window", "Excel", "--row", "4", "--column", "2"])
    out = capsys.readouterr().out

    assert code == 0
    assert "id: 142" in out
    assert "name: B4" in out
    assert "value: B4" in out
    assert "path: Sheet1/Table/TableCell[B4]" in out
    assert fake_bridge.action_requests[-1]["action"] == "cell_at"
    assert fake_bridge.action_requests[-1]["args"]["row"] == 4
    assert fake_bridge.action_requests[-1]["args"]["column"] == 2


def test_cell_at_json_payload(fake_bridge, capsys):
    code = cli.main(["--json", "cell-at", "--window", "Excel", "--row", "4", "--column", "2"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["row"] == 4
    assert payload["column"] == 2
    assert payload["id"] == 142
    assert payload["name"] == "B4"
    assert payload["value"] == "B4"
    assert payload["path"] == "Sheet1/Table/TableCell[B4]"


def test_cell_at_without_a_window_exits_two(fake_bridge):
    code = cli.main(["cell-at", "--row", "4", "--column", "2"])

    assert code == 2
    assert fake_bridge.requests == []


def test_script_exposes_cell_at(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('print(cell_at(row=4, column=2).element["name"])\n'),
    )

    code = cli.main(["--window", "Excel"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == "B4"


def test_script_wait_for_times_out(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('wait_for("Nope", timeout_ms=1)\n'))

    code = cli.main(["--window", "Excel"])
    err = capsys.readouterr().err

    assert code == 2
    assert "no element matches" in err


def test_snapshot_sends_actionable_when_asked(fake_bridge):
    code = cli.main(["snapshot", "--window", "Excel", "--actionable"])

    assert code == 0

    snapshots = [
        request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"
    ]

    assert snapshots[-1]["body"]["actionable"] is True


def test_snapshot_omits_actionable_by_default(fake_bridge):
    code = cli.main(["snapshot", "--window", "Excel"])

    assert code == 0

    snapshots = [
        request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"
    ]

    assert "actionable" not in snapshots[-1]["body"]


def test_find_miss_renders_candidates(fake_bridge, capsys):
    fake_bridge.find_miss_error = True

    code = cli.main(["find", "--window", "Excel", "Button[name='Nope']"])
    err = capsys.readouterr().err

    assert code == 2
    assert "no element matches" in err
    assert '(near: Button "Save" (id2), Button "Save As")' in err


@pytest.mark.parametrize(
    ("argv", "action"),
    [
        (["click", "--window", "Excel", "--selector", "Button"], "click"),
        (["invoke", "--window", "Excel", "--selector", "Button"], "invoke"),
        (
            ["set-value", "--window", "Excel", "--selector", "Button", "--value", "pressed"],
            "set_value",
        ),
        (["get-value", "--window", "Excel", "--selector", "Button"], "get_value"),
        (["focus", "--window", "Excel", "--selector", "Button"], "focus"),
    ],
)
def test_selector_resolves_the_target_before_acting(fake_bridge, argv, action):
    code = cli.main(argv)

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == action
    assert request["target"] == {"id": 2, "runtime_id": "42.3"}
    assert "/api/app/find" in fake_bridge.paths()


def test_selector_sends_the_set_value_argument(fake_bridge):
    code = cli.main(
        ["set-value", "--window", "Excel", "--selector", "Button", "--value", "pressed"]
    )

    assert code == 0
    assert fake_bridge.action_requests[-1]["args"]["value"] == "pressed"


def test_keys_with_selector_targets_the_resolved_element(fake_bridge):
    code = cli.main(["keys", "--window", "Excel", "--selector", "Button", "--keys", "^s"])

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == "keys"
    assert request["target"] == {"id": 2, "runtime_id": "42.3"}
    assert request["args"]["keys"] == "^s"


def test_selector_conflicts_with_target_flags(fake_bridge, capsys):
    code = cli.main(["click", "--window", "Excel", "--selector", "Button", "--name", "Save"])
    err = capsys.readouterr().err

    assert code == 2
    assert "--selector" in err
    assert fake_bridge.requests == []


def test_json_error_carries_details(fake_bridge, capsys):
    fake_bridge.find_miss_error = True

    code = cli.main(["--json", "find", "--window", "Excel", "Button[name='Nope']"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 2
    assert payload["error"]["type"] == "target_not_found"
    assert payload["error"]["details"] == {
        "candidates": ['Button "Save" (id2)', 'Button "Save As"'],
        "scope": "window",
    }
    assert "(near: " in captured.err


def test_snapshot_json_surfaces_bridge_notes(fake_bridge, capsys):
    fake_bridge.snapshot_notes = ["snapshot cut by max_elements (kept 4)"]

    code = cli.main(["--json", "snapshot", "--window", "Excel"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["notes"] == ["snapshot cut by max_elements (kept 4)"]


def test_snapshot_omits_notes_when_the_bridge_sent_none(fake_bridge, capsys):
    code = cli.main(["--json", "snapshot", "--window", "Excel"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "notes" not in payload


def test_action_output_names_the_delivery_outcome(fake_bridge, capsys):
    fake_bridge.action_outcome = "pointer"

    code = cli.main(["invoke", "--window", "Excel", "--name", "Save"])
    out = capsys.readouterr().out

    assert code == 0
    assert "[outcome: pointer]" in out


def test_path_flag_is_sent_as_a_selector(fake_bridge):
    code = cli.main(["invoke", "--window", "Excel", "--path", "Window/Button[Save]"])

    assert code == 0
    assert fake_bridge.action_requests[0]["target"] == {"path": "Window/Button[Save]"}


def test_emit_prints_one_json_document(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('emit({"value": 1, "name": "B2"})\n'))

    code = cli.main(["--window", "Excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert json.loads(out) == {"value": 1, "name": "B2"}


def test_multiple_emits_become_one_json_list(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("emit(1)\nemit(2)\n"))

    code = cli.main(["--window", "Excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert json.loads(out) == [1, 2]


def test_emit_nothing_prints_nothing(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("print('hello')\n"))

    code = cli.main(["--window", "Excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.strip() == "hello"


def test_expect_failure_stops_the_script_with_exit_one(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('expect(False, "B2 did not change")\nprint("unreachable")\n')
    )

    code = cli.main(["--window", "Excel"])
    captured = capsys.readouterr()

    assert code == 1
    assert "B2 did not change" in captured.err
    assert "unreachable" not in captured.out


def test_expect_failure_still_prints_earlier_emissions(fake_bridge, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('emit({"seen": True})\nexpect(False, "stop")\n'))

    code = cli.main(["--window", "Excel"])
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out) == {"seen": True}


def _snapshot_requests(fake_bridge) -> int:
    return len(
        [request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"]
    )


def test_repeated_snapshot_hits_the_bridge_once(fake_bridge, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("snapshot()\nsnapshot()\n"))

    code = cli.main(["--window", "Excel"])

    assert code == 0
    assert _snapshot_requests(fake_bridge) == 1


def test_an_action_clears_the_snapshot_cache(fake_bridge, monkeypatch):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('snapshot()\ninvoke(name="Save")\nsnapshot()\n'),
    )

    code = cli.main(["--window", "Excel"])

    assert code == 0
    assert _snapshot_requests(fake_bridge) == 2


def test_refresh_forces_a_new_snapshot(fake_bridge, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("snapshot()\nrefresh()\nsnapshot()\n"))

    code = cli.main(["--window", "Excel"])

    assert code == 0
    assert _snapshot_requests(fake_bridge) == 2


def test_find_reuses_the_cached_snapshot(fake_bridge, monkeypatch):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('snapshot()\nfind("Button")\nfind("Edit")\n'),
    )

    code = cli.main(["--window", "Excel"])

    assert code == 0
    assert _snapshot_requests(fake_bridge) == 1


def test_help_hides_the_one_shot_verbs_but_keeps_the_probes(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    out = capsys.readouterr().out

    assert "snapshot" in out
    assert "find" in out
    assert "state" in out
    assert "{script,state,windows,doctor,help,recipes,snapshot,find,cell-at,screenshot}" in out
    assert "Click an element or an explicit screen point." not in out
    assert "Write a value to an element." not in out


def test_hidden_verbs_still_render_their_own_help(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["invoke", "--help"])

    out = capsys.readouterr().out

    assert info.value.code == 0
    assert "--selector" in out
    assert "--name" in out


def test_script_cell_at_accepts_a_grid_selector(fake_bridge, monkeypatch):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO("cell_at(4, 2, grid=\"Button[name='Save']\")\n"),
    )

    code = cli.main(["--window", "Excel"])

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == "cell_at"
    assert request["target"] == {"id": 2, "runtime_id": "42.3"}


def test_cell_at_verb_accepts_a_grid_selector(fake_bridge):
    code = cli.main(
        [
            "cell-at",
            "--window",
            "Excel",
            "--row",
            "4",
            "--column",
            "2",
            "--grid",
            "Button[name='Save']",
        ]
    )

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["target"] == {"id": 2, "runtime_id": "42.3"}


def test_click_selector_at_center_uses_a_pointer_click(fake_bridge):
    code = cli.main(
        ["click", "--window", "Excel", "--selector", "Button[name='Save']", "--at", "center"]
    )

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == "click"
    assert request["target"] is None
    assert request["args"]["point"] == {"x": 340, "y": 32}
    assert request["args"]["button"] == "left"
    assert request["args"]["count"] == 1


def test_click_target_at_center_uses_the_element_bounds(fake_bridge):
    code = cli.main(["click", "--window", "Excel", "--name", "Save", "--at", "center"])

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["target"] == {"name": "Save"}
    assert request["args"]["point"] == {"x": 340, "y": 32}


def test_double_click_selector_uses_a_pointer_action(fake_bridge):
    code = cli.main(["double-click", "--window", "Excel", "--selector", "Button"])

    assert code == 0
    request = fake_bridge.action_requests[-1]
    assert request["action"] == "double_click"
    assert request["args"]["point"] == {"x": 340, "y": 32}


def test_type_text_selector_falls_back_to_keys(fake_bridge):
    fake_bridge.set_value_mode = "unsupported"

    code = cli.main(
        [
            "type-text",
            "--window",
            "Excel",
            "--selector",
            "Button",
            "--text",
            "hello",
            "--commit",
        ]
    )

    assert code == 0
    actions = [request["action"] for request in fake_bridge.action_requests]
    assert actions[0] == "set_value"
    assert "focus" in actions
    assert any(request["args"].get("keys") == "hello" for request in fake_bridge.action_requests)
    assert fake_bridge.action_requests[-2]["args"]["keys"] == "{ENTER}"


def test_dialogs_verb_lists_dialog_windows(fake_bridge, capsys):
    fake_bridge.dialogs = [DIALOG_WINDOW]

    code = cli.main(["--json", "dialogs"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["dialogs"][0]["title"] == "Microsoft Excel"
    assert payload["dialogs"][0]["dialog"] is True


def test_help_list_apps_works_without_a_bridge(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    code = cli.main(["help", "--list-apps"])
    out = capsys.readouterr().out

    assert code == 0
    assert "excel" in out
    assert "libreoffice" in out


def test_help_app_works_without_a_bridge(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    code = cli.main(["help", "--app", "excel"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Microsoft Excel" in out
    assert "Selectors:" in out


def test_help_unknown_app_prints_the_list_and_exits_two(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    code = cli.main(["help", "--app", "frobnicate"])
    captured = capsys.readouterr()

    assert code == 2
    assert "unknown app" in captured.err
    assert "excel" in captured.out


def test_host_windows_forwards_to_interop(monkeypatch):
    calls: list[list[str]] = []

    def fake_forward(argv):
        calls.append(list(argv))
        return 7

    monkeypatch.setattr(cli.interop, "maybe_forward", fake_forward)

    code = cli.main(["--host", "windows", "state"])

    assert code == 7
    assert calls == [["--host", "windows", "state"]]


def test_interop_flag_forwards(monkeypatch):
    monkeypatch.setattr(cli.interop, "maybe_forward", lambda argv: 9)

    assert cli.main(["--interop", "windows"]) == 9


def test_hidden_type_text_verb_help_lists_text_flag(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["type-text", "--help"])

    out = capsys.readouterr().out

    assert info.value.code == 0
    assert "--text" in out
    assert "--replace" in out


def test_script_exposes_the_extended_helpers(fake_bridge, monkeypatch):
    names = (
        "double_click",
        "right_click",
        "hover",
        "drag",
        "select",
        "scroll_into_view",
        "scroll_to",
        "type_text",
        "edit_text",
        "dialogs",
        "accept_dialog",
        "cancel_dialog",
        "dismiss_dialogs",
        "spreadsheet",
        "paste_tsv",
        "set_clipboard",
        "get_clipboard",
    )
    script = f"print(all(name in globals() for name in {names!r}))\n"

    monkeypatch.setattr(sys, "stdin", io.StringIO(script))
    code = cli.main(["--window", "Excel"])

    assert code == 0
