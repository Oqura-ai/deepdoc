import uuid

LLM_CONFIG = {
    "provider": "openai",
    "model": "gpt-4o-mini", 
    "temperature": 0.5,
    # Let the provider SDK recover from temporary 429/5xx responses.
    "max_retries": 6,
    "timeout": 120.0,
}

THREAD_CONFIG = {
    # Section agents are parallel branches. Bound their concurrency so large
    # prompts do not arrive at the model provider in one token-heavy burst.
    "max_concurrency": 2,
    "configurable": {
        "thread_id": str(uuid.uuid4()),
        "max_queries": 3,
        "search_depth": 2,
        "num_reflections": 2,
        # Retrieve a shortlist for Jev instead of trusting one vector match.
        "n_points": 6,
        "evidence_keep_per_query": 3,
        # Starting thresholds; calibrate these on representative documents.
        "jev_relevance_threshold": 0.45,
        "jev_evidence_threshold": 0.55,
        "jev_contradiction_threshold": 0.70,
        "jev_injection_threshold": 0.70,
        "jev_reflection_threshold": 0.70,
    }
}
