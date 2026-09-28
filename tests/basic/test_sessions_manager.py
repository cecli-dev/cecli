"""SessionManager on-disk persistence and optional encryption."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.helpers import crypto as session_crypto
from cecli.helpers.sessions import SessionManager
from cecli.io import InputOutput


def _prepare_workspace(coder, tmp_path) -> Path:
    root = Path(tmp_path)
    coder.abs_root_path.side_effect = lambda x: str(root / x)
    (root / ".cecli" / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "file1.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def mock_coder(monkeypatch):
    main_model = MagicMock()
    main_model.name = "test_model"
    main_model.weak_model.name = "weak"
    main_model.editor_model.name = "editor"
    main_model.agent_model.name = "agent"
    main_model.editor_edit_format = "editor-diff"
    main_model.retries = 0
    main_model.debug = False

    conv_manager = MagicMock()
    conv_manager.get_messages_dict.return_value = []
    files_manager = MagicMock()
    monkeypatch.setattr(
        "cecli.helpers.sessions.payload.ConversationService.get_manager",
        lambda _coder: conv_manager,
    )
    monkeypatch.setattr(
        "cecli.helpers.sessions.payload.ConversationService.get_files",
        lambda _coder: files_manager,
    )
    monkeypatch.setattr(
        "cecli.helpers.sessions.payload.models.Model",
        lambda *args, **kwargs: main_model,
    )

    coder = MagicMock()
    coder.abs_fnames = set()
    coder.abs_read_only_fnames = set()
    coder.abs_read_only_stubs_fnames = set()
    coder.auto_commits = True
    coder.auto_lint = True
    coder.auto_test = False
    coder.total_tokens_sent = 0
    coder.total_tokens_received = 0
    coder.total_cached_tokens = 0
    coder.total_cost = 0.0
    coder.edit_format = "diff"
    coder.format_chat_chunks = MagicMock()
    coder.get_rel_fname.side_effect = lambda x: os.path.basename(x)
    coder.local_agent_folder.side_effect = lambda x: f".cecli/{x}"
    coder.io = MagicMock(spec=InputOutput)
    coder.agent_config = {}
    coder.mcp_manager = None
    coder.skills_manager = None
    coder.main_model = main_model
    coder.args = SimpleNamespace(
        model="test_model",
        weak_model="weak",
        editor_model="editor",
        agent_model="agent",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=False,
        session_key_file=None,
    )
    return coder


@pytest.fixture
def session_manager(mock_coder):
    return SessionManager(mock_coder, mock_coder.io)


@pytest.fixture
def encrypt_coder(mock_coder, session_key_env):
    mock_coder.args = SimpleNamespace(
        model="test_model",
        weak_model="weak",
        editor_model="editor",
        agent_model="agent",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=True,
        session_key_file=None,
    )
    return mock_coder


def test_save_plaintext_json(session_manager, mock_coder, tmp_path):
    root = _prepare_workspace(mock_coder, tmp_path)
    assert session_manager.save_session("plain", output=False)
    path = root / ".cecli" / "sessions" / "plain.json"
    raw = path.read_bytes()
    assert raw.startswith(b"{")
    data = json.loads(raw.decode("utf-8"))
    assert data["session_name"] == "plain"
    assert data["version"] == 1


def test_save_encrypted_blob(encrypt_coder, session_key32, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    root = _prepare_workspace(encrypt_coder, tmp_path)
    assert manager.save_session("secret", output=False)
    path = root / ".cecli" / "sessions" / "secret.json"
    raw = path.read_bytes()
    assert session_crypto.is_encrypted_payload(raw)
    assert session_crypto.decrypt_session_bytes(raw, session_key32)["session_name"] == "secret"


def test_save_encrypt_without_key_fails(mock_coder, monkeypatch, tmp_path):
    monkeypatch.delenv(session_crypto.KEY_ENV, raising=False)
    _prepare_workspace(mock_coder, tmp_path)
    mock_coder.args = SimpleNamespace(
        model="test_model",
        weak_model="weak",
        editor_model="editor",
        agent_model="agent",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=True,
        session_key_file=None,
    )
    assert SessionManager(mock_coder, mock_coder.io).save_session("nope", output=False) is False


def test_list_encrypted_with_key(encrypt_coder, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    _prepare_workspace(encrypt_coder, tmp_path)
    manager.save_session("listed", output=False)
    rows = manager.list_sessions()
    assert len(rows) == 1
    assert rows[0]["name"] == "listed"
    assert rows[0].get("encrypted") is True
    assert rows[0]["model"] == "test_model"


def test_list_encrypted_placeholder_without_key(encrypt_coder, monkeypatch, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    _prepare_workspace(encrypt_coder, tmp_path)
    manager.save_session("locked", output=False)
    monkeypatch.delenv(session_crypto.KEY_ENV, raising=False)
    encrypt_coder.args = SimpleNamespace(
        model="test_model",
        weak_model="weak",
        editor_model="editor",
        agent_model="agent",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=False,
        session_key_file=None,
    )
    rows = manager.list_sessions()
    assert rows[0]["encrypted"] is True
    assert rows[0]["model"] == "encrypted"


def test_read_legacy_plaintext_when_encrypt_enabled(encrypt_coder, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    root = _prepare_workspace(encrypt_coder, tmp_path)
    legacy = root / ".cecli" / "sessions" / "legacy.json"
    legacy.write_text(
        json.dumps({"version": 1, "session_name": "legacy", "model": "test_model"}),
        encoding="utf-8",
    )
    data = manager._read_session_file(legacy)
    assert data is not None
    assert data["session_name"] == "legacy"


@pytest.mark.asyncio
async def test_load_encrypted_without_switch(encrypt_coder, session_key32, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    root = _prepare_workspace(encrypt_coder, tmp_path)
    encrypt_coder.edit_format = "ask"
    assert manager.save_session("enc", output=False)
    encrypt_coder.edit_format = "diff"
    path = root / ".cecli" / "sessions" / "enc.json"
    assert await manager.load_session(str(path), switch=False) is True
    loaded = session_crypto.decrypt_session_bytes(path.read_bytes(), session_key32)
    assert loaded["edit_format"] == "ask"


@pytest.mark.asyncio
async def test_load_encrypted_using_env_key_only(encrypt_coder, session_key_env, tmp_path):
    manager = SessionManager(encrypt_coder, encrypt_coder.io)
    root = _prepare_workspace(encrypt_coder, tmp_path)
    encrypt_coder.edit_format = "architect"
    manager.save_session("env", output=False)
    encrypt_coder.args = SimpleNamespace(
        model="test_model",
        weak_model="weak",
        editor_model="editor",
        agent_model="agent",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=False,
        session_key_file=None,
    )
    path = root / ".cecli" / "sessions" / "env.json"
    assert await manager.load_session(str(path), switch=False) is True
    loaded = session_crypto.decrypt_session_bytes(path.read_bytes(), session_key_env)
    assert loaded["edit_format"] == "architect"


def test_save_agent_folder_writes_reference(session_manager, mock_coder, tmp_path):
    """Agent-folder saves keep the payload in the agent folder and a pointer in sessions/."""
    root = _prepare_workspace(mock_coder, tmp_path)
    assert session_manager.save_session("auto-save", output=False, to_agent_folder=True)

    reference_file = root / ".cecli" / "sessions" / "auto-save.json"
    reference = json.loads(reference_file.read_text(encoding="utf-8"))
    assert reference["type"] == SessionManager.SESSION_REFERENCE_TYPE
    assert reference["session_name"] == "auto-save"

    payload_file = root / reference["path"]
    assert payload_file != reference_file
    assert payload_file.exists()
    assert json.loads(payload_file.read_text(encoding="utf-8"))["session_name"] == "auto-save"


def test_list_resolves_agent_folder_reference(session_manager, mock_coder, tmp_path):
    _prepare_workspace(mock_coder, tmp_path)
    assert session_manager.save_session("auto-save", output=False, to_agent_folder=True)

    rows = session_manager.list_sessions()
    assert len(rows) == 1
    assert rows[0]["name"] == "auto-save"
    assert rows[0]["model"] == "test_model"


@pytest.mark.asyncio
async def test_load_agent_folder_reference(session_manager, mock_coder, tmp_path):
    root = _prepare_workspace(mock_coder, tmp_path)
    assert session_manager.save_session("auto-save", output=False, to_agent_folder=True)

    reference_file = root / ".cecli" / "sessions" / "auto-save.json"
    assert await session_manager.load_session(str(reference_file), switch=False) is True


def test_sub_agent_save_keeps_primary_reference(mock_coder, monkeypatch, tmp_path):
    """A sub-agent auto-save must not clobber the primary session reference."""
    root = _prepare_workspace(mock_coder, tmp_path)
    manager = SessionManager(mock_coder, mock_coder.io)
    assert manager.save_session("auto-save", output=False, to_agent_folder=True)

    reference_file = root / ".cecli" / "sessions" / "auto-save.json"
    original_reference = reference_file.read_text(encoding="utf-8")

    # Sub-agents write to their own agent folder; the reference stays put.
    sub_dir = root / ".cecli" / "agents" / "sub456"
    sub_dir.mkdir(parents=True, exist_ok=True)
    mock_coder.local_agent_folder.side_effect = lambda x: f".cecli/agents/sub456/{x}"
    monkeypatch.setattr(manager, "_sub_agent_name", lambda: "worker")

    assert manager.save_session("auto-save", output=False, to_agent_folder=True)

    assert reference_file.read_text(encoding="utf-8") == original_reference

    payload_file = sub_dir / "auto-save.json"
    assert payload_file.exists()
    data = json.loads(payload_file.read_text(encoding="utf-8"))
    assert data["agent_name"] == "worker"
    assert data["agent_root"] is None


def test_sub_agent_save_records_workspace_root(mock_coder, monkeypatch, tmp_path):
    """Workspace sub-agents persist their type and root for later restoration."""
    root = _prepare_workspace(mock_coder, tmp_path)
    sub_dir = root / ".cecli" / "agents" / "sub789"
    sub_dir.mkdir(parents=True, exist_ok=True)
    mock_coder.local_agent_folder.side_effect = lambda x: f".cecli/agents/sub789/{x}"
    mock_coder.root = "/workspace/app"

    manager = SessionManager(mock_coder, mock_coder.io)
    monkeypatch.setattr(manager, "_sub_agent_name", lambda: "ws:app")

    assert manager.save_session("auto-save", output=False, to_agent_folder=True)

    data = json.loads((sub_dir / "auto-save.json").read_text(encoding="utf-8"))
    assert data["agent_name"] == "ws:app"
    assert data["agent_root"] == "/workspace/app"
    assert not (root / ".cecli" / "sessions" / "auto-save.json").exists()


@pytest.mark.asyncio
async def test_load_primary_reference_reloads_sub_agents(mock_coder, monkeypatch, tmp_path):
    """Loading a primary session rebuilds the sub-agents saved beside it."""
    root = _prepare_workspace(mock_coder, tmp_path)
    manager = SessionManager(mock_coder, mock_coder.io)
    assert manager.save_session("auto-save", output=False, to_agent_folder=True)

    # Sub-agent payloads live in the "s/{uuid}/" directory next to the primary.
    sub_dir = root / ".cecli" / "s" / "sub123"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "auto-save.json").write_text(
        json.dumps({"version": 1, "session_name": "auto-save", "agent_name": "worker"}),
        encoding="utf-8",
    )

    fake_service = MagicMock()
    fake_service.spawn = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        classmethod(lambda cls, coder: fake_service),
    )
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_registry",
        classmethod(lambda cls: {"worker": object()}),
    )
    monkeypatch.setattr(SessionManager, "_apply_session_data", AsyncMock(return_value=(True, None)))

    reference_file = root / ".cecli" / "sessions" / "auto-save.json"
    assert await manager.load_session(str(reference_file), switch=False) is True

    fake_service.spawn.assert_awaited_once_with(
        "worker", parent=mock_coder, auto_reap=False, independent=True
    )


def test_resolve_reload_agent_name_registers_workspace_agent(mock_coder, tmp_path):
    """A stored ``ws:`` agent is re-registered from its persisted root."""
    from cecli.helpers.agents.service import AgentService
    from cecli.helpers.sessions import subagents
    from cecli.utils import make_repo

    project = tmp_path / "app"
    project.mkdir(parents=True, exist_ok=True)
    make_repo(project)

    registry = AgentService.get_registry()
    registry.pop("ws:app", None)

    try:
        name = subagents.resolve_reload_agent_name("ws:app", str(project))

        assert name == "ws:app"
        assert AgentService.get_registry()["ws:app"].metadata["root"] == str(project.resolve())
    finally:
        registry.pop("ws:app", None)


def _fake_sub_coder():
    coder = MagicMock()
    coder.args = SimpleNamespace(session_encrypt=False, session_key_file=None)

    return coder


def _fake_sub_services(monkeypatch, sub_agents):
    monkeypatch.setattr(
        "cecli.helpers.sessions.subagents.live_sub_agents", lambda coder: sub_agents
    )


def test_save_session_with_sub_agents_writes_bundle(mock_coder, monkeypatch, tmp_path):
    """An explicit save with sub-agents writes a folder bundle of payloads."""
    root = _prepare_workspace(mock_coder, tmp_path)
    manager = SessionManager(mock_coder, mock_coder.io)
    _fake_sub_services(monkeypatch, [("worker", _fake_sub_coder()), ("ws:app", _fake_sub_coder())])
    monkeypatch.setattr(
        "cecli.helpers.sessions.subagents.build_payload",
        lambda coder, io, name, agent_name=None: {
            "version": 1,
            "session_name": name,
            "agent_name": agent_name,
        },
    )

    assert manager.save_session("team", output=False)

    bundle = root / ".cecli" / "sessions" / "team"
    assert (bundle / "primary.json").is_file()
    assert (bundle / "s" / "worker" / "agent.json").is_file()
    assert (bundle / "s" / "ws_app" / "agent.json").is_file()
    assert not (root / ".cecli" / "sessions" / "team.json").exists()

    data = json.loads((bundle / "s" / "ws_app" / "agent.json").read_text(encoding="utf-8"))
    assert data["agent_name"] == "ws:app"


def test_save_session_without_sub_agents_writes_file(mock_coder, monkeypatch, tmp_path):
    """An explicit save without sub-agents keeps the single-file shape."""
    root = _prepare_workspace(mock_coder, tmp_path)
    manager = SessionManager(mock_coder, mock_coder.io)
    _fake_sub_services(monkeypatch, [])

    assert manager.save_session("solo", output=False)

    assert (root / ".cecli" / "sessions" / "solo.json").is_file()
    assert not (root / ".cecli" / "sessions" / "solo").exists()


@pytest.mark.asyncio
async def test_load_session_bundle_reloads_sub_agents(mock_coder, monkeypatch, tmp_path):
    """Loading a folder-bundle session rebuilds its sub-agents."""
    root = _prepare_workspace(mock_coder, tmp_path)
    bundle = root / ".cecli" / "sessions" / "team"
    sub_dir = bundle / "s" / "worker"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (bundle / "primary.json").write_text(
        json.dumps({"version": 1, "session_name": "team"}), encoding="utf-8"
    )
    (sub_dir / "agent.json").write_text(
        json.dumps({"version": 1, "session_name": "team", "agent_name": "worker"}),
        encoding="utf-8",
    )

    fake_service = MagicMock()
    fake_service.spawn = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        classmethod(lambda cls, coder: fake_service),
    )
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_registry",
        classmethod(lambda cls: {"worker": object()}),
    )
    monkeypatch.setattr(SessionManager, "_apply_session_data", AsyncMock(return_value=(True, None)))

    manager = SessionManager(mock_coder, mock_coder.io)
    assert await manager.load_session("team", switch=False) is True

    fake_service.spawn.assert_awaited_once_with(
        "worker", parent=mock_coder, auto_reap=False, independent=True
    )


@pytest.mark.asyncio
async def test_load_bundle_restores_only_relevant_sub_agents(mock_coder, monkeypatch, tmp_path):
    """Finished dependent and memorizer payloads are skipped; others are restored."""
    root = _prepare_workspace(mock_coder, tmp_path)
    bundle = root / ".cecli" / "sessions" / "team"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "primary.json").write_text(
        json.dumps({"version": 1, "session_name": "team"}), encoding="utf-8"
    )

    payloads = {
        "done": {"agent_name": "worker", "independent": False, "status": "finished"},
        "broke": {"agent_name": "worker", "independent": False, "status": "error"},
        "busy": {"agent_name": "reviewer", "independent": False, "status": "running"},
        "solo": {"agent_name": "tester", "independent": True, "status": "finished"},
        "memo": {"agent_name": "memorizer", "independent": True, "status": "finished"},
    }
    for child, extra in payloads.items():
        sub_dir = bundle / "s" / child
        sub_dir.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "session_name": "team"}
        data.update(extra)
        (sub_dir / "agent.json").write_text(json.dumps(data), encoding="utf-8")

    fake_service = MagicMock()
    fake_service.spawn = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        classmethod(lambda cls, coder: fake_service),
    )
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_registry",
        classmethod(lambda cls: {"worker": object(), "reviewer": object(), "tester": object()}),
    )
    monkeypatch.setattr(SessionManager, "_apply_session_data", AsyncMock(return_value=(True, None)))

    manager = SessionManager(mock_coder, mock_coder.io)
    assert await manager.load_session("team", switch=False) is True

    spawned = {
        call.args[0]: call.kwargs["independent"] for call in fake_service.spawn.await_args_list
    }
    assert spawned == {"reviewer": False, "tester": True}


def test_should_restore_sub_agent_rules():
    """Independent agents always restore; dependent ones only while in flight."""
    from cecli.helpers.sessions import subagents

    assert subagents.should_restore_sub_agent({"agent_name": "worker"}) is True
    assert (
        subagents.should_restore_sub_agent(
            {"agent_name": "worker", "independent": True, "status": "finished"}
        )
        is True
    )
    assert (
        subagents.should_restore_sub_agent(
            {"agent_name": "worker", "independent": False, "status": "running"}
        )
        is True
    )
    assert (
        subagents.should_restore_sub_agent(
            {"agent_name": "worker", "independent": False, "status": "finished"}
        )
        is False
    )
    assert (
        subagents.should_restore_sub_agent(
            {"agent_name": "worker", "independent": False, "status": "error"}
        )
        is False
    )
    assert (
        subagents.should_restore_sub_agent(
            {"agent_name": "memorizer", "independent": True, "status": "running"}
        )
        is False
    )
    assert subagents.should_restore_sub_agent({"agent_name": None}) is False


def test_sub_agent_state_reads_service(monkeypatch):
    """The stored lifecycle flags are read back from the AgentService."""
    from types import SimpleNamespace

    from cecli.helpers.agents.service import AgentService, SubAgentStatus
    from cecli.helpers.sessions import subagents

    info = SimpleNamespace(independent=False, status=SubAgentStatus.RUNNING)
    service = SimpleNamespace(sub_agents={"sub1": info})
    monkeypatch.setattr(AgentService, "get_instance", classmethod(lambda cls, coder: service))

    class _Coder:
        uuid = "sub1"

    assert subagents.sub_agent_state(_Coder()) == (False, "running")

    class _Unknown:
        uuid = "sub9"

    assert subagents.sub_agent_state(_Unknown()) == (False, None)


def test_build_payload_records_sub_agent_state(mock_coder, monkeypatch):
    """build_payload stores independence and status for sub-agents."""
    from types import SimpleNamespace

    from cecli.helpers.agents.service import AgentService, SubAgentStatus
    from cecli.helpers.sessions import payload as payload_module

    mock_coder.uuid = "sub1"
    info = SimpleNamespace(independent=True, status=SubAgentStatus.FINISHED)
    service = SimpleNamespace(sub_agents={"sub1": info})
    monkeypatch.setattr(AgentService, "get_instance", classmethod(lambda cls, coder: service))

    data = payload_module.build_payload(mock_coder, mock_coder.io, "n", agent_name="worker")
    assert data["independent"] is True
    assert data["status"] == "finished"

    primary = payload_module.build_payload(mock_coder, mock_coder.io, "n")
    assert primary["independent"] is None
    assert primary["status"] is None


def test_list_sessions_discovers_bundle(mock_coder, tmp_path):
    """Folder-bundle sessions show up in listings with a sub-agent count."""
    root = _prepare_workspace(mock_coder, tmp_path)
    bundle = root / ".cecli" / "sessions" / "team"
    (bundle / "s" / "worker").mkdir(parents=True, exist_ok=True)
    (bundle / "primary.json").write_text(
        json.dumps(
            {
                "version": 1,
                "session_name": "team",
                "model": "test_model",
                "edit_format": "diff",
                "chat_history": {"done_messages": [{}], "cur_messages": []},
                "files": {"editable": ["file1.py"]},
            }
        ),
        encoding="utf-8",
    )
    (bundle / "s" / "worker" / "agent.json").write_text(
        json.dumps({"version": 1, "agent_name": "worker"}), encoding="utf-8"
    )

    manager = SessionManager(mock_coder, mock_coder.io)
    rows = manager.list_sessions()

    assert len(rows) == 1
    assert rows[0]["name"] == "team"
    assert rows[0]["model"] == "test_model"
    assert rows[0]["num_sub_agents"] == 1
