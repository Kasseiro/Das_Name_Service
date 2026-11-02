"""Admin API: JSON over HTTP on --admin, and the /ui dashboard.

Behaviour: contract.md § Admin API. Spec: specs/004-querylog-api/spec.md.
Uses only the stores in ServerState (specs/001-parser-listener/contracts/interfaces.md § 3).
"""
import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from dnsd.listener import Invalid, ServerState
from dnsd.parser import Name, type_from_text, type_to_text

MAX_BODY = 64 * 1024  # DC-3: larger bodies are not read
DEFAULT_LIMIT = 100  # contract.md § /log
JSON = "application/json"

Reply = tuple[int, str, bytes]  # status, Content-Type ("" for none), body


@dataclass(frozen=True)
class Request:
    args: list[str]  # the {parameters} of the path, percent-decoded
    query: str
    body: bytes | None  # None if Content-Length is invalid or over MAX_BODY


Endpoint = Callable[[ServerState, Request], Reply]


# --- helpers

def _json(status: int, value: object) -> Reply:
    return status, JSON, json.dumps(value).encode()


def _empty(status: int) -> Reply:
    return status, "", b""  # contract.md § Status codes: 201/204 bodies are unspecified


def _error(status: int, reason: str) -> Reply:
    return _json(status, {"error": reason})  # spec Assumptions: lets /ui show the reason


def _name(text: str) -> Name | None:
    """A domain name in any case, with or without trailing dot (FR-004); None if invalid."""
    try:
        return Name.from_text(text)
    except ValueError:
        return None


def _rtype(text: str) -> int | None:
    """A type mnemonic in any case; None if unknown."""
    try:
        return type_from_text(text)
    except ValueError:
        return None


def _object(body: bytes | None, kinds: dict[str, type]) -> dict | None:
    """The JSON object in body if every field in kinds is present with exactly that type; else None."""
    if body is None:
        return None
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    if any(type(value.get(key)) is not kind for key, kind in kinds.items()):
        return None  # type(...) is, not isinstance: rejects true/false as ttl
    return value


def _limit(query: str) -> int | None:
    """The /log limit: ASCII digits only, default 100; None if invalid (contract.md § /log)."""
    values = parse_qs(query, keep_blank_values=True).get("limit")
    if values is None:
        return DEFAULT_LIMIT
    text = values[0]
    if not (text.isascii() and text.isdigit()):
        return None
    digits = text.lstrip("0") or "0"
    return int(digits) if len(digits) <= 9 else 10**9  # avoids int()'s digit limit on huge input


# --- endpoints (contract.md § Admin API)

def _get_stats(state: ServerState, _request: Request) -> Reply:
    return _json(200, state.stats.snapshot())


def _get_blocklist(state: ServerState, _request: Request) -> Reply:
    return _json(200, [name.to_text() for name in state.blocklist.domains()])


def _post_blocklist(state: ServerState, request: Request) -> Reply:
    fields = _object(request.body, {"domain": str})
    if fields is None:
        return _error(400, 'body must be a JSON object with a string "domain"')
    name = _name(fields["domain"])
    if name is None:
        return _error(400, "domain is not a valid domain name")
    state.blocklist.add(name)
    return _empty(201)


def _delete_blocklist(state: ServerState, request: Request) -> Reply:
    name = _name(request.args[0])
    if name is None or not state.blocklist.remove(name):
        return _error(404, "domain is not listed")
    return _empty(204)


def _get_records(state: ServerState, _request: Request) -> Reply:
    zone = state.zone
    return _json(200, [
        {"name": r.name.to_text(), "type": type_to_text(r.rtype), "ttl": r.ttl,
         "value": zone.value_text(r)}
        for r in zone.records()
    ])


def _post_records(state: ServerState, request: Request) -> Reply:
    fields = _object(request.body, {"name": str, "type": str, "ttl": int, "value": str})
    if fields is None:
        return _error(400, "body must be a JSON object with string name, type, value and integer ttl")
    record = state.zone.make_record(fields["name"], fields["type"], fields["ttl"], fields["value"])
    if isinstance(record, Invalid):
        return _error(400, record.reason)
    state.zone.add(record)
    return _empty(201)


def _delete_records(state: ServerState, request: Request) -> Reply:
    name = _name(request.args[0])
    rtype = _rtype(request.args[1])
    if name is None or rtype is None or state.zone.remove(name, rtype) == 0:
        return _error(404, "no records with that name and type")
    return _empty(204)


def _get_log(state: ServerState, request: Request) -> Reply:
    limit = _limit(request.query)
    if limit is None:
        return _error(400, "limit must be a non-negative integer")
    return _json(200, [asdict(entry) for entry in state.log.recent(limit)])


def _get_ui(_state: ServerState, _request: Request) -> Reply:
    return 200, "text/html; charset=utf-8", UI_PAGE.encode()


ROUTES: dict[str, dict[str, Endpoint]] = {
    "stats": {"GET": _get_stats},
    "blocklist": {"GET": _get_blocklist, "POST": _post_blocklist},
    "blocklist/{domain}": {"DELETE": _delete_blocklist},
    "records": {"GET": _get_records, "POST": _post_records},
    "records/{name}/{type}": {"DELETE": _delete_records},
    "log": {"GET": _get_log},
    "ui": {"GET": _get_ui},
}


def _route(path: str) -> tuple[str, list[str]] | None:
    """The ROUTES key for a URL path and its {parameters}; None for an unknown path."""
    parts = path.split("/")
    if len(parts) < 2 or parts[0] != "":
        return None
    parts = parts[1:]
    if len(parts) == 1 and parts[0] in ROUTES:
        return parts[0], []
    if len(parts) == 2 and parts[0] == "blocklist" and parts[1]:
        return "blocklist/{domain}", [unquote(parts[1])]
    if len(parts) == 3 and parts[0] == "records" and parts[1] and parts[2]:
        return "records/{name}/{type}", [unquote(parts[1]), unquote(parts[2])]
    return None


# --- HTTP server

class _Handler(BaseHTTPRequestHandler):
    server: "AdminServer"
    timeout = 10  # DC-3: a client that stops sending only holds its own thread

    def _handle(self) -> None:
        try:
            status, content_type, payload = self._reply()
        except Exception:  # noqa: BLE001 - DC-3: an unexpected error answers 500; both servers keep running
            status, content_type, payload = _error(500, "internal error")
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        if status != 204:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _handle

    def _reply(self) -> Reply:
        body = self._body()  # read for every method, so the client never gets a reset
        url = urlsplit(self.path)
        route = _route(url.path)
        if route is None:
            return _error(404, "unknown path")
        key, args = route
        endpoint = ROUTES[key].get(self.command)
        if endpoint is None:
            return _error(405, "method not allowed")
        return endpoint(self.server.state, Request(args, url.query, body))

    def _body(self) -> bytes | None:
        text = self.headers.get("Content-Length", "0")
        if not (text.isascii() and text.isdigit()) or len(text) > 6 or int(text) > MAX_BODY:
            return None
        return self.rfile.read(int(text))


class AdminServer(ThreadingHTTPServer):
    def __init__(self, state: ServerState) -> None:
        self.state = state
        super().__init__(state.config.admin, _Handler)


def start_admin(state: ServerState) -> AdminServer:
    """Bind --admin now and serve in a daemon thread (FR-002). Raises OSError if it cannot bind."""
    server = AdminServer(state)
    threading.Thread(target=server.serve_forever, name="admin", daemon=True).start()
    return server


# --- /ui (contract.md § /ui; FR-010, DC-2): self-contained, uses only the endpoints above

UI_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dnsd admin</title>
<style>
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; color: #222; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
#error { color: #b00020; min-height: 1.2em; font-weight: bold; }
.stats { display: flex; gap: 1rem; flex-wrap: wrap; }
.stats div { border: 1px solid #ccc; border-radius: 6px; padding: .5rem 1rem; }
.stats b { display: block; font-size: 1.5rem; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: .25rem .5rem; border-bottom: 1px solid #eee; }
form { margin: .5rem 0; display: flex; gap: .5rem; flex-wrap: wrap; }
input, select, button { font: inherit; }
</style>
</head>
<body>
<h1>dnsd admin</h1>
<p id="error" role="alert"></p>
<div class="stats" id="stats"></div>

<h2>Blocklist</h2>
<form id="block-form">
<input id="block-domain" placeholder="ads.example.com" required>
<button>Block</button>
</form>
<table><tbody id="blocklist"></tbody></table>

<h2>Records</h2>
<form id="record-form">
<input id="rec-name" placeholder="host.home.lan." required>
<select id="rec-type"><option>A</option><option>AAAA</option><option>CNAME</option></select>
<input id="rec-ttl" type="number" min="0" value="300" required>
<input id="rec-value" placeholder="192.168.1.50" required>
<button>Add</button>
</form>
<table>
<thead><tr><th>Name</th><th>Type</th><th>TTL</th><th>Value</th><th></th></tr></thead>
<tbody id="records"></tbody>
</table>

<h2>Recent queries</h2>
<button id="refresh">Refresh</button>
<table>
<thead><tr><th>Time</th><th>Client</th><th>Name</th><th>Type</th><th>Result</th></tr></thead>
<tbody id="log"></tbody>
</table>

<script>
const $ = id => document.getElementById(id);

async function api(method, path, body) {
  const options = {method};
  if (body !== undefined) {
    options.headers = {"Content-Type": "application/json"};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let reason = response.statusText;
    try { reason = (await response.json()).error || reason; } catch (e) {}
    throw new Error(method + " " + path + ": " + response.status + " " + reason);
  }
  return response.status === 200 ? response.json() : null;
}

function row(cells, onDelete) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    td.textContent = cell;
    tr.appendChild(td);
  }
  if (onDelete) {
    const td = document.createElement("td");
    const button = document.createElement("button");
    button.textContent = "Delete";
    button.onclick = () => run(onDelete);
    td.appendChild(button);
    tr.appendChild(td);
  }
  return tr;
}

async function load() {
  const [stats, blocklist, records, log] = await Promise.all([
    api("GET", "/stats"), api("GET", "/blocklist"), api("GET", "/records"), api("GET", "/log?limit=50")]);
  $("stats").replaceChildren(...Object.entries(stats).map(([key, value]) => {
    const div = document.createElement("div");
    const b = document.createElement("b");
    b.textContent = value;
    div.append(b, key.replace("_", " "));
    return div;
  }));
  $("blocklist").replaceChildren(...blocklist.map(domain =>
    row([domain], () => api("DELETE", "/blocklist/" + encodeURIComponent(domain)))));
  $("records").replaceChildren(...records.map(r =>
    row([r.name, r.type, r.ttl, r.value],
        () => api("DELETE", "/records/" + encodeURIComponent(r.name) + "/" + r.type))));
  $("log").replaceChildren(...log.map(e =>
    row([new Date(e.time * 1000).toLocaleTimeString(), e.client, e.name, e.type, e.result])));
}

async function run(action) {
  $("error").textContent = "";
  try {
    if (action) await action();
    await load();
  } catch (error) {
    $("error").textContent = error.message;
  }
}

$("block-form").onsubmit = event => {
  event.preventDefault();
  run(() => api("POST", "/blocklist", {domain: $("block-domain").value}));
};
$("record-form").onsubmit = event => {
  event.preventDefault();
  run(() => api("POST", "/records", {name: $("rec-name").value, type: $("rec-type").value,
    ttl: Number($("rec-ttl").value), value: $("rec-value").value}));
};
$("refresh").onclick = () => run();
run();
</script>
</body>
</html>
"""