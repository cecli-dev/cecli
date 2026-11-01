"""Token profiler for tracking and reporting LLM token timing metrics."""

import time
from typing import Optional


class TokenProfiler:
    """
    A profiler for tracking LLM token timing metrics with minimal interface.

    Handles all timing logic internally - just need to:
    1. Create with enable_printing flag
    2. Call start() when starting LLM request
    3. Call on_token() for each token received (auto-detects first token)
    4. Call set_token_counts() with input/output token counts
    5. Call get_report() to get formatted report (only if enabled)
    6. Call on_error() for error cases
    """

    def __init__(self, enable_printing: bool = False):
        """
        Initialize the token profiler.

        Args:
            enable_printing: If True, generate reports when get_report() is called
        """
        self._enabled = enable_printing
        self._start_time: Optional[float] = None
        self._first_token_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._has_seen_first_token: bool = False

    def start(self) -> None:
        """Start timing an LLM request."""
        self._start_time = time.time()
        self._first_token_time = None
        self._end_time = None
        self._has_seen_first_token = False
        self._input_tokens = 0
        self._output_tokens = 0

    def on_token(self) -> None:
        """
        Record that a token was received.
        Auto-detects if this is the first token.
        """
        if not self._enabled or not self._start_time:
            return

        if not self._has_seen_first_token:
            self._first_token_time = time.time()
            self._has_seen_first_token = True

    def set_token_counts(self, input_tokens: int, output_tokens: int) -> None:
        """
        Set the token counts for the request.

        Args:
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/generated tokens
        """
        if not self._enabled:
            return

        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def on_error(self) -> None:
        """Handle error case - finalize timing."""
        if not self._enabled or not self._start_time:
            return

        if self._end_time is None:
            self._end_time = time.time()

    def get_report(self) -> Optional[str]:
        """
        Get the compact speed report (only if enabled).

        Returns:
            Formatted report string, or None if disabled or no data
        """
        if not self._enabled or not self._start_time:
            return None

        # Calculate elapsed time
        if self._end_time is not None:
            elapsed = self._end_time - self._start_time
        else:
            elapsed = time.time() - self._start_time

        parts = []
        ttft = None
        response_time = elapsed

        if self._first_token_time is not None:
            ttft = self._first_token_time - self._start_time
            response_time = max(0.0, elapsed - ttft)
            parts.append(f"• {ttft:.2f}s")

        has_counts = self._input_tokens > 0 and self._output_tokens > 0

        # Prompt processing speed (based on time to first token)
        if ttft is not None and has_counts and ttft > 0:
            prompt_speed = self._input_tokens / ttft
            parts.append(f"↑ {_format_rate(prompt_speed)}")

        parts.append(f"◇ {response_time:.2f}s")

        # Token generation speed (based on response time by itself)
        if ttft is not None and has_counts and response_time > 0:
            generation_speed = self._output_tokens / response_time
            parts.append(f"↓ {generation_speed:.0f}")

        return " ".join(parts)

    def get_elapsed(self) -> Optional[float]:
        """
        Get the elapsed time for the current request.

        Returns:
            Elapsed time in seconds, or None if not started
        """
        if not self._start_time:
            return None

        if self._end_time is not None:
            return self._end_time - self._start_time

        return time.time() - self._start_time

    def add_to_usage_report(
        self, usage_report: Optional[str], input_tokens: int = 0, output_tokens: int = 0
    ) -> str:
        """
        Add speed report to usage_report and return the combined string.

        Args:
            usage_report: The existing usage report string
            input_tokens: Number of input/prompt tokens (optional, updates if provided)
            output_tokens: Number of output/generated tokens (optional, updates if provided)

        Returns:
            The usage report with speed info appended (if enabled), or original if disabled
        """
        if not usage_report:
            return usage_report

        # Update token counts if provided
        if input_tokens > 0 or output_tokens > 0:
            self.set_token_counts(input_tokens, output_tokens)

        speed_report = self.get_report()
        if speed_report:
            return f"{usage_report} {speed_report}"

        return usage_report


def _format_rate(value: float) -> str:
    """Format a tokens/sec rate compactly, truncating the decimal (6857 -> '6.8k')."""
    if value < 1000:
        return f"{value:.0f}"
    if value < 10000:
        return f"{int(value / 100) / 10:.1f}k"
    return f"{round(value / 1000)}k"
