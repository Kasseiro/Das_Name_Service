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