import hashlib
import json
from typing import Any, Dict


def stable_json(obj: Any) -> str:
    """Deterministic JSON serialization (sorted keys, compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_trace(trace: Dict[str, Any]) -> str:
    """SHA-256 digest of the trace dictionary."""
    payload = stable_json(trace).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
