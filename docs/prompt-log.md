# Prompt log

Owner: Daniel. Everyone adds entries.

Add an entry for every prompt whose output got committed, and for every prompt
that failed in an interesting way. A two-line entry written now beats a
detailed one written in week two from memory. Mark entries worth using in the
report with ★ so section 4.5 can be pulled straight from here.

IDs run S-001, S-002, ... Put the ID in
the commit trailer (`Prompt: S-014`).

When a prompt is a retry of an earlier one, link it with `Refines:`. A chain
like S-007 → S-009 → S-012 is a ready-made prompt-evolution example for section 4.5.

---

## Template

### S-000 ★
- **Module:** cache
- **Who / tool / model:** Daniel / Cursor / Claude Sonnet
- **Date:**
- **Refines:** (earlier prompt ID, if any)
- **Prompt:**
  ```
  exact text, or the /speckit.* command plus arguments
  ```
- **Why this prompt:** what I was trying to get and why I phrased it this way
- **Expected:**
- **Got:** what the AI actually produced
- **Verdict:** worked | partly | failed
- **Failure mode:** (wrong logic, ignored spec, hallucinated API, missed edge case, ...)
- **Fixed by:** next prompt ID, manual edit, or spec change
- **Commit:**

---

## Entries

### S-001 ★
- **Module:** (project)
- **Who / tool / model:** Johnny / Claude Code v2.1.312 / Claude Opus 5.5
- **Date:** 2026-10-31
- **Refines:** –
- **Prompt:**
  ```
  /speckit-constitution Project: a local DNS resolver with blocking ("dnsd"), Python 3.11, standard library only.

  Principles:
  1. RFC 1035 is authoritative for wire format and semantics; RFC 2308, 4343 and 5452 apply where contract.md cites them.
  2. contract.md is binding and frozen. Specs reference its sections instead of restating them. If a spec conflicts with contract.md, contract.md wins and the spec is fixed.
  3. No DNS libraries (dnspython, dnslib, etc.) and no third-party packages in dnsd/. Only stdlib. DNS libraries are allowed in tests/ only.
  4. Every functional requirement names the test(s) in tests/ that verify it. A requirement with no test is either given one or dropped.
  5. The server must never crash on any input. All parsing is bounds-checked; malformed input is handled per contract.md.
  6. Security defaults: random 16-bit upstream query ID and random source port per query, replies with a mismatched ID are discarded.
  7. Code in dnsd/ passes ruff check and bandit -r with no findings.
  8. Keep it simple: no abstraction or configurability beyond what the contract requires.
  9. Module boundaries: parser, listener, zone, forwarder, cache, blocklist, api. Internal interfaces between modules are defined in the parser/listener spec and changed only by amending that spec.
  10. No AI-generated code is merged by its author; review order Johnny → Daniel → Adam → Johnny.
  ```
- **Why this prompt:** fix the non-negotiables (RFC authority, frozen contract, stdlib only, requirement-to-test traceability, security defaults, review rule) before any feature spec, so every later /speckit-* step is checked against them. Principles 1–4 come from the README, 5–7 and 10 from contract.md, ci.yml and the ground rules; 8–9 added to limit over-engineering and to pin the inter-module interface to the parser/listener spec.
- **Expected:** .specify/memory/constitution.md with the 10 principles, template placeholders replaced.
- **Got:** constitution v1.0.0 with all 10 principles, each with a rationale. Added unprompted: Technical Constraints, Development Workflow and Governance sections (amendments need all three members' approval), a requirement that the upstream ID and port come from `secrets` and are not configurable, and a rule allowing single-line ruff/bandit suppressions only with a reason and reviewer approval. Kept a Sync Impact Report comment at the top.
- **Verdict:** partly
- **Failure mode:** ignored project context: Principle IX listed "exactly" the seven modules from the prompt and omitted the query log module named in the README, plus `__main__.py`. Principle V widened "never crash" to the zone and blocklist files, beyond contract.md, which only covers runtime input.
- **Fixed by:** manual edit: IX now lists querylog and `__main__.py`; V limited to runtime input (UDP, TCP, admin API, upstream replies).
- **Commit:** 

### S-002 ★
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** –
- **Prompt:**
  ```
  /speckit-specify Feature: wire parser and UDP/TCP listener for dnsd. This feature comes first and defines the interfaces the other modules (zone, forwarder, cache, blocklist, querylog, api) build on.

  Scope:
  - Command line per contract.md § Command line. All five flags are accepted and validated, even those used by other modules.
  - Listen on UDP and TCP on the --listen address. A slow query (an upstream wait of up to 2 s) must not block other clients.
  - Parse and encode complete DNS messages: header, question, and answer/authority/additional records, with name compression on read. Other modules need this: the forwarder builds upstream queries and reads upstream replies, and the cache needs answer TTLs and an SOA record's TTL and MINIMUM from the authority section. Records of unknown types are kept as raw rdata.
  - Query handling per contract.md § Responses › Malformed and unusual queries, § Truncation and § TCP, plus the rules in § Responses on copying ID and question, QR and RA.
  - Hand each valid query, with the client address, to one resolution handler and send back the response it returns. Until the resolution modules exist, a stub handler answers every query with SERVFAIL.
  - Define the server's shared state (zone records, blocklist, cache, stats counters, query log) and how the listener and the admin API access it concurrently, so the zone, blocklist, querylog and api specs use the same objects.

  Out of scope: the local zone, forwarding, cache, blocklist, query log and admin API (other features). The --admin, --zone, --blocklist and --upstream values are only parsed here.

  The interface between the listener and the resolution handler, the shared state, and the message types other modules use must be specified precisely enough that the other three specs can depend on them without redefining them (constitution Principle IX).

  Verified by: tests/test_listener.py, tests/test_fuzz.py, tests/test_harness.py.
  ```
- **Why this prompt:** parser + listener goes first and must define the inter-module interfaces (message model, resolution handler, shared state) so the other three specs build on them instead of redefining them (Principle IX). Shared state was added because the admin API and the DNS path must use the same zone, blocklist and counters.
- **Expected:** spec.md with FRs mapped to tests, the interface definitions, and a SERVFAIL stub handler.
- **Got:** spec.md with FR-001–FR-031, each naming its tests in file::test form, plus an "Inter-module interfaces" section (message model, handler Query/Outcome, ServerState with five stores and their operations) and a quality checklist. It read the tests on its own and found that 9 of the named tests in test_listener.py/test_fuzz.py need blocklist or zone answers (0.0.0.0, big.home.lan) and cannot pass with the SERVFAIL stub, and that invalid-flag rejection and "slow query must not block" had no test. It raised both as clarification questions (Principle IV) instead of guessing. No branch was created: current Spec Kit only creates branches through the optional git extension, which is not installed, so the branch was made by hand.
- **Verdict:** partly
- **Failure mode:** scope creep: turned "accepted and validated" into strict CLI validation (IPv4 only, readable files, exit codes on bad flags or bind failure) that contract.md leaves unspecified. Also made unprompted choices recorded under Assumptions: truncated UDP replies carry no records, TCP closes after the first answer, and the listener does all /stats and /log counting.
- **Fixed by:** S-003
- **Commit:**

### S-003
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-002
- **Prompt:**
  ```
  Q1: B. Drop invalid-flag rejection (FR-002 to FR-004 validation): the contract leaves it unspecified, argparse's default behaviour is enough. Keep FR-007/FR-029; the slow-query test will be added to the suite by Daniel (test suite owner), so mark their tests as "pending: slow-upstream test (Daniel)" instead of writing the test yourself. Don't modify tests/.
  Q2: A. The feature is accepted when the 11 stub-compatible tests pass; the other 9 are re-checked when the blocklist (004) and zone (002) features merge. Record this in Verification status.
  Don't add the prompt log entry, I'll write it myself.
  ```
- **Why this prompt:** answer S-002's two questions in line with Principle IV without changing the test suite shared with Vibe_Name_Service, and keep the AI from logging its own run.
- **Expected:** CLI validation dropped, slow-query requirement kept with its test marked pending, acceptance gate recorded.
- **Got:** FR-003/FR-004 marked "Removed in clarification" (numbering kept), FR-002 reduced to parsing, related user story, edge case, SC-005 and assumptions updated. FR-007/FR-029 marked "pending: slow-upstream test (Daniel)". Verification status rewritten into 11 gate tests, 9 deferred tests tied to 002/004, and the pending test. Clarifications section added, checklist 16/16. tests/ untouched, no log entry written.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:**

### S-004 ★
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** –
- **Prompt:**
  ```
  /speckit-plan Python 3.11, standard library only (Principle III). Keep it minimal (Principle VIII): no frameworks, no extra layers, no new dependencies.

  - Files: dnsd/__init__.py, dnsd/__main__.py (argparse and startup), dnsd/parser.py (message model, decode/encode, type mnemonics, name text form), dnsd/listener.py (UDP and TCP serving, query intake, response finalisation, Stats, ServerState container, placeholder stores, stub handler). No other files unless a requirement needs one.
  - Concurrency: socketserver.ThreadingUDPServer and ThreadingTCPServer with daemon threads. Each store guards itself with its own threading.Lock; no lock is held during network I/O or while calling another store (FR-028, FR-029).
  - Message model as frozen dataclasses; Message holds lists of records.
  - TCP idle timeout: 5 seconds.
  - Errors go to stderr with print; no logging framework.
  - contracts/: write the inter-module interfaces from the spec as concrete Python signatures (message model types and functions, Query/Outcome and the handler signature, ServerState and each store's methods). This file is the binding interface for features 002–004.
  - Verification is the existing black-box suite in tests/; do not add test files or modify tests/.
  ```
- **Why this prompt:** pin the technical choices (four files, stdlib only, socketserver threads, per-store locks) up front so the plan cannot over-engineer, and get the inter-module interfaces as concrete Python signatures that features 002–004 build on.
- **Expected:** plan.md, research.md, data-model.md, contracts/ and quickstart.md within the given constraints.
- **Got:** all five artifacts. Constitution check passes before and after design, nothing in Complexity Tracking. research.md records 12 design decisions (R-1–R-12) with rejected alternatives; contracts/interfaces.md holds the binding signatures (message model, Query/Outcome/Handler, ServerState, each store's methods, concurrency rules, serve()). Unprompted but within the spec: no name compression on write, truncated UDP replies carry header and question only, one 5 s deadline per TCP connection, stats and log recorded before sending. It flagged two places where it interpreted rather than followed the spec (R-3: decode_query returns Message instead of Query(Message); R-9: zone result types and LogEntry defined in listener.py) and asked for a decision instead of silently diverging.
- **Verdict:** worked
- **Failure mode:** – (minor spec/contract mismatch, raised by the AI itself)
- **Fixed by:** S-005 (spec amended)
- **Commit:**

### S-005
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-004
- **Prompt:**
  ```
  Accept R-3 and R-9. Amend spec.md § Inter-module interfaces so it agrees with contracts/interfaces.md: decode_query returns the Message itself for a valid query (no separate Query(Message) type), and the zone result types (Answer, NoData, NXDomain, NotLocal, Invalid) and LogEntry are defined in dnsd/listener.py, imported from there by features 002–004. Change nothing else.

  (follow-up) Yes, update those lines in research.md and plan.md to say R-3 and R-9 were accepted and the spec amended. Nothing else.
  ```
- **Why this prompt:** spec.md and contracts/interfaces.md must agree (Principle IX); without the amendment /speckit-analyze would flag the mismatch and 002–004 would not know where to import the shared types from.
- **Expected:** two targeted edits to spec.md § Inter-module interfaces.
- **Got:** exactly those two edits (decode_query signature, a sentence on where the shared types live). It then pointed out on its own that research.md (R-3) and plan.md's post-design re-check still described R-3/R-9 as unamended interpretations, and updated those lines on request.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:**

### S-006
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** –
- **Prompt:**
  ```
  /speckit-tasks
  ```
- **Why this prompt:** break the plan into ordered, reviewable implementation tasks.
- **Expected:** tasks.md touching only the four dnsd/ files, no test tasks.
- **Got:** tasks.md with 43 tasks (T001–T043) in 9 phases, one per user story plus setup, foundational and polish. Each story ends with a check task running the existing tests or quickstart steps; no new tests. It moved __main__.py into US1, since every check starts the server, and suggested phases 1–3 as MVP (6 of 11 gate tests). Two check tasks (T035, T038) temporarily modify the stub handler and say to revert and confirm with git diff. It listed the prompt-log entry as a task (T043) rather than writing it.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-007 ★
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** –
- **Prompt:**
  ```
  /speckit-analyze
  ```
- **Why this prompt:** cross-check spec, plan, tasks and contracts against each other and the constitution before any code is written.
- **Expected:** a few consistency findings.
- **Got:** 16 findings, 2 critical. Real defects found before implementation: FR-007/FR-029 kept without a test, violating Principle IV (C1); spec restating contract.md (C2); FR-014 contradicting FR-010 on opcode (K1); string annotations in the contract that would fail ruff F821 and break CI (L1); T024 requiring tests that can only pass after US2 (O1); the fuzz test stopping at packet 100 with the stub, so only 5% of the stream reaches the server (G1); handler output that fails to encode producing no reply instead of SERVFAIL (U1); a task ordering that would count a query twice (O2); a task telling the AI to write its own prompt-log entry (W1). Read-only, no files changed.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** S-008
- **Commit:** 

### S-008
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-007
- **Prompt:**
  ```
  Apply these fixes, then stop:

  C1: Move FR-007 and FR-029's store-concurrency clause into a non-normative "Design goals (pending test)" note: they become requirements again once Daniel's slow-upstream test is in tests/. The plan's threading design stays. Keep T037/T038 as manual checks.
  C2: Replace restated contract.md text in FR-008 rules 1–5, FR-010 and FR-031 with citations; keep only what the spec adds (rule order, header bits, listener-only ownership).
  K1: FR-014 applies to responses to valid queries.
  O1: In T024, run only the non-error cases of the qr/ra tests; the full tests go in T029.
  L1: In contracts/interfaces.md, state that ZoneStore, Blocklist, Cache and QueryLog are roles, not importable types; annotate the ServerState fields with typing.Any. Update T015.
  G1: Add to T041 a scratch run that sends the full seeded fuzz stream and checks only that the process is still running and answers a valid query. No stub changes.
  U1: Extend T027: an exception while finalising or encoding the handler's Outcome also falls back to the FR-020 SERVFAIL.
  W1: Remove T043.
  O2: In T034, move the _account call after the size check so a query is counted once.
  Also fix the low and medium items: I1, I2, D1, S1, S2 (recount milestones), S3.
  Do not touch tests/ and do not write prompt-log entries.
  ```
- **Why this prompt:** resolve all S-007 findings in one pass. For C1, demote rather than keep "pending" requirements (Principle IV); for G1, a scratch survival run instead of a stub faking 0.0.0.0, which would game the shared test suite.
- **Expected:** targeted edits in spec.md, contracts/interfaces.md and tasks.md.
- **Got:** all fixes applied across spec, contract, plan, research, quickstart, checklist and tasks. FR-007/FR-029 became non-normative DG-1/DG-2; ServerState fields annotated Any with role comments; T043 removed. It verified with pytest --collect-only that the -k filter selects the 8 normal QR/RA cases. tests/ untouched.
- **Verdict:** worked
- **Failure mode:** – (C2's scope was too narrow; caught in S-009)
- **Fixed by:** –
- **Commit:** 

### S-009
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-007
- **Prompt:**
  ```
  /speckit-analyze
  ```
- **Why this prompt:** confirm the S-008 fixes and catch anything they introduced.
- **Expected:** clean report.
- **Got:** all earlier findings resolved except G2 (documented deferral). 8 new findings, 1 critical: FR-006, FR-009 and FR-012–FR-015 still restated contract.md (C3); the first run had scoped C2 too narrowly. Also a gate test wrongly marked † (I3), the contract's concurrency rule binding while DG-2 is non-normative (I4), US5 still reading as a normal story (I5), a T027 fallback with no requirement behind it (U2), and a type error in T034's pseudo-code (O3).
- **Verdict:** partly
- **Failure mode:** inconsistent scope between runs: the first analyze missed restatements of the same kind it flagged in C2.
- **Fixed by:** S-010
- **Commit:** 

### S-010
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-009
- **Prompt:**
  ```
  Apply these fixes, then stop:

  C3: Same pattern as C2 for FR-006, FR-009 and FR-012–FR-015: cite contract.md and keep only what this spec adds (FR-014: opcode 0 and the query's RD bit, whatever the handler set; FR-015: the listener removes OPT records from the handler's response). Test lists unchanged.
  I3: Drop the † on test_truncated_response_keeps_question_and_whole_records under FR-016 and add "gate test; full check with 002".
  I4: In the spec, state that contracts/interfaces.md keeps concurrency rule 2 as a binding design constraint for 002–004, independent of DG-2's normative status.
  I5: Add to US5: "Verified by design goal DG-1; acceptance pending the slow-upstream test."
  U2: Extend FR-020 with "or returns an Outcome that cannot be finalised or encoded".
  O3: In T034 use _finalise(query.message, ...).
  S4: Rewrap to 100 characters.
  G2 stays as documented deferral.
  Do not touch tests/ and do not write prompt-log entries.
  ```
- **Why this prompt:** resolve S-009's findings.
- **Expected:** targeted edits in spec.md and tasks.md.
- **Got:** all applied; FRs now cite contract.md and say "This spec adds: …". Rewrapped lines its own earlier edits had merged past 100 characters. It removed a tests/__pycache__/ directory its own --collect-only check had created. Left a stale "no branch was created" metadata line.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** S-012 (Feature Branch line)
- **Commit:** 

### S-011
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-009
- **Prompt:**
  ```
  /speckit-analyze
  ```
- **Why this prompt:** confirmation run after S-010, which rewrote many FRs. Stopping rule set beforehand: fix CRITICAL/HIGH once and then implement, without a fourth run.
- **Expected:** clean report.
- **Got:** S-010 fixes all held. One critical (C4): FR-005, FR-011, FR-016 and FR-017 still restated contract.md, the same finding as C2 and C3 for the third time. Only this run swept every FR. Also 3 low items: a broken Feature Branch line from a manual edit, a bad rewrap, and an edge case not matching the extended FR-020.
- **Verdict:** partly
- **Failure mode:** analyze found the same defect class across three runs because each run checked only part of the spec instead of sweeping it fully.
- **Fixed by:** S-012
- **Commit:** 

### S-012
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-011
- **Prompt:**
  ```
  Apply C4 as you recommended (FR-005, FR-011, FR-016, FR-017: cite, then "This spec adds", test lists unchanged), plus S5 (make the line **Feature Branch**: `001-parser-listener`), S6 and U3. Then stop. Do not touch tests/ and do not write prompt-log entries.
  ```
- **Why this prompt:** resolve S-011; per the stopping rule no further analyze run follows.
- **Expected:** four spec-only edits.
- **Got:** all four applied in spec.md only: FR-005, FR-011, FR-016 and FR-017 now cite contract.md and say "This spec adds"; Feature Branch line fixed; Shared state paragraph reflowed; handler-failure edge case extended to match FR-020. It checked that no line exceeds 100 characters. tests/ untouched.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-013
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** –
- **Prompt:**
  ```
  /speckit-implement Work through tasks.md in order. Stop after each phase checkpoint and report so I can review before continuing. Revert the temporary stub edits in T035 and T038 and show git diff afterwards. Do not modify tests/, do not commit, do not write prompt-log entries.
  ```
- **Why this prompt:** implement phase by phase with a human review at each checkpoint (Principle X), and keep temporary verification edits out of commits.
- **Expected:** Phase 1–2 (T001–T015): dnsd/__init__.py, parser.py model and wire helpers, listener.py shared types, Stats, placeholders, stub handler.
- **Got:** as expected; checkpoint passes (imports work, ruff and bandit clean). It discovered that unpinned ruff 0.17.3 enables far broader default rules (TRY, BLE, PLR, RUF) than the plan assumed (verified independently: BLE001 fires on a bare `except Exception` with no config). TRY004 conflicted with the contract's ValueError, which it kept with one justified noqa, and it flagged that the required catch-all excepts would hit BLE001. Unprompted additions: constructor type checks on name fields (to keep encode from raising), UTF-8 handling of non-ASCII in Name.from_text, Python patterns added to .gitignore. All reported for review.
- **Verdict:** worked
- **Failure mode:** – (tooling drift: plan assumed ruff's old default rule set)
- **Fixed by:** S-014 (keep ruff defaults, single-line justified noqa per Principle VII; pinning ruff to be raised with the team)
- **Commit:** 

### S-014
- **Module:** parser, listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-013
- **Prompt:**
  ```
  Keep ruff's defaults; use a single-line # noqa with a reason where the spec requires it (BLE001 for the FR-011/FR-020 catch-alls). Points 2–4 accepted. Continue with Phase 3.
  ```
- **Why this prompt:** settle the ruff question within Principle VII without changing shared CI config, and continue to US1.
- **Expected:** Phase 3 (T016–T024): decode_query, _finalise, _account, _process, UDP/TCP servers, serve(), __main__.py.
- **Got:** as expected; decode_query split into shared _read_header/_read_question for reuse by decode_message. T024: US1 gate tests 10/10 passed (including parametrised cases), non-error QR/RA cases 8 passed, quickstart one-liners correct over UDP and TCP; ruff/bandit clean, no noqa needed yet. It flagged on its own that T020's allow_reuse_address=True on UDP lets a second instance bind the same port silently.
- **Verdict:** worked
- **Failure mode:** – (task-level design flaw in T020, raised by the AI)
- **Fixed by:** S-015 (UDP reuse dropped)
- **Commit:** 

### S-015
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-014
- **Prompt:**
  ```
  Drop allow_reuse_address for the UDP server only; keep it for TCP. Then continue with Phase 4.
  ```
- **Why this prompt:** SO_REUSEADDR on UDP lets two instances bind the same port silently and split queries between them; TCP keeps it for fast restarts. Then continue to US2.
- **Expected:** one-line UDP fix; Phase 4 (T025–T029): bare FORMERR/NOTIMP replies, handler fallback, catch-alls.
- **Got:** as expected. Four single-line `# noqa: BLE001 - FR-0xx: <reason>` suppressions (two FR-020, two FR-011); it also moved the earlier TRY004 reason inline for consistency. T029: 31/31 cases passed, all 11 gate tests green. Deferred tests fail only on the final blocked-name probe (needs 004); fuzz fails at its first canary with SERVFAIL, never "server exited". ruff/bandit clean.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-016
- **Module:** parser
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-015
- **Prompt:**
  ```
  Continue with Phase 5.
  ```
- **Why this prompt:** next checkpoint; decode_message completes the interface 002–004 depend on.
- **Expected:** Phase 5 (T030–T032): _read_rdata, decode_message, contract check.
- **Got:** as expected. T032 checker executes the code blocks of contracts/interfaces.md and compares them programmatically with the modules instead of copying signatures by hand: 70 checks pass (first run had 2 failures caused by its own checker's alias handling, not by dnsd/). Round trip of compressed dnspython replies (7 answer/2 authority/2 additional; NXDOMAIN with SOA) gives equal records and readable SOA TTL/MINIMUM; 10,000 random/corrupted inputs never make either decoder raise; all malformed RDATA cases return Malformed. 41 gate cases still pass, ruff/bandit clean. Re-encoded replies grow without compression (273 → 470 bytes), as planned.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-017
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-016
- **Prompt:**
  ```
  Continue with Phase 6.
  ```
- **Why this prompt:** next checkpoint: truncation and OPT rules (US3).
- **Expected:** Phase 6 (T033–T035): OPT removal, UDP 512/TCP 65535 limits, verification with a temporary 40-record stub, reverted.
- **Got:** as expected; accounting stays once per query, after the size check. T035: with a temporary stub (40 A records plus an OPT record and TC=1, to exercise more rules) a scratch script passed 12/12 checks: UDP reply truncated to header+question with TC=1 and case kept, EDNS 4096 still limited to 512 with no OPT, TCP complete with TC=0 and OPT removed. Unprompted extras: ran the three deferred 40-record tests against the temporary stub (all pass); tested the 65535-byte TCP branch by calling _process directly with a scratch handler, without editing dnsd/. Revert verified byte-identical to a pre-edit snapshot; no TEMP lines; ruff/bandit clean.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-018
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-017
- **Prompt:**
  ```
  Continue with Phase 7.
  ```
- **Why this prompt:** next checkpoint: command line (US4).
- **Expected:** T036 verification of __main__.py; fixes only if needed.
- **Got:** all checks passed with no code change: host:port split at the last colon; missing or malformed flags give argparse usage and exit 2; zone/blocklist paths never opened (server starts with non-existent files); first UDP query answered 0.20 s after launch (SC-005: 5 s); harness test passes. Noted without changing anything: IPv6 brackets are kept by the split and the servers are IPv4-only, both outside contract.md's scope.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:**

### S-019
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-018
- **Prompt:**
  ```
  Continue with Phase 8.
  ```
- **Why this prompt:** next checkpoint: concurrency (US5, design goals DG-1/DG-2), checked by hand since no official test exists yet.
- **Expected:** T037 review, T038 manual check with a temporary slow stub, reverted.
- **Got:** T037 review found no violations, no code change. T038 with a temporary 1.5 s stub: 9/9 checks; a fast query was answered in 0.002 s (UDP) and 0.001 s (TCP) while the slow one was in progress (SC-004: 0.5 s); idle and half-prefix TCP connections closed after 5 s without slowing other clients. Revert verified byte-identical, no TEMP lines. Found that port 5353 is held by the system mDNS daemon: dnsd now refuses to start there, confirming the S-015 decision (with SO_REUSEADDR it would have shared the port silently). Noted a minor TCP write-timeout edge case near the 5 s deadline.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** S-020 (write timeout, quickstart port)
- **Commit:**

### S-020
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-019
- **Prompt:**
  ```
  Give the TCP reply write its own fixed timeout (one line), and change the quickstart port from 5353 to a free one. Then continue with Phase 9 and give the final report.
  ```
- **Why this prompt:** fix the two small issues found in S-019, then finish the polish phase (T039–T042).
- **Expected:** one-line write timeout, quickstart port change, lint/gate/fuzz/contract checks.
- **Got:** write gets its own 5 s timeout; quickstart moved to port 5300 and re-run exactly as written. T039 ruff/bandit clean (764 lines, no #nosec). T040 gate: 41/41 cases pass. T041: deferred tests fail only on the answer they expect; full 2000-packet fuzz stream via scratch script: all 20 checks answered, server never exited, nothing on stderr. T042: no public names beyond the contract, no unused code. All 42 tasks done. Final report lists every decision made along the way for the reviewer. Verified by hand afterwards: ruff/bandit clean; pytest harness+listener+fuzz gives 41 passed, 11 failed = 9 deferred tests (one parametrised ×3): 8 cases get SERVFAIL instead of the blocklist's NOERROR, 3 lack the big.home.lan zone records; none fail on "server exited" or "no response".
- **Verdict:** worked
- **Failure mode:** minor: its summary counts of deferred tests didn't add up (7 + 3); verified by hand: 9 tests / 11 cases, as expected
- **Fixed by:** –
- **Commit:**