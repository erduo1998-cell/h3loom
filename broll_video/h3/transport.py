"""Small injectable HTTP transport used by the H3 runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib import error, request


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes
    headers: dict[str, str] | None = None
    url: str | None = None

    def json(self) -> dict[str, Any]:
        value = json.loads(self.body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("HTTP response JSON must be an object")
        return value


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        timeout: float = 60.0,
        max_response_bytes: int | None = None,
    ) -> HTTPResponse:
        """Execute one HTTP request."""


class ResponseTooLarge(RuntimeError):
    """Raised before a response can consume unbounded memory."""


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        timeout: float = 60.0,
        max_response_bytes: int | None = None,
    ) -> HTTPResponse:
        if json_body is not None and body is not None:
            raise ValueError("json_body and body are mutually exclusive")
        payload = body
        actual_headers = dict(headers or {})
        if json_body is not None:
            payload = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            actual_headers.setdefault("Content-Type", "application/json")
        req = request.Request(url, data=payload, headers=actual_headers, method=method.upper())
        opener = request.build_opener(_NoRedirectHandler())
        try:
            with opener.open(req, timeout=timeout) as response:
                body = (
                    response.read(max_response_bytes + 1)
                    if max_response_bytes is not None
                    else response.read()
                )
                if max_response_bytes is not None and len(body) > max_response_bytes:
                    raise ResponseTooLarge(f"response exceeds {max_response_bytes} bytes")
                return HTTPResponse(
                    response.status,
                    body,
                    {key.lower(): value for key, value in response.headers.items()},
                    response.geturl(),
                )
        except error.HTTPError as exc:
            body = (
                exc.read(max_response_bytes + 1)
                if max_response_bytes is not None
                else exc.read()
            )
            if max_response_bytes is not None and len(body) > max_response_bytes:
                raise ResponseTooLarge(f"response exceeds {max_response_bytes} bytes")
            return HTTPResponse(
                exc.code,
                body,
                {key.lower(): value for key, value in exc.headers.items()} if exc.headers else {},
                exc.geturl(),
            )


class MockTransport:
    """FIFO transport for deterministic, network-free tests."""

    def __init__(self, responses: list[HTTPResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        timeout: float = 60.0,
        max_response_bytes: int | None = None,
    ) -> HTTPResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json_body": json_body,
                "body": body,
                "timeout": timeout,
                "max_response_bytes": max_response_bytes,
            }
        )
        if not self.responses:
            raise AssertionError("mock transport has no response queued")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
