from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .files import ConversationFiles
    from .integration import ConversationChunks
    from .manager import ConversationManager


class ConversationService:
    """Facade for accessing conversation components."""

    @staticmethod
    def get_manager(coder) -> "ConversationManager":
        from .manager import ConversationManager

        return ConversationManager.get_instance(coder)

    @staticmethod
    def get_chunks(coder) -> "ConversationChunks":
        from .integration import ConversationChunks

        return ConversationChunks.get_instance(coder)

    @staticmethod
    def get_files(coder) -> "ConversationFiles":
        from .files import ConversationFiles

        return ConversationFiles.get_instance(coder)

    @staticmethod
    def destroy_instances(coder_uuid: UUID):
        """Explicit cleanup for sub-agents."""
        from .files import ConversationFiles
        from .integration import ConversationChunks
        from .manager import ConversationManager

        ConversationManager.destroy_instance(coder_uuid)
        ConversationChunks.destroy_instance(coder_uuid)
        ConversationFiles.destroy_instance(coder_uuid)
