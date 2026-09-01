"""Derive default per-model configuration from model metadata.

The model config package turns a flat litellm-style model metadata file into the
``{api, llm, agent}`` override blocks that :mod:`cecli.models` consumes,
mirroring the ``model-overrides`` section of ``.cecli.conf.yml``.
"""

from .pipeline import ModelConfigPipeline, get_default_config

__all__ = ["ModelConfigPipeline", "get_default_config"]
