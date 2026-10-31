"""Immutable, hash-chained audit log plus real-time fan-out.

``record_event`` appends an :class:`Event` inside the caller's transaction. The
chain head row is locked (``SELECT … FOR UPDATE``) while appending, so concurrent
writers produce a single linear chain. Events are published to the
:class:`EventBus` only after the transaction commits, so subscribers never see
events that were rolled back.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import utcnow
from .models import Event, EventChainHead

log = logging.getLogger("forgeflow.events")
GENESIS = "0" * 64


@dataclass(frozen=True)
class Actor:
    type: str  # human | agent | system
    id: str

    @classmethod
    def system(cls) -> "Actor":
        return cls("system", "forgeflow")


def _canonical(e: Event) -> bytes:
    body = {
        "id": str(e.id), "type": e.type, "repository_id": _s(e.repository_id), "task_id": _s(e.task_id),
        "workspace_id": _s(e.workspace_id), "execution_id": _s(e.execution_id), "agent_id": _s(e.agent_id),
        "subject_type": e.subject_type, "subject_id": e.subject_id, "actor_type": e.actor_type,
        "actor_id": e.actor_id, "message": e.message, "payload": e.payload,
        "created_at": e.created_at.isoformat(),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


def compute_hash(prev_hash: str, e: Event) -> str:
    return hashlib.sha256(prev_hash.encode() + b"\n" + _canonical(e)).hexdigest()


def record_event(
    session: Session,
    type: str,
    actor: Actor,
    message: str = "",
    *,
    payload: dict[str, Any] | None = None,
    repository_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    subject: tuple[str, Any] | None = None,
) -> Event:
    # Take the write lock before reading the head. PostgreSQL honours FOR UPDATE; SQLite ignores it and
    # only begins a transaction at the first write, so the no-op UPDATE is what serializes appenders there.
    session.execute(update(EventChainHead).where(EventChainHead.id == 1).values(count=EventChainHead.count))
    head = session.execute(
        select(EventChainHead).where(EventChainHead.id == 1).with_for_update()
        .execution_options(populate_existing=True)  # never trust a cached head from earlier in this session
    ).scalar_one_or_none()
    if head is None:
        head = EventChainHead(id=1, hash=GENESIS, count=0)
        session.add(head)
        session.flush()
    e = Event(
        id=uuid.uuid4(), type=type, actor_type=actor.type, actor_id=actor.id, message=message,
        payload=json.loads(json.dumps(payload or {}, default=str)),
        repository_id=repository_id, task_id=task_id, workspace_id=workspace_id, execution_id=execution_id,
        agent_id=agent_id, subject_type=subject[0] if subject else None,
        subject_id=str(subject[1]) if subject else None, created_at=utcnow(), prev_hash=head.hash,
    )
    e.hash = compute_hash(head.hash, e)
    head.hash = e.hash
    head.count = (head.count or 0) + 1
    session.add(e)
    session.flush()
    session.info.setdefault("ff_pending_events", []).append(event_to_dict(e))
    return e


def event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "seq": e.seq, "id": str(e.id), "type": e.type, "message": e.message, "payload": e.payload,
        "repository_id": _s(e.repository_id), "task_id": _s(e.task_id), "workspace_id": _s(e.workspace_id),
        "execution_id": _s(e.execution_id), "agent_id": _s(e.agent_id), "subject_type": e.subject_type,
        "subject_id": e.subject_id, "actor_type": e.actor_type, "actor_id": e.actor_id,
        "created_at": e.created_at.isoformat(), "hash": e.hash, "prev_hash": e.prev_hash,
    }


def verify_chain(session: Session, batch: int = 1000) -> dict[str, Any]:
    prev = GENESIS
    checked = 0
    last_seq = 0
    while True:
        rows = session.execute(
            select(Event).where(Event.seq > last_seq).order_by(Event.seq).limit(batch)
        ).scalars().all()
        if not rows:
            break
        for e in rows:
            if e.prev_hash != prev or compute_hash(prev, e) != e.hash:
                return {"valid": False, "checked": checked, "broken_at": e.seq, "event_id": str(e.id)}
            prev = e.hash
            checked += 1
            last_seq = e.seq
    head = session.get(EventChainHead, 1)
    if head is not None and head.hash != prev:
        return {"valid": False, "checked": checked, "broken_at": "head", "event_id": None}
    return {"valid": True, "checked": checked, "head": prev}


# ------------------------------------------------------------------------ bus
class EventBus:
    def publish(self, event: dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def subscribe(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class InMemoryBus(EventBus):
    """Thread-safe fan-out to asyncio subscribers in this process."""

    def __init__(self, max_queue: int = 1000) -> None:
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self.max_queue = max_queue

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            def put(q=q):
                if q.qsize() < self.max_queue:
                    q.put_nowait(event)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:  # loop closed
                with self._lock:
                    self._subs.discard((loop, q))

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue()
        entry = (asyncio.get_running_loop(), q)
        with self._lock:
            self._subs.add(entry)
        try:
            while True:
                yield await q.get()
        finally:
            with self._lock:
                self._subs.discard(entry)


class RedisBus(EventBus):
    channel = "forgeflow:events"

    def __init__(self, url: str) -> None:
        import redis

        self.url = url
        self._client = redis.Redis.from_url(url)

    def publish(self, event: dict[str, Any]) -> None:
        try:
            self._client.publish(self.channel, json.dumps(event, default=str))
        except Exception:  # noqa: BLE001 - the audit log is the source of truth; fan-out is best effort
            log.exception("failed to publish event to redis")

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        import redis.asyncio as aioredis

        client = aioredis.Redis.from_url(self.url)
        pubsub = client.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(self.channel)
            await client.aclose()

    def close(self) -> None:
        self._client.close()


@sa_event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    pending = session.info.pop("ff_pending_events", [])
    bus: EventBus | None = session.info.get("ff_bus")
    if bus is None:
        return
    for e in pending:
        bus.publish(e)


@sa_event.listens_for(Session, "after_rollback")
def _discard_after_rollback(session: Session) -> None:
    session.info.pop("ff_pending_events", None)
