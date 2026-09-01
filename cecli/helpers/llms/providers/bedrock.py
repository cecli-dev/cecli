"""AWS Bedrock provider adapter.

Bedrock authenticates every request with AWS Signature V4 (service
``bedrock``) using ambient AWS credentials — there is no API key. This adapter
resolves the region (``{region}`` placeholder in the api_base template is
substituted from the environment) and leaves auth to the bedrock domain, which
signs the final URL + body via :mod:`cecli.helpers.llms.aws_sigv4`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..aws_sigv4 import resolve_aws_region
from .base import ProviderAdapter


class BedrockProvider(ProviderAdapter):
    """Bedrock: SigV4-signed Converse requests, no API key."""

    provider: str = "bedrock"

    def resolve_api_base(self, resolved: Dict[str, Any]) -> str:
        """Substitute the ``{region}`` placeholder from the environment."""
        base = resolved["api_base"]

        if not resolved.get("aws_region"):
            region = resolve_aws_region()

            if region:
                resolved["aws_region"] = region
            elif "{region}" in base:
                raise ValueError(
                    "Bedrock requires an AWS region: set AWS_REGION_NAME or AWS_REGION."
                )

        region = resolved.get("aws_region")

        if region and "{region}" in base:
            return base.replace("{region}", region)

        return base

    def resolve_api_key(self, resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
        """Bedrock uses SigV4 (AWS env credentials); no API key is needed."""
        return None


__all__ = ["BedrockProvider"]
