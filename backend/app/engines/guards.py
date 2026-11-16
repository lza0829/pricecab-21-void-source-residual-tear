from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException

# 应用与作废互斥：同一进程内两类写操作共用一把锁。
# 拿到锁只是快路径；真正的正确性仍由事务内条件状态流转兜底（跨进程/跨连接同样成立）。
_write_lock = threading.RLock()


def write_lock_busy() -> bool:
    """True if an apply/void currently holds the global write lock (test/observability aid)."""
    acquired = _write_lock.acquire(blocking=False)
    if acquired:
        _write_lock.release()
        return False
    return True


@contextmanager
def ticket_write_guard(operation: str) -> Iterator[None]:
    """Serialize apply vs void. The loser gets an explicit 409, never a silent no-op."""
    acquired = _write_lock.acquire(blocking=False)
    if not acquired:
        other = "作废" if operation == "应用" else "应用"
        raise HTTPException(409, f"改价单{other}正在进行，{operation}被拒绝（应用与作废互斥）")
    try:
        yield
    finally:
        _write_lock.release()
