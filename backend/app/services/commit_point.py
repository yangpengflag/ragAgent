"""入库阶段的切换点提交（design D1）。

服务层的既有约定是「只 `flush`，事务由调用方提交」——该约定针对 FastAPI 请求路径
（`core/db.py::get_db`）。但 Celery 长任务自管事务，若把「瞬态状态」与长达数十秒的
外部 I/O 放在同一未提交事务里，并发只读查询永远看不到进行中状态，且进程被杀时
瞬态残留会让文档永久卡死。

因此在**阶段切换点**（置瞬态状态 + 推进 `ingest_job` 之后、调用外部依赖之前）做一次
提交，是本项目对上述约定的**唯一例外**。

`commit` 参数可注入：生产不传（用会话自身提交），测试注入替身以断言「提交发生在
外部 I/O 之前」，同时保持用例不真正落库。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session


def commit_stage(session: Session, commit: Callable[[], None] | None = None) -> None:
    """提交当前阶段状态（瞬态 + job 推进），使其对外可见。"""
    (commit or session.commit)()
