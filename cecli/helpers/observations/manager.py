import asyncio
from datetime import datetime

from cecli.helpers.conversation.service import ConversationService
from cecli.helpers.conversation.tags import MessageTag


class ObservationManager:
    _instances = {}

    @classmethod
    def get_instance(cls, coder):
        if coder.uuid not in cls._instances:
            cls._instances[coder.uuid] = cls(coder)
        return cls._instances[coder.uuid]

    def __init__(self, coder):
        self.coder = coder
        self.observation_threshold = max((coder.context_compaction_max_tokens or 0) / 3, 20000)
        self.reflection_threshold = self.observation_threshold * 2
        self.is_processing = False
        self._last_observed_index = 0
        self.observations = []  # Internal storage

    async def check_and_trigger(self):
        if self.is_processing:
            return

        manager = ConversationService.get_manager(self.coder)
        cur_messages = manager.get_messages_dict(MessageTag.CUR)

        # Calculate unobserved tokens
        unobserved = cur_messages[self._last_observed_index :]
        if not unobserved:
            return

        tokens = self.coder.summarizer.count_tokens(unobserved)

        if tokens >= self.observation_threshold:
            asyncio.create_task(self.run_observation(unobserved))
            self._last_observed_index = len(cur_messages)

        obs_tokens = self.coder.summarizer.count_tokens(
            [{"role": "user", "content": o} for o in self.observations]
        )

        if obs_tokens >= self.reflection_threshold:
            asyncio.create_task(self.run_reflection())

    async def run_observation(self, messages):
        self.is_processing = True
        try:
            manager = ConversationService.get_manager(self.coder)
            all_messages = manager.get_messages_dict()
            prompt = self.coder.gpt_prompts.observation_prompt
            observation = await self.coder.summarizer.summarize_all_as_text(
                all_messages, prompt, max_tokens=8192
            )
            self.observations.append(self.format_observation(observation))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.coder.io.tool_error(f"Error during observation: {e}")
        finally:
            self.is_processing = False

    async def run_reflection(self):
        self.is_processing = True
        try:
            # Prepare observations for the reflector
            obs_text = "\n".join([f"- {o}" for o in self.observations])

            # Use the Reflector to condense and get next steps
            reflection_prompt = self.coder.gpt_prompts.reflection_prompt
            reflection = await self.coder.summarizer.summarize_all_as_text(
                [{"role": "user", "content": obs_text}],
                reflection_prompt,
                max_tokens=8192,
            )

            # 1. Internal State Update: Store the condensed log internally
            self.observations = [reflection]

            self._last_observed_index = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.coder.io.tool_error(f"Error during reflection: {e}")
        finally:
            self.is_processing = False

    def reset(self):
        self.observations = []
        self._last_observed_index = 0

    def format_observation(self, text):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"[{timestamp}] {text}"
