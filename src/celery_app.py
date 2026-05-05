from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


celery_app = Celery(
    "patentflow",
    broker=_redis_url(),
    backend=_redis_url(),
    include=["src.tasks", "src.services.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    result_extended=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
)
