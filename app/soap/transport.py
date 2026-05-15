"""Shared aiohttp client for outbound SOAP (text and binary/MTOM retrieve)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientConnectorError, ClientOSError

from app.soap.addressing import extract_wsa_action, soap_action_short
from app.soap.fault import parse_soap_fault, soap_fault_log_fields
from app.soap.xmlutil import wsa_header_first_string

if TYPE_CHECKING:
    from app.config import Config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpBodyIntegrityReport:
    """Compares the downloaded body length to ``Content-Length`` when the header is present.

    Chunked MTOM responses often omit ``Content-Length``; in that case ``ok`` is True and
    ``content_length`` is None. A mismatch indicates truncation or a buggy peer and must not
    be treated as a complete image payload.
    """

    ok: bool
    body_len: int
    content_length: int | None
    reason_code: str | None = None


def http_body_integrity_from_aiohttp_response(
    body: bytes, response: object
) -> HttpBodyIntegrityReport:
    """Build an integrity report using aiohttp's parsed ``content_length`` (may be None)."""
    n = len(body)
    cl = getattr(response, "content_length", None)
    if cl is None:
        return HttpBodyIntegrityReport(ok=True, body_len=n, content_length=None, reason_code=None)
    if cl != n:
        return HttpBodyIntegrityReport(
            ok=False,
            body_len=n,
            content_length=cl,
            reason_code="http_content_length_mismatch",
        )
    return HttpBodyIntegrityReport(ok=True, body_len=n, content_length=cl, reason_code=None)


_shared_session: ClientSession | None = None

_default_client: SoapHttpClient | None = None
_default_client_fingerprint: tuple[float, float | None] | None = None


def _get_shared_session() -> ClientSession:
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = ClientSession()
    return _shared_session


def configure_soap_http_client_from_config(config: Config) -> None:
    """Rebuild the process-wide default :class:`SoapHttpClient` when SOAP timeout settings change.

    Call once per process after :class:`~app.config.Config` is constructed (e.g. from ``main``)
    so outbound SOAP uses env-driven connect vs read budgets.

    Args:
        config: Loaded runtime configuration (``WSD_SOAP_HTTP_*`` timeout fields).
    """
    global _default_client, _default_client_fingerprint
    fingerprint = (config.soap_http_connect_timeout_sec, config.soap_http_read_timeout_sec)
    if _default_client is not None and _default_client_fingerprint == fingerprint:
        return
    _default_client_fingerprint = fingerprint
    _default_client = SoapHttpClient(
        connect_timeout_sec=config.soap_http_connect_timeout_sec,
        read_timeout_override_sec=config.soap_http_read_timeout_sec,
    )


def is_scanner_xaddr_transport_failover(exc: BaseException) -> bool:
    """Return True when the next WS-Discovery **XAddr** candidate should be tried.

    Used after outbound SOAP (or preflight **Get**) toward a scanner endpoint: connection-level
    failures and full request timeouts warrant trying the next address in ProbeMatches order.
    Application-level SOAP faults and HTTP 4xx/5xx responses are not treated here.

    Args:
        exc: Exception raised from :meth:`SoapHttpClient.post_text` / ``post_retrieve_image``.

    Returns:
        Whether registration (or similar) should fail over to another **XAddr**.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return isinstance(exc, (ClientConnectorError, ClientOSError))


def reset_soap_http_client_singleton_for_tests() -> None:
    """Clear the lazily created default client (pytest isolation)."""
    global _default_client, _default_client_fingerprint
    _default_client = None
    _default_client_fingerprint = None


class SoapHttpClient:
    """SOAP over HTTP with an optional injected ``ClientSession`` (else process-wide shared session)."""

    __slots__ = ("_session", "_owns_session", "_connect_timeout_sec", "_read_timeout_override_sec")

    def __init__(
        self,
        session: ClientSession | None = None,
        *,
        connect_timeout_sec: float = 10.0,
        read_timeout_override_sec: float | None = None,
    ) -> None:
        """Wrap requests; when ``session`` is None, use a lazily created shared session.

        Args:
            session: Optional aiohttp session (tests may inject a mock).
            connect_timeout_sec: ``sock_connect`` budget for establishing the TCP connection.
            read_timeout_override_sec: When set, ``sock_read`` for every request uses this value
                instead of each call's ``timeout_sec``. When unset, per-call ``timeout_sec`` is
                used for ``sock_read`` (preserves prior single-timeout behavior on the read leg).
        """
        self._session = session
        self._owns_session = session is None
        self._connect_timeout_sec = float(connect_timeout_sec)
        self._read_timeout_override_sec = (
            float(read_timeout_override_sec) if read_timeout_override_sec is not None else None
        )

    def _session_for_request(self) -> ClientSession:
        return self._session if self._session is not None else _get_shared_session()

    def _client_timeout(self, read_sec: float) -> ClientTimeout:
        """Build aiohttp timeout with separate connect vs read (``sock_read``) ceilings."""
        read_budget = (
            self._read_timeout_override_sec
            if self._read_timeout_override_sec is not None
            else float(read_sec)
        )
        return ClientTimeout(
            sock_connect=self._connect_timeout_sec,
            sock_read=read_budget,
        )

    async def post_text(
        self,
        *,
        url: str,
        payload: str,
        timeout_sec: float,
    ) -> tuple[int, str]:
        """POST SOAP XML; return HTTP status and response text."""
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        req_action = extract_wsa_action(payload)
        req_action_short = soap_action_short(req_action)
        req_message_id = wsa_header_first_string(payload, "MessageID")
        read_effective = (
            self._read_timeout_override_sec
            if self._read_timeout_override_sec is not None
            else float(timeout_sec)
        )
        log.info(
            f"{req_action_short or 'unknown'}",
            extra={
                "soap_leg": "client_request",
                "soap_action": req_action_short,
                "wsa_message_id": req_message_id,
                "url": url,
                "bytes": len(payload.encode("utf-8")),
                "timeout_sec": timeout_sec,
                "soap_connect_timeout_sec": self._connect_timeout_sec,
                "soap_read_timeout_sec": read_effective,
            },
        )
        session = self._session_for_request()
        timeout = self._client_timeout(timeout_sec)
        try:
            async with session.post(
                url,
                data=payload.encode("utf-8"),
                headers=headers,
                timeout=timeout,
            ) as response:
                text = await response.text()
                resp_action = extract_wsa_action(text)
                resp_action_short = soap_action_short(resp_action)
                resp_message_id = wsa_header_first_string(text, "MessageID")
                fault = parse_soap_fault(text)
                resp_extra: dict[str, str | int | float | None] = {
                    "soap_leg": "client_response",
                    "soap_action": resp_action_short,
                    "wsa_message_id": resp_message_id,
                    "url": url,
                    "http_status": response.status,
                    "bytes": len(text.encode("utf-8")),
                }
                resp_extra.update(soap_fault_log_fields(fault))
                log.info(f"{resp_action_short or 'unknown'}", extra=resp_extra)
                if response.status < 200 or response.status >= 300 or fault.get("fault_code"):
                    warn_extra = {**resp_extra, "fault_code": fault.get("fault_code")}
                    log.warning(
                        f"{resp_action_short or 'unknown'} indicates failure",
                        extra=warn_extra,
                    )
                return response.status, text
        except asyncio.TimeoutError:
            log.warning(
                f"{req_action_short or 'unknown'} timed out",
                extra={
                    "soap_leg": "client_response",
                    "soap_action": req_action_short,
                    "wsa_message_id": req_message_id,
                    "url": url,
                    "timeout_sec": timeout_sec,
                    "soap_connect_timeout_sec": self._connect_timeout_sec,
                    "soap_read_timeout_sec": read_effective,
                },
            )
            raise
        except ClientError as exc:
            log.warning(
                f"{req_action_short or 'unknown'} transport error",
                extra={
                    "soap_leg": "client_response",
                    "soap_action": req_action_short,
                    "wsa_message_id": req_message_id,
                    "url": url,
                    "error": str(exc),
                },
            )
            raise

    async def post_retrieve_image(
        self,
        *,
        url: str,
        payload: str,
        timeout_sec: float,
    ) -> tuple[int, bytes, str | None, HttpBodyIntegrityReport]:
        """POST RetrieveImage; return status, body bytes, Content-Type, and length integrity."""
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        req_action = extract_wsa_action(payload)
        req_action_short = soap_action_short(req_action)
        req_message_id = wsa_header_first_string(payload, "MessageID")
        read_effective = (
            self._read_timeout_override_sec
            if self._read_timeout_override_sec is not None
            else float(timeout_sec)
        )
        log.info(
            f"{req_action_short or 'unknown'}",
            extra={
                "soap_leg": "client_request",
                "soap_action": req_action_short,
                "wsa_message_id": req_message_id,
                "url": url,
                "bytes": len(payload.encode("utf-8")),
                "timeout_sec": timeout_sec,
                "soap_connect_timeout_sec": self._connect_timeout_sec,
                "soap_read_timeout_sec": read_effective,
            },
        )
        session = self._session_for_request()
        timeout = self._client_timeout(timeout_sec)
        try:
            async with session.post(
                url,
                data=payload.encode("utf-8"),
                headers=headers,
                timeout=timeout,
            ) as response:
                body = await response.read()
                http_integrity = http_body_integrity_from_aiohttp_response(body, response)
                resp_ct = response.headers.get("Content-Type")
                is_mtom = bool(resp_ct and "multipart/related" in resp_ct.lower())
                soap_text_probe = body[: min(4096, len(body))].decode("utf-8", errors="replace")
                resp_action = extract_wsa_action(soap_text_probe) if not is_mtom else None
                resp_action_short = soap_action_short(resp_action)
                resp_message_id = (
                    wsa_header_first_string(soap_text_probe, "MessageID") if not is_mtom else None
                )
                fault = {} if is_mtom else parse_soap_fault(soap_text_probe)
                resp_extra: dict[str, str | int | float | bool | None] = {
                    "soap_leg": "client_response",
                    "soap_action": resp_action_short,
                    "wsa_message_id": resp_message_id,
                    "url": url,
                    "http_status": response.status,
                    "bytes": len(body),
                    "response_content_type": resp_ct,
                    "http_body_len": http_integrity.body_len,
                    "http_content_length": http_integrity.content_length,
                    "http_body_integrity_ok": http_integrity.ok,
                }
                if not http_integrity.ok:
                    resp_extra["http_body_integrity_reason"] = http_integrity.reason_code
                resp_extra.update(soap_fault_log_fields(fault))
                log.info(f"{resp_action_short or 'unknown'}", extra=resp_extra)
                if response.status < 200 or response.status >= 300 or fault.get("fault_code"):
                    warn_extra = {**resp_extra, "fault_code": fault.get("fault_code")}
                    log.warning(
                        f"{resp_action_short or 'unknown'} indicates failure",
                        extra=warn_extra,
                    )
                if not http_integrity.ok:
                    log.warning(
                        "RetrieveImage HTTP body length does not match Content-Length",
                        extra={
                            "soap_leg": "client_response",
                            "soap_action": resp_action_short,
                            "url": url,
                            "http_body_len": http_integrity.body_len,
                            "http_content_length": http_integrity.content_length,
                            "reason_code": http_integrity.reason_code,
                        },
                    )
                return response.status, body, resp_ct, http_integrity
        except asyncio.TimeoutError:
            log.warning(
                f"{req_action_short or 'unknown'} timed out",
                extra={
                    "soap_leg": "client_response",
                    "soap_action": req_action_short,
                    "wsa_message_id": req_message_id,
                    "url": url,
                    "timeout_sec": timeout_sec,
                    "soap_connect_timeout_sec": self._connect_timeout_sec,
                    "soap_read_timeout_sec": read_effective,
                },
            )
            raise
        except ClientError as exc:
            log.warning(
                f"{req_action_short or 'unknown'} transport error",
                extra={
                    "soap_leg": "client_response",
                    "soap_action": req_action_short,
                    "wsa_message_id": req_message_id,
                    "url": url,
                    "error": str(exc),
                },
            )
            raise


def default_soap_http_client() -> SoapHttpClient:
    """Process-wide default SOAP HTTP client (shared ``ClientSession``)."""
    global _default_client
    if _default_client is None:
        _default_client = SoapHttpClient()
    return _default_client
