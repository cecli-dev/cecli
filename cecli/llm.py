import asyncio
import contextlib
import importlib
import os
import warnings
from collections.abc import Coroutine

from cecli.dump import dump  # noqa: F401
from cecli.helpers.model_providers import ensure_litellm_providers_registered

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

SITE_URL = "https://cecli.dev"
APP_NAME = "cecli"

os.environ["OR_SITE_URL"] = SITE_URL
os.environ["OR_APP_NAME"] = APP_NAME
os.environ["LITELLM_MODE"] = "PRODUCTION"

# `import litellm` takes 1.5 seconds, defer it!

VERBOSE = False


class LazyLiteLLM:
    _lazy_module = None
    _lazy_classes = {
        "ModelResponse": "ModelResponse",
        "Choices": "Choices",
        "Message": "Message",
    }

    def __getattr__(self, name):
        # Check if the requested attribute is one of the explicitly lazy-loaded classes
        if name in self._lazy_classes:
            self._load_litellm()
            class_name = self._lazy_classes[name]
            return getattr(self._lazy_module, class_name)

        # Handle other attributes (like `acompletion`) as before
        if name == "_lazy_module":
            return super()
        self._load_litellm()
        return getattr(self._lazy_module, name)

    def _load_litellm(self):
        if self._lazy_module is not None:
            return

        self._lazy_module = importlib.import_module("litellm")
        self._lazy_module.disable_streaming_logging = True
        self._lazy_module.suppress_debug_info = True
        self._lazy_module.set_verbose = False
        self._lazy_module.drop_params = True
        self._lazy_module._logging._disable_debugging()

        # Make sure JSON-based OpenAI-compatible providers are registered
        ensure_litellm_providers_registered()

        # Patch GLOBAL_LOGGING_WORKER to avoid event loop binding issues
        # See: https://github.com/BerriAI/litellm/issues/16518
        # See: https://github.com/BerriAI/litellm/issues/14521
        try:
            from litellm.litellm_core_utils import logging_worker
        except ImportError:
            # Module didn't exist before litellm 1.76.0
            # https://github.com/BerriAI/litellm/pull/13905
            pass
        else:

            class NoOpLoggingWorker:
                """No-op worker that executes callbacks immediately without queuing."""

                def start(self) -> None:
                    pass

                def enqueue(self, coroutine: Coroutine) -> None:
                    # Execute immediately in current loop instead of queueing,
                    # and do nothing if there's no current loop
                    with contextlib.suppress(RuntimeError):
                        # This logging task is fire-and-forget
                        asyncio.create_task(coroutine)

                def ensure_initialized_and_enqueue(self, async_coroutine: Coroutine) -> None:
                    self.enqueue(async_coroutine)

                async def stop(self) -> None:
                    pass

                async def flush(self) -> None:
                    pass

                async def clear_queue(self) -> None:
                    pass

            logging_worker.GLOBAL_LOGGING_WORKER = NoOpLoggingWorker()


litellm = LazyLiteLLM()

__all__ = [litellm]
