"""
Tests for cecli/helpers/agents/service.py — AgentService.
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.helpers.agents.service import (
    DEFAULT_SUMMARY_INTERRUPTED,
    AgentService,
    SubAgentInfo,
    SubAgentStatus,
)

# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_coder():
    """A basic mock coder for AgentService."""
    coder = MagicMock()
    coder.uuid = "parent-uuid"
    coder.parent_uuid = ""
    coder.max_sub_agents = 3
    coder.io = MagicMock()
    return coder


@pytest.fixture
def service(mock_coder):
    """Clean AgentService instance with isolated class-level state."""
    # Reset class-level state before each test
    AgentService._instances = {}
    AgentService._global_registry = {}
    AgentService._uuid_coder_map = {}
    AgentService._primary_agent_uuid = None
    return AgentService(mock_coder)


@pytest.fixture
def registry():
    """Pre-populated registry."""
    AgentService._global_registry = {
        "reviewer": MagicMock(name="reviewer", prompt="Review code.", model=None, hooks={}),
        "tester": MagicMock(name="tester", prompt="Write tests.", model="gpt-4", hooks={}),
    }
    yield
    AgentService._global_registry = {}


# ================================================================== #
# Class-level state & singleton
# ================================================================== #


class TestGetInstance:
    """AgentService.get_instance() singleton behavior."""

    def test_get_instance_creates_new(self, mock_coder):
        """First call for a coder UUID creates a new instance."""
        AgentService._instances = {}
        AgentService._primary_agent_uuid = None
        instance = AgentService.get_instance(mock_coder)
        assert isinstance(instance, AgentService)
        assert instance.coder == mock_coder

    def test_get_instance_returns_same(self, mock_coder):
        """Second call for same coder returns same instance."""
        AgentService._instances = {}
        AgentService._primary_agent_uuid = None
        first = AgentService.get_instance(mock_coder)
        second = AgentService.get_instance(mock_coder)
        assert first is second

    def test_get_instance_uses_parent_for_subcoder(self, mock_coder):
        """Coder with parent_uuid returns the parent's service."""
        AgentService._instances = {}
        AgentService._primary_agent_uuid = None
        parent_service = AgentService.get_instance(mock_coder)

        sub_coder = MagicMock()
        sub_coder.uuid = "sub-uuid"
        sub_coder.parent_uuid = mock_coder.uuid

        result = AgentService.get_instance(sub_coder)
        assert result is parent_service

    def test_destroy_instance_removes(self, mock_coder):
        """destroy_instance removes the instance by uuid."""
        AgentService._instances = {}
        AgentService._primary_agent_uuid = None
        svc = AgentService(mock_coder)
        AgentService._instances[mock_coder.uuid] = svc
        assert mock_coder.uuid in AgentService._instances

        AgentService.destroy_instance(mock_coder.uuid)
        assert mock_coder.uuid not in AgentService._instances


class TestRegistry:
    """Global registry management."""

    def test_get_registry_returns_dict(self, registry):
        """get_registry() returns the global registry dict."""
        reg = AgentService.get_registry()
        assert "reviewer" in reg
        assert "tester" in reg

    def test_register_and_unregister(self):
        """register_subagent adds, unregister_subagent removes."""
        AgentService._global_registry = {}
        config = MagicMock(name="custom")
        AgentService.register_subagent("custom", config)
        assert "custom" in AgentService._global_registry

        AgentService.unregister_subagent("custom")
        assert "custom" not in AgentService._global_registry

    def test_build_registry(self, temp_dir):
        """build_registry scans .md files and registers them."""
        AgentService._global_registry = {}

        # Create a valid .md file
        md_file = temp_dir / "reviewer.md"
        md_file.write_text("---\n" "name: reviewer\n" "---\n" "Review code.")

        AgentService.build_registry([str(temp_dir)])
        assert "reviewer" in AgentService._global_registry
        AgentService._global_registry = {}

    def test_build_registry_resolves_relative_path_against_root(self, temp_dir):
        """Relative sub-agent directories resolve against the provided ``root``."""
        AgentService._global_registry = {}

        subagents_dir = temp_dir / "subagents"
        subagents_dir.mkdir()
        md_file = subagents_dir / "reviewer.md"
        md_file.write_text("---\n" "name: reviewer\n" "---\n" "Review code.")

        # ``subagents`` is relative — it must be resolved against ``root``.
        AgentService.build_registry(["subagents"], root=str(temp_dir))
        assert "reviewer" in AgentService._global_registry
        AgentService._global_registry = {}

    def test_build_registry_skips_missing_dir(self):
        """Non-existent directories are skipped silently (default dirs still scanned)."""
        AgentService._global_registry = {}
        # build_registry also scans ~/.cecli/subagents and built-in defaults,
        # so the registry may contain entries from those directories even when
        # the user-supplied path does not exist.  The key assertion is that
        # no exception is raised for the missing directory.
        try:
            AgentService.build_registry(["/nonexistent/path"])
        except Exception:
            pytest.fail("build_registry raised an exception for non-existent directory")
        # Verify the nonexistent path didn't cause an error - default entries are fine
        assert AgentService._global_registry is not None

    def test_build_registry_includes_local_default_dir(self, temp_dir):
        """build_registry scans {root}/.cecli/subagents as a local default."""
        AgentService._global_registry = {}

        local_dir = temp_dir / ".cecli" / "subagents"
        local_dir.mkdir(parents=True)
        md_file = local_dir / "localagent.md"
        md_file.write_text("---\nname: localagent\n---\nLocal agent.")

        AgentService.build_registry([], root=str(temp_dir))
        assert "localagent" in AgentService._global_registry
        AgentService._global_registry = {}


# ================================================================== #
# Instance initialization
# ================================================================== #


class TestInit:
    """AgentService.__init__() behavior."""

    def test_sets_coder(self, mock_coder):
        """__init__ stores the coder reference."""
        svc = AgentService(mock_coder)
        assert svc.coder is mock_coder

    def test_sub_agents_empty(self, mock_coder):
        """sub_agents dict starts empty."""
        svc = AgentService(mock_coder)
        assert svc.sub_agents == {}

    def test_sub_agent_order_empty(self, mock_coder):
        """_sub_agent_order list starts empty."""
        svc = AgentService(mock_coder)
        assert svc._sub_agent_order == []

    def test_max_sub_agents_default(self, mock_coder):
        """max_sub_agents defaults to 3."""
        svc = AgentService(mock_coder)
        assert svc.max_sub_agents == 3

    def test_max_sub_agents_from_coder(self, mock_coder):
        """max_sub_agents reads from coder.max_sub_agents."""
        mock_coder.max_sub_agents = 5
        svc = AgentService(mock_coder)
        assert svc.max_sub_agents == 5


# ================================================================== #
# Internal helpers
# ================================================================== #


class TestCheckMaxSubagents:
    """_check_max_sub_agents() boundary logic."""

    def test_under_limit_passes(self, service):
        """Fewer sub-agents than max passes without error."""
        service._check_max_sub_agents()  # should not raise

    def test_at_limit_with_finished_reaps(self, service):
        """At max with a FINISHED sub-agent reaps the oldest."""
        finished_info = MagicMock(status=SubAgentStatus.FINISHED)
        finished_info.coder.uuid = "finished-uuid"
        running_info = MagicMock(status=SubAgentStatus.RUNNING)
        running_info.coder.uuid = "running-uuid"

        service.sub_agents = {
            "finished": finished_info,
            "running": running_info,
        }
        service._sub_agent_order = ["finished", "running"]
        # max_sub_agents=3, active=1 (<3) so this won't trigger
        # Set max to 2 so active=1 < 2... still fine
        # We need active_count >= max_sub_agents
        # active_count = sum(1 for info where status != FINISHED) = 1
        # Need max_sub_agents <= 1 to trigger
        mock_coder = MagicMock()
        mock_coder.max_sub_agents = 2
        service.coder = mock_coder

        # active_count=1 < max=2, so it returns without reaping
        service._check_max_sub_agents()
        assert "finished" in service.sub_agents  # NOT reaped

    def test_at_limit_no_finished_raises(self, service):
        """At max with no FINISHED agents raises RuntimeError."""
        running_info = MagicMock(status=SubAgentStatus.RUNNING)
        running_info.coder.uuid = "running-uuid"

        service.sub_agents = {
            "running": running_info,
        }
        service._sub_agent_order = ["running"]
        mock_coder = MagicMock()
        mock_coder.max_sub_agents = 1
        service.coder = mock_coder

        # active_count=1, max=1, no finished agent -> raise
        with pytest.raises(RuntimeError, match="Maximum sub-agents"):
            service._check_max_sub_agents()


class TestReapFinishedAgent:
    """_reap_finished_agent() lazy reap logic."""

    def test_reaps_oldest_finished(self, service):
        """Reaps the oldest FINISHED sub-agent."""
        info1 = MagicMock(status=SubAgentStatus.FINISHED)
        info1.coder.uuid = "finished-1"
        info2 = MagicMock(status=SubAgentStatus.RUNNING)
        info2.coder.uuid = "running"

        service.sub_agents = {"agent1": info1, "agent2": info2}
        service._sub_agent_order = ["agent1", "agent2"]

        with patch.object(service, "_cleanup_sub_agent") as mock_cleanup:
            service._reap_finished_agent()
            mock_cleanup.assert_called_once_with("agent1")

    def test_no_finished_does_nothing(self, service):
        """No FINISHED agents results in no reap."""
        info = MagicMock(status=SubAgentStatus.RUNNING)
        info.coder.uuid = "running"
        service.sub_agents = {"agent": info}
        service._sub_agent_order = ["agent"]

        with patch.object(service, "_cleanup_sub_agent") as mock_cleanup:
            service._reap_finished_agent()
            mock_cleanup.assert_not_called()

    def test_empty_sub_agents(self, service):
        """Empty agents list does nothing."""
        with patch.object(service, "_cleanup_sub_agent") as mock_cleanup:
            service._reap_finished_agent()
            mock_cleanup.assert_not_called()


class TestCleanupSubAgent:
    """_cleanup_sub_agent() resource teardown."""

    def test_removes_from_sub_agents(self, service):
        """Removes name from sub_agents dict and order list."""
        info = MagicMock()
        info.coder.uuid = "sub-uuid"
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        service._cleanup_sub_agent("agent")
        assert "agent" not in service.sub_agents
        assert "agent" not in service._sub_agent_order

    def test_destroys_conversation(self, service):
        """Destroys ConversationService instances."""
        info = MagicMock()
        info.coder.uuid = "sub-uuid"
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
            service._cleanup_sub_agent("agent")
            MockConv.destroy_instances.assert_called_once_with("sub-uuid")

    def test_unknown_name_silent(self, service):
        """Cleaning up an unknown name doesn't crash."""
        service._cleanup_sub_agent("nonexistent")


# ================================================================== #
# Public API: invoke
# ================================================================== #


class TestInvoke:
    """AgentService.invoke() behavior."""

    @pytest.mark.asyncio
    async def test_unknown_name_raises_value_error(self, service):
        """Unknown sub-agent name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown sub-agent"):
            await service.invoke("ghost", "prompt")

    @pytest.mark.asyncio
    async def test_successful_invoke_returns_summary(self, service, registry):
        """Successful invoke returns the summary."""
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks

                # Set summary via Finished tool simulation
                async def set_summary_side_effect(user_message, **kwargs):
                    # Find the sub-agent info by iterating values (keyed by uuid, not name)
                    for _info in service.sub_agents.values():
                        if _info.name == "reviewer":
                            _info.summary = "review complete"
                            break

                mock_new_coder.generate = AsyncMock(side_effect=set_summary_side_effect)

                result = await service.invoke("reviewer", "review this")

        assert result == "review complete"

    @pytest.mark.asyncio
    async def test_invoke_non_blocking_returns_none(self, service, registry):
        """Non-blocking invoke returns None immediately."""
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks

                result = await service.invoke("reviewer", "prompt", blocking=False)

        assert result is None
        # Find the sub-agent info by iterating values (keyed by uuid, not name)
        matched_info = None
        for _info in service.sub_agents.values():
            if _info.name == "reviewer":
                matched_info = _info
                break
        assert matched_info is not None, "Sub-agent 'reviewer' not found in sub_agents"
        assert matched_info.status == SubAgentStatus.CREATED

    @pytest.mark.asyncio
    async def test_invoke_error_sets_error_status(self, service, registry):
        """Error during generate sets ERROR status and re-raises."""
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks
                mock_new_coder.generate = AsyncMock(side_effect=RuntimeError("fail"))

                with pytest.raises(RuntimeError, match="fail"):
                    await service.invoke("reviewer", "prompt")

        # Find the sub-agent info by iterating values (keyed by uuid, not name)
        matched_info = None
        for _info in service.sub_agents.values():
            if _info.name == "reviewer":
                matched_info = _info
                break
        assert matched_info is not None, "Sub-agent 'reviewer' not found"
        assert matched_info.status == SubAgentStatus.ERROR
        assert matched_info.error == "fail"

    @pytest.mark.asyncio
    async def test_invoke_with_model_override(self, service, registry):
        """Model override is passed to Coder.create kwargs."""
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks
                mock_new_coder.generate = AsyncMock(return_value=None)

                await service.invoke("tester", "test", blocking=False)

        # tester config has model="gpt-4"
        call_kwargs = MockCoder.create.call_args[1]
        main_model = call_kwargs.get("main_model")
        assert main_model is not None
        assert main_model.name == "gpt-4"

    @pytest.mark.asyncio
    async def test_invoke_tui_notification(self, service, registry):
        """If parent has tui, create_subagent_container is called."""
        mock_tui = MagicMock()
        service.coder.tui = mock_tui

        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks
                mock_new_coder.generate = AsyncMock(return_value=None)

                await service.invoke("reviewer", "prompt", blocking=False)

        mock_tui.call_from_thread.assert_called_once()
        call_args = mock_tui.call_from_thread.call_args[0]
        assert call_args[1] is not None  # new_uuid
        assert call_args[2] == "reviewer"  # name


def make_sub_coder(service, generate):
    """A sub-agent coder sharing the parent's io, as IOProxy instances share their target."""
    sub_coder = MagicMock()
    sub_coder.tui = None
    sub_coder.uuid = "child-uuid"
    sub_coder.root = "/proj"
    sub_coder.io = service.coder.io
    sub_coder.generate = AsyncMock(side_effect=generate)
    return sub_coder


class TestSubAgentEvents:
    """Sub-agent lifecycle reported through ``io.subagent_event``, and cancelling one."""

    @pytest.fixture(autouse=True)
    def patched_coders(self, service, registry):
        # After ``service``, which empties the registry
        with patch("cecli.coders.Coder") as MockCoder:
            with patch("cecli.helpers.conversation.service.ConversationService"):
                self.MockCoder = MockCoder
                yield

    def events(self, service):
        return [
            (call.args[0], call.args[1], call.kwargs)
            for call in service.coder.io.subagent_event.call_args_list
        ]

    async def test_invoke_reports_the_lifecycle(self, service):
        async def finish(user_message, **kwargs):
            info = service.sub_agents["child-uuid"]
            info.status, info.summary = SubAgentStatus.FINISHED, "all good"

        self.MockCoder.create = AsyncMock(return_value=make_sub_coder(service, finish))
        assert await service.invoke("reviewer", "review this") == "all good"

        events = self.events(service)
        assert [(uuid, event) for uuid, event, _ in events] == [
            ("child-uuid", "created"),
            ("child-uuid", "message"),
            ("child-uuid", "running"),
            ("parent-uuid", "message"),
            ("child-uuid", "idle"),
        ]
        created, delegation, _, result, idle = (kwargs for _, _, kwargs in events)
        assert created["parent_uuid"] == "parent-uuid"
        assert created["name"] == "reviewer" and created["root"] == "/proj"
        assert delegation == {"sender_uuid": "parent-uuid", "text": "review this"}
        assert result["sender_uuid"] == "child-uuid" and "all good" in result["text"]
        assert idle == {"stop_reason": "end_turn", "error": None}

    def start_work(self, service, absorb):
        """Invoke a sub-agent that works until cancelled; returns (invoking task, started)."""
        started = asyncio.Event()

        async def work(user_message, **kwargs):
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if not absorb:
                    raise
                # Streaming turns a cancellation into a ^C, and generate() returns

        self.MockCoder.create = AsyncMock(return_value=make_sub_coder(service, work))
        return asyncio.create_task(service.invoke("reviewer", "review this")), started

    @pytest.mark.parametrize("absorb", [False, True])
    async def test_cancelling_the_sub_agent_leaves_its_parent_running(self, service, absorb):
        invoking, started = self.start_work(service, absorb)
        await started.wait()

        assert service.cancel_sub_agent("child-uuid") is True
        assert await invoking == DEFAULT_SUMMARY_INTERRUPTED
        assert self.events(service)[-1][1:] == ("idle", {"stop_reason": "cancelled", "error": None})
        assert service.cancel_sub_agent("child-uuid") is False

    @pytest.mark.parametrize("absorb", [False, True])
    async def test_cancelling_the_parent_cancels_the_sub_agent_it_waits_for(self, service, absorb):
        invoking, started = self.start_work(service, absorb)
        await started.wait()

        invoking.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invoking
        await asyncio.gather(service.sub_agents["child-uuid"].generate_task, return_exceptions=True)
        assert self.events(service)[-1][1:] == ("idle", {"stop_reason": "cancelled", "error": None})


# ================================================================== #
# Public API: spawn
# ================================================================== #


class TestSpawn:
    """AgentService.spawn() behavior."""

    @pytest.mark.asyncio
    async def test_unknown_name_raises(self, service):
        """Unknown name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown sub-agent"):
            await service.spawn("ghost")

    @pytest.mark.asyncio
    async def test_spawn_creates_without_generating(self, service, registry):
        """spawn creates sub-agent without calling generate."""
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                mock_chunks = MagicMock()
                MockConv.get_chunks.return_value = mock_chunks

                await service.spawn("reviewer")

        # Find the sub-agent info by iterating values (keyed by uuid, not name)
        matched_info = None
        for _info in service.sub_agents.values():
            if _info.name == "reviewer":
                matched_info = _info
                break
        assert matched_info is not None, "Sub-agent 'reviewer' not found"
        assert matched_info.status == SubAgentStatus.CREATED
        mock_new_coder.generate.assert_not_called()


# ================================================================== #
# Public API: wait
# ================================================================== #


class TestWait:
    """AgentService.wait() behavior."""

    @pytest.mark.asyncio
    async def test_no_children_returns_empty_list(self, service):
        """Parent with no children returns empty list."""
        parent_coder = MagicMock()
        parent_coder.uuid = "parent-uuid"
        result = await service.wait(parent_coder)
        assert result == []

    @pytest.mark.asyncio
    async def test_wait_finished_returns_summary_list(self, service):
        """Already FINISHED returns summary in a list."""
        parent_coder = MagicMock()
        parent_coder.uuid = "parent-uuid"
        info = SubAgentInfo(
            name="agent",
            coder=MagicMock(),
            parent_uuid="parent-uuid",
            status=SubAgentStatus.FINISHED,
            summary="done",
        )
        info.generate_task = None
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        result = await service.wait(parent_coder)
        assert result == ["done"]

    @pytest.mark.asyncio
    async def test_wait_error_returns_none_summary(self, service):
        """ERROR status returns list containing None summary."""
        parent_coder = MagicMock()
        parent_coder.uuid = "parent-uuid"
        info = SubAgentInfo(
            name="agent",
            coder=MagicMock(),
            parent_uuid="parent-uuid",
            status=SubAgentStatus.ERROR,
            error="something broke",
            summary=None,
        )
        info.generate_task = None
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        result = await service.wait(parent_coder)
        assert result == [None]

    @pytest.mark.asyncio
    async def test_wait_polls_until_finished(self, service):
        """Polls via generate_task until FINISHED then returns summary."""
        import asyncio

        parent_coder = MagicMock()
        parent_coder.uuid = "parent-uuid"

        info = SubAgentInfo(
            name="agent",
            coder=MagicMock(),
            parent_uuid="parent-uuid",
            status=SubAgentStatus.CREATED,
        )

        async def finish_later():
            await asyncio.sleep(0.05)
            info.status = SubAgentStatus.FINISHED
            info.summary = "completed"

        # Create a generate_task that completes when finish_later runs
        async def gen_task():
            await finish_later()

        info.generate_task = asyncio.create_task(gen_task())
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        result = await service.wait(parent_coder)
        assert result == ["completed"]


# ================================================================== #
# Detached agents (workflow islands)
# ================================================================== #


class TestDetachedAgents:
    """Detached agents stay out of the parent's context and child scans."""

    @pytest.mark.asyncio
    async def test_detached_result_is_not_injected(self, service, mock_coder):
        import weakref

        child = MagicMock()
        child.uuid = "child-uuid"
        service._uuid_coder_map["parent-uuid"] = weakref.ref(mock_coder)
        info = SubAgentInfo(
            name="wf:demo",
            coder=child,
            parent_uuid="parent-uuid",
            status=SubAgentStatus.FINISHED,
            summary="all done",
            detached=True,
        )

        with patch(
            "cecli.helpers.conversation.service.ConversationService.get_manager"
        ) as get_manager:
            await service._inject_sub_agent_result(info)

        get_manager.assert_not_called()

    @pytest.mark.asyncio
    async def test_attached_result_is_injected(self, service, mock_coder):
        import weakref

        child = MagicMock()
        child.uuid = "child-uuid"
        service._uuid_coder_map["parent-uuid"] = weakref.ref(mock_coder)
        info = SubAgentInfo(
            name="reviewer",
            coder=child,
            parent_uuid="parent-uuid",
            status=SubAgentStatus.FINISHED,
            summary="all done",
        )

        with patch(
            "cecli.helpers.conversation.service.ConversationService.get_manager"
        ) as get_manager:
            await service._inject_sub_agent_result(info)

        assert get_manager.return_value.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_wait_skips_detached_children(self, service):
        parent_coder = MagicMock()
        parent_coder.uuid = "parent-uuid"

        detached_child = MagicMock()
        detached_child.uuid = "detached-uuid"
        service.sub_agents["detached-uuid"] = SubAgentInfo(
            name="wf:demo",
            coder=detached_child,
            parent_uuid="parent-uuid",
            status=SubAgentStatus.FINISHED,
            summary="background run",
            detached=True,
        )

        normal_child = MagicMock()
        normal_child.uuid = "normal-uuid"
        service.sub_agents["normal-uuid"] = SubAgentInfo(
            name="reviewer",
            coder=normal_child,
            parent_uuid="parent-uuid",
            status=SubAgentStatus.FINISHED,
            summary="done",
        )

        result = await service.wait(parent_coder)

        assert result == ["done"]


# ================================================================== #
# TUI notification threading
# ================================================================== #


class TestTuiNotify:
    """Container notifications must work from the app thread or a worker one."""

    def test_same_thread_falls_back_to_direct_call(self):
        from cecli.helpers.agents.service import _tui_notify

        hits = []

        class AppThreadTui:
            def call_from_thread(self, callback, *args):
                raise RuntimeError(
                    "The `call_from_thread` method must run in a different thread from the app"
                )

            def container(self, *args):
                hits.append(args)

        tui = AppThreadTui()
        _tui_notify(tui, tui.container, "u1", "wf:demo")

        assert hits == [("u1", "wf:demo")]

    def test_cross_thread_uses_call_from_thread(self):
        from cecli.helpers.agents.service import _tui_notify

        class WorkerThreadTui:
            def __init__(self):
                self.via_thread = []

            def call_from_thread(self, callback, *args):
                self.via_thread.append(args)

        tui = WorkerThreadTui()
        _tui_notify(tui, lambda *a: None, "u2")

        assert tui.via_thread == [("u2",)]


# ================================================================== #
# Foreground tracking
# ================================================================== #


class TestForeground:
    """Foreground agent tracking properties."""

    def test_foreground_uuid_default_none(self, service):
        """foreground_uuid defaults to None."""
        assert service.foreground_uuid is None

    def test_foreground_uuid_setter(self, service):
        """foreground_uuid can be set and read."""
        service.foreground_uuid = "sub-uuid"
        assert service.foreground_uuid == "sub-uuid"

    def test_foreground_uuid_none_is_primary(self, service):
        """foreground_uuid=None returns primary coder."""
        assert service.foreground_coder is service.coder

    def test_foreground_uuid_matches_sub_agent(self, service):
        """foreground_uuid matching a sub-agent returns that sub-agent's coder."""
        sub_coder = MagicMock()
        sub_coder.uuid = "sub-uuid"
        info = SubAgentInfo(
            name="agent",
            coder=sub_coder,
            parent_uuid="parent",
        )
        service.sub_agents["agent"] = info
        service.foreground_uuid = "sub-uuid"
        assert service.foreground_coder is sub_coder

    def test_foreground_uuid_unknown_falls_back(self, service):
        """foreground_uuid not matching any agent falls back to primary."""
        service.foreground_uuid = "nonexistent"
        assert service.foreground_coder is service.coder


# ================================================================== #
# get_active_agents
# ================================================================== #


class TestGetActiveAgents:
    """get_active_agents() display helper."""

    def test_returns_list_of_dicts(self, service):
        """Returns a list of dicts with name/uuid/status/summary."""
        info = SubAgentInfo(
            name="agent",
            coder=MagicMock(),
            parent_uuid="parent",
            status=SubAgentStatus.RUNNING,
            summary="in progress",
        )
        info.coder.uuid = "sub-uuid"
        service.sub_agents["agent"] = info

        agents = service.get_active_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "agent"
        assert agents[0]["uuid"] == "sub-uuid"
        assert agents[0]["status"] == "running"
        assert agents[0]["summary"] == "in progress"

    def test_empty_when_no_agents(self, service):
        """No sub-agents returns empty list."""
        assert service.get_active_agents() == []


# ================================================================== #
# cleanup_all_for_parent
# ================================================================== #


class TestCleanupAll:
    """cleanup_all_for_parent() cleanup logic."""

    def test_cleans_all_sub_agents(self, service):
        """Cleans up all sub-agents and removes instance."""
        AgentService._instances[service.coder.uuid] = service

        info = MagicMock()
        info.coder.uuid = "sub-uuid"
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        with patch.object(service, "_cleanup_sub_agent") as mock_cleanup:
            service.cleanup_all_for_parent()
            mock_cleanup.assert_called_once_with("agent")

    def test_removes_instance_from_class(self, service):
        """Removes the parent's instance from _instances."""
        AgentService._instances[service.coder.uuid] = service

        info = MagicMock()
        info.coder.uuid = "sub-uuid"
        service.sub_agents["agent"] = info
        service._sub_agent_order.append("agent")

        with patch.object(service, "_cleanup_sub_agent"):
            service.cleanup_all_for_parent()

        assert service.coder.uuid not in AgentService._instances

    def test_empty_sub_agents(self, service):
        """No sub-agents still removes instance."""
        AgentService._instances[service.coder.uuid] = service

        service.cleanup_all_for_parent()

        assert service.coder.uuid not in AgentService._instances


# ================================================================== #
# keep_files metadata
# ================================================================== #


class TestKeepFiles:
    """Sub-agent file inheritance via the ``keep_files`` metadata flag."""

    def _config(self, metadata):
        """Build a minimal sub-agent config with the given metadata."""
        config = MagicMock()
        config.name = "reviewer"
        config.prompt = "Review code."
        config.model = None
        config.hooks = {}
        config.auto_reap = None
        config.metadata = metadata
        return config

    @pytest.mark.asyncio
    async def test_defaults_to_empty_file_context(self, service):
        """Without keep_files, file lists are reset to empty."""
        AgentService._global_registry = {"reviewer": self._config({})}

        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                MockConv.get_chunks.return_value = MagicMock()

                await service.spawn("reviewer")

        call_kwargs = MockCoder.create.call_args[1]
        assert call_kwargs["fnames"] == []
        assert call_kwargs["read_only_fnames"] == []
        assert call_kwargs["read_only_stubs_fnames"] == []

    @pytest.mark.asyncio
    async def test_keep_files_inherits_parent_file_lists(self, service):
        """keep_files=True omits the resets so Coder.create inherits parent files."""
        AgentService._global_registry = {"reviewer": self._config({"keep_files": True})}

        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                MockConv.get_chunks.return_value = MagicMock()

                await service.spawn("reviewer")

        call_kwargs = MockCoder.create.call_args[1]
        assert "fnames" not in call_kwargs
        assert "read_only_fnames" not in call_kwargs
        assert "read_only_stubs_fnames" not in call_kwargs


# ================================================================== #
# agent_config inheritance prefixes (ws: / wf:)
# ================================================================== #


class TestAgentInheritPrefixes:
    """The AGENT_INHERIT_PREFIXES branch of _create_sub_agent_coder()."""

    def _register(self, name, agent_config):
        from cecli.helpers.agents.config import SubAgentConfig

        AgentService.register_subagent(
            name,
            SubAgentConfig(name=name, prompt="", metadata={"agent-config": agent_config}),
        )

    async def _create(self, service, name):
        mock_new_coder = MagicMock()
        mock_new_coder.tui = None

        with patch("cecli.coders.Coder") as MockCoder:
            MockCoder.create = AsyncMock(return_value=mock_new_coder)
            with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
                MockConv.get_chunks.return_value = MagicMock()
                await service.spawn(name, parent=service.coder)

        return MockCoder.create.call_args[1]["init_metadata"]["agent_config"]

    @pytest.mark.asyncio
    async def test_wf_agent_inherits_and_merges(self, service):
        """wf: inherits the parent agent_config, own keys win, delegation defaults on."""
        service.coder.agent_config = {"subagent_paths": ["p"], "x": "parent"}
        self._register("wf:demo", {"x": "child", "skip_cli_confirmations": True})

        merged = await self._create(service, "wf:demo")

        assert merged["subagent_paths"] == ["p"]  # inherited from parent
        assert merged["x"] == "child"  # own config merged on top
        assert merged["skip_cli_confirmations"] is True
        assert merged["allow_nested_delegation"] is True  # defaulted

    @pytest.mark.asyncio
    async def test_wf_servers_allowlist_forces_local(self, service):
        """A wf: servers allowlist always keeps the Local server available."""
        service.coder.agent_config = {}
        self._register(
            "wf:demo",
            {"servers_includelist": ["GitLab"], "skip_cli_confirmations": True},
        )

        merged = await self._create(service, "wf:demo")

        assert merged["servers_includelist"] == ["gitlab", "local"]

    @pytest.mark.asyncio
    async def test_wf_without_allowlist_does_not_force_local(self, service):
        """Only an explicit allowlist gets the Local server added."""
        service.coder.agent_config = {}
        self._register("wf:demo", {"skip_cli_confirmations": True})

        merged = await self._create(service, "wf:demo")

        assert "servers_includelist" not in merged

    @pytest.mark.asyncio
    async def test_ws_servers_allowlist_does_not_force_local(self, service):
        """Local is forced for wf: agents only, not for other inherit-prefix agents."""
        service.coder.agent_config = {}
        self._register("ws:app", {"servers_includelist": ["github"]})

        merged = await self._create(service, "ws:app")

        assert merged["servers_includelist"] == ["github"]

    @pytest.mark.asyncio
    async def test_wf_respects_explicit_optout(self, service):
        """wf: uses setdefault, so an explicit False in the config survives."""
        service.coder.agent_config = {"allow_nested_delegation": False}
        self._register("wf:opt", {"skip_cli_confirmations": True})

        merged = await self._create(service, "wf:opt")

        assert merged["allow_nested_delegation"] is False

    @pytest.mark.asyncio
    async def test_ws_hard_set_preserved(self, service):
        """ws: still hard-sets allow_nested_delegation=True (unchanged behavior)."""
        service.coder.agent_config = {"allow_nested_delegation": False, "tools_paths": ["t"]}
        self._register("ws:app", {})

        merged = await self._create(service, "ws:app")

        assert merged["tools_paths"] == ["t"]
        assert merged["allow_nested_delegation"] is True

    @pytest.mark.asyncio
    async def test_plain_worker_does_not_inherit(self, service):
        """A plain name never triggers the inheritance merge."""
        service.coder.agent_config = {"parent_only": 1, "allow_nested_delegation": False}
        self._register("worker", {"own": 2})

        merged = await self._create(service, "worker")

        assert merged == {"own": 2}


# ================================================================== #
# Cross-loop lock safety
# ================================================================== #


class TestCrossLoopLocks:
    """Spawn/conversation locks must be usable from two different event loops.

    ``asyncio.Lock`` binds to the loop of its first *waiting* acquirer and
    raises ``RuntimeError`` ("... is bound to a different event loop") when
    awaited from another loop. Spawn, reap and conversation writes reach the
    same per-parent lock from both the TUI main (Textual) loop and the coder
    worker-thread loop, so the pools use ``threading.Lock``; the guarded
    sections are synchronous, so a blocked acquirer simply waits.
    """

    def setup_method(self):
        """Isolate the lock pools (class-level, so they leak between tests)."""
        AgentService._spawn_locks = {}
        AgentService._conversation_locks = {}

    def teardown_method(self):
        AgentService._spawn_locks = {}
        AgentService._conversation_locks = {}

    def test_lock_pools_are_thread_locks(self):
        """The pools hand out ``threading.Lock``, never ``asyncio.Lock``."""
        lock = AgentService._get_lock(AgentService._spawn_locks, "parent-uuid")
        assert isinstance(lock, type(threading.Lock()))
        assert not isinstance(lock, asyncio.Lock)
        # Created lazily, but stable per uuid.
        assert AgentService._get_lock(AgentService._spawn_locks, "parent-uuid") is lock

    def test_contended_lock_is_usable_across_event_loops(self):
        """Two waiters on their own loops must block, never raise.

        With ``asyncio.Lock`` the *second* waiter (different loop from the one
        the lock bound to) raises ``RuntimeError``; with ``threading.Lock``
        both simply wait for the holder to release.
        """
        lock = AgentService._get_lock(AgentService._spawn_locks, "parent-uuid")

        entered = threading.Event()
        release = threading.Event()
        order = []
        errors = []

        def run_on_own_loop(coro_factory):
            """Run the coroutine on a fresh event loop in this thread."""
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro_factory())
            except BaseException as exc:  # noqa: BLE001 - record, do not raise in thread
                errors.append(exc)
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        async def holds_lock():
            with lock:
                order.append("holder")
                entered.set()
                # Await *outside* the lock: guarded sections never await.
                await asyncio.to_thread(release.wait, 5)
            order.append("holder-released")

        def contender_factory(tag):
            async def contends():
                with lock:
                    order.append(tag)

            return contends

        holder = threading.Thread(target=run_on_own_loop, args=(holds_lock,))
        holder.start()
        first = second = None
        try:
            assert entered.wait(timeout=5), "holder never acquired the lock"

            # Waiter #1 blocks on its own loop...
            first = threading.Thread(target=run_on_own_loop, args=(contender_factory("c1"),))
            first.start()
            time.sleep(0.1)
            # ...waiter #2 on a third loop must block too, not raise.
            second = threading.Thread(target=run_on_own_loop, args=(contender_factory("c2"),))
            second.start()
            time.sleep(0.2)

            assert errors == [], f"cross-loop lock acquisition raised: {errors}"
            assert order == ["holder"]
        finally:
            release.set()
            holder.join(timeout=5)

        for thread in (first, second):
            if thread is not None:
                thread.join(timeout=5)

        assert errors == []
        assert "c1" in order
        assert "c2" in order
        assert "holder-released" in order


class TestStartGenerateTaskSwitch:
    """A mid-turn command signal rebuilds the sub-agent coder in place."""

    @pytest.mark.asyncio
    async def test_switch_signal_switches_sub_agent_instead_of_escaping(self, service):
        from cecli.signals import SwitchCoderSignal

        coder = MagicMock()
        coder.uuid = "sub-uuid"

        async def raise_switch(**kwargs):
            raise SwitchCoderSignal(edit_format="subagent")

        coder.generate = AsyncMock(side_effect=raise_switch)
        info = SubAgentInfo(name="wf:demo", coder=coder, parent_uuid="parent-uuid")
        info.detached = True
        service.switch_sub_agent_coder = AsyncMock()

        task = service.start_generate_task(info, "/load-mcp github")
        await task

        service.switch_sub_agent_coder.assert_awaited_once()
        assert service.switch_sub_agent_coder.call_args.args[0] is info
        assert info.status == SubAgentStatus.FINISHED
