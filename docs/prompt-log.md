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

### S-021
- **Module:** (project)
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-01
- **Refines:** S-001
- **Prompt:**
  ```
  /speckit-constitution Amend to version 1.1.0 (MINOR). Change only these:
  1. Principle X: Johnny builds all remaining features; Daniel reviews every PR before merge. Nobody merges their own AI-generated code.
  2. Technical Constraints: a red CI run blocks merge, except for failures in tests that the feature's spec lists as deferred to a later feature (spec § Verification status); the reviewer checks that every failure is one of those.
  3. Governance: amendments need approval from the active team members (Johnny and Daniel).
  Update the Sync Impact Report. Change nothing else. Do not write prompt-log entries.
  ```
- **Why this prompt:** change of plan: Adam unavailable, Daniel finishing the vibe build, so Johnny builds 002–004 and Daniel reviews. Also, the 1.0.0 CI rule made it impossible to merge any feature first, because CI runs the whole suite (raised in the 001 PR and approved there).
- **Expected:** three targeted edits, version 1.1.0, updated Sync Impact Report.
- **Got:** the three edits plus one unrequested but necessary change (Principle X's rationale still mentioned the rotation), all reported. It flagged that by the constitution's own versioning rule the Principle X change could count as MAJOR (2.0.0); kept MINOR as instructed, since the rule itself (independent review, no self-merge) is unchanged and only the reviewer assignment changed. It left Principle IX's rationale ("three developers") stale on purpose and listed it as a follow-up.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** manual edits: Principle IX rationale updated; README review-order bullet and change-of-plan note added
- **Commit:**

### S-022 ★
- **Module:** zone, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** –
- **Prompt:**
  ```
  /speckit-specify Feature: local zone, forwarder and the real resolution handler for dnsd. Builds on feature 001: use the message model, Query/Outcome/Handler, ServerState and the store roles from specs/001-parser-listener/contracts/interfaces.md; import shared types from dnsd.listener and do not redefine them (Principle IX).

  Scope:
  - Zone file loading per contract.md § Zone file, at startup, before the server answers (FR-005 of 001). A ZoneStore filling the zone role exactly as interfaces.md defines it, including the operations the admin API will use (records, add, remove, make_record, value_text).
  - Local answers per contract.md § Responses and § Zone file: records, NODATA, NXDOMAIN under a local zone suffix, CNAME handling, AA=1.
  - Forwarder per contract.md § Forwarded queries: random query ID and source port per query from secrets (Principle VI), only replies with a matching ID count, 2 s budget, TCP retry on TC=1, SERVFAIL on timeout or failure.
  - The real resolution handler that replaces stub_handler: applies the rows of contract.md § Responses top to bottom (local zone, blocked, cache, forward), building the blocked responses itself and calling the blocklist and cache roles through ServerState. Until features 003 and 004 replace their placeholders, those branches never fire.
  - Outcome fields per 001's interface: result and upstream_asked set correctly for every path.

  Out of scope: the cache store's logic (003), the blocklist store, query log store and admin API (004).

  Verified by: tests/test_zone.py, tests/test_forwarder.py, and the three deferred 001 tests that need big.home.lan (test_udp_response_over_512_bytes_is_truncated, test_truncated_answer_is_complete_over_tcp, test_edns_does_not_raise_udp_limit).
  ```
- **Why this prompt:** specify 002 on top of 001's interfaces; put the contract's response-table logic (including blocked responses) in the handler so later features only supply stores.
- **Expected:** spec.md with FRs mapped to tests in test_zone.py and test_forwarder.py.
- **Got:** spec.md with 22 FRs, each naming its tests, and a checklist. One clarification question: whether an upstream SERVFAIL relayed to the client is logged as "forwarded" or "error" (the contract's wording fits both; no test checks it). It also found on its own that 14 of 34 tests could not pass in 002 however correct the code: the test harness probes readiness with ads.example.com, which without a blocklist goes upstream and makes every exact upstream-count assertion off by one. This included the two random-ID/port security tests (Principle VI), for which it proposed a manual check.
- **Verdict:** partly
- **Failure mode:** – (scope problem caused by the feature split, found by the AI)
- **Fixed by:** S-023 (Q1 answered; Blocklist store moved into 002)
- **Commit:** 

### S-023 ★
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-022
- **Prompt:**
  ```
  Q1: A.

  Scope change: since I am building all features, move the Blocklist store into 002: blocklist file loading per contract.md § Blocklist file at startup, and a store filling the blocklist role exactly as interfaces.md defines it (is_blocked with whole-label, case-insensitive matching; domains, add, remove). 004 keeps only the query log store and the admin API. Update the spec accordingly: scope, requirements with their tests, and Verification status. Recount which tests are still deferred and to which feature (003 cache, 004 querylog/api), and drop the manual security check if the random ID/port tests become verifiable. Do not touch tests/ and do not write prompt-log entries.

  (follow-up) Apply the follow-ups in this branch:
  1. Constitution § Development Workflow: change the feature list to "parser + listener, zone + blocklist + forwarder, cache, query log + admin API". Version 1.1.1 (PATCH), update the Sync Impact Report; Daniel approves it in the 002 PR.
  2. README.md: update the feature list on line 38 the same way. Keep my existing edits.
  3. 001: in contracts/interfaces.md change the blocklist owner from 004 to 002. In 001 spec.md § Verification status add one line: "Superseded 2026-11-02: the blocklist store moved to 002; the six blocklist-dependent tests are verified there (see 002 § Verification status)." Change nothing else in 001.
  4. 002 checklist Notes: remove the stale Principle IV note about 14 deferred tests and the manual FR-013 check.
  Do not touch tests/ and do not write prompt-log entries.
  ```
- **Why this prompt:** Q1 per the contract's literal "error (SERVFAIL)". Moving the blocklist into 002 removes the off-by-one caused by the harness's readiness probe, so 002 can be verified on its own, including the Principle VI tests, without manual checks. The follow-ups bring the constitution, README and 001 in line with the new split.
- **Expected:** spec updated with the blocklist in scope and tests recounted; the follow-up edits in the other files.
- **Got:** spec rewritten: User Story 4 (blocking), FR-002/003 (blocklist loading), FR-013/014 (Blocklist store), FRs renumbered to FR-001–FR-025, Q1 and the scope change recorded under Clarifications. Recount: 65 tests required (13 zone, 22 forwarder, 10 blocklist, all 20 listener/fuzz/harness); deferred: 9 to 004, 2 to 003, 4 to 003+004; none of 001's tests deferred any more; manual security check dropped. It found on its own that the constitution, README and 001's spec and interfaces.md still described the old split, and left them unedited until asked. Follow-up: constitution 1.1.1 (PATCH) with an updated Sync Impact Report, README feature list, the 001 blocklist owner changed in both places in interfaces.md (one more than named, needed for consistency), the superseded note added verbatim; the stale checklist note had already been removed in the rewrite.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-024
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** –
- **Prompt:**
  ```
  /speckit-plan Python 3.11, standard library only. Keep it minimal (Principle VIII).
  - Files: dnsd/zone.py (zone file loading, ZoneStore), dnsd/blocklist.py (blocklist file loading, Blocklist store), dnsd/forwarder.py (upstream exchange and the real handler factory, (ServerState) -> Handler). __main__.py changes only to load both files and install the real stores and handler. No changes to parser.py or listener.py signatures (001 interfaces.md is binding).
  - Forwarder: socket module directly, secrets for ID and port, one deadline of 2 s for the whole exchange including TCP retry.
  - Stores: one threading.Lock each, per 001 concurrency rules.
  - Missing or malformed zone/blocklist file: print the problem to stderr and exit non-zero before serving.
  - Verification is the existing suite; do not add or modify tests/. Do not write prompt-log entries.
  ```
- **Why this prompt:** pin files and technical choices up front as for 001. The handler goes in forwarder.py, because Principle IX has no resolver module.
- **Expected:** plan, research, data model, contract and quickstart within the given constraints.
- **Got:** all artifacts; Constitution Check (v1.1.1) passes before and after design. 10 decisions in research.md. contracts/modules.md lists the new public names (load_zone, load_blocklist, exchange, make_handler), only imported by __main__; the stores keep exactly their role's methods, so the loaders are module functions. Forwarder: fresh secrets ID (also for the TCP retry) and source port, UDP socket connected to the upstream, reply must match ID and question, one 2 s deadline. Blocked answers built as IPv4Address(0)/IPv6Address(0) to avoid bandit's "0.0.0.0" check. Four decisions flagged for review: ";" comments in zone lines (RFC 1035), blocklist lines with an inline "#" treated as malformed, UDP bind to ("", port) not yet run through bandit, a record directly under the root makes unmatched names NXDOMAIN.
- **Verdict:** worked
- **Failure mode:** – (one harsh default: inline "#" in the blocklist refuses startup)
- **Fixed by:** S-025 (inline "#" treated as comment)
- **Commit:** 

### S-025
- **Module:** blocklist
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-024
- **Prompt:**
  ```
  Change one decision: in the blocklist file, text from "#" to the end of a line is a comment (contract.md leaves it unspecified), so "ads.example.com # ads" lists ads.example.com. Update research.md and wherever else it appears. Everything else accepted. Do not write prompt-log entries.
  ```
- **Why this prompt:** refusing to start over an inline annotation is harsh; the contract leaves it unspecified, so the forgiving rule is better.
- **Expected:** decision changed in research.md and wherever it is referenced.
- **Got:** R-2 rewritten (cut each line at the first "#"; covers whole-line and trailing comments with one step, mirrors the zone file's ";" rule; "#" cannot occur in a hostname); old rule kept as the rejected alternative. data-model.md, the spec's edge case and plan.md's Principle II row updated to match; it confirmed the other artifacts don't mention the rule.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-026
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** –
- **Prompt:**
  ```
  /speckit-tasks
  ```
- **Why this prompt:** break the 002 plan into ordered, reviewable tasks.
- **Expected:** tasks.md touching only zone.py, blocklist.py, forwarder.py and __main__.py; no test tasks.
- **Got:** 31 tasks (T001–T031) in 10 phases, one per user story plus setup, foundational and polish. Ordered US4 (blocklist) before US5 (forwarding), because the forwarder tests need the harness's readiness probe to be blocked. A temporary SERVFAIL branch in the handler (T005) lets the server start early; T015/T020 replace it and T031 checks none is left. Flags three tests that pass early by accident (SERVFAIL already satisfies "not blocked"). Manual checks for startup errors (T028) and unreachable upstream; T030 defines which full-suite failures are acceptable (only 003/004-deferred, never "dnsd exited"/"no response"). It corrected its own task cross-references and parallel markers in a second pass.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:**

### S-027
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** –
- **Prompt:**
  ```
  /speckit-analyze
  ```
- **Why this prompt:** cross-check the 002 artifacts before implementation.
- **Expected:** a few findings.
- **Got:** 1 critical, 1 medium, 7 low. C1 (Principle IV): three FRs had clauses no named test could check (FR-003 "never written", FR-016's random ID on the TCP retry, FR-025's no-accounting/no-lock rules), the same pattern as in 001. W1: /speckit-clarify was never run; Q1 was settled during specify. Lows: stale "plan picks" wording (I1), QR=1 check missing from the assumptions (I2), trailing-# rule only in edge cases (I3), duplicated "not forwarded" clause (D1), tests that pass trivially under the temporary SERVFAIL (U1), unused 001 placeholders (U2), a vague bandit fallback (U3). Read-only.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** S-028
- **Commit:** 

### S-028
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-027
- **Prompt:**
  ```
  Apply these, then stop:
  C1: as you recommend. FR-003: drop "neither is ever written" (contract.md § Command line says it). FR-016: keep the TCP-retry ID rule, marked as checked by review (T022), not by a test. FR-025: name tests/test_admin_api.py::test_stats_queries_counts_udp_and_tcp † for the Stats/log part; move "no lock while calling a store or the network" into a binding design constraint citing 001 interfaces.md rule 4, as 001 did for rule 2.
  I1: state R-3's decision in the Assumptions and the edge case.
  I2: add QR=1 to the Assumption on stricter reply checks.
  I3: add the trailing-# rule to FR-002.
  U1: add the three trivially-passing blocklist tests to T021's command.
  U2: add to T031 that stub_handler and the two placeholders stay in listener.py on purpose (R-9).
  U3: spell out the bind fallback in T027 as you describe.
  Skip D1. Do not touch tests/ and do not write prompt-log entries.
  ```
- **Why this prompt:** resolve C1 the way 001 did, and take the cheap low items that make implementation smoother. W1 is accepted: as in 001, clarification happened inside the specify step (Q1, recorded in § Clarifications), so /speckit-clarify was skipped. No second analyze run: the only critical finding was narrow.
- **Expected:** spec and task edits only.
- **Got:** all applied in spec.md and tasks.md only. FR-003 trimmed; FR-016 notes the TCP-retry ID is checked by review (T022); FR-025 names test_stats_queries_counts_udp_and_tcp (double counting would fail it); new "Design constraints (binding; no test)" section with DC-1 (no lock while calling a store or the network, citing 001 rule 4). R-3's decision, QR=1 and the trailing-# rule stated in the spec. T021 re-runs the three trivially-passing tests, T031 documents the unused 001 placeholders, T027 spells out the bind fallback. It also pointed T026's review at DC-1 unasked, to keep the references consistent.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-029
- **Module:** zone, blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** –
- **Prompt:**
  ```
  /speckit-implement Work through specs/002-zone-forwarder/tasks.md in order. Stop after each phase checkpoint and report so I can review before continuing. Do not change dnsd/parser.py or dnsd/listener.py. Do not modify tests/, do not commit, do not write prompt-log entries.
  ```
- **Why this prompt:** implement 002 phase by phase with a review at each checkpoint (Principle X); keep 001 code untouched (Principle IX).
- **Expected:** Phase 1 (T001): baseline check.
- **Got:** tools confirmed (ruff 0.17.3, bandit 1.9.4, pytest 9.2.0); the 11 001 gate tests pass before any change (41/41 cases). Only the task checkbox changed.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-030
- **Module:** zone, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-029
- **Prompt:**
  ```
  Continue with Phase 2
  ```
- **Why this prompt:** next checkpoint: foundational zone store, loader and handler skeleton (T002–T006).
- **Expected:** dnsd/zone.py, dnsd/forwarder.py skeleton, __main__.py wiring; 001 tests still green.
- **Got:** as expected. ZoneStore with one lock, records by name and derived suffixes; make_record/value_text pure; load_zone with ";" comments, five-field check and errors as "<path>:<line>: …". make_handler answers from the zone and otherwise returns a temporary SERVFAIL marked for T031. __main__ loads the zone (stderr + exit 1 on error) and installs the real handler. ruff/bandit clean, 001 gate 41/41, parser.py and listener.py unchanged. Manual checks: 46 fixture records, value_text forms, make_record rejects MX, negative/boolean TTL, scoped IPv6 and "01.2.3.4". It resolved a ruff TRY004 finding by restructuring the code instead of suppressing it.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-031
- **Module:** zone
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-030
- **Prompt:**
  ```
  Continue with Phase 3
  ```
- **Why this prompt:** next checkpoint: local answers (US1, T007–T008).
- **Expected:** lookup returns Answer for matching records; US1 tests and the three big.home.lan tests deferred from 001 pass.
- **Got:** as expected; 11 tests (13 cases) pass, including the three 001-deferred truncation/EDNS tests and the full check of test_truncated_response_keeps_question_and_whole_records. ruff/bandit clean, 001 files unchanged.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-032
- **Module:** zone
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-031
- **Prompt:**
  ```
  Continue with Phase 4
  ```
- **Why this prompt:** next checkpoint: negative local answers (US2, T009–T010).
- **Expected:** lookup returns NoData / NXDomain per contract.md; US2 tests pass, US1 still green.
- **Got:** as expected; test_nodata and test_nxdomain_under_local_suffix pass, US1 set still green (25/25 cases). Unprompted edge checks: the suffix itself (home.lan.) and a name below a local name give NXDomain; lan., other.lan. and the root stay NotLocal. ruff/bandit clean, 001 files unchanged.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:**

### S-033
- **Module:** zone
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-032
- **Prompt:**
  ```
  Continue with Phase 5
  ```
- **Why this prompt:** next checkpoint: one-step CNAME (US3, T011–T012).
- **Expected:** CNAME case between "records of this type" and NODATA; CNAME tests pass.
- **Got:** as expected; CNAME first, then target records of the requested type only if the target is local; one step only; a CNAME query still returns just the CNAME. Three CNAME tests pass, US1–US2 still green (29/29 cases). ruff/bandit clean, 001 files unchanged.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-034
- **Module:** blocklist, forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-033
- **Prompt:**
  ```
  Continue with Phase 6
  ```
- **Why this prompt:** next checkpoint: blocklist store, loader and blocked responses (US4, T013–T017).
- **Expected:** dnsd/blocklist.py, blocked branch in the handler, __main__ wiring; blocklist tests and the 001 blocklist-dependent tests pass.
- **Got:** as expected. Blocklist store with one lock, case-insensitive de-duplication, whole-label matching by walking up to the root; load_blocklist with "#" comments, one domain per line, "<path>:<line>: …" errors. Handler builds 0.0.0.0/:: with TTL 60 and AA=0, or NXDOMAIN for other types, result "blocked". test_blocklist.py 22/22 cases (three pass trivially until forwarding exists, as T017 notes), the five 001 listener tests 7/7, US1–US3 29/29; fixture loads its four entries; a malformed line exits 1. ruff/bandit clean. Its report did not mention the sixth 001-deferred test (fuzz); verified by hand: <passed / failed>.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-035
- **Module:** forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-034
- **Prompt:**
  ```
  Continue with Phase 7
  ```
- **Why this prompt:** next checkpoint: upstream exchange and the cache/forward branch (US5, T018–T021).
- **Expected:** exchange() with UDP, TCP retry and one 2 s deadline; handler forwards and replaces the temporary SERVFAIL.
- **Got:** as expected. exchange: secrets-drawn ID and source port (each in one helper, for an easy Principle VI review), UDP socket connected to the upstream, reply counts only with QR=1, matching ID and question, TCP retry with a new ID, any OSError → None. Handler: cache get → "cached"; failure → SERVFAIL "error" without put; reply → put, then relay RCODE and sections with AA=0, "error" if the upstream said SERVFAIL (Q1). Bandit accepted the ("", port) bind, so the T027 fallback is unneeded. T021: 19 tests / 26 cases pass, including the TCP retry and the three formerly trivial blocklist tests; regression over zone/blocklist/listener/harness 99/99. 001 files unchanged.
- **Verdict:** worked
- **Failure mode:** –
- **Fixed by:** –
- **Commit:** 

### S-036 ★
- **Module:** forwarder
- **Who / tool / model:** Johnny / Claude Code v2.1.316 / Claude Opus 5.5 (effort high)
- **Date:** 2026-11-02
- **Refines:** S-035
- **Prompt:**
  ```
  Continue with Phase 8
  ```
- **Why this prompt:** next checkpoint: Principle VI review and spoofing/failure checks (US6, T022–T024).
- **Expected:** review of exchange; US6 tests pass; manual unreachable-upstream check.
- **Got:** the T022 review confirmed ID/port come only from secrets, fresh per call, a new ID on the TCP retry, nothing configurable, one deadline. It found a real defect in its own Phase 7 code: the TCP sendall used the connect-time timeout instead of the remaining budget, so a slow connect plus a slow send could overrun 2 s; fixed with one settimeout line. T023: 8 US6 tests pass (random ID/port, wrong ID ignored, timeouts over UDP and TCP, recovery, full fuzz stream); the TCP-retry tests re-run after the fix, 10/10. T024: unreachable upstream gives SERVFAIL in 0.002 s (ICMP on the connected socket), the server keeps answering, nothing on stderr. This also confirms the 001-deferred fuzz test now passes.
- **Verdict:** worked
- **Failure mode:** deadline bug in its own S-035 code, caught by its own review task before commit
- **Fixed by:** same prompt
- **Commit:** <hash>