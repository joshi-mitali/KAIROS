"""KAIROS Memory MCP Package.
Provides persistent, recency-weighted memory for quantitative equity research,
trading proposals, and historical trade execution outcomes.
Supports PostgreSQL + pgvector with seamless, truthful fallback to local-first SQLite + Vector search.
"""

from kairos.memory.models import (
    MemoryRecord,
    MemorySearchResult,
    RecordType,
    TradeOutcome,
)
from kairos.memory.recency import (
    calculate_composite_score,
    calculate_recency_weight,
    calculate_relevance_score,
)
from kairos.memory.storage import (
    MemoryManager,
    PostgresMemoryBackend,
    SQLiteMemoryBackend,
    get_memory_manager,
)

__all__ = [
    "RecordType",
    "TradeOutcome",
    "MemoryRecord",
    "MemorySearchResult",
    "calculate_recency_weight",
    "calculate_relevance_score",
    "calculate_composite_score",
    "PostgresMemoryBackend",
    "SQLiteMemoryBackend",
    "MemoryManager",
    "get_memory_manager",
]

