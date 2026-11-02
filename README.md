# Do Not Suck (DNS) – spec-driven build
 
Team E. A local DNS resolver with Pi-hole style blocking, written in Python 3.11 with the
standard library only. This repository is the **spec-driven** build, made with
[GitHub Spec Kit](https://github.com/github/spec-kit). The vibe-coded build of the same system
is `Vibe_Name_Service`. Both builds implement the same frozen [`contract.md`](contract.md) and
are checked by the same black-box test suite in `tests/`.
 
**Status:** complete. All four features are merged and the full suite passes
(244 passed, 0 failed).
 
## What it does
 
- Answers A, AAAA and CNAME records from a local zone file (authoritative, AA=1),
  including NODATA and NXDOMAIN under the local zone suffixes.
- Blocks domains from a blocklist file, including their subdomains (`0.0.0.0` / `::`).
- Forwards everything else to an upstream resolver over UDP, with a random query ID and
  source port per query, a 2 s budget and TCP retry on truncation.
- Caches upstream answers for their TTL, including negative answers with an SOA (RFC 2308).
- Serves a JSON admin API and a web dashboard (`/ui`): counters, query log, and live editing
  of the blocklist and local records.
Not in scope: iterative resolution, DNSSEC, EDNS, DoT/DoH. See `contract.md` for the exact
external behaviour.
 
## Running it
 
```
python -m dnsd --listen 127.0.0.1:5300 --admin 127.0.0.1:8080 \
    --zone tests/fixtures/zone.txt --blocklist tests/fixtures/blocklist.txt \
    --upstream 1.1.1.1:53
```
 
- DNS on UDP and TCP at `--listen`; the dashboard at `http://127.0.0.1:8080/ui`.
- Test it with e.g. `dig @127.0.0.1 -p 5300 nas.home.lan` or `dig @127.0.0.1 -p 5300 ads.example.com`.
- Port 53 needs root, and 5353 is usually taken by mDNS, so use another port for local runs.
- A missing or malformed zone or blocklist file prints `dnsd: <path>:<line>: <reason>` and
  exits with status 1 before anything is bound.
- Changes made through the admin API live in memory and are lost on restart.
## Running the tests
 
```
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r tests/requirements.txt
 
ruff check dnsd && bandit -r dnsd
pytest tests --impl .                       # this build
pytest tests --impl ../Vibe_Name_Service    # the other build
```
 
The suite starts the build itself (`python -m dnsd` in the `--impl` directory, on free ports,
against a fake upstream) and stops it after each test. Keep `tests` before `--impl` on the
command line, or write `--impl=<path>`. CI (`.github/workflows/ci.yml`) runs ruff, bandit and the
full suite on Python 3.11 on every push.
 
## Layout
 
```
contract.md                 external behaviour, shared with Vibe_Name_Service (frozen)
dnsd/                       the server (standard library only)
  __main__.py               command line and startup
  parser.py                 DNS message model, wire decoding and encoding        (001)
  listener.py               UDP/TCP serving, shared state and interfaces, Stats  (001)
  zone.py                   zone file loading, ZoneStore                          (002)
  blocklist.py              blocklist file loading, Blocklist store              (002)
  forwarder.py              upstream exchange, the resolution handler            (002)
  cache.py                  TTL-respecting cache                                  (003)
  querylog.py               query log store                                       (004)
  api.py                    admin API and /ui dashboard                           (004)
tests/                      black-box suite (pytest + dnspython), run against both builds
.specify/memory/constitution.md   project principles (binding for every spec)
specs/NNN-*/                one folder per feature: spec, plan, research, tasks, contracts
docs/prompt-log.md          every committed prompt, IDs S-001, S-002, ...
docs/audit-log.md           flaws found in review, IDs SA-001, ...
```
 
The inter-module interfaces (message model, resolution handler, shared state and the store
roles) are defined once in
[`specs/001-parser-listener/contracts/interfaces.md`](specs/001-parser-listener/contracts/interfaces.md);
later features import them and do not redefine them.
 
## How it was built
 
| Feature | Scope | Built by | Prompts | PR |
|---|---|---|---|---|
| — | constitution 1.0.0 | Johnny | S-001 | on main |
| 001 | parser + listener, shared interfaces | Johnny | S-002 – S-020 | #1 |
| — | constitution 1.1.0 (team change) | Johnny | S-021 | #2 |
| 002 | zone + blocklist + forwarder + handler | Johnny | S-022 – S-038 | #3 |
| 003 | cache | Johnny | S-039 – S-050 | #4 |
| 004 | query log + admin API + /ui | Adam | none (see below) | #5 |
 
Features 001–003 followed the full Spec Kit workflow:
`/speckit-specify` → (clarifications answered in the spec) → `/speckit-plan` →
`/speckit-tasks` → `/speckit-analyze` (findings fixed, at most two rounds) →
`/speckit-implement` phase by phase, with a review and a commit at each checkpoint → PR,
reviewed and merged by someone other than the author. Each feature branch is kept as evidence.
 
## Changes of plan and threats to validity
 
Recorded here for the report (section 5.1):
 
- **Test suite available during development.** This build had `tests/` while it was written;
  the vibe build did not.
- **One spec author (2026-11-01).** Originally each member owned modules
  (Johnny: parser/listener, Daniel: zone/forwarder/cache and the test suite, Adam: blocklist,
  query log, admin API). Because of availability, Johnny wrote every spec and built 001–003;
  Daniel reviewed. Constitution 1.1.0 records this.
- **Blocklist moved from 004 to 002 (2026-11-02).** The test harness probes readiness with a
  blocked name, so without a blocklist every exact upstream-count test in 002 was off by one.
  Constitution 1.1.1 updates the feature list.
- **CI exception for deferred tests.** Until 004 merged, CI was red by design; constitution 1.1.0
  allows failures only in tests a spec lists as deferred to a later feature.
- **004 is vibe-coded (2026-11-02).** Adam built 004 without the Spec Kit workflow: only
  `specs/004-querylog-api/spec.md` was written, with no plan, tasks or analyze run, and no
  prompts were logged. It was accepted because all tests pass and time was short. The spec build
  therefore contains one vibe-coded feature. See the note in `docs/prompt-log.md` and SA-001 in
  `docs/audit-log.md`.
## Working on this repository
 
Spec Kit is already initialised (Claude Code integration). **Do not run `specify init` again.**
 
```
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```
 
- With another agent: `specify integration install <agent>`.
- In Claude Code the commands are `/speckit-specify`, `/speckit-plan`, … (hyphen, not dot).
- Spec Kit does not create branches here. Before `/speckit-specify`:
  `git checkout main && git pull && git checkout -b NNN-<name>`.
- Tell the agent in every prompt not to modify `tests/`, not to commit and not to write
  prompt-log entries; the human commits and logs.
Rules (from the constitution): `contract.md` wins over any spec; standard library only in
`dnsd/`; every requirement names the test that verifies it; the server never crashes on input;
ruff and bandit report zero findings (a `# noqa` only on one line, with a reason); nobody merges
their own AI-generated code.
 
### Commit messages
 
```
<type>(<module>): <what changed>
 
Prompt: S-014
Spec: specs/003-cache/spec.md
```
 
`type`: feat, fix, test, docs, refactor, chore.
`module`: parser, listener, zone, blocklist, forwarder, cache, querylog, api, tests, report.
 
Every prompt whose output gets committed goes in `docs/prompt-log.md` with the next S number;
mark entries useful for the report with ★.