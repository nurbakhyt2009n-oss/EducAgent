"""Идентификаторы вида `att_01JB7J...`: префикс типа + ULID.

ULID сортируется по времени создания, поэтому записи в журнале попыток
можно упорядочивать прямо по id.
"""

import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None) -> str:
    """26 символов: 48 бит времени в миллисекундах + 80 случайных бит."""
    ts = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    value = (ts << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def new_id(prefix: str) -> str:
    """new_id("att") → "att_01JB7J..."."""
    return f"{prefix}_{ulid()}"
