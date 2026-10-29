"""Tests for cecli/helpers/agents/tree.py — agent visibility domains."""

import pytest

from cecli.helpers.agents.tree import AgentTree


@pytest.fixture(autouse=True)
def clean_tree():
    """Start and end every test with an empty tree."""
    AgentTree.clear()
    yield
    AgentTree.clear()


@pytest.fixture
def tree():
    """A primary/worker/workflow hierarchy.

    primary
    ├── worker
    │   └── grandchild
    └── wf:demo
        └── wf-child
    """
    AgentTree.register("primary", name="primary")
    AgentTree.register("worker", parent_uuid="primary", name="worker")
    AgentTree.register("grandchild", parent_uuid="worker", name="worker")
    AgentTree.register("wf:demo", parent_uuid="primary", name="wf:demo")
    AgentTree.register("wf-child", parent_uuid="wf:demo", name="worker")
    return AgentTree


class TestVisibility:
    """Workflow trees are isolated from the rest of the agent hierarchy."""

    def test_primary_sees_only_non_workflow_agents(self, tree):
        visible = tree.get_visible_uuids("primary")

        assert visible == {"primary", "worker", "grandchild"}
        assert not tree.is_visible("primary", "wf:demo")
        assert not tree.is_visible("primary", "wf-child")

    def test_workflow_root_keeps_primary_as_structural_parent(self, tree):
        """Isolation is visibility-only; the parent link is still the primary."""
        assert tree.get_parent("wf:demo") == "primary"
        assert "wf:demo" in tree.get_children("primary")
        assert not tree.is_visible("primary", "wf:demo")

    def test_regular_sub_agent_shares_primary_domain(self, tree):
        visible = tree.get_visible_uuids("worker")

        assert visible == {"primary", "worker", "grandchild"}
        assert not tree.is_visible("worker", "wf:demo")

    def test_workflow_root_sees_own_tree_only(self, tree):
        visible = tree.get_visible_uuids("wf:demo")

        assert visible == {"wf:demo", "wf-child"}
        assert not tree.is_visible("wf:demo", "primary")
        assert not tree.is_visible("wf:demo", "worker")

    def test_workflow_descendant_sees_same_tree(self, tree):
        visible = tree.get_visible_uuids("wf-child")

        assert visible == {"wf:demo", "wf-child"}
        assert not tree.is_visible("wf-child", "primary")

    def test_nested_workflow_is_a_separate_domain(self):
        AgentTree.register("primary", name="primary")
        AgentTree.register("wf:outer", parent_uuid="primary", name="wf:outer")
        AgentTree.register("outer-child", parent_uuid="wf:outer", name="worker")
        AgentTree.register("wf:inner", parent_uuid="outer-child", name="wf:inner")
        AgentTree.register("inner-child", parent_uuid="wf:inner", name="worker")

        assert AgentTree.get_visible_uuids("wf:outer") == {"wf:outer", "outer-child"}
        assert AgentTree.get_visible_uuids("outer-child") == {"wf:outer", "outer-child"}
        assert AgentTree.get_visible_uuids("wf:inner") == {"wf:inner", "inner-child"}


class TestMutations:
    """Registration, removal and replacement maintain the hierarchy."""

    def test_children_and_descendants(self, tree):
        assert set(tree.get_children("primary")) == {"worker", "wf:demo"}
        assert set(tree.get_descendants("primary")) == {
            "worker",
            "grandchild",
            "wf:demo",
            "wf-child",
        }

    def test_unregister_splices_children_onto_parent(self, tree):
        tree.unregister("wf:demo")

        assert tree.get_parent("wf-child") == "primary"
        assert tree.get_workflow_root("wf-child") == "wf:demo"
        assert tree.get_visible_uuids("wf-child") == {"wf-child"}

    def test_replace_moves_children_to_new_uuid(self, tree):
        tree.replace("worker", "worker-2")

        assert tree.get_parent("worker-2") == "primary"
        assert tree.get_parent("grandchild") == "worker-2"
        assert tree.get_parent("worker") is None
        assert tree.get_visible_uuids("worker-2") == {"primary", "worker-2", "grandchild"}

    def test_unknown_uuid_is_tolerated(self, tree):
        assert tree.get_parent("missing") is None
        assert tree.get_children("missing") == []
        assert tree.get_workflow_root("missing") is None
        assert tree.get_visible_uuids("missing") == {"primary", "worker", "grandchild"}
