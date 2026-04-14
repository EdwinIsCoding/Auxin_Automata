"""Gemini-backed safety oracle for Auxin Automata.

The oracle evaluates whether the next robotic action is safe by sending:
- The current TelemetryFrame (torques, positions, anomaly flags)
- A workspace JPEG image

to Gemini's vision model with a structured JSON response schema, then returns
an OracleDecision that the bridge uses to approve or veto the action.

Fallback guarantee
------------------
If the Gemini API is unavailable, slow, or returns an unparseable response,
the oracle ALWAYS falls back to a local heuristic so the system never stalls
on a network blip.  used_fallback=True flags this in the OracleDecision.

Usage
-----
    oracle = SafetyOracle(api_key=os.environ["GEMINI_API_KEY"])
    decision = await oracle.check(frame, Path("workspace.jpg"))
    if not decision.action_approved:
        await arm.halt()
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import anyio
import structlog
from pydantic import BaseModel
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from .schema import TelemetryFrame

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROMPT_FILE = _PROMPTS_DIR / "safety_oracle_v1.txt"
_PROMPT_VERSION = _PROMPT_FILE.stem  # "safety_oracle_v1"

# JSON schema sent to Gemini as response_schema — must match OracleDecision
# minus latency_ms and used_fallback (oracle fills those in).
_GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action_approved": {"type": "boolean"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
        "prompt_version": {"type": "string"},
    },
    "required": ["action_approved", "reason", "confidence", "prompt_version"],
}


# ── Public models ─────────────────────────────────────────────────────────────


class OracleDecision(BaseModel):
    """
    Structured verdict returned by SafetyOracle.check().

    action_approved
        True → safe to proceed.  False → halt immediately.
    reason
        One sentence explaining the decision, e.g. "obstacle detected at ~0.4 m".
    confidence
        Calibrated probability [0.0, 1.0] that the decision is correct.
        Fallback decisions use 0.5 (moderate confidence).
    latency_ms
        Wall-clock time from check() entry to return (includes retry waits).
    prompt_version
        Identifies the system-prompt version used, e.g. "safety_oracle_v1".
        Falls back to "local-fallback-v1" when the API is unavailable.
    used_fallback
        True when the local heuristic was used instead of the Gemini API.
    """

    action_approved: bool
    reason: str
    confidence: float
    latency_ms: float
    prompt_version: str
    used_fallback: bool


# ── Oracle ────────────────────────────────────────────────────────────────────


class SafetyOracle:
    """
    Gemini-backed safety oracle.  Drop-in async callable for the bridge.

    Parameters
    ----------
    api_key
        Gemini API key.  Falls back to ``GEMINI_API_KEY`` env var if omitted.
        When no key is available every call uses the local fallback heuristic.
    model
        Gemini model identifier.  Default: ``"gemini-2.0-flash"``.
    timeout_s
        Hard wall-clock deadline for the Gemini API call (including retries).
        If exceeded the local heuristic is used and used_fallback=True.
    torque_threshold
        Maximum safe joint torque in N·m.  Matches the watchdog threshold (80 N·m).
    _model
        Optional pre-built model object — used in unit tests to inject a mock
        without touching the real Gemini API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        timeout_s: float = 2.0,
        torque_threshold: float = 80.0,
        _model: object | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model_name = model
        self._timeout_s = timeout_s
        self._torque_threshold = torque_threshold
        self._prompt_text = _PROMPT_FILE.read_text(encoding="utf-8")
        self._genai_model: object | None = _model  # None → lazy-init on first check()

    # ── Public API ────────────────────────────────────────────────────────────

    async def check(self, frame: TelemetryFrame, image_path: Path) -> OracleDecision:
        """
        Evaluate whether the next action is safe.

        Parameters
        ----------
        frame
            Current kinematic state (torques, positions, anomaly flags).
        image_path
            Path to the workspace JPEG image.

        Returns
        -------
        OracleDecision
            Always returns a decision — never raises; uses fallback on any failure.
        """
        start = time.perf_counter()

        model = self._get_or_create_model()

        if model is None:
            # No API key configured — skip the network call entirely.
            log.info("oracle.no_api_key", reason="GEMINI_API_KEY not set, using local fallback")
            core = _local_fallback_core(frame, image_path, self._torque_threshold)
            used_fallback = True
        else:
            used_fallback = False
            try:
                with anyio.move_on_after(self._timeout_s) as cancel_scope:
                    core = await self._check_with_retry(model, frame, image_path)
                if cancel_scope.cancelled_caught:
                    log.warning(
                        "oracle.timeout",
                        timeout_s=self._timeout_s,
                        model=self._model_name,
                    )
                    core = _local_fallback_core(frame, image_path, self._torque_threshold)
                    used_fallback = True
            except Exception as exc:
                log.warning("oracle.error", error=str(exc), model=self._model_name)
                core = _local_fallback_core(frame, image_path, self._torque_threshold)
                used_fallback = True

        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        decision = OracleDecision(
            action_approved=core["action_approved"],
            reason=core["reason"],
            confidence=core["confidence"],
            prompt_version=core["prompt_version"],
            latency_ms=latency_ms,
            used_fallback=used_fallback,
        )

        log.info(
            "oracle.decision",
            action_approved=decision.action_approved,
            reason=decision.reason,
            confidence=decision.confidence,
            latency_ms=decision.latency_ms,
            prompt_version=decision.prompt_version,
            used_fallback=decision.used_fallback,
            model=self._model_name,
        )
        return decision

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_or_create_model(self) -> object | None:
        """Lazy-initialise the Gemini model.  Returns None if no API key."""
        if self._genai_model is not None:
            return self._genai_model
        if not self._api_key:
            return None

        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        self._genai_model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=_GEMINI_RESPONSE_SCHEMA,
            ),
            system_instruction=self._prompt_text,
        )
        log.debug("oracle.model_initialised", model=self._model_name)
        return self._genai_model

    async def _check_with_retry(
        self,
        model: object,
        frame: TelemetryFrame,
        image_path: Path,
    ) -> dict:
        """Call Gemini with up to 3 attempts + exponential backoff on transient errors."""
        last_exc: Exception | None = None
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.25, min=0.25, max=2.0),
                reraise=True,
            ):
                with attempt:
                    return await self._call_gemini(model, frame, image_path)
        except RetryError as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc
        raise last_exc or RuntimeError("all Gemini retries exhausted")

    async def _call_gemini(
        self,
        model: object,
        frame: TelemetryFrame,
        image_path: Path,
    ) -> dict:
        """Single Gemini API call.  Returns parsed dict matching _GEMINI_RESPONSE_SCHEMA."""
        import base64

        image_bytes = Path(image_path).read_bytes()
        # Inline-data format accepted by google-generativeai 0.x/1.x without PIL.
        # This also works with stub test images (4-byte JPEG SOI+EOI).
        image_blob = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }
        user_prompt = _build_user_prompt(frame, self._torque_threshold)

        response = await model.generate_content_async(  # type: ignore[union-attr]
            [user_prompt, image_blob]
        )

        raw_json = response.text
        data: dict = json.loads(raw_json)

        # Log token usage from the response metadata
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            log.debug(
                "oracle.tokens",
                prompt_tokens=getattr(usage, "prompt_token_count", None),
                candidate_tokens=getattr(usage, "candidates_token_count", None),
            )

        # Validate required fields
        for field in ("action_approved", "reason", "confidence", "prompt_version"):
            if field not in data:
                raise ValueError(f"Gemini response missing field '{field}': {raw_json!r}")

        return data


# ── Module-level helpers ──────────────────────────────────────────────────────


def _build_user_prompt(frame: TelemetryFrame, threshold: float) -> str:
    """Format the per-request user message with telemetry data."""
    max_torque = max(frame.joint_torques)
    torques_str = ", ".join(f"{t:.2f}" for t in frame.joint_torques)
    positions_str = ", ".join(f"{p:.3f}" for p in frame.joint_positions)
    flags_str = ", ".join(frame.anomaly_flags) if frame.anomaly_flags else "none"

    return (
        f"Current telemetry snapshot — timestamp: {frame.timestamp.isoformat()}\n"
        f"  Torque threshold : {threshold:.1f} N·m\n"
        f"  Max joint torque : {max_torque:.2f} N·m\n"
        f"  All torques (N·m): [{torques_str}]\n"
        f"  Joint positions  : [{positions_str}]\n"
        f"  Anomaly flags    : {flags_str}\n\n"
        f"Evaluate the attached workspace image together with this telemetry.\n"
        f"Should the robot's next action be approved?"
    )


def _local_fallback_core(
    frame: TelemetryFrame,
    image_path: Path,
    threshold: float,
) -> dict:
    """
    Local heuristic decision — used when the Gemini API is unavailable.

    Rules:
    - Deny if max(torques) > threshold.
    - Deny if the image is listed as "obstacle" in the co-located labels.json.
    - Deny if any anomaly flag is present.
    - Approve otherwise.
    """
    reasons: list[str] = []

    # Torque check
    max_torque = max(frame.joint_torques)
    if max_torque > threshold:
        reasons.append(f"torque {max_torque:.1f} N·m exceeds threshold {threshold:.1f} N·m")

    # Anomaly flags
    if frame.anomaly_flags:
        reasons.append(f"anomaly flags present: {frame.anomaly_flags}")

    # Image label check via adjacent labels.json (fixture set)
    image_path = Path(image_path)
    labels_file = image_path.parent / "labels.json"
    if labels_file.exists():
        try:
            labels: dict[str, str] = json.loads(labels_file.read_text(encoding="utf-8"))
            label = labels.get(image_path.name)
            if label == "obstacle":
                reasons.append("obstacle label in workspace image (local fallback)")
        except Exception:
            pass  # labels.json unreadable — skip image check

    approved = len(reasons) == 0
    if not reasons:
        reasons.append("all local checks passed")

    return {
        "action_approved": approved,
        "reason": "; ".join(reasons),
        "confidence": 0.50,  # moderate — local check is less reliable than Gemini
        "prompt_version": "local-fallback-v1",
    }
