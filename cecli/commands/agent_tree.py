from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.helpers.agents.service import AgentService, SubAgentInfo, SubAgentStatus
from cecli.helpers.agents.tree import AgentTree


class TreeNode:
    """A node in the agent hierarchy tree."""

    def __init__(self, agent_info: SubAgentInfo):
        self.agent_info = agent_info
        self.children: List[TreeNode] = []

    def add_child(self, child_node: "TreeNode"):
        self.children.append(child_node)


class AgentTreeCommand(BaseCommand):
    """Command to display the hierarchy of active agents."""

    NORM_NAME = "agent-tree"
    DESCRIPTION = "Display the hierarchy of active agents."

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the /agent-tree command."""
        agent_service = AgentService.get_instance(coder)
        if not agent_service:
            io.tool_output("Agent service not available.")
            return

        # Collect all agents: primary coder + sub-agents from sub_agents dict
        primary_coder = agent_service.coder
        primary_uuid = str(primary_coder.uuid)
        primary_info = SubAgentInfo(
            name="primary",
            coder=primary_coder,
            parent_uuid=str(primary_coder.parent_uuid or ""),
            status=SubAgentStatus.RUNNING,
        )
        all_infos: List[SubAgentInfo] = [primary_info]

        # Sub-agents from the service's sub_agents dict
        for info in agent_service.sub_agents.values():
            if info and info.coder:
                all_infos.append(info)

        if len(all_infos) <= 1:
            io.tool_output("No active sub-agents found.")
            return

        # The shared tree is process-wide, so structure the display from the
        # primary's subtree only.
        infos_by_uuid = {str(info.coder.uuid): info for info in all_infos}
        subtree = AgentTree.get_subtree(primary_uuid)
        if not subtree:
            subtree = list(infos_by_uuid)

        root_nodes = cls._build_tree(primary_uuid, infos_by_uuid, subtree)
        tree_output = cls._render_tree(root_nodes)
        io.tool_output(tree_output)

    @classmethod
    def _build_tree(cls, root_uuid, infos, subtree_uuids) -> List[TreeNode]:
        """Build the display tree from the shared :class:`AgentTree`."""
        nodes = {uuid: TreeNode(infos[uuid]) for uuid in subtree_uuids if uuid in infos}
        root = nodes.get(root_uuid)
        if root is None:
            return []

        for uuid, node in nodes.items():
            if uuid == root_uuid:
                continue

            parent = nodes.get(AgentTree.get_parent(uuid))
            if parent is not None:
                parent.add_child(node)
            else:
                # Keep a node reachable even if its parent fell outside the
                # session subtree (e.g. a spliced node left over).
                root.add_child(node)

        return [root]

    @classmethod
    def _render_tree(cls, nodes: List[TreeNode]) -> str:
        """Render the agent tree to a string."""
        output = []

        def render_node(node: TreeNode, prefix: str = "", is_last: bool = True):
            connector = "└── " if is_last else "├── "
            output.append(
                f"{prefix}{connector}{node.agent_info.name}"
                f" ({node.agent_info.status.value})"
                f" - {str(node.agent_info.coder.uuid)}"
            )

            child_prefix = prefix + ("    " if is_last else "│   ")
            for i, child in enumerate(node.children):
                render_node(child, child_prefix, i == len(node.children) - 1)

        for i, node in enumerate(nodes):
            render_node(node, is_last=i == len(nodes) - 1)

        return "\n".join(output)
