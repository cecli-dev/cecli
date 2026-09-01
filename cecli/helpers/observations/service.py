import asyncio
import weakref
from datetime import datetime

from cecli.helpers.conversation.service import ConversationService


class ObservationService:
    _instances = weakref.WeakKeyDictionary()  # coder -> ObservationService (ties lifetime)
    _uuid_index = weakref.WeakValueDictionary()  # uuid -> ObservationService (secondary lookup)

    @classmethod
    def get_instance(cls, coder):
        # Fast path: exact coder object already registered
        if coder in cls._instances:
            return cls._instances[coder]

        # Fallback: child coder inheriting parent's uuid
        if coder.uuid in cls._uuid_index:
            instance = cls._uuid_index[coder.uuid]

            if instance.get_coder() is not coder:
                instance.coder = weakref.ref(coder)

            cls._instances[coder] = instance

            return instance

        # New coder with a new uuid — create fresh
        instance = cls(coder)
        cls._instances[coder] = instance
        cls._uuid_index[coder.uuid] = instance
        return instance

    def __init__(self, coder):
        self.coder = weakref.ref(coder)
        self.observation_threshold = max((coder.context_compaction_max_tokens or 0) / 3, 20000)
        self.reflection_threshold = self.observation_threshold * 2
        self.is_processing = False
        self.is_reflecting = False
        self._last_observed_index = 0
        self.observations = []  # Internal storage

    def get_coder(self):
        return self.coder()

    async def check_and_trigger(self):
        if self.is_processing:
            return

        coder = self.get_coder()
        if coder is None:
            return

        cur_messages = ConversationService.get_manager(coder).get_messages_dict()

        # Calculate unobserved tokens
        unobserved = cur_messages[self._last_observed_index :]
        current_index = len(cur_messages)

        if not unobserved:
            return

        tokens = coder.summarizer.count_tokens(unobserved)

        if (
            tokens >= self.observation_threshold
            and (not self._last_observed_index or current_index - self._last_observed_index >= 10)
        ) or tokens >= 2 * self.observation_threshold:
            asyncio.create_task(self.run_observation(unobserved))
            self._last_observed_index = len(cur_messages)

    async def run_observation(self, messages):
        coder = self.get_coder()
        if coder is None:
            return

        self.is_processing = True
        try:
            # Use the fully-formatted message dict (system prompt, rules, repo map,
            # file contexts, and conversation) from format_chat_chunks() so that
            # background observation requests share the same prompt prefix as the
            # main chat and get a higher cache hit ratio. Pass a copy because
            # summarize_all_as_text() appends the observation prompt in place.
            all_messages = list(coder.format_chat_chunks())
            prompt = coder.gpt_prompts.observation_prompt
            if self.observations:
                prompt += "\n\n---\nCURRENT OBSERVATIONS (Do not duplicate):\n\n"
                prompt += "\n".join(self.observations)

            observation = await coder.summarizer.summarize_all_as_text(
                all_messages, prompt, max_tokens=8192, coder=coder
            )
            self.observations.append(self.format_observation(observation))

            obs_tokens = coder.summarizer.count_tokens(
                [{"role": "user", "content": o} for o in self.observations]
            )

            if obs_tokens >= self.reflection_threshold:
                await self.run_reflection()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            coder.io.tool_error(f"Error during observation: {e}")
        finally:
            self.is_processing = False

    async def run_reflection(self):
        coder = self.get_coder()
        if coder is None:
            return

        if self.is_reflecting:
            return

        self.is_reflecting = True
        try:
            if not self.observations:
                return

            # Prepare observations for the reflector
            obs_text = "\n".join([f"- {o}" for o in self.observations])

            # Use the Reflector to condense and get next steps
            reflection_prompt = coder.gpt_prompts.reflection_prompt
            reflection = await coder.summarizer.summarize_all_as_text(
                [{"role": "user", "content": obs_text}],
                reflection_prompt,
                max_tokens=8192,
                coder=coder,
            )

            # 1. Internal State Update: Store the condensed log internally
            self.observations = [reflection]

            self._last_observed_index = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            coder.io.tool_error(f"Error during reflection: {e}")
        finally:
            self.is_reflecting = False

    def reset(self):
        self.observations = []
        self._last_observed_index = 0

    def reset_index(self):
        self._last_observed_index = 0

    def format_observation(self, text):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"[{timestamp}]\n{text}"
