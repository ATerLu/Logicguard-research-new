"""Minimal OpenAI-compatible chat client used by LogicGuard experiments.

The client deliberately avoids storing API keys in config files. Callers pass
the key from an environment variable at runtime, and result artifacts only keep
provider/model metadata plus token usage returned by the service.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable
from urllib import error, request


Transport = Callable[[str, dict[str, str], dict[str, object], int], dict[str, object]]


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """Normalized response returned by one LLM chat-completion call."""

    content: str
    raw_json: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class OpenAICompatibleChatClient:
    """Small client for providers that expose OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: Transport | None = None,
    ) -> None:
        """Create a client.

        `transport` is injectable so unit tests can verify the exact request
        shape without calling a remote model provider.
        """

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or _urllib_transport

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse:
        """Call `/chat/completions` and normalize the response content."""

        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        raw = self.transport(
            f"{self.base_url}/chat/completions",
            headers,
            payload,
            timeout_seconds,
        )
        content = _extract_content(raw)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ChatResponse(
            content=content,
            raw_json=json.dumps(raw, ensure_ascii=False),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
        )


def _urllib_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    """POST JSON using the standard library and return decoded JSON."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LLM provider HTTP {exc.code}: {_safe_error_excerpt(error_body)}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM provider connection failed: {exc.reason}") from exc

    try:
        decoded = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM provider returned non-JSON response") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("LLM provider returned JSON that is not an object")
    return decoded


def _extract_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM provider response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("LLM provider choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("LLM provider choice has no message object")
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    raise RuntimeError("LLM provider message content is not text")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_error_excerpt(text: str, max_chars: int = 600) -> str:
    """Trim provider errors while avoiding accidental huge log output."""

    return text[:max_chars].replace("\n", " ")
