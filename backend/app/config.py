from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "pricecab.db"
PROJECT = "pricecab"
PROJECT_NAME = "价签柜"

# 已应用改价单的“命运策略”——全局唯一，互斥，不提供切换。
# applied_rollback：允许作废已应用单；作废时按价格历史回退该单写入的价签，
# 来源单标记作废，历史只追加只读审计，不删除任何历史行，不回改应用批次原计数。
# 另一种策略（仅允许作废 scheduled、applied 拒绝作废）在本系统中不存在并存实现。
APPLIED_VOID_POLICY = "applied_rollback"
APPLIED_VOID_POLICY_LABEL = "允许作废已应用：按价格历史回退价签，历史只读留痕，批次原计数不变"
