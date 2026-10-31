"""Parent/child tree of tracked agent UUIDs.

The tree is the single source of truth for agent visibility. A workflow agent
(``wf:``) roots an isolated subtree: it cannot see the primary agent or any
agent outside its own subtree, and the primary cannot see it. All other agents
share the primary's visibility domain.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Set

_PARENT = "parent"
_CHILDREN = "children"
_NAME = "name"
_WORKFLOW = "workflow"


class AgentTree:
    """Process-wide tree of agent UUIDs used to resolve visibility.

    Nodes are registered when a coder is created and removed when it is reaped.
    Every lookup tolerates unknown UUIDs so callers never need to guard calls.
    """

    _nodes: Dict[str, Dict[str, Any]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    @classmethod
    def register(
        cls,
        agent_uuid: str,
        parent_uuid: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        """Add or reparent *agent_uuid*, inheriting its parent's workflow domain.

        A ``wf:`` name starts a new workflow domain rooted at the node itself.
        """
        agent_key = str(agent_uuid)
        parent_key = str(parent_uuid) if parent_uuid else None
        if parent_key == agent_key:
            parent_key = None

        with cls._lock:
            node = cls._ensure_node(agent_key)
            if name is not None:
                node[_NAME] = name

            workflow = agent_key if cls._is_workflow_name(node[_NAME]) else None
            if workflow is None and parent_key:
                parent = cls._nodes.get(parent_key)
                if parent is not None:
                    workflow = parent[_WORKFLOW]

            if node[_PARENT] != parent_key:
                cls._detach_locked(agent_key)
                node[_PARENT] = parent_key
                if parent_key:
                    cls._ensure_node(parent_key)[_CHILDREN].add(agent_key)

            cls._set_workflow_locked(agent_key, workflow)

    @classmethod
    def unregister(cls, agent_uuid: str) -> List[str]:
        """Remove *agent_uuid*, splicing its children onto its parent.

        Returns the UUIDs that were removed (currently just the node itself).
        """
        agent_key = str(agent_uuid)
        with cls._lock:
            node = cls._nodes.pop(agent_key, None)
            if node is None:
                return []

            parent_key = node[_PARENT]
            parent = cls._nodes.get(parent_key) if parent_key else None
            if parent is not None:
                parent[_CHILDREN].discard(agent_key)

            for child in list(node[_CHILDREN]):
                child_node = cls._nodes.get(child)
                if child_node is None:
                    continue
                child_node[_PARENT] = parent_key
                if parent is not None:
                    parent[_CHILDREN].add(child)

            return [agent_key]

    @classmethod
    def replace(cls, old_uuid: str, new_uuid: str) -> None:
        """Move *old_uuid*'s position and children onto *new_uuid*."""
        old_key = str(old_uuid)
        new_key = str(new_uuid)
        if old_key == new_key:
            return

        with cls._lock:
            old_node = cls._nodes.pop(old_key, None)
            if old_node is None:
                cls.register(new_key)
                return

            cls._detach_locked(new_key)
            new_node = cls._ensure_node(new_key)
            new_node[_NAME] = old_node[_NAME]
            new_node[_PARENT] = old_node[_PARENT]

            parent_key = old_node[_PARENT]
            if parent_key:
                parent = cls._nodes.get(parent_key)
                if parent is not None:
                    parent[_CHILDREN].discard(old_key)
                    parent[_CHILDREN].add(new_key)

            for child in list(old_node[_CHILDREN]):
                child_node = cls._nodes.get(child)
                if child_node is not None:
                    child_node[_PARENT] = new_key
                    new_node[_CHILDREN].add(child)

            cls._set_workflow_locked(new_key, old_node[_WORKFLOW])

    @classmethod
    def clear(cls) -> None:
        """Drop every node (used by tests and full session teardown)."""
        with cls._lock:
            cls._nodes.clear()

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #

    @classmethod
    def get_parent(cls, agent_uuid: str) -> Optional[str]:
        """Return the parent UUID of *agent_uuid*, or None if it is a root."""
        with cls._lock:
            node = cls._nodes.get(str(agent_uuid))
            return node[_PARENT] if node is not None else None

    @classmethod
    def get_children(cls, agent_uuid: str) -> List[str]:
        """Return the direct children of *agent_uuid*."""
        with cls._lock:
            node = cls._nodes.get(str(agent_uuid))
            return list(node[_CHILDREN]) if node is not None else []

    @classmethod
    def get_descendants(cls, agent_uuid: str) -> List[str]:
        """Return every descendant of *agent_uuid*, excluding itself."""
        with cls._lock:
            return cls._descendants_locked(str(agent_uuid), set())

    @classmethod
    def get_subtree(cls, agent_uuid: str) -> List[str]:
        """Return *agent_uuid* and all of its descendants."""
        with cls._lock:
            agent_key = str(agent_uuid)
            if agent_key not in cls._nodes:
                return []
            return [agent_key] + cls._descendants_locked(agent_key, {agent_key})

    @classmethod
    def get_workflow_root(cls, agent_uuid: str) -> Optional[str]:
        """Return the UUID of the workflow tree containing *agent_uuid*.

        Returns None for agents outside any workflow tree.
        """
        with cls._lock:
            node = cls._nodes.get(str(agent_uuid))
            return node[_WORKFLOW] if node is not None else None

    @classmethod
    def is_workflow_agent(cls, agent_uuid: str) -> bool:
        """Return whether *agent_uuid* is itself a workflow (``wf:``) agent."""
        with cls._lock:
            node = cls._nodes.get(str(agent_uuid))
            return node is not None and cls._is_workflow_name(node[_NAME])

    @classmethod
    def get_visible_uuids(cls, observer_uuid: str) -> Set[str]:
        """Return the UUIDs that *observer_uuid* is allowed to see.

        Agents outside a workflow domain see every non-workflow agent; agents
        inside one see only the members of that same workflow tree.
        """
        observer_key = str(observer_uuid)
        with cls._lock:
            node = cls._nodes.get(observer_key)
            workflow = node[_WORKFLOW] if node is not None else None

            if workflow is not None:
                visible = {
                    key for key, candidate in cls._nodes.items() if candidate[_WORKFLOW] == workflow
                }
                if workflow in cls._nodes:
                    visible.add(workflow)
                return visible

            return {key for key, candidate in cls._nodes.items() if candidate[_WORKFLOW] is None}

    @classmethod
    def is_visible(cls, observer_uuid: str, target_uuid: str) -> bool:
        """Return whether *observer_uuid* may see *target_uuid*."""
        return str(target_uuid) in cls.get_visible_uuids(observer_uuid)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def _ensure_node(cls, agent_key: str) -> Dict[str, Any]:
        node = cls._nodes.get(agent_key)
        if node is None:
            node = {_PARENT: None, _CHILDREN: set(), _NAME: None, _WORKFLOW: None}
            cls._nodes[agent_key] = node
        return node

    @classmethod
    def _detach_locked(cls, agent_key: str) -> None:
        node = cls._nodes.get(agent_key)
        if node is None:
            return

        parent_key = node[_PARENT]
        if not parent_key:
            return

        parent = cls._nodes.get(parent_key)
        if parent is not None:
            parent[_CHILDREN].discard(agent_key)
        node[_PARENT] = None

    @classmethod
    def _set_workflow_locked(cls, agent_key: str, workflow: Optional[str]) -> None:
        node = cls._nodes.get(agent_key)
        if node is None:
            return

        if cls._is_workflow_name(node[_NAME]):
            workflow = agent_key

        node[_WORKFLOW] = workflow
        for child in list(node[_CHILDREN]):
            cls._set_workflow_locked(child, workflow)

    @classmethod
    def _descendants_locked(cls, agent_key: str, seen: Set[str]) -> List[str]:
        node = cls._nodes.get(agent_key)
        if node is None:
            return []

        result = []
        for child in list(node[_CHILDREN]):
            if child in seen:
                continue
            seen.add(child)
            result.append(child)
            result.extend(cls._descendants_locked(child, seen))

        return result

    @staticmethod
    def _is_workflow_name(name: object) -> bool:
        return isinstance(name, str) and name.startswith("wf:")
