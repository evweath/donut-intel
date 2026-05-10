"""Async task manager with dependency tracking for parallel scans."""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PENDING = 'pending'
RUNNING = 'running'
COMPLETE = 'complete'
ERROR = 'error'


class Task:
    def __init__(self, task_id: str, name: str, fn: Callable, depends_on: List[str]) -> None:
        self.id = task_id
        self.name = name
        self.fn = fn
        self.depends_on = depends_on
        self.status = PENDING
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'depends_on': self.depends_on,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'error': self.error,
        }


class TaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = {}
        self._broadcast: Optional[Callable] = None

    def set_broadcast(self, fn: Callable) -> None:
        self._broadcast = fn

    async def _notify(self, task: Task) -> None:
        if self._broadcast:
            try:
                await self._broadcast({'event': 'task_update', 'task': task.to_dict()})
            except Exception:
                pass

    def submit(self, name: str, fn: Callable, depends_on: Optional[List[str]] = None) -> str:
        task_id = uuid.uuid4().hex[:8]
        task = Task(task_id, name, fn, depends_on or [])
        self._tasks[task_id] = task
        asyncio.create_task(self._run(task_id))
        return task_id

    async def _run(self, task_id: str) -> None:
        task = self._tasks[task_id]

        # Wait for all dependencies to finish
        while task.depends_on:
            dep_tasks = [self._tasks[d] for d in task.depends_on if d in self._tasks]
            if any(t.status == ERROR for t in dep_tasks):
                task.status = ERROR
                task.error = 'A dependency failed'
                task.finished_at = datetime.utcnow()
                await self._notify(task)
                return
            if all(t.status == COMPLETE for t in dep_tasks):
                break
            await asyncio.sleep(2)

        task.status = RUNNING
        task.started_at = datetime.utcnow()
        await self._notify(task)

        try:
            await task.fn()
            task.status = COMPLETE
        except asyncio.CancelledError:
            task.status = ERROR
            task.error = 'Cancelled'
            raise
        except Exception as exc:
            task.status = ERROR
            task.error = str(exc)
            logger.error(f"Task {task.name!r} failed: {exc}", exc_info=True)
        finally:
            task.finished_at = datetime.utcnow()
            await self._notify(task)

    def get_all(self, recent_n: int = 30) -> List[dict]:
        active = [t for t in self._tasks.values() if t.status in (PENDING, RUNNING)]
        done = sorted(
            [t for t in self._tasks.values() if t.status in (COMPLETE, ERROR)],
            key=lambda t: t.finished_at or datetime.min,
            reverse=True,
        )
        return [t.to_dict() for t in active + done[:recent_n]]

    def has_active(self) -> bool:
        return any(t.status in (PENDING, RUNNING) for t in self._tasks.values())

    def clear_finished(self) -> None:
        self._tasks = {tid: t for tid, t in self._tasks.items() if t.status in (PENDING, RUNNING)}


task_manager = TaskManager()
