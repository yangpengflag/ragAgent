"""Celery 应用装配（长任务 broker）。

`celery -A app.tasks worker` 启动入口：`-A app.tasks` 加载本模块，暴露 `celery` 实例。
broker 指向 Redis（配置来自 `config.py` 的 `celery_broker_url`）。
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

celery = Celery(
    "ragagent",
    broker=get_settings().celery_broker_url,
)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    enable_utc=True,
    timezone="UTC",
    include=["app.tasks.ingest"],
)

__all__ = ["celery"]