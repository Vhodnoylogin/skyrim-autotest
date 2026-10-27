"""Optional in-process HTTP lifetime owned by one native session mutex.

An existing receiver is adopted only after authenticated same-database proof.
No endpoint is restarted and no adopted receiver is closed by this module.
"""
from contextlib import contextmanager
import http.client
import sqlite3
import threading

from .command_bus import BusError, CommandBus, load_config, read_token
from .command_bus_http import CommandHTTPClient, CommandHTTPServer


class ManagedCommandEndpoint:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.token = read_token(self.config)
        self.bus = CommandBus(self.config['database'], self.config['claimTimeoutSeconds'])
        self.identity = self.bus.identity()
        self.client = CommandHTTPClient(config_path, timeout=2)
        self.server = self.thread = None
        self.mode = None

    def metadata(self):
        return {'mode': self.mode, 'host': self.config['host'], 'port': self.config['port'],
                'channelId': self.identity['channelId'], 'ready': True}

    def check(self):
        """Fresh authenticated proof; never creates, retries or repairs an endpoint."""
        try:
            if self.mode == 'owned' and (self.thread is None or not self.thread.is_alive()):
                raise BusError('Owned command endpoint stopped; no automatic restart')
            if (load_config(self.config_path) != self.config or read_token(self.config) != self.token or
                    self.bus.identity() != self.identity):
                raise BusError('Managed command channel configuration or database identity changed')
            observed = self.client.call('identity', {})
            if (type(observed) is not dict or type(observed.get('schemaVersion')) is not int or
                    observed != self.identity):
                raise BusError('Command endpoint does not identify the selected command database')
        except (BusError, OSError, sqlite3.Error, http.client.HTTPException) as exc:
            # Peer content, database paths and credentials never enter run logs.
            raise BusError('Managed command endpoint authenticated identity/readiness is unavailable', 'unavailable', 503) from exc
        return self.metadata()

    def __enter__(self):
        try:
            try:
                self.server = CommandHTTPServer((self.config['host'], self.config['port']),
                    self.bus, self.token, self.config['maxRequestBytes'])
            except OSError:
                # Binding is the port-free test. A failed bind grants no right to
                # stop another receiver, even when authentication/proof fails.
                self.mode = 'adopted'
            else:
                self.mode = 'owned'
                self.thread = threading.Thread(target=self.server.serve_forever,
                    kwargs={'poll_interval': .05}, name='autotest-command-endpoint', daemon=True)
                self.thread.start()
            self.check()
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.server is not None:
            if self.thread is not None and self.thread.is_alive():
                self.server.shutdown()
            self.server.server_close()
            if self.thread is not None:
                self.thread.join(3)
            self.server = self.thread = None

    def __exit__(self, *_):
        self.close()


@contextmanager
def managed_endpoint(settings):
    """Absent/false preserves the separately managed legacy receiver contract."""
    if not settings or settings.get('manageCommandEndpoint') is not True:
        yield None
    else:
        with ManagedCommandEndpoint(settings['channelConfig']) as endpoint:
            yield endpoint
