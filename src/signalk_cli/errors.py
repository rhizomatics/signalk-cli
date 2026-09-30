"""Exceptions raised by the signalk_cli library API."""

import contextlib

import niquests


def api_error(exc: niquests.RequestException) -> str:
    """Return the most informative message from an API error response."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        with contextlib.suppress(Exception):
            body = resp.json()
            return body.get("error") or body.get("message") or str(exc)
    return str(exc)


class SignalKError(Exception):
    """A request to a SignalK server failed.

    Attributes:
        status_code: HTTP status of the failed response, or None if the
            server couldn't be reached.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @classmethod
    def from_request(cls, exc: niquests.RequestException) -> "SignalKError":
        """Wrap a niquests exception, using the server's error message if it sent one."""
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        return cls(
            api_error(exc), status_code=status if isinstance(status, int) else None
        )
