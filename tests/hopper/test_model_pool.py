from cecli.hopper.router import ModelPoolEntry, resolve_model_pool


def test_resolve_pool_priority_order():
    pool = [
        ModelPoolEntry(model="ollama_chat/fast-a", tier="fast", enabled=False),
        ModelPoolEntry(model="ollama_chat/fast-b", tier="fast", enabled=True),
        ModelPoolEntry(model="ollama_chat/code-x", tier="code", enabled=True),
    ]
    resolved = resolve_model_pool(
        pool,
        session_code="ollama_chat/session",
        fallback_fast="",
        fallback_code=None,
    )
    assert resolved.fast == "ollama_chat/fast-b"
    assert resolved.code == "ollama_chat/code-x"


def test_empty_code_row_uses_session():
    pool = [
        ModelPoolEntry(model="ollama_chat/fast", tier="fast", enabled=True),
        ModelPoolEntry(model="", tier="code", enabled=True),
    ]
    resolved = resolve_model_pool(
        pool,
        session_code="ollama_chat/session",
    )
    assert resolved.fast == "ollama_chat/fast"
    assert resolved.code == "ollama_chat/session"
