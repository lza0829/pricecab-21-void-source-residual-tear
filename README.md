# 06-pricecab（价签柜）

Pricecab — 改价单按预约时刻生效，现行价签可查，并与销售夹具对账。

与 Feedstitch（多源归并）、Batchgate（作业编排）、Syncledger（双端对账）、Changecast（CDC 投影）、Proofpack（采样放行）主链路不同。  
不是电商订单/购物车，不是仓库进出库 CRUD，不是考勤 OA。夹具全本地。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5600 |
| API | http://localhost:10600 |

## 主链（0-1）

选商品建改价单（写明生效时刻）→ 拨业务钟或点「应用到期」→ 现行价签更新 → 销售对账看一致/不一致

## 作废与已应用单命运策略

误建或需要纠偏的改价单可作废旧。系统对「已应用单的命运」只实现**一种、全局互斥**的策略，不存在两种命运并存：

- 策略 `applied_rollback`（可经 `GET /api/tickets/void-policy` 只读核验）：**允许作废已应用单**。
  - 作废 scheduled 单：仅置 `voided`、记录必填原因，之后永不再被到期扫描命中。
  - 作废 applied 单：以该单在 `price_history` 的应用行为锚点，取其前驱价回退价签本；
    历史**只追加**一条 `rollback` 只读审计行，原应用行不删除、不改写；应用批次的
    `ticket_count/line_count` 等原计数一律不动。
  - 若价签本已被更新的单接管（来源单不再是被作废单），只留审计回退行，不覆盖更新的价签。
- 应用与作废互斥：进行中的一方会让另一方得到显式 `409`；事务内条件状态流转作为跨连接兜底，
  作废后的单不可能再被应用成功，重复作废同样被拒。
- 作废原因必填并写入 `ticket_voids` 留痕；`void_count`、单状态、价签本、历史末行、批次原计数互相印证。

后端测试（`backend/tests/`）覆盖：作废未生效单、所选策略下对已应用单的回退、应用与作废并发冲突被拒。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 后端测试

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```
