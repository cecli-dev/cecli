import weakref

from cecli.helpers.orchestration.environment import AgentExecutionEnv


class OrchestrationService:
    """
    Singleton-per-coder registry for AgentExecutionEnv instances.

    Uses weak references (keyed by coder and uuid) so that envs are
    automatically cleaned up when their owning coder is garbage collected.
    """

    _instances = weakref.WeakKeyDictionary()
    _uuid_index = weakref.WeakValueDictionary()

    @classmethod
    def get_instance(cls, coder) -> AgentExecutionEnv:
        if coder in cls._instances:
            return cls._instances[coder]

        if coder.uuid in cls._uuid_index:
            instance = cls._uuid_index[coder.uuid]
            cls._instances[coder] = instance
            return instance

        orchestration_config = {}
        if hasattr(coder, "agent_config"):
            orchestration_config = coder.agent_config.get("orchestration", {})

        instance = AgentExecutionEnv(coder, orchestration_config=orchestration_config)
        cls._instances[coder] = instance
        cls._uuid_index[coder.uuid] = instance
        return instance
