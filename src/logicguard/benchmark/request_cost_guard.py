"""Durable, fail-closed request and catalog-cost guard for paid experiments."""

from __future__ import annotations

import json
import math
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from logicguard.core.config import find_project_root
from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file


UNRESOLVED_STATUSES = {
    "in_flight",
    "provider_error",
    "usage_unknown",
    "cost_violation",
}
TERMINAL_STATUSES = {"complete", "invalid_schema", "skipped"}


class RequestCostGuardError(RuntimeError):
    """Raised when a request cannot be admitted or reconciled safely."""


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield
    finally:
        path.unlink()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RequestCostGuardError(f"{name} must be a nonnegative integer")
    return value


class RequestCostGuard:
    """Persist reservations before calls and fail closed on uncertain usage.

    The guard never calls a provider and never retries. A runner must reserve a
    frozen request slot, perform exactly one provider call, then reconcile the
    returned usage. A crash after reservation leaves the slot ``in_flight`` and
    blocks every later dispatch until it is audited in a new namespace.
    """

    def __init__(self, *, launch_manifest: Path, state_path: Path) -> None:
        self.manifest_path = launch_manifest.resolve()
        self.root = find_project_root(self.manifest_path)
        self.state_path = state_path.resolve()
        if not self.state_path.is_relative_to(self.root):
            raise ValueError("guard state must remain inside the project")
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        request_artifact = self.manifest["artifacts"]["request_plan"]
        self.plan_path = (self.root / request_artifact["path"]).resolve()
        if not self.plan_path.is_relative_to(self.root):
            raise ValueError("request plan resolves outside the project")
        if sha256_file(self.plan_path) != request_artifact["sha256"]:
            raise RequestCostGuardError("frozen request plan hash mismatch")
        rows = load_jsonl(self.plan_path)
        self.slots = {str(row["request_slot_id"]): row for row in rows}
        if len(self.slots) != len(rows):
            raise RequestCostGuardError("duplicate request_slot_id in frozen plan")
        if len(rows) != int(self.manifest["limits"]["max_provider_calls"]):
            raise RequestCostGuardError("request plan count differs from frozen cap")

    def reserve(
        self, request_slot_id: str, *, actual_prompt_fingerprint: str
    ) -> dict[str, Any]:
        """Durably reserve one frozen slot before the provider call."""

        if not actual_prompt_fingerprint:
            raise ValueError("actual_prompt_fingerprint is required")
        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            self._assert_dispatchable(state)
            if request_slot_id not in self.slots:
                raise RequestCostGuardError("request slot is not in the frozen plan")
            if request_slot_id in state["requests"]:
                raise RequestCostGuardError("request slot was already recorded")
            slot = self.slots[request_slot_id]
            if slot.get(
                "actual_prompt_binding"
            ) == "fully_frozen" and actual_prompt_fingerprint != slot.get(
                "prompt_fingerprint"
            ):
                raise RequestCostGuardError("actual prompt differs from frozen slot")
            dependency = slot.get("depends_on_request_slot_id")
            if dependency:
                prior = state["requests"].get(dependency)
                if prior is None or prior.get("status") != "complete":
                    raise RequestCostGuardError(
                        "request dependency is not complete; dispatch is forbidden"
                    )
            committed = self._committed_cost(state)
            reserved = float(slot["reserved_cost_cny"])
            hard_cap = float(self.manifest["limits"]["hard_cost_cap_cny"])
            if committed + reserved > hard_cap + 1e-12:
                state["status"] = "STOPPED_REQUEST_BUDGET"
                state["updated_at"] = _utc_now()
                atomic_write_json(self.state_path, state)
                raise RequestCostGuardError("request reservation exceeds hard cost cap")
            record = {
                "request_slot_id": request_slot_id,
                "status": "in_flight",
                "reserved_cost_cny": reserved,
                "input_token_cap": int(slot["input_token_cap"]),
                "output_token_cap": int(slot["output_token_cap"]),
                "actual_prompt_fingerprint": actual_prompt_fingerprint,
                "reserved_at": _utc_now(),
            }
            state["requests"][request_slot_id] = record
            state["status"] = "RUNNING"
            state["updated_at"] = _utc_now()
            atomic_write_json(self.state_path, state)
            return dict(record)

    def complete(
        self,
        request_slot_id: str,
        *,
        prompt_tokens: Any,
        completion_tokens: Any,
        reasoning_tokens: Any = 0,
    ) -> dict[str, Any]:
        """Reconcile provider usage; any missing or excessive usage stops the run."""

        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            record = self._in_flight_record(state, request_slot_id)
            try:
                prompt = _nonnegative_int(prompt_tokens, "prompt_tokens")
                completion = _nonnegative_int(completion_tokens, "completion_tokens")
                reasoning = _nonnegative_int(reasoning_tokens, "reasoning_tokens")
            except RequestCostGuardError:
                record["status"] = "usage_unknown"
                state["status"] = "STOPPED_UNCERTAIN_REQUEST"
                state["updated_at"] = _utc_now()
                atomic_write_json(self.state_path, state)
                raise
            pricing = self.manifest["pricing"]
            actual_cost = (
                prompt * float(pricing["input_per_million_tokens_cny"])
                + completion * float(pricing["output_per_million_tokens_cny"])
            ) / 1_000_000
            record.update(
                prompt_tokens=prompt,
                completion_tokens=completion,
                reasoning_tokens=reasoning,
                actual_cost_cny=actual_cost,
                reconciled_at=_utc_now(),
            )
            violation = (
                prompt > record["input_token_cap"]
                or completion > record["output_token_cap"]
                or reasoning != 0
                or actual_cost > record["reserved_cost_cny"] + 1e-12
            )
            if violation:
                record["status"] = "cost_violation"
                state["status"] = "STOPPED_COST_VIOLATION"
                state["updated_at"] = _utc_now()
                atomic_write_json(self.state_path, state)
                raise RequestCostGuardError("provider usage exceeded a frozen limit")
            record["status"] = "complete"
            self._refresh_status(state)
            atomic_write_json(self.state_path, state)
            return dict(record)

    def provider_error(self, request_slot_id: str, *, error_type: str) -> None:
        """Record only the exception type; provider text and secrets are excluded."""

        if not error_type.isidentifier():
            raise ValueError("error_type must be an exception class name")
        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            record = self._in_flight_record(state, request_slot_id)
            record.update(status="provider_error", error_type=error_type)
            state["status"] = "STOPPED_UNCERTAIN_REQUEST"
            state["updated_at"] = _utc_now()
            atomic_write_json(self.state_path, state)

    def invalidate_schema(
        self, request_slot_id: str, *, error_type: str
    ) -> dict[str, Any]:
        """Mark a paid, reconciled response invalid without retrying the request."""

        if not error_type.isidentifier():
            raise ValueError("error_type must be an exception class name")
        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            record = state["requests"].get(request_slot_id)
            if record is None or record.get("status") != "complete":
                raise RequestCostGuardError(
                    "only a reconciled complete request can become invalid_schema"
                )
            record.update(status="invalid_schema", error_type=error_type)
            self._refresh_status(state)
            atomic_write_json(self.state_path, state)
            return dict(record)

    def skip(self, request_slot_id: str, *, reason: str) -> dict[str, Any]:
        """Resolve a never-dispatched downstream slot after a frozen phase failure."""

        allowed = {"upstream_phase_invalid", "attempt_generation_invalid"}
        if reason not in allowed:
            raise ValueError(f"unsupported skip reason: {reason}")
        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            self._assert_dispatchable(state)
            if request_slot_id not in self.slots:
                raise RequestCostGuardError("request slot is not in the frozen plan")
            if request_slot_id in state["requests"]:
                raise RequestCostGuardError("request slot was already recorded")
            dependency = self.slots[request_slot_id].get("depends_on_request_slot_id")
            prior = state["requests"].get(dependency) if dependency else None
            if prior is None or prior.get("status") not in {
                "invalid_schema",
                "skipped",
            }:
                raise RequestCostGuardError(
                    "skip requires a frozen invalid or skipped dependency"
                )
            record = {
                "request_slot_id": request_slot_id,
                "status": "skipped",
                "reason": reason,
                "resolved_at": _utc_now(),
            }
            state["requests"][request_slot_id] = record
            self._refresh_status(state)
            atomic_write_json(self.state_path, state)
            return dict(record)

    def summary(self) -> dict[str, Any]:
        with _exclusive_lock(self.lock_path):
            state = self._load_or_create_state()
            statuses: dict[str, int] = {}
            for row in state["requests"].values():
                statuses[row["status"]] = statuses.get(row["status"], 0) + 1
            known = sum(
                float(row.get("actual_cost_cny", 0))
                for row in state["requests"].values()
                if row["status"] in {"complete", "invalid_schema"}
            )
            return {
                "launch_fingerprint": state["launch_fingerprint"],
                "status": state["status"],
                "request_status_counts": statuses,
                "planned_request_slots": len(self.slots),
                "recorded_request_slots": len(state["requests"]),
                "known_catalog_cost_cny": known,
                "reserved_or_charged_cny": self._committed_cost(state),
                "hard_cost_cap_cny": self.manifest["limits"]["hard_cost_cap_cny"],
            }

    def _load_or_create_state(self) -> dict[str, Any]:
        fingerprint = str(self.manifest["launch_fingerprint"])
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("launch_fingerprint") != fingerprint:
                raise RequestCostGuardError("guard state launch fingerprint mismatch")
            return state
        state = {
            "schema_version": 1,
            "launch_fingerprint": fingerprint,
            "request_plan_sha256": sha256_file(self.plan_path),
            "status": "READY",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "requests": {},
        }
        atomic_write_json(self.state_path, state)
        return state

    def _assert_dispatchable(self, state: dict[str, Any]) -> None:
        unresolved = [
            key
            for key, row in state["requests"].items()
            if row["status"] in UNRESOLVED_STATUSES
        ]
        if unresolved:
            raise RequestCostGuardError(
                "unresolved request blocks dispatch: " + ",".join(unresolved)
            )
        if state["status"].startswith("STOPPED") or state["status"] == "COMPLETE":
            raise RequestCostGuardError(f"guard is not dispatchable: {state['status']}")

    def _in_flight_record(
        self, state: dict[str, Any], request_slot_id: str
    ) -> dict[str, Any]:
        record = state["requests"].get(request_slot_id)
        if record is None or record.get("status") != "in_flight":
            raise RequestCostGuardError("request slot is not durably in_flight")
        return record

    @staticmethod
    def _committed_cost(state: dict[str, Any]) -> float:
        total = 0.0
        for row in state["requests"].values():
            if row["status"] in {"complete", "invalid_schema"}:
                total += float(row["actual_cost_cny"])
            elif row["status"] != "skipped":
                total += float(row["reserved_cost_cny"])
        if not math.isfinite(total):
            raise RequestCostGuardError("non-finite committed cost")
        return total

    def _refresh_status(self, state: dict[str, Any]) -> None:
        values = list(state["requests"].values())
        if len(values) == len(self.slots) and all(
            row["status"] in TERMINAL_STATUSES for row in values
        ):
            state["status"] = "COMPLETE"
        else:
            state["status"] = "READY"
        state["updated_at"] = _utc_now()
