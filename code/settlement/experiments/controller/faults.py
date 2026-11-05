"""Controller-side fault mechanisms: the response proxy, process restarts and ground truth."""
import datetime
import http.client
import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOP_HEADERS = {'connection', 'keep-alive', 'proxy-connection', 'transfer-encoding', 'upgrade', 'te', 'trailer',
               'content-length', 'host'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class GroundTruth:
    """The controller's record of what was injected and when.

    It is written only under the controller's own output directory, which is
    never passed to a runtime process.
    """

    def __init__(self, path, header):
        self.path = Path(path)
        self.doc = dict(header, events=[])
        self.lock = threading.Lock()

    def event(self, kind, **fields):
        with self.lock:
            self.doc['events'].append(dict(time=now(), event=kind, **fields))

    def write(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.doc, indent=2, sort_keys=True))
            tmp.replace(self.path)


def rpc_block_source(url, timeout=5):
    def block():
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []}).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return int(json.loads(res.read())['result'], 16)
    return block


def wait_blocks(block_source, count, stop, poll=0.2):
    """Wait until `count` blocks have been produced after the call."""
    if count <= 0:
        return True
    start = block_source()
    while not stop.is_set():
        if block_source() >= start + count:
            return True
        stop.wait(poll)
    return False


class ResponseProxy:
    """HTTP proxy between buyer and seller.

    Requests are always forwarded, so the seller sees and settles them. In mode
    'drop' a successful (2xx) response is discarded and the buyer's connection
    is closed without a reply; 402 challenges and errors pass. In mode 'delay'
    a successful response is held for `delay_blocks` blocks.
    """

    def __init__(self, listen, upstream, mode='pass', delay_blocks=0, block_source=None, truth=None):
        if mode not in ('pass', 'drop', 'delay'):
            raise ValueError(f'unknown proxy mode {mode}')
        if mode == 'delay' and block_source is None:
            raise ValueError('delay mode needs a block source')
        host, port = listen.rsplit(':', 1)
        self.upstream = urllib.parse.urlsplit(upstream)
        if self.upstream.scheme != 'http':
            raise ValueError('proxy upstream must be http')
        self.mode, self.delay_blocks, self.block_source, self.truth = mode, delay_blocks, block_source, truth
        self.stop = threading.Event()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def _forward(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length) if length else None
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
                conn = http.client.HTTPConnection(proxy.upstream.hostname, proxy.upstream.port or 80, timeout=60)
                try:
                    conn.request(self.command, self.path, body=body, headers=headers)
                    res = conn.getresponse()
                    data = res.read()
                    status, res_headers = res.status, res.getheaders()
                finally:
                    conn.close()
                ok = 200 <= status < 300
                if ok and proxy.mode == 'drop':
                    if proxy.truth:
                        proxy.truth.event('response_dropped', method=self.command, path=self.path, status=status)
                    self.close_connection = True
                    return
                if ok and proxy.mode == 'delay':
                    if proxy.truth:
                        proxy.truth.event('response_delay_started', path=self.path, blocks=proxy.delay_blocks)
                    if not wait_blocks(proxy.block_source, proxy.delay_blocks, proxy.stop):
                        self.close_connection = True
                        return
                    if proxy.truth:
                        proxy.truth.event('response_released', path=self.path)
                self.send_response(status)
                for k, v in res_headers:
                    if k.lower() not in HOP_HEADERS:
                        self.send_header(k, v)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _forward

        self.server = ThreadingHTTPServer((host, int(port)), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def address(self):
        host, port = self.server.server_address[:2]
        return f'http://{host}:{port}'

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()


class RestartInjector(threading.Thread):
    """Kill a process when it reports a trigger event, then relaunch it.

    A runtime process reports progress as JSON lines {"event": name} in
    events.jsonl in its own directory. The controller kills it with SIGKILL on
    the first line naming the trigger, waits `delay_blocks` blocks and starts
    the same command again.
    """

    def __init__(self, events_file, trigger, kill, restart, delay_blocks=0, block_source=None, truth=None,
                 poll=0.05):
        super().__init__(daemon=True)
        self.events_file, self.trigger = Path(events_file), trigger
        self.kill, self.restart = kill, restart
        self.delay_blocks, self.block_source, self.truth, self.poll = delay_blocks, block_source, truth, poll
        self.stop = threading.Event()
        self.fired = threading.Event()
        self.error = None

    def _seen(self, offset):
        if not self.events_file.exists():
            return False, offset
        with self.events_file.open('rb') as f:
            f.seek(offset)
            data = f.read()
        lines = data.split(b'\n')
        consumed = offset + len(data) - len(lines[-1])
        for line in lines[:-1]:
            try:
                if json.loads(line).get('event') == self.trigger:
                    return True, consumed
            except (ValueError, AttributeError):
                continue
        return False, consumed

    def run(self):
        offset = 0
        try:
            while not self.stop.is_set():
                seen, offset = self._seen(offset)
                if seen:
                    break
                self.stop.wait(self.poll)
            else:
                return
            self.kill()
            if self.truth:
                self.truth.event('process_killed', trigger=self.trigger)
            if self.delay_blocks and not wait_blocks(self.block_source, self.delay_blocks, self.stop):
                return
            self.restart()
            if self.truth:
                self.truth.event('process_restarted', delay_blocks=self.delay_blocks)
            self.fired.set()
        except Exception as exc:  # reported in the result envelope
            self.error = repr(exc)
            if self.truth:
                self.truth.event('restart_failed', error=self.error)


def expected_verdict(kind, parameters):
    """The content verdict the controller knows to be correct, when the fault defines one."""
    if kind == 'wrong_verdict':
        return {'false_fail': 'PASS', 'false_pass': 'FAIL'}.get(parameters.get('misjudgment_direction'))
    if kind == 'collusion':
        return 'FAIL'
    if kind == 'false_non_delivery_claim':
        return 'DELIVERED'
    if kind in ('false_wrong_delivery_collusion', 'honest_high_rate'):
        return 'PASS'
    return None


def sleep_until(deadline, stop):
    while not stop.is_set() and time.monotonic() < deadline:
        stop.wait(min(0.1, max(0.0, deadline - time.monotonic())))
