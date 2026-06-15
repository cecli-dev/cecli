from cecli.hopper.router import (
    ModelPoolEntry,
    ModelRouterConfig,
    RouteTurnContext,
    classify_prompt,
    context_exceeds_fast_model_limit,
    escalation_target,
    estimate_message_tokens,
    estimate_prompt_tokens,
    resolve_model_pool,
    should_escalate_code_turn,
    should_escalate_fast_turn,
    thinking_for_role,
)


def test_from_payload_normalizes_heavy_keep_alive_zero():
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/small",
            "heavy_model": "ollama_chat/big",
            "keep_alive_heavy": 0,
        }
    )
    assert cfg is not None
    assert cfg.keep_alive_heavy == -1


def test_from_payload_think_and_code_models():
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/fast",
            "code_model": "ollama_chat/code",
            "think_model": "ollama_chat/think",
            "model_pool": [
                {"model": "ollama_chat/fast", "tier": "fast", "enabled": True},
                {"model": "ollama_chat/code", "tier": "code", "enabled": True},
                {"model": "ollama_chat/think", "tier": "think", "enabled": True},
            ],
        }
    )
    assert cfg is not None
    assert cfg.resolved_code_model == "ollama_chat/code"
    assert cfg.resolved_think_model == "ollama_chat/think"


def test_classify_low_tokens_fast_keyword():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/big",
    )
    d = classify_prompt(
        "Rename the button label to Save",
        message_tokens=500,
        router=router,
        code_model_name="ollama_chat/big",
    )
    assert d.role == "fast"
    assert d.model_name == "ollama_chat/small"
    assert d.enable_thinking is False


def test_classify_architect_think():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
    )
    d = classify_prompt(
        "Refactor the race condition in the session pool",
        message_tokens=800,
        router=router,
        code_model_name="ollama_chat/code",
    )
    assert d.role == "think"
    assert d.model_name == "ollama_chat/think"
    assert d.enable_thinking is True


def test_classify_architect_falls_back_to_code_without_think():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
    )
    d = classify_prompt(
        "Refactor the race condition in the session pool",
        message_tokens=800,
        router=router,
        code_model_name="ollama_chat/code",
    )
    assert d.role == "code"
    assert "think_unconfigured" in " ".join(d.reasons)


def test_classify_agent_command_code():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/big",
    )
    d = classify_prompt(
        "/agent explore the repo and update the checklist",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/big",
    )
    assert d.role == "code"
    assert "slash:/agent" in d.reasons


def test_classify_implement_turn_code():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
    )
    d = classify_prompt(
        "Implement only implementation task 1.2 per the injected spec.",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/code",
        turn=RouteTurnContext(implement_turn=True),
    )
    assert d.role == "code"
    assert d.model_name == "ollama_chat/code"


def test_classify_inject_todo_spec_think():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
    )
    d = classify_prompt(
        "Continue planning the auth module",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/code",
        turn=RouteTurnContext(inject_todo_spec=True),
    )
    assert d.role == "think"


def test_classify_high_message_tokens_think_without_code_task():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
        token_heavy_min=12_000,
    )
    d = classify_prompt(
        "summarize the session so far",
        message_tokens=15_000,
        router=router,
        code_model_name="ollama_chat/code",
    )
    assert d.role == "think"
    assert "msg_tokens>=" in d.reasons[0]


def test_classify_high_message_tokens_code_task():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
        token_heavy_min=12_000,
    )
    d = classify_prompt(
        "implement the whole module",
        message_tokens=15_000,
        router=router,
        code_model_name="ollama_chat/code",
    )
    assert d.role == "code"


def test_files_in_chat_do_not_force_code_when_under_fast_window():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/big",
    )
    msg = "I'd like to add @ references like we have for /add with chips"
    message_tokens = estimate_message_tokens(msg)
    context_tokens = estimate_prompt_tokens(msg, files_in_chat=4)
    assert context_tokens > message_tokens
    assert message_tokens < router.token_fast_max
    assert not context_exceeds_fast_model_limit(
        context_tokens, router.fast_model, fast_max_input=32_768
    )[0]
    d = classify_prompt(
        msg,
        message_tokens=message_tokens,
        context_tokens=context_tokens,
        router=router,
        code_model_name="ollama_chat/big",
    )
    assert d.role == "fast"
    assert d.estimated_tokens == context_tokens


def test_context_exceeds_fast_model_limit():
    exceeds, limit = context_exceeds_fast_model_limit(
        17_670,
        "ollama_chat/deepseek-coder:6.7b",
        fast_max_input=16_384,
    )
    assert exceeds is True
    assert limit == 16_384
    fits, _ = context_exceeds_fast_model_limit(
        10_000,
        "ollama_chat/deepseek-coder:6.7b",
        fast_max_input=16_384,
    )
    assert fits is False


def test_classify_routes_code_when_context_exceeds_fast_window():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/deepseek-coder:6.7b",
        code_model="ollama_chat/qwen3.6:27b-q4_K_M",
    )
    msg = "tweak the chat panel label"
    message_tokens = estimate_message_tokens(msg)
    assert message_tokens < router.token_fast_max
    d = classify_prompt(
        msg,
        message_tokens=message_tokens,
        context_tokens=17_670,
        router=router,
        code_model_name="ollama_chat/qwen3.6:27b-q4_K_M",
        fast_max_input=16_000,
    )
    assert d.role == "code"
    assert d.model_name == "ollama_chat/qwen3.6:27b-q4_K_M"
    assert any("fast_max=" in r for r in d.reasons)


def test_fast_keyword_loses_to_context_overflow():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/deepseek-coder:6.7b",
        code_model="ollama_chat/big",
    )
    d = classify_prompt(
        "Rename the button label to Save",
        message_tokens=200,
        context_tokens=20_000,
        router=router,
        code_model_name="ollama_chat/big",
        fast_max_input=16_000,
    )
    assert d.role == "code"


def test_code_task_middle_band_defaults_code():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/big",
    )
    d = classify_prompt(
        "implement the login form",
        message_tokens=800,
        router=router,
        code_model_name="ollama_chat/big",
    )
    assert d.role == "code"
    assert "code_task" in d.reasons


def test_escalate_when_fast_no_edits():
    router = ModelRouterConfig(enabled=True, fast_model="a", code_model="b")
    decision = classify_prompt(
        "implement the login form",
        message_tokens=800,
        router=router,
        code_model_name="b",
        force_tier="fast",
    )
    assert should_escalate_fast_turn(
        decision,
        router=router,
        user_message="implement the login form",
        edited_files=[],
        assistant_text="ok",
    )


def test_escalate_code_to_think():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="a",
        code_model="b",
        think_model="c",
    )
    decision = classify_prompt(
        "Refactor the auth layer",
        message_tokens=800,
        router=router,
        code_model_name="b",
        force_tier="code",
    )
    assert should_escalate_code_turn(
        decision,
        router=router,
        user_message="Refactor the auth layer",
        edited_files=[],
        assistant_text="Here is a plan",
    )


def test_escalation_target_chain():
    fast = classify_prompt(
        "fix",
        message_tokens=100,
        router=ModelRouterConfig(enabled=True, fast_model="a", code_model="b", think_model="c"),
        code_model_name="b",
        force_tier="fast",
    )
    assert escalation_target(fast) == "code"
    code = classify_prompt(
        "fix",
        message_tokens=100,
        router=ModelRouterConfig(enabled=True, fast_model="a", code_model="b", think_model="c"),
        code_model_name="b",
        force_tier="code",
    )
    assert escalation_target(code) == "think"


def test_escalate_on_context_limit_tool_error():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/deepseek-coder:6.7b",
        code_model="ollama_chat/big",
    )
    decision = classify_prompt(
        "tweak git tab",
        message_tokens=200,
        context_tokens=5_000,
        router=router,
        code_model_name="ollama_chat/big",
        force_tier="fast",
    )
    err = (
        "Your estimated chat context of 32,672 tokens exceeds the "
        "16,384 token limit for ollama_chat/deepseek-coder:6.7b!"
    )
    assert should_escalate_fast_turn(
        decision,
        router=router,
        user_message="tweak git tab",
        edited_files=[],
        assistant_text="",
        had_tool_error=True,
        tool_error_text=err,
    )


def test_lint_in_long_message_not_used_when_routing_short_intent():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/big",
    )
    preamble = "## Spec-focus mode\nEARS lint requirements\n" + ("x" * 5000)
    short = "In the Git tab, add revert and open-in-editor cues."
    d = classify_prompt(
        short,
        message_tokens=estimate_message_tokens(short),
        context_tokens=estimate_prompt_tokens(preamble + short, files_in_chat=0),
        router=router,
        code_model_name="ollama_chat/big",
    )
    assert d.role != "fast" or "keyword:lint" not in " ".join(d.reasons)


def test_estimate_tokens_with_files_capped():
    bare = estimate_prompt_tokens("hello")
    with_files = estimate_prompt_tokens("hello", files_in_chat=10)
    assert with_files > bare
    assert with_files <= bare + 2000


def test_thinking_for_role():
    assert thinking_for_role("think", "ollama_chat/deepseek-r1:32b") is True
    assert thinking_for_role("code", "ollama_chat/qwen3.6:27b") is False


def test_pool_entry_overrides_role_thinking():
    pool = [
        ModelPoolEntry(
            model="ollama_chat/custom",
            tier="code",
            enabled=True,
            enable_thinking=True,
        )
    ]
    assert thinking_for_role("code", "ollama_chat/custom", pool=pool) is True
    assert thinking_for_role("code", "ollama_chat/other", pool=pool) is False


def test_resolve_model_pool_roles():
    pool = [
        ModelPoolEntry(model="ollama_chat/fast-a", tier="fast", enabled=True),
        ModelPoolEntry(model="", tier="code", enabled=True),
        ModelPoolEntry(model="ollama_chat/r1", tier="think", enabled=True),
    ]
    resolved = resolve_model_pool(
        pool,
        session_code="ollama_chat/session",
        fallback_fast="",
    )
    assert resolved.fast == "ollama_chat/fast-a"
    assert resolved.code == "ollama_chat/session"
    assert resolved.think == "ollama_chat/r1"


def test_from_payload_parses_hopper_extra_params():
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/fast",
            "code_model": "ollama_chat/code",
            "model_pool": [
                {
                    "model": "ollama_chat/code",
                    "tier": "code",
                    "enabled": True,
                    "extra_params": {"top_p": 0.85},
                }
            ],
        }
    )
    assert cfg is not None
    assert cfg.model_pool[0].extra_params == {"top_p": 0.85}


def test_pool_prefers_think_when_think_above_code():
    from cecli.hopper.router import pool_prefers_think

    pool = [
        ModelPoolEntry(model="ollama_chat/r1:32b", tier="think", enabled=True),
        ModelPoolEntry(model="ollama_chat/qwen3:27b", tier="code", enabled=True),
        ModelPoolEntry(model="ollama_chat/small", tier="fast", enabled=True),
    ]
    assert pool_prefers_think(pool) is True


def test_pool_prefers_think_false_when_code_above_think():
    from cecli.hopper.router import pool_prefers_think

    pool = [
        ModelPoolEntry(model="ollama_chat/qwen3:27b", tier="code", enabled=True),
        ModelPoolEntry(model="ollama_chat/r1:32b", tier="think", enabled=True),
        ModelPoolEntry(model="ollama_chat/small", tier="fast", enabled=True),
    ]
    assert pool_prefers_think(pool) is False


def test_pool_prefers_think_false_when_no_think():
    from cecli.hopper.router import pool_prefers_think

    pool = [
        ModelPoolEntry(model="ollama_chat/qwen3:27b", tier="code", enabled=True),
        ModelPoolEntry(model="ollama_chat/small", tier="fast", enabled=True),
    ]
    assert pool_prefers_think(pool) is False


def test_prefer_think_routes_agent_to_think():
    """Agent turns always use code model (tool-capable) even with prefer_think."""
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
        prefer_think=True,
    )
    d = classify_prompt(
        "/agent explore the repo",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/code",
    )
    assert d.role == "code"
    assert d.model_name == "ollama_chat/code"
    assert "slash:/agent" in d.reasons


def test_prefer_think_routes_implement_turn_to_think():
    """Implement turns always use code model (tool-capable) even with prefer_think."""
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        think_model="ollama_chat/think",
        prefer_think=True,
    )
    d = classify_prompt(
        "implement the EncryptedStorageRepository",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/code",
        turn=RouteTurnContext(implement_turn=True),
    )
    assert d.role == "code"
    assert d.model_name == "ollama_chat/code"
    assert "implement_turn" in d.reasons


def test_prefer_think_falls_back_to_code_without_think_model():
    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/small",
        code_model="ollama_chat/code",
        prefer_think=True,
    )
    d = classify_prompt(
        "/agent explore the repo",
        message_tokens=400,
        router=router,
        code_model_name="ollama_chat/code",
    )
    # No think model configured; falls back to code despite prefer_think
    assert d.role == "code"
    assert "prefer_think" not in d.reasons


def test_from_payload_derives_prefer_think_from_pool_order():
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/fast",
            "code_model": "ollama_chat/code",
            "think_model": "ollama_chat/think",
            "model_pool": [
                {"model": "ollama_chat/think", "tier": "think", "enabled": True},
                {"model": "ollama_chat/code", "tier": "code", "enabled": True},
                {"model": "ollama_chat/fast", "tier": "fast", "enabled": True},
            ],
        }
    )
    assert cfg is not None
    assert cfg.prefer_think is True


def test_from_payload_no_prefer_think_when_code_first():
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/fast",
            "code_model": "ollama_chat/code",
            "think_model": "ollama_chat/think",
            "model_pool": [
                {"model": "ollama_chat/code", "tier": "code", "enabled": True},
                {"model": "ollama_chat/think", "tier": "think", "enabled": True},
                {"model": "ollama_chat/fast", "tier": "fast", "enabled": True},
            ],
        }
    )
    assert cfg is not None
    assert cfg.prefer_think is False



def test_router_lane_fast_prompt_routes_fast_with_think_enabled():
    """E2E router lane contract (regression for e2e/router-llm.spec.ts).

    Hopper order fast → code → think (think last) ⇒ ``prefer_think`` is False, so a
    trivial fast-keyword prompt must route to the fast tier even though a think model
    is enabled. The e2e ``fast tier routes to Fighter pilot`` test asserts exactly this;
    if routing here returned ``think`` the e2e would fail (and previously did, when the
    fast model was cold-evicted and the turn escalated fast→code→think).
    """
    cfg = ModelRouterConfig.from_payload(
        {
            "enabled": True,
            "fast_model": "ollama_chat/qwen2.5-coder:7b",
            "code_model": "ollama_chat/qwen3.6:27b-q4_K_M",
            "think_model": "ollama_chat/deepseek-r1:32b",
            "model_pool": [
                {"model": "ollama_chat/qwen2.5-coder:7b", "tier": "fast", "enabled": True},
                {"model": "ollama_chat/qwen3.6:27b-q4_K_M", "tier": "code", "enabled": True},
                {"model": "ollama_chat/deepseek-r1:32b", "tier": "think", "enabled": True},
            ],
        }
    )
    assert cfg is not None
    assert cfg.prefer_think is False
    d = classify_prompt(
        'Suggest a better button label than "Start" in one sentence only. '
        "No code blocks, no file edits.",
        message_tokens=30,
        router=cfg,
        code_model_name="ollama_chat/qwen3.6:27b-q4_K_M",
        think_model_name="ollama_chat/deepseek-r1:32b",
    )
    assert d.role == "fast", d.reasons
    assert d.model_name == "ollama_chat/qwen2.5-coder:7b"
