"""Tests for net.py (discovery, host cache) and _cli.py (shared CLI helpers)."""

import logging
from unittest.mock import MagicMock

import click
import pytest
from zeroconf import ServiceStateChange

from signalk_cli import _cli, net


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(net, "_HOST_CACHE_FILE", tmp_path / "host.cache")
    return tmp_path


def _fake_zeroconf(monkeypatch, *, info=None, state=ServiceStateChange.Added):
    """Patch zeroconf so ServiceBrowser fires one service event immediately."""
    zc = MagicMock()
    zc.get_service_info.return_value = info

    def _browser(zeroconf, service_type, handlers):
        for handler in handlers:
            handler(
                zeroconf=zeroconf,
                service_type=service_type,
                name="boat._signalk-ws._tcp.local.",
                state_change=state,
            )

    monkeypatch.setattr(net, "Zeroconf", MagicMock(return_value=zc))
    monkeypatch.setattr(net, "ServiceBrowser", _browser)
    return zc


def _service_info(addrs=("10.0.0.5",), port=3000):
    info = MagicMock()
    info.parsed_addresses.return_value = list(addrs)
    info.port = port
    return info


# ---------------------------------------------------------------------------
# normalise_host
# ---------------------------------------------------------------------------


def test_normalise_host_adds_http():
    assert net.normalise_host("10.0.0.1") == "http://10.0.0.1"


def test_normalise_host_preserves_http():
    assert net.normalise_host("http://10.0.0.1") == "http://10.0.0.1"


def test_normalise_host_preserves_https():
    assert net.normalise_host("https://example.com") == "https://example.com"


# ---------------------------------------------------------------------------
# Host cache
# ---------------------------------------------------------------------------


def test_host_cache_round_trip(cache_dir):
    assert net.get_cached_host() is None
    net.save_cached_host("http://boat:3000")
    assert net.get_cached_host() == "http://boat:3000"


def test_host_cache_empty_file_is_none(cache_dir):
    (cache_dir / "host.cache").write_text("  \n")
    assert net.get_cached_host() is None


def test_host_cache_unwritable_is_ignored(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(net, "CACHE_DIR", blocker / "sub")
    monkeypatch.setattr(net, "_HOST_CACHE_FILE", blocker / "sub" / "host.cache")
    net.save_cached_host("http://boat:3000")  # no exception
    assert net.get_cached_host() is None


# ---------------------------------------------------------------------------
# discover_host
# ---------------------------------------------------------------------------


def test_discover_host_found(monkeypatch):
    zc = _fake_zeroconf(monkeypatch, info=_service_info())
    assert net.discover_host(timeout=1) == "http://10.0.0.5:3000"
    zc.close.assert_called_once()


@pytest.mark.parametrize(
    ("info", "state"),
    [
        (None, ServiceStateChange.Added),
        (_service_info(addrs=()), ServiceStateChange.Added),
        (_service_info(), ServiceStateChange.Removed),
    ],
    ids=["no-info", "no-addresses", "not-added"],
)
def test_discover_host_ignores_unusable_services(monkeypatch, info, state):
    zc = _fake_zeroconf(monkeypatch, info=info, state=state)
    assert net.discover_host(timeout=0.05) is None
    zc.close.assert_called_once()


# ---------------------------------------------------------------------------
# resolve_host
# ---------------------------------------------------------------------------


def test_resolve_host_explicit_is_normalised(cache_dir):
    assert _cli.resolve_host("boat:3000") == "http://boat:3000"


def test_resolve_host_uses_cache(cache_dir, monkeypatch):
    net.save_cached_host("http://cached:3000")
    discover = MagicMock()
    monkeypatch.setattr(net, "discover_host", discover)
    assert _cli.resolve_host(None) == "http://cached:3000"
    discover.assert_not_called()


def test_resolve_host_discovers_and_caches(cache_dir, monkeypatch):
    monkeypatch.setattr(net, "discover_host", lambda: "http://found:3000")
    assert _cli.resolve_host(None) == "http://found:3000"
    assert net.get_cached_host() == "http://found:3000"


def test_resolve_host_no_cache_skips_cache(cache_dir, monkeypatch):
    net.save_cached_host("http://cached:3000")
    monkeypatch.setattr(net, "discover_host", lambda: "http://found:3000")
    assert _cli.resolve_host(None, no_cache=True) == "http://found:3000"
    assert net.get_cached_host() == "http://cached:3000"


def test_resolve_host_nothing_found(cache_dir, monkeypatch):
    monkeypatch.setattr(net, "discover_host", lambda: None)
    with pytest.raises(click.UsageError, match="No SignalK server found"):
        _cli.resolve_host(None)


# ---------------------------------------------------------------------------
# stderr_ctx — library log messages on the CLI
# ---------------------------------------------------------------------------

_log = logging.getLogger("signalk_cli")


def test_stderr_ctx_shows_library_info(capsys):
    with _cli.stderr_ctx(bare=False):
        _log.info("Resolving patterns...")
    assert capsys.readouterr().err == "Resolving patterns...\n"


def test_stderr_ctx_bare_discards_everything(capsys):
    with _cli.stderr_ctx(bare=True):
        _log.warning("Warning: something")
        click.echo("Server: x", err=True)
    assert capsys.readouterr().err == ""


def test_stderr_ctx_detaches_afterwards(capsys):
    with _cli.stderr_ctx(bare=False):
        pass
    _log.info("after")
    assert capsys.readouterr().err == ""
