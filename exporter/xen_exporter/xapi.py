"""Minimal XAPI (XenServer / XCP-ng API) client: XML-RPC + rrd_updates."""

from __future__ import annotations

import logging
import ssl
import time
import xmlrpc.client
from urllib.parse import urlparse

import requests
import urllib3

log = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class XapiError(Exception):
    def __init__(self, description: list):
        self.description = description
        super().__init__(" ".join(str(d) for d in description))

    @property
    def code(self) -> str:
        return str(self.description[0]) if self.description else ""


class _TimeoutTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float, context: ssl.SSLContext | None):
        super().__init__(context=context)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _PlainTimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def normalize_url(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    return url.rstrip("/")


class XapiSession:
    """A logged-in session against a pool master. Follows HOST_IS_SLAVE redirects."""

    def __init__(self, url: str, username: str, password: str,
                 verify_ssl: bool = False, timeout: float = 20.0):
        self.url = normalize_url(url)
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session_id: str | None = None
        self._proxy: xmlrpc.client.ServerProxy | None = None

    # -- transport -------------------------------------------------------
    def _make_proxy(self) -> xmlrpc.client.ServerProxy:
        if self.url.startswith("https://"):
            ctx = ssl.create_default_context()
            if not self.verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            transport = _TimeoutTransport(self.timeout, ctx)
        else:
            transport = _PlainTimeoutTransport(self.timeout)
        return xmlrpc.client.ServerProxy(self.url, transport=transport, allow_none=True)

    @staticmethod
    def _unwrap(result: dict):
        if result.get("Status") == "Success":
            return result.get("Value")
        raise XapiError(result.get("ErrorDescription", ["UNKNOWN_ERROR"]))

    # -- session ---------------------------------------------------------
    def login(self) -> None:
        for _ in range(3):  # follow at most a couple of HOST_IS_SLAVE redirects
            self._proxy = self._make_proxy()
            try:
                self.session_id = self._unwrap(self._proxy.session.login_with_password(
                    self.username, self.password, "1.0", "xen-mon"))
                log.info("logged in to %s", self.url)
                return
            except XapiError as e:
                if e.code == "HOST_IS_SLAVE" and len(e.description) > 1:
                    scheme = urlparse(self.url).scheme or "https"
                    new_url = f"{scheme}://{e.description[1]}"
                    log.warning("%s is a pool member, redirecting to master %s", self.url, new_url)
                    self.url = new_url
                    continue
                raise
        raise XapiError(["TOO_MANY_REDIRECTS"])

    def logout(self) -> None:
        if self._proxy and self.session_id:
            try:
                self._proxy.session.logout(self.session_id)
            except Exception:  # noqa: BLE001 - best effort
                pass
        self.session_id = None

    def call(self, method: str, *args):
        """Call an XAPI method (e.g. 'VM.get_all_records'), re-logging in if needed."""
        if not self.session_id:
            self.login()
        for attempt in range(2):
            fn = self._proxy
            for part in method.split("."):
                fn = getattr(fn, part)
            try:
                return self._unwrap(fn(self.session_id, *args))
            except XapiError as e:
                if e.code == "SESSION_INVALID" and attempt == 0:
                    self.login()
                    continue
                raise
        return None  # unreachable

    # -- rrd -------------------------------------------------------------
    def rrd_updates(self, host_address: str, window: int = 120) -> str:
        """Fetch the rrd_updates XML (host + resident VMs) from one host."""
        if not self.session_id:
            self.login()
        scheme = urlparse(self.url).scheme or "https"
        port = urlparse(self.url).port
        netloc = f"{host_address}:{port}" if port else host_address
        params = {
            "session_id": self.session_id,
            "start": int(time.time()) - window,
            "cf": "AVERAGE",
            "interval": 5,
            "host": "true",
        }
        r = requests.get(f"{scheme}://{netloc}/rrd_updates", params=params,
                         verify=self.verify_ssl, timeout=self.timeout)
        if r.status_code in (401, 403):
            # session expired: log in again once
            self.login()
            params["session_id"] = self.session_id
            r = requests.get(f"{scheme}://{netloc}/rrd_updates", params=params,
                             verify=self.verify_ssl, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} from {netloc}/rrd_updates: {r.text[:200]!r}")
        return r.text
