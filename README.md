# Do Not Suck (DNS) – spec-driven build

Team E. Local DNS resolver with Pi-hole style blocking, built with
spec-driven development using GitHub Spec Kit. The vibe-coded build of the same
system lives in `Vibe_Name_Service`. The black-box test suite in `tests/` is run against
both builds.

| Person | Role | Modules |
|---|---|---|
| Johnny Löfman | Protocol Core Developer, Lead Spec Writer | wire parser, UDP/TCP listener |
| Daniel Kass | Resolution Logic Developer, Prompt Engineer | local zone, forwarder, cache |
| Adam Beijar | Admin API Developer, Testing & Verification Lead | blocklist, query log, admin API, test suite |

## Ground rules

- Spec work starts **Wed 14 Oct**, after `vibe-final` is tagged in `Vibe_Name_Service`.
  The test suite can be written from Sat 10 Oct, from `contract.md` and the RFCs only.
- Nobody merges their own AI-generated code. Review order: Johnny → Daniel → Adam → Johnny.
- Every `/speckit.*` call and every implementation prompt whose output gets
  committed goes in `docs/prompt-log.md`.
- Log hours in `docs/hours.csv` at the end of each session.

Note for threats to validity (report 5.1): this build had the test suite available
during development; the vibe build did not.

## Setup

```
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify init --here --ai <agent>     # claude, copilot, cursor-agent, ...
```

Then in the agent, in this order:

1. `/speckit.constitution` (Johnny): RFC 1035 is authoritative, `contract.md` is binding,
   no DNS libraries outside tests, every requirement maps to a test.
2. `/speckit.specify` once per feature: parser + listener, zone + forwarder, cache,
   blocklist + admin API.
3. `/speckit.clarify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.analyze` → `/speckit.implement`.

Spec Kit creates a feature branch per spec. Keep them; they are evidence for section 4.4.

## Layout

```
contract.md         external behaviour (shared with Vibe_Name_Service, frozen from 9 Oct)
.specify/, specs/   created by Spec Kit
tests/              black-box suite (pytest + dnspython), run against both builds
docs/prompt-log.md  prompts, IDs S-001, S-002, ...
docs/hours.csv      time spent per person / module
docs/audit-log.md   flaws found in review, IDs SA-001, ...
```

## Commit messages

```
<type>(<module>): <what changed>

Prompt: S-014
Spec: specs/003-cache/spec.md
```

`type`: feat, fix, test, docs, refactor, chore.
`module`: parser, listener, zone, forwarder, cache, blocklist, api, tests, report.

## Running the tests

```
cd tests
pip install -r requirements.txt
pytest --dns 127.0.0.1:5353 --admin http://127.0.0.1:8080
```

Start either build first with the flags in `contract.md`.
