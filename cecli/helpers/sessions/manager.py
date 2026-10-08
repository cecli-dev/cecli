"""``SessionManager`` - the facade over the session helper modules."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from . import layout, subagents
from .layout import SESSION_REFERENCE_TYPE
from .payload import apply_payload, build_payload
from .storage import (
    encrypt_settings,
    read_payload,
    resolve_payload_file,
    write_payload,
    write_reference,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages chat session saving, listing, and loading."""

    SESSION_REFERENCE_TYPE = SESSION_REFERENCE_TYPE

    def __init__(self, coder, io):
        self.coder = coder
        self.io = io

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #

    def save_session(self, session_name: str, output=True, to_agent_folder=False) -> bool:
        """Save the current chat session.

        ``to_agent_folder`` selects the auto-save shape: the payload is written
        into the coder's local agent folder and a reference document is written
        to the sessions directory (primary agent only). Otherwise the session is
        saved as a self-contained ``sessions/{name}.json`` file, or a
        ``sessions/{name}/`` folder bundle when the coder has sub-agents.
        """
        if not session_name:
            if output:
                self.io.tool_error("Please provide a session name.")

            return False

        session_name = session_name.replace(".json", "")

        try:
            if to_agent_folder:
                return self._save_to_agent_folder(session_name, output)

            return self._save_named(session_name, output)

        except Exception as e:
            self.io.tool_error(f"Error saving session: {e}")

            return False

    def _save_to_agent_folder(self, session_name: str, output: bool) -> bool:
        """Auto-save: payload in the agent folder, reference in sessions dir."""
        session_dir = layout.session_directory(self.coder)
        session_file = layout.entry_for(session_dir, session_name)
        if session_file.exists() and output:
            self.io.tool_warning(f"Session '{session_name}' already exists. Overwriting.")

        data_file = layout.agent_payload_file(self.coder, session_name)
        session_data = build_payload(self.coder, self.io, session_name, self._sub_agent_name())

        if not write_payload(self.coder, self.io, data_file, session_data):
            return False

        # Only the primary agent owns the sessions-directory reference;
        # sub-agents stop at their own payload so they cannot clobber the
        # pointer that auto-load resolves.
        if not session_data.get("agent_name") and not write_reference(
            self.coder, self.io, session_file, session_name, data_file
        ):
            return False

        if output:
            suffix = " (encrypted)" if encrypt_settings(self.coder)[0] else ""
            self.io.tool_output(f"Session saved: {data_file}{suffix}")

        return True

    def _save_named(self, session_name: str, output: bool) -> bool:
        """Explicit save: a folder bundle when sub-agents exist, else a file."""
        session_dir = layout.session_directory(self.coder)
        bundle = layout.bundle_dir(session_dir, session_name)

        if output and (layout.entry_for(session_dir, session_name).exists() or bundle.exists()):
            self.io.tool_warning(f"Session '{session_name}' already exists. Overwriting.")

        if subagents.live_sub_agents(self.coder):
            return self._save_bundle(session_dir, session_name, output)

        return self._save_file(session_dir, session_name, output)

    def _save_file(self, session_dir: Path, session_name: str, output: bool) -> bool:
        """Save a session without sub-agents as a single ``{name}.json`` file."""
        entry = layout.entry_for(session_dir, session_name)
        session_data = build_payload(self.coder, self.io, session_name, self._sub_agent_name())

        if not write_payload(self.coder, self.io, entry, session_data):
            return False

        # Drop a stale bundle saved under the same name so one entry stays canonical.
        shutil.rmtree(layout.bundle_dir(session_dir, session_name), ignore_errors=True)

        if output:
            suffix = " (encrypted)" if encrypt_settings(self.coder)[0] else ""
            self.io.tool_output(f"Session saved: {entry}{suffix}")

        return True

    def _save_bundle(self, session_dir: Path, session_name: str, output: bool) -> bool:
        """Save a session with sub-agents as a ``{name}/`` folder bundle."""
        bundle = layout.bundle_dir(session_dir, session_name)
        primary = bundle / layout.PRIMARY_PAYLOAD_NAME
        session_data = build_payload(self.coder, self.io, session_name, self._sub_agent_name())

        if not write_payload(self.coder, self.io, primary, session_data):
            return False

        subagents.save_sub_agents(self.coder, self.io, session_name, layout.sub_agents_dir(primary))

        # Drop a stale single-file entry saved under the same name.
        layout.entry_for(session_dir, session_name).unlink(missing_ok=True)

        if output:
            suffix = " (encrypted)" if encrypt_settings(self.coder)[0] else ""
            self.io.tool_output(f"Session saved: {bundle}{suffix}")

        return True

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #

    def list_sessions(self) -> List[Dict]:
        """List all saved sessions with metadata."""
        from .storage import describe_session

        session_dir = layout.session_directory(self.coder)
        entries = layout.discover_entries(session_dir)

        if not entries:
            self.io.tool_output("No saved sessions found.")

            return []

        sessions = []
        ordered = sorted(entries, key=lambda item: item[1].stat().st_mtime, reverse=True)
        for name, locator in ordered:
            try:
                info = describe_session(self.coder, self.io, name, locator)

            except Exception as e:
                self.io.tool_output(f"  {name} [error reading: {e}]")

                continue

            if info is not None:
                sessions.append(info)

        return sessions

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    async def load_session(self, session_identifier: str, switch=True, quiet: bool = False) -> bool:
        """Load a saved session by name or file path."""
        if not session_identifier:
            self.io.tool_error("Please provide a session name or file path.")

            return False

        session_file = self._find_session_file(session_identifier)
        if not session_file:
            return False

        data_file = resolve_payload_file(self.coder, self.io, session_file, quiet=quiet)
        if data_file is None:
            return False

        session_data = read_payload(self.coder, self.io, data_file, quiet=quiet)
        if session_data is None:
            return False

        if not isinstance(session_data, dict) or "version" not in session_data:
            if not quiet:
                self.io.tool_error("Invalid session format.")

            return False

        # Apply session data
        applied, loaded_edit_format = await self._apply_session_data(session_data, session_file)

        # A primary session may have sub-agents saved alongside it; restore the
        # whole agent tree rather than just the primary conversation.
        if applied and not session_data.get("agent_name"):
            await self._reload_sub_agents(data_file)

        if applied and switch:
            from cecli.commands import SwitchCoderSignal

            edit_format_to_switch_to = self.coder.edit_format
            if loaded_edit_format:
                edit_format_to_switch_to = loaded_edit_format
                self.coder.edit_format = loaded_edit_format

            raise SwitchCoderSignal(
                edit_format=edit_format_to_switch_to,
                from_coder=self.coder,
                summarize_from_coder=False,
                show_announcements=True,
            )

        return applied

    # ------------------------------------------------------------------ #
    # Sub-agent restore
    # ------------------------------------------------------------------ #

    async def _reload_sub_agents(self, data_file: Path) -> None:
        """Rebuild every sub-agent saved alongside a primary session payload."""
        payloads = layout.sub_agent_payloads(data_file)
        if not payloads:
            return

        from cecli.helpers.agents.service import AgentService

        service = AgentService.get_instance(self.coder)

        for sub_file in payloads:
            try:
                await self._reload_sub_agent(service, sub_file)

            except Exception as e:
                logger.warning("Failed to restore sub-agent from %s: %s", sub_file, e)
                self.io.tool_warning(f"Could not restore sub-agent from {sub_file}: {e}")

    async def _reload_sub_agent(self, service, sub_file: Path) -> None:
        """Spawn and restore a single sub-agent from its saved payload.

        Only sub-agents that were still relevant when the session was saved are
        rebuilt: independent agents are always restored, while a dependent agent
        is restored only if it had not finished or errored. The transient
        ``memorizer`` helper is never restored.
        """
        sub_data = self._read_session_payload(sub_file, quiet=True)
        if not isinstance(sub_data, dict):
            return

        if not subagents.should_restore_sub_agent(sub_data):
            return

        name = subagents.resolve_reload_agent_name(
            sub_data.get("agent_name") or "worker", sub_data.get("agent_root")
        )
        if not name:
            return

        independent = bool(sub_data.get("independent", True))

        new_coder, _info = await service.spawn(
            name, parent=self.coder, auto_reap=False, independent=independent
        )

        sub_manager = SessionManager(new_coder, self.io)
        applied, _edit_format = await sub_manager._apply_session_data(
            sub_data, sub_file, sub_agent=True
        )
        if not applied:
            logger.warning("Restored sub-agent '%s' but could not apply its saved state", name)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _find_session_file(self, session_identifier: str) -> Optional[Path]:
        """Find a session locator (single file or folder bundle) by name or path."""
        session_file = Path(session_identifier)
        if session_file.exists():
            return session_file

        session_dir = layout.session_directory(self.coder)

        if not session_identifier.endswith(".json"):
            session_file = layout.entry_for(session_dir, session_identifier)
            if session_file.exists():
                return session_file

            session_file = layout.bundle_dir(session_dir, session_identifier)
            if session_file.exists():
                return session_file

        session_file = session_dir / session_identifier
        if session_file.exists():
            return session_file

        self.io.tool_error(f"Session not found: {session_identifier}")
        self.io.tool_output("Use /list-sessions to see available sessions.")

        return None

    def _read_session_file(self, session_file: Path, quiet: bool = False) -> dict | None:
        """Resolve and read a session payload, following reference documents."""
        data_file = resolve_payload_file(self.coder, self.io, session_file, quiet=quiet)
        if data_file is None:
            return None

        return read_payload(self.coder, self.io, data_file, quiet=quiet)

    def _read_session_payload(self, data_file: Path, quiet: bool = False) -> dict | None:
        """Read a session payload file, decrypting it when necessary."""
        return read_payload(self.coder, self.io, data_file, quiet=quiet)

    def _sub_agent_name(self) -> Optional[str]:
        """Return this coder's sub-agent type, or ``None`` for the primary agent."""
        return subagents.detect_agent_name(self.coder)

    async def _apply_session_data(
        self, session_data: Dict, session_file: Path, sub_agent: bool = False
    ) -> tuple[bool, Optional[str]]:
        """Apply a session payload to this manager's coder."""
        return await apply_payload(
            self.coder, self.io, session_data, session_file, sub_agent=sub_agent
        )
