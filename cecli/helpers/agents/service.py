"""Agent service for managing sub-agents.

Provides the singleton AgentService (keyed by parent coder UUID)
that tracks sub-agent info and handles invoke/spawn/wait lifecycle.
"""

import asyncio
import logging
import time
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import cecli.models as models
from cecli.helpers.coroutines import fire_and_forget

logger = logging.getLogger(__name__)

# Default summary strings used as fallbacks when a sub-agent finishes
# without setting an explicit summary. These are exported so consumers
# (e.g. the /merge command) can check against them reliably.
DEFAULT_SUMMARY_NO_SUMMARY = "(no summary)"
DEFAULT_SUMMARY_COMPLETED = "(completed without explicit summary)"
DEFAULT_SUMMARY_INTERRUPTED = "(interrupted)"

# Sentinel model markers that resolve to a parent coder's models at runtime.
# These can be used in the ``model`` field of sub-agent .md config files
# to dynamically select the appropriate model without hard-coding a name.
MODEL_SENTINEL_WEAK = "<weak_model>"
MODEL_SENTINEL_AGENT = "<agent_model>"
MODEL_SENTINEL_MAIN = "<main_model>"
MODEL_SENTINEL_CURRENT = "<current>"


class SubAgentStatus(Enum):
    """Status of a sub-agent."""

    CREATED = "created"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class SubAgentInfo:
    """Information about a running sub-agent."""

    name: str
    coder: Any  # SubAgentCoder instance
    parent_uuid: str
    status: SubAgentStatus = SubAgentStatus.CREATED
    summary: Optional[str] = None
    error: Optional[str] = None
    generate_task: Optional[asyncio.Task] = (
        None  # Track the generate() task for cancellation/monitoring
    )
    auto_reap: bool = True  # If True, agent may be automatically reaped when FINISHED
    independent: bool = False


class AgentService:
    """Singleton service for managing sub-agents per parent coder.

    Pattern matches ObservationService — instances are keyed by parent
    coder.uuid so each primary agent session gets its own service.
    """

    _instances: Dict[str, "AgentService"] = {}
    _global_registry: Dict[str, Any] = {}  # name -> SubAgentConfig (from .md files)
    # UUID -> weakref of coder instance for convenient lookup
    _uuid_coder_map: Dict[str, weakref.ref] = {}
    # Lock pools keyed by parent UUID — created lazily so only parents that
    # actually use them allocate a lock.
    _spawn_locks: Dict[str, asyncio.Lock] = {}
    _conversation_locks: Dict[str, asyncio.Lock] = {}
    _primary_agent_uuid: str = None

    # ------------------------------------------------------------------ #
    # Singleton
    # ------------------------------------------------------------------ #

    @classmethod
    def get_instance(cls, coder) -> "AgentService":
        """Return the primary AgentService instance (keyed by first coder uuid).

        The method performs two side-effect responsibilities each time it is
        called regardless of which code-path is taken:

          1. Keep coder references fresh — coders inherit uuids through state
             operation chains so the same uuid can refer to different coder
             instances over time.

          2. Keep the ``_uuid_coder_map`` up to date so look-ups by uuid work.

        The *return* value is always the primary agent's service instance so
        that sub-agents, tools and TUI components all share the same singleton.
        """
        if not cls._primary_agent_uuid:
            cls._primary_agent_uuid = coder.uuid

        parent_uuid = coder.parent_uuid
        if parent_uuid and parent_uuid in cls._instances:
            # Sub-agent path — refresh the coder reference stored on the
            # parent‘s SubAgentInfo so we don’t hold a stale coder object.
            parent_service = cls._instances[cls._primary_agent_uuid]
            existing_info = parent_service.sub_agents.get(coder.uuid)
            if existing_info and existing_info.coder != coder:
                existing_info.coder = coder
                cls._uuid_coder_map[coder.uuid] = weakref.ref(coder)
        else:
            # Primary / standalone coder path — ensure an AgentService
            # instance exists for this uuid and refresh the coder ref.
            uid = coder.uuid
            if uid not in cls._instances:
                cls._instances[uid] = cls(coder)

            if cls._instances[uid].coder != coder:
                cls._instances[uid].coder = coder
                cls._uuid_coder_map[coder.uuid] = weakref.ref(coder)

        return cls._instances[cls._primary_agent_uuid]

    @classmethod
    def destroy_instance(cls, coder_uuid: str) -> None:
        """Explicitly remove a service instance (cleanup)."""
        cls._instances.pop(coder_uuid, None)

    # ------------------------------------------------------------------ #
    # Registry helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def get_registry(cls) -> Dict[str, Any]:
        """Return the global sub-agent registry (name -> config)."""
        return cls._global_registry

    @classmethod
    def get_all_agents(cls) -> List[Any]:
        """Return all live coder instances tracked in the global uuid map.

        Dereferences weakrefs, skipping any that have been garbage-collected.
        """
        agents = []
        for ref in cls._uuid_coder_map.values():
            coder = ref()
            if coder is not None:
                agents.append(coder)
        return agents

    @classmethod
    def register_subagent(cls, name: str, config: Any) -> None:
        """Register a sub-agent config by name."""
        cls._global_registry[name] = config

    @classmethod
    def unregister_subagent(cls, name: str) -> None:
        """Remove a sub-agent from the global registry."""
        cls._global_registry.pop(name, None)

    @classmethod
    def mark_sub_agent_finished(
        cls,
        sub_coder_uuid: str,
        parent_uuid: str,
        summary: Optional[str] = None,
    ) -> None:
        """Public API to mark a sub-agent as finished.

        Looks up the parent's AgentService by parent_uuid and updates
        the matching sub-agent's status and summary.

        Args:
            sub_coder_uuid: UUID of the sub-agent coder.
            parent_uuid: UUID of the parent coder.
            summary: Optional summary string from the sub-agent.
        """
        for uid, service in cls._instances.items():
            if uid != parent_uuid:
                continue
            for info in list(service.sub_agents.values()):
                if info.coder.uuid == sub_coder_uuid:
                    info.summary = summary or DEFAULT_SUMMARY_NO_SUMMARY
                    info.status = SubAgentStatus.FINISHED
                    return

    @classmethod
    def build_registry(cls, paths: List[str]) -> None:
        """Scan directories for .md sub-agent definition files and load them.

        Each .md file should contain YAML front matter with:

          ---
          name: <agent-name>
          model: <optional-model-override>
          ---
          <system prompt body>

        The ``model`` field supports sentinel placeholders that are resolved
        at runtime to the parent coder's models:

            ``<weak_model>``   - The parent coder's weak model
            ``<agent_model>``  - The parent coder's agent model
            ``<main_model>``   - The parent coder's main model
            ``<current>``      - The currently active (foreground) coder's main model
        """
        from pathlib import Path

        from .config import parse_subagent_file

        # Always check the default sub-agents directory in the user's home
        default_dir = str(Path.home() / ".cecli" / "subagents")
        if default_dir not in paths:
            paths = [default_dir] + list(paths)

        # Also scan the built-in defaults directory for .yml definitions
        import cecli.helpers.agents.defaults as _defaults_pkg

        defaults_dir = str(Path(_defaults_pkg.__file__).parent)
        if defaults_dir not in paths:
            paths = [defaults_dir] + list(paths)

        for directory in paths:
            dir_path = Path(directory).expanduser()
            if not dir_path.is_dir():
                continue
            for agent_file in sorted(list(dir_path.glob("*.md"))):
                try:
                    config = parse_subagent_file(str(agent_file))
                    if config and config.name:
                        cls._global_registry[config.name] = config
                        logger.info("Loaded sub-agent '%s' from %s", config.name, agent_file)
                except (ValueError, OSError) as exc:
                    logger.warning("Failed to parse sub-agent file %s: %s", agent_file, exc)
                except Exception as exc:
                    logger.warning(
                        "Unexpected error parsing sub-agent file %s: %s", agent_file, exc
                    )

    # ------------------------------------------------------------------ #
    # Instance
    # ------------------------------------------------------------------ #

    def __init__(self, coder) -> None:
        self.coder = coder
        # Register the primary coder in the global uuid map
        if hasattr(coder, "uuid"):
            self._uuid_coder_map[str(coder.uuid)] = weakref.ref(coder)
        # uuid -> SubAgentInfo
        self.sub_agents: Dict[str, SubAgentInfo] = {}
        # Ordered list of sub-agent UUIDs for LRU reap
        self._sub_agent_order: List[str] = []

    @property
    def max_sub_agents(self) -> int:
        """Return the max number of sub-agents allowed for this coder."""
        return getattr(self.coder, "max_sub_agents", 30)

    # ------------------------------------------------------------------ #
    # Internal helpers
    @classmethod
    def _get_lock(cls, pool: Dict[str, asyncio.Lock], uuid: str) -> asyncio.Lock:
        """Return a lock for *uuid* from *pool*, creating one if absent."""
        if uuid not in pool:
            pool[uuid] = asyncio.Lock()
        return pool[uuid]

    @staticmethod
    def _get_tui(coder: Any) -> Any:
        """Dereference the TUI weakref from a coder, returning None if unavailable.

        The TUI stores itself on coders via ``coder.tui = weakref.ref(app)``,
        so it must be called (``tui()``) to obtain the live object.

        Args:
            coder: A coder instance that may have a ``tui`` attribute.

        Returns:
            The TUI application instance, or ``None`` if the weakref is dead
            or the coder has no ``tui`` attribute.
        """
        tui_ref = getattr(coder, "tui", None)
        if tui_ref is None:
            return None
        # weakref.ref objects are callable — calling them returns the live
        # reference or None if the object has been garbage-collected.
        if isinstance(tui_ref, weakref.ref):
            return tui_ref()
        # If it is already a plain reference (e.g., in tests), use it directly.
        return tui_ref

    def _resolve_model_sentinel(self, value: str, parent_coder: Any):
        """Resolve a sentinel model marker to the appropriate Model instance.

        Allows sub-agent .md config files to use placeholders like
        ``<weak_model>``, ``<agent_model>``, ``<main_model>``, or
        ``<current>`` in the ``model`` field instead of hard-coding a
        specific model name.  The sentinel is resolved at runtime using
        the parent coder's model hierarchy.

        Args:
            value: The sentinel string (e.g. ``"<weak_model>"``) or a
                   regular model name (returned as ``None``).
            parent_coder: The parent coder instance whose models are used.

        Returns:
            A ``Model`` instance if *value* is a recognised sentinel,
            ``None`` otherwise (so callers can fall through to the
            normal ``Model()`` constructor path).
        """
        if value == MODEL_SENTINEL_WEAK:
            model = parent_coder.main_model.weak_model
            return model if model is not None else parent_coder.main_model
        elif value == MODEL_SENTINEL_AGENT:
            model = parent_coder.main_model.agent_model
            return model if model is not None else parent_coder.main_model
        elif value == MODEL_SENTINEL_MAIN:
            return parent_coder.main_model
        elif value == MODEL_SENTINEL_CURRENT:
            # Use the foreground coder's model if set, otherwise fall back to parent
            foreground = self.foreground_coder
            if foreground is not None:
                return foreground.main_model
            return parent_coder.main_model

        return None

    # ------------------------------------------------------------------ #

    def _reap_finished_agent(self) -> None:
        """Remove the oldest FINISHED or ERROR sub-agent (lazy reap).

        Only reaps sub-agents whose descendants (children, grandchildren, etc.)
        have all also finished.  This prevents reaping a sub-agent while it
        still has running descendant tasks that its ``generate()`` loop may
        need to process.
        """
        # Build parent → children mapping
        parent_to_children: Dict[str, List[SubAgentInfo]] = {}
        for info in self.sub_agents.values():
            parent_to_children.setdefault(info.parent_uuid, []).append(info)

        def _has_unfinished_descendants(agent_uuid: str) -> bool:
            """Return True if *agent_uuid* has any non-FINISHED/non-ERROR descendant."""
            for child in parent_to_children.get(agent_uuid, []):
                if child.status not in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR):
                    return True
                if _has_unfinished_descendants(child.coder.uuid):
                    return True
            return False

        for coder_uuid in list(self._sub_agent_order):
            info = self.sub_agents.get(coder_uuid)
            if (
                info
                and info.status in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR)
                and info.auto_reap
                and (info.generate_task is None or info.generate_task.done())
                and not _has_unfinished_descendants(coder_uuid)
            ):
                self._cleanup_sub_agent(coder_uuid)
                return

    async def reap_all_finished_agents(self, parent: Any = None) -> None:
        """Remove all FINISHED or ERROR sub-agents that have ``auto_reap`` enabled.

        Builds a parent→children mapping of all sub-agents and only reaps
        finished sub-agents whose descendants (children, grandchildren, etc.)
        have all also finished.  This prevents reaping a sub-agent while it
        still has running descendant tasks that its ``generate()`` loop may
        need to process.  Acquires the spawn lock for the given *parent*
        (or ``self.coder`` if omitted) to serialise with concurrent
        ``_create_sub_agent_coder()`` operations under the same parent.

        Args:
            parent: Optional coder instance whose spawn lock will be acquired.
                    If provided, reaping is serialised against spawns under this
                    specific parent. Defaults to ``self.coder``.
        """
        # Build parent → children mapping
        parent_to_children: Dict[str, List[SubAgentInfo]] = {}
        for info in self.sub_agents.values():
            parent_to_children.setdefault(info.parent_uuid, []).append(info)

        def _has_unfinished_descendants(agent_uuid: str) -> bool:
            """Return True if *agent_uuid* has any non-FINISHED/non-ERROR descendant."""
            for child in parent_to_children.get(agent_uuid, []):
                if child.status not in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR):
                    return True
                if _has_unfinished_descendants(child.coder.uuid):
                    return True
            return False

        # Acquire the spawn lock for the primary coder to serialise with
        # concurrent spawn operations that also hold this lock.
        parent_coder = parent if parent is not None else self.coder
        async with self._get_lock(self._spawn_locks, parent_coder.uuid):
            for coder_uuid in list(self._sub_agent_order):
                info = self.sub_agents.get(coder_uuid)
                if (
                    info
                    and info.status in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR)
                    and info.auto_reap
                    and (info.generate_task is None or info.generate_task.done())
                    and not _has_unfinished_descendants(coder_uuid)
                ):
                    self._cleanup_sub_agent(coder_uuid)

    def _cleanup_sub_agent(self, agent_uuid: str) -> None:
        """Remove agent instance from tracking and notify TUI if possible."""
        info = self.sub_agents.pop(agent_uuid, None)
        if agent_uuid in self._sub_agent_order:
            self._sub_agent_order.remove(agent_uuid)

        if info is None:
            return

        # Destroy conversation resources for the sub-agent
        from cecli.helpers.conversation.service import ConversationService

        try:
            ConversationService.destroy_instances(info.coder.uuid)
        except (KeyError, AttributeError, RuntimeError):
            logger.warning("Failed to destroy conversation instances", exc_info=True)

        # Unregister the sub-agent's input queue from the global registry so it
        # does not leak for the process lifetime (IOProxy registers one queue
        # per coder, including every sub-agent).
        from cecli.helpers import queues as _queues

        try:
            _queues.unregister_coder_queue(info.coder.uuid)
        except (KeyError, AttributeError, RuntimeError):
            logger.warning("Failed to unregister coder queue", exc_info=True)

        # Destroy hook resources for the sub-agent
        from cecli.hooks.service import HookService

        try:
            HookService.destroy_instances(info.coder.uuid)
            HookService.destroy_registry(info.coder.uuid)
        except (KeyError, AttributeError, RuntimeError):
            logger.warning("Failed to destroy hook instances", exc_info=True)

        # Notify TUI to remove the sub-agent container
        try:
            # Use self.coder (parent) for TUI lookup — sub-agents don't have
            # their own tui attribute; only the primary coder stores it.
            tui = self._get_tui(self.coder)
            if tui is not None:
                tui.call_from_thread(tui.remove_sub_agent_container, info.coder.uuid)
        except (AttributeError, RuntimeError):
            logger.warning("Failed to notify TUI to remove sub-agent container", exc_info=True)

        # Cancel any tracked generate task to avoid floating tasks
        if info.generate_task is not None and not info.generate_task.done():
            info.generate_task.cancel()

        # Reset foreground tracking if the cleaned agent was foreground
        if getattr(self, "_foreground_uuid", None) == info.coder.uuid:
            self._foreground_uuid = None

        # Remove from global coder lookup and clean up our service tracking
        # Note: this destroys the service instance keyed by the sub-agent's uuid,
        # not the parent's service instance. The parent's instance is cleaned
        # up separately in cleanup_all_for_parent().
        self._uuid_coder_map.pop(info.coder.uuid, None)
        self.destroy_instance(info.coder.uuid)

    def _check_max_sub_agents(self) -> None:
        """If we've hit max_sub_agents, reap the oldest finished one.

        Raises RuntimeError if no finished agents can be reaped.
        """
        active_count = sum(
            1
            for info in self.sub_agents.values()
            if info.status not in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR)
        )
        if active_count < self.max_sub_agents:
            return

        # Try to reap a finished agent via the shared helper
        self._reap_finished_agent()

        # Recalculate active count after reaping
        active_count = sum(
            1
            for info in self.sub_agents.values()
            if info.status not in (SubAgentStatus.FINISHED, SubAgentStatus.ERROR)
        )
        if active_count >= self.max_sub_agents:
            raise RuntimeError(
                f"Maximum sub-agents ({self.max_sub_agents}) reached. "
                "Wait for one to finish or use /reap-agent to free resources."
            )

    async def _create_sub_agent_coder(
        self,
        name: str,
        parent: Any = None,
        auto_reap: Optional[bool] = None,
        independent: bool = False,
    ) -> Tuple[Any, SubAgentInfo]:
        """Create a sub-agent coder, register it, and set up its container and prompt.

        Shared helper used by both ``invoke()`` and ``spawn()`` to eliminate
        code duplication in the sub-agent creation pipeline.

        Args:
            name: Name of the sub-agent to create.
            parent: Optional coder instance to use as the parent for nested
                    sub-agent hierarchies. If provided, the new sub-agent's
                    ``parent_uuid`` will be ``parent.uuid`` instead of
                    ``self.coder.uuid``. Defaults to ``self.coder``.
            auto_reap: If True, agent may be automatically reaped when FINISHED.
                    If not set, defers to the sub-agent config's ``auto_reap``
                    value, then defaults to ``True``.

        Returns:
            Tuple of ``(new_coder, info)``.

        Raises:
            ValueError: If the named sub-agent is not registered.
            RuntimeError: If the maximum number of sub-agents is reached.
        """
        config = self._global_registry.get(name)
        if not config:
            raise ValueError(
                f"Unknown sub-agent '{name}'. " f"Available: {list(self._global_registry.keys())}"
            )

        # Resolve auto_reap: None means defer to sub-agent config, then default to True
        if auto_reap is None:
            auto_reap = getattr(config, "auto_reap", None)
            if auto_reap is None:
                auto_reap = True

        # Critical section: max-sub-agent check and registration must be atomic
        # to prevent TOCTOU race when multiple spawns fire concurrently.
        # Coder.create() is called *outside* the lock to avoid holding an
        # await across a lock (which risks deadlock if Coder.create() ever
        # tried to acquire the same lock).
        parent_coder = parent if parent is not None else self.coder

        async with self._get_lock(self._spawn_locks, parent_coder.uuid):
            self._check_max_sub_agents()
            new_uuid = str(uuid4())

        from cecli.coders import Coder

        metadata = getattr(config, "metadata", {}).copy()
        agent_config = metadata.get("agent-config", {})

        kwargs = dict(
            io=parent_coder.io,
            from_coder=parent_coder,
            edit_format="subagent",
            cur_messages=[],
            uuid=new_uuid,
            parent_uuid=parent_coder.uuid,
            map_tokens=0,
            init_metadata={"agent_config": agent_config},
        )

        if agent_config:
            # Reset the per-instance tool/server filters so AgentCoder.post_init()
            # rebuilds them from *this* sub-agent's own agent-config (tools_includelist/
            # excludelist, servers_includelist/excludelist) instead of inheriting the
            # parent's filters verbatim. Deliberately do NOT reset mcp_manager here:
            # doing so used to discard the parent's already-connected MCP servers and
            # replace them with a brand new, empty manager, making it impossible for a
            # sub-agent's servers_includelist to ever match anything. Leaving mcp_manager
            # unset lets it inherit from from_coder (see Coder.create()) so the same
            # connected MCP servers remain available and can then be filtered.
            kwargs.update(
                dict(
                    registered_tools=None,
                    registered_servers=None,
                )
            )

        model_override = getattr(config, "model", None)
        if model_override:
            # Resolve model sentinels (e.g. "<weak_model>", "<agent_model>")
            resolved = self._resolve_model_sentinel(model_override, parent_coder)
            if resolved is not None:
                kwargs["main_model"] = resolved
            else:
                kwargs["main_model"] = models.Model(
                    model_override,
                    from_model=parent_coder.main_model,
                    agent_model=model_override,
                )

        new_coder = await Coder.create(**kwargs)
        new_coder.max_sub_agents = getattr(self.coder, "max_sub_agents", 30)
        # IOProxy wrapping is handled by base_coder.py's Coder.__init__

        # Re-acquire the lock to register — we must re-check max agents since
        # the lock was released and other spawns may have registered in between.
        async with self._get_lock(self._spawn_locks, parent_coder.uuid):
            self._check_max_sub_agents()

            # Register in global coder lookup
            self._uuid_coder_map[new_uuid] = weakref.ref(new_coder)

            info = SubAgentInfo(
                name=name,
                coder=new_coder,
                parent_uuid=parent_coder.uuid,
                status=SubAgentStatus.CREATED,
                auto_reap=auto_reap,
                independent=independent,
            )
            self.sub_agents[new_coder.uuid] = info
            self._sub_agent_order.append(new_coder.uuid)

        # Notify TUI to create a container
        try:
            tui = self._get_tui(self.coder)
            if tui is not None:
                tui.call_from_thread(tui.create_sub_agent_container, new_uuid, name)
        except Exception:
            logger.warning("Failed to notify TUI to create sub-agent container", exc_info=True)

        # Initialize system prompt from config
        system_prompt = getattr(config, "prompt", "")
        from cecli.helpers.conversation.service import ConversationService

        ConversationService.get_chunks(new_coder).add_system_message(system_prompt)

        # Initialize hooks from sub-agent config if defined
        hooks_config = getattr(config, "hooks", {})
        if hooks_config:
            import tempfile
            from pathlib import Path

            from cecli.hooks import HookService

            hook_registry = HookService.get_registry(new_coder)

            # Write hooks config to a temp YAML file and load it
            import yaml

            with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as temp_file:
                yaml.dump({"hooks": hooks_config}, temp_file)
                temp_file_path = Path(temp_file.name)

            try:
                loaded_hooks = hook_registry.load_hooks_from_config(temp_file_path)
                if loaded_hooks:
                    logger.info(
                        "Loaded %d hooks for sub-agent '%s': %s",
                        len(loaded_hooks),
                        name,
                        ", ".join(loaded_hooks),
                    )
            finally:
                temp_file_path.unlink(missing_ok=True)

        return new_coder, info

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start_generate_task(self, info: SubAgentInfo, user_message: str) -> asyncio.Task:
        """Start a sub-agent's generate task in the background with status management.

        Sets status to RUNNING before starting, and handles FINISHED/ERROR
        when the task completes or fails. Stores the task on ``info.generate_task``
        for cancellation/monitoring.

        Args:

        .. note:

            **Ordering dependency with mark_sub_agent_finished()**

            ``mark_sub_agent_finished()`` (called *synchronously* inside the tool
            execution pipeline of ``generate()``) writes ``info.status`` and
            ``info.summary`` before ``generate()`` returns to this task.

            The ``if info.status == SubAgentStatus.RUNNING:`` guard below correctly
            prevents the task from overwriting those values with defaults.

            This ordering is currently safe because tool execution is synchronous.
            If tool execution is refactored to introduce interleaved ``await`` points,
            this dependency would break and an ``asyncio.Event`` would be needed.
            info: The SubAgentInfo for the sub-agent.
            user_message: The user message to pass to ``generate()``.

        Returns:
            The ``asyncio.Task`` wrapping ``generate()``.
        """
        from cecli.commands import SwitchCoderSignal

        async def _run_generate():
            info.status = SubAgentStatus.RUNNING
            try:
                await info.coder.generate(user_message=user_message, preproc=True)
                await self._inject_sub_agent_result(info)
                if info.status == SubAgentStatus.RUNNING:
                    info.status = SubAgentStatus.FINISHED
                    info.summary = info.summary or DEFAULT_SUMMARY_COMPLETED

                if info.auto_reap and info.independent:

                    async def _cleanup():
                        await asyncio.sleep(5)

                        # Cleanup conversation resources
                        from cecli.helpers.conversation.service import (
                            ConversationService,
                        )

                        ConversationService.destroy_instances(info.coder.uuid)
                        # Remove from tracking and clean up
                        self._cleanup_sub_agent(info.coder.uuid)

                    fire_and_forget(_cleanup())

            except asyncio.CancelledError:
                await self._inject_sub_agent_result(info)
                info.status = SubAgentStatus.FINISHED
                info.summary = info.summary or DEFAULT_SUMMARY_INTERRUPTED
                logger.debug("Sub-agent %s generate cancelled (interrupted)", info.name)
                raise
            except Exception as exc:
                await self._inject_sub_agent_result(info)
                info.status = SubAgentStatus.ERROR
                info.error = str(exc)
                logger.error(
                    "Sub-agent %s generate failed: %s",
                    info.name,
                    exc,
                    exc_info=True,
                )
                raise
            except SwitchCoderSignal:
                raise

        # Cancel any previous generate task to prevent duplicate concurrent generates
        if info.generate_task is not None and not info.generate_task.done():
            info.generate_task.cancel()

        task = asyncio.create_task(_run_generate())
        info.generate_task = task

        def _raise_if_signal(exc):
            if isinstance(exc, SwitchCoderSignal):
                raise exc

        # Suppress "Task exception was never retrieved" for fire-and-forget tasks
        task.add_done_callback(
            lambda t: _raise_if_signal(t.exception()) if not t.cancelled() else None
        )
        return task

    async def _inject_sub_agent_result(self, info: SubAgentInfo) -> None:
        """Inject the sub-agent's result (summary/error) into the parent's conversation.

        Adds a user message with the result content and an assistant acknowledgment
        so the parent coder (and therefore the LLM) sees what the sub-agent produced.
        Uses unique hash keys so multiple sub-agent completions don't overwrite each other.
        """
        from cecli.helpers.conversation.service import ConversationService
        from cecli.helpers.conversation.tags import MessageTag

        # Capture coder UUID early in case the sub-agent is cleaned up before
        # this method completes (the weakref could become invalid).
        coder_uuid = getattr(info.coder, "uuid", "(unknown)")

        parent_coder_ref = self._uuid_coder_map.get(info.parent_uuid)
        if not parent_coder_ref:
            return

        parent_coder = parent_coder_ref()
        if not parent_coder:
            return

        if info.status == SubAgentStatus.ERROR:
            user_content = (
                f"The **{info.name}** agent (`{coder_uuid}`) encountered an error:\n"
                f"{info.error}"
            )
            assistant_content = (
                f"The {info.name} agent `{coder_uuid}` failed with the error above. "
                f"You may want to review or retry the delegation."
            )
        elif info.status == SubAgentStatus.FINISHED:
            is_interrupted = info.summary == DEFAULT_SUMMARY_INTERRUPTED
            summary_text = info.summary or DEFAULT_SUMMARY_COMPLETED
            if is_interrupted:
                user_content = (
                    f"The **{info.name}** agent (`{coder_uuid}`) was interrupted:\n"
                    f"{summary_text}"
                )
                assistant_content = (
                    f"The {info.name} agent `{coder_uuid}` was interrupted before completing its task. "
                    f"You may want to review or retry the delegation."
                )
            else:
                user_content = (
                    f"The **{info.name}** agent (`{coder_uuid}`) completed with the following summary:\n"
                    f"{summary_text}"
                )
                assistant_content = (
                    f"Thank you for sharing the summary for {info.name} agent `{coder_uuid}`. "
                    f"The agent has finished its task."
                )
        else:
            return

        async with self._get_lock(self._conversation_locks, info.parent_uuid):
            ConversationService.get_manager(parent_coder).add_message(
                message_dict={"role": "user", "content": user_content},
                tag=MessageTag.CUR,
                hash_key=("sub_agent_result", "user", coder_uuid, str(time.monotonic_ns())),
                force=True,
            )
            ConversationService.get_manager(parent_coder).add_message(
                message_dict={"role": "assistant", "content": assistant_content},
                tag=MessageTag.CUR,
                hash_key=("sub_agent_result", "assistant", coder_uuid, str(time.monotonic_ns())),
                force=True,
            )

    async def invoke(
        self,
        name: str,
        prompt: str,
        blocking: bool = True,
        parent: Any = None,
        auto_reap: Optional[bool] = None,
    ) -> Optional[str]:
        """Invoke a sub-agent by name with the given prompt (blocking by default).

        Args:
            name: Name of the sub-agent to invoke.
            prompt: The user message to pass to the sub-agent.
            blocking: If True, waits for completion and returns summary.
            parent: Optional coder instance to use as the parent for nested
                   sub-agent hierarchies. Defaults to ``self.coder``.
        """
        new_coder, info = await self._create_sub_agent_coder(
            name, auto_reap=auto_reap, parent=parent
        )

        if not blocking:
            return None

        # Blocking: run the sub-agent with the prompt using start_generate_task
        task = self.start_generate_task(info, prompt)
        await task
        return info.summary

    async def spawn(
        self,
        name: str,
        prompt: Optional[str] = None,
        parent: Any = None,
        auto_reap: Optional[bool] = None,
        independent: bool = False,
    ) -> Tuple[Any, SubAgentInfo]:
        """Spawn a sub-agent (non-blocking) that waits for user input.

        Args:
            name: Name of the sub-agent to spawn.
            prompt: Optional prompt. If provided, starts the generate task
                    immediately with this prompt (fire-and-forget).
            parent: Optional coder instance to use as the parent for nested
                   sub-agent hierarchies. Defaults to ``self.coder``.

        Returns:
            Tuple of ``(new_coder, info)`` so callers can further interact
            with the sub-agent (e.g. call ``start_generate_task`` later).
        """
        new_coder, info = await self._create_sub_agent_coder(
            name, auto_reap=auto_reap, parent=parent, independent=independent
        )
        if prompt:
            self.start_generate_task(info, prompt)
        return new_coder, info

    async def wait(self, parent: Any) -> List[str]:
        """Await all active sub-agents whose ``parent_uuid`` matches ``parent.uuid``.

        Waits for every child's generate task to finish (via ``asyncio.gather``)
        and returns their summaries as a list.

        Args:
            parent: A coder instance (with ``.uuid``) or a UUID string whose
                    children should be awaited.

        Returns:
            ``List[str]`` — one summary per child sub-agent.  May be empty
            if the parent has no active children.
        """
        uid = str(parent.uuid) if hasattr(parent, "uuid") else str(parent)
        children = [info for info in self.sub_agents.values() if info.parent_uuid == uid]
        if not children:
            logger.debug("wait(%s): no children found", uid)
            return []

        # Collect all active generate tasks
        tasks = []
        for info in children:
            if info.generate_task is not None and not info.generate_task.done():
                tasks.append(info.generate_task)

        if tasks:
            logger.debug("wait(%s): awaiting %d generate task(s)", uid, len(tasks))
            await asyncio.gather(*tasks)

        return [info.summary for info in children]

    def get_active_agents(self) -> List[Dict[str, Any]]:
        """Return list of active sub-agents for display."""
        return [
            {
                "name": info.name,
                "uuid": info.coder.uuid,
                "status": info.status.value,
                "summary": info.summary,
            }
            for info in self.sub_agents.values()
        ]

    def get_children(self, coder_or_uuid: Any) -> List[SubAgentInfo]:
        """Return sub-agents whose parent is the given coder or UUID.

        Accepts either a coder instance (object with a ``uuid`` attribute)
        or a plain UUID string.  Returns all ``SubAgentInfo`` entries whose
        ``parent_uuid`` matches the resolved identifier.

        Args:
            coder_or_uuid: A coder instance (with ``.uuid``) or a UUID string.

        Returns:
            List of ``SubAgentInfo`` objects whose parent is the given coder.
        """
        if hasattr(coder_or_uuid, "uuid"):
            uid = str(coder_or_uuid.uuid)
        else:
            uid = str(coder_or_uuid)

        return [info for info in self.sub_agents.values() if info.parent_uuid == uid]

    def get_parent(self, coder_or_uuid: Any) -> Any:
        """Return the parent coder for the given coder or UUID.

        If the given coder is the primary coder (``self.coder``), returns itself.
        Otherwise, looks up the sub-agent's parent in the tracking data and
        returns that parent's coder instance.

        This is used for lock key resolution when reaping from a sub-agent
        context — the spawn lock should be acquired with the parent's UUID
        to properly serialise with concurrent spawn operations under that
        same parent.

        Args:
            coder_or_uuid: A coder instance (with ``.uuid``) or a UUID string.

        Returns:
            The parent coder instance, or ``self.coder`` if the given coder is
            the primary coder or has no known parent.
        """
        if hasattr(coder_or_uuid, "uuid"):
            uid = str(coder_or_uuid.uuid)
        else:
            uid = str(coder_or_uuid)

        # Primary coder returns itself
        if uid == self.coder.uuid:
            return self.coder

        # Look up the sub-agent to find its parent_uuid
        info = self.sub_agents.get(uid)
        if info and info.parent_uuid:
            # Parent is the primary coder
            if info.parent_uuid == self.coder.uuid:
                return self.coder
            # Parent is another sub-agent — look up its coder
            parent_info = self.sub_agents.get(info.parent_uuid)
            if parent_info:
                return parent_info.coder

        return self.coder

    def get_agent_name(self, coder_or_uuid: Any) -> Optional[str]:
        """Return the sub-agent name for the given coder or UUID.

        Looks up the sub-agent info by UUID and returns its ``name`` field
        (the configured sub-agent type, e.g. ``"worker"``, ``"memorizer"``).
        Returns ``None`` if the given coder/UUID is not a known sub-agent
        (e.g. it is the primary coder or has no entry in ``sub_agents``).

        Args:
            coder_or_uuid: A coder instance (with ``.uuid``) or a UUID string.

        Returns:
            The sub-agent name string, or ``None`` if not found.
        """
        if hasattr(coder_or_uuid, "uuid"):
            uid = str(coder_or_uuid.uuid)
        else:
            uid = str(coder_or_uuid)

        info = self.sub_agents.get(uid)
        if info is not None:
            return info.name

        return None

    # ------------------------------------------------------------------ #
    # Foreground agent tracking
    # ------------------------------------------------------------------ #

    @property
    def foreground_uuid(self):
        """Get the UUID of the currently active (foreground) agent."""
        return getattr(self, "_foreground_uuid", None)

    @foreground_uuid.setter
    def foreground_uuid(self, uuid):
        """Set the UUID of the currently active (foreground) agent.

        Args:
            uuid: The UUID of the agent to make foreground, or None for primary.
        """
        self._foreground_uuid = uuid

    @property
    def foreground_coder(self):
        """Get the coder of the currently active (foreground) agent."""
        uuid = self.foreground_uuid
        if uuid is None or uuid == self.coder.uuid:
            return self.coder
        for info in self.sub_agents.values():
            if info.coder.uuid == uuid:
                return info.coder
        return self.coder

    def cleanup_all_for_parent(self) -> None:
        """Clean up all sub-agents when the parent session ends."""
        for uuid in list(self.sub_agents.keys()):
            self._cleanup_sub_agent(uuid)
        # Clean up lock pools to prevent memory leaks
        self._spawn_locks.pop(self.coder.uuid, None)
        self._conversation_locks.pop(self.coder.uuid, None)
        self._instances.pop(self.coder.uuid, None)
