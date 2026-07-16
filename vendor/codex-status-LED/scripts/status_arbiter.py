"""Deterministic per-session status arbitration for one physical display."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Callable


PRIORITY = {
    "waiting": 50,
    "error": 40,
    "working": 30,
    "waiting_connection": 25,
    "complete": 20,
    "idle": 10,
    "sleeping": 0,
}

PHASE_SECONDS = {
    "complete": 3.0,
    "error": 10.0,
    "idle": 30.0,
}

STALE_SECONDS = {
    "working": 15.0 * 60.0,
    "waiting": 30.0 * 60.0,
}

TRANSITION_ANIM = {
    "idle": "idle",
    "sleeping": "sleeping",
}


def client_key(delivery: dict[str, Any]) -> str:
    """Return a stable registry key while preserving platform-only clients."""

    client_id = str(
        delivery.get("client_id") or delivery.get("source") or "manual"
    ).strip()
    session_id = str(delivery.get("session_id") or "").strip()
    return f"{client_id}:{session_id}" if session_id else client_id


@dataclass
class ClientState:
    client_key: str
    client_id: str
    client_kind: str
    session_id: str
    source: str
    semantic_status: str
    anim: str
    event: str
    tool: str
    updated_at: float
    phase_deadline: float | None
    stale_at: float | None
    display_role: str = "masked"


@dataclass(frozen=True)
class Decision:
    client_key: str | None
    client_id: str | None
    session_id: str | None
    status: str
    anim: str
    delivery: dict[str, Any]


class StatusArbiter:
    """Track platform sessions and choose one effective display state."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        *,
        hold_seconds: float = 1.0,
    ) -> None:
        self.clock = clock
        self.hold_seconds = max(0.0, float(hold_seconds))
        self.clients: dict[str, ClientState] = {}
        self.current_key: str | None = None
        self.hold_until = 0.0

    def update(
        self, delivery: dict[str, Any], now: float | None = None
    ) -> Decision:
        timestamp = self.clock() if now is None else float(now)
        key = client_key(delivery)
        status = str(delivery.get("status") or "working").strip()
        if status not in PRIORITY:
            status = "working"
        phase_seconds = PHASE_SECONDS.get(status)
        stale_seconds = STALE_SECONDS.get(status)
        self.clients[key] = ClientState(
            client_key=key,
            client_id=str(
                delivery.get("client_id") or delivery.get("source") or "manual"
            ).strip(),
            client_kind=str(
                delivery.get("client_kind") or delivery.get("source") or "manual"
            ).strip(),
            session_id=str(delivery.get("session_id") or "").strip(),
            source=str(delivery.get("source") or "manual").strip(),
            semantic_status=status,
            anim=str(delivery.get("anim") or TRANSITION_ANIM.get(status) or "idle"),
            event=str(delivery.get("event") or ""),
            tool=str(delivery.get("tool") or ""),
            updated_at=timestamp,
            phase_deadline=(
                timestamp + phase_seconds if phase_seconds is not None else None
            ),
            stale_at=(
                timestamp + stale_seconds if stale_seconds is not None else None
            ),
        )
        return self.evaluate(timestamp)

    def evaluate(self, now: float | None = None) -> Decision:
        timestamp = self.clock() if now is None else float(now)
        for state in self.clients.values():
            self._advance(state, timestamp)

        if not self.clients:
            self.current_key = None
            return Decision(None, None, None, "idle", "idle", {"anim": "idle"})

        candidate = max(self.clients.values(), key=self._rank)
        current = self.clients.get(self.current_key or "")
        if (
            current is not None
            and candidate.client_key != current.client_key
            and timestamp < self.hold_until
            and PRIORITY[candidate.semantic_status]
            <= PRIORITY[current.semantic_status]
        ):
            candidate = current

        if candidate.client_key != self.current_key:
            self.current_key = candidate.client_key
            self.hold_until = timestamp + self.hold_seconds

        for state in self.clients.values():
            state.display_role = (
                "effective" if state.client_key == self.current_key else "masked"
            )
        return self._decision(candidate)

    def next_deadline(self, now: float | None = None) -> float | None:
        timestamp = self.clock() if now is None else float(now)
        for state in self.clients.values():
            self._advance(state, timestamp)
        deadlines = [
            deadline
            for state in self.clients.values()
            for deadline in (state.phase_deadline, state.stale_at)
            if deadline is not None and deadline > timestamp
        ]
        if self.hold_until > timestamp:
            deadlines.append(self.hold_until)
        return min(deadlines, default=None)

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        timestamp = self.clock() if now is None else float(now)
        decision = self.evaluate(timestamp)
        counts = {status: 0 for status in PRIORITY}
        for state in self.clients.values():
            counts[state.semantic_status] += 1
        return {
            "aggregate": {
                "effective_client_key": decision.client_key,
                "effective_status": decision.status,
                "active_count": sum(
                    count
                    for status, count in counts.items()
                    if status != "sleeping"
                ),
                "waiting_count": counts["waiting"],
                "working_count": counts["working"],
                "error_count": counts["error"],
                "next_deadline": self.next_deadline(timestamp),
            },
            "clients": {
                key: asdict(state) for key, state in sorted(self.clients.items())
            },
        }

    @staticmethod
    def _rank(state: ClientState) -> tuple[int, float, str]:
        return (
            PRIORITY[state.semantic_status],
            state.updated_at,
            state.client_key,
        )

    @staticmethod
    def _advance(state: ClientState, now: float) -> None:
        while True:
            if state.stale_at is not None and now >= state.stale_at:
                transition_at = state.stale_at
                state.semantic_status = "sleeping"
                state.anim = TRANSITION_ANIM["sleeping"]
                state.updated_at = transition_at
                state.phase_deadline = None
                state.stale_at = None
                continue
            if state.phase_deadline is None or now < state.phase_deadline:
                return
            transition_at = state.phase_deadline
            if state.semantic_status in {"complete", "error"}:
                state.semantic_status = "idle"
                state.anim = TRANSITION_ANIM["idle"]
                state.updated_at = transition_at
                state.phase_deadline = transition_at + PHASE_SECONDS["idle"]
                state.stale_at = None
                continue
            if state.semantic_status == "idle":
                state.semantic_status = "sleeping"
                state.anim = TRANSITION_ANIM["sleeping"]
                state.updated_at = transition_at
                state.phase_deadline = None
                state.stale_at = None
                continue
            state.phase_deadline = None
            return

    @staticmethod
    def _decision(state: ClientState) -> Decision:
        delivery = {
            "source": state.source,
            "client_id": state.client_id,
            "client_kind": state.client_kind,
            "session_id": state.session_id,
            "client_key": state.client_key,
            "status": state.semantic_status,
            "anim": state.anim,
            "event": state.event,
            "tool": state.tool,
        }
        return Decision(
            client_key=state.client_key,
            client_id=state.client_id,
            session_id=state.session_id,
            status=state.semantic_status,
            anim=state.anim,
            delivery=delivery,
        )
