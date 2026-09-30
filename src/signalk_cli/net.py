"""SignalK server discovery (mDNS) and the on-disk host cache."""

import time
from pathlib import Path

try:
    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
except ImportError:  # slim/Pyodide installs ship without zeroconf
    Zeroconf = None  # type: ignore[assignment,misc]

CACHE_DIR = Path.home() / ".cache" / "signalk-cli"
_SIGNALK_TYPE = "_signalk-ws._tcp.local."
_HOST_CACHE_FILE = CACHE_DIR / "host.cache"


def get_cached_host() -> str | None:
    try:
        if _HOST_CACHE_FILE.exists():
            return _HOST_CACHE_FILE.read_text().strip() or None
    except OSError:
        pass
    return None


def save_cached_host(host: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _HOST_CACHE_FILE.write_text(host)
    except OSError:
        pass


def discover_host(timeout: float = 5.0) -> str | None:
    """Browse mDNS for a SignalK server and return its base URL, or None."""
    if Zeroconf is None:
        return None
    found: list[str] = []

    def _on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name)
        if info is None:
            return
        addrs = info.parsed_addresses()
        if not addrs:
            return
        host = f"http://{addrs[0]}:{info.port}"
        found.append(host)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, _SIGNALK_TYPE, handlers=[_on_change])
        deadline = time.monotonic() + timeout
        while not found and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        zc.close()

    return found[0] if found else None


def normalise_host(host: str) -> str:
    """Prepend http:// if the host has no scheme."""
    if "://" not in host:
        return f"http://{host}"
    return host
