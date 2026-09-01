"""LiteLLM-shaped facade (compat surface).

The litellm wrapper implementation (``LazyLiteLLM`` proxy + litellm-shaped
shim dataclasses and exceptions) lives in
:mod:`cecli.helpers.llms.litellm_compat`; this module re-exports the
:data:`litellm` proxy so the rest of cecli can keep importing
``from cecli.llm import litellm`` unchanged.
"""

from cecli.helpers.llms.litellm_compat import litellm

__all__ = ["litellm"]
