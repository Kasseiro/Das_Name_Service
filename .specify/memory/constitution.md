<!--
Sync Impact Report
==================
Version change: (unratified template) → 1.0.0
Bump rationale: first ratification; all placeholders replaced with project content.

Principles (template slots → final titles):
- [PRINCIPLE_1_NAME] → I. RFC 1035 Is Authoritative
- [PRINCIPLE_2_NAME] → II. contract.md Is Binding and Frozen
- [PRINCIPLE_3_NAME] → III. Standard Library Only (NON-NEGOTIABLE)
- [PRINCIPLE_4_NAME] → IV. Every Requirement Maps to a Test
- [PRINCIPLE_5_NAME] → V. Never Crash on Any Input
- Added: VI. Secure Forwarding Defaults
- Added: VII. Clean Lint and Security Scan
- Added: VIII. Simplicity
- Added: IX. Fixed Module Boundaries
- Added: X. No Self-Merged AI-Generated Code

Added sections:
- Technical Constraints (template [SECTION_2_NAME])
- Development Workflow (template [SECTION_3_NAME])

Removed sections: none

Templates: not modified (they read the constitution at runtime).

Follow-up TODOs:
- Principle IX depends on the parser/listener spec, which does not exist yet. Until it is
  written, no module-to-module interface is ratified.
-->

# dnsd Constitution

## Core Principles

### I. RFC 1035 Is Authoritative

- RFC 1035 is the authority for DNS wire format and semantics.
- RFC 2308 (negative caching), RFC 4343 (case-insensitivity) and RFC 5452 (forgery
  resilience) apply only where `contract.md` cites them.
- Where neither `contract.md` nor a cited RFC defines a behaviour, RFC 1035 decides.

Rationale: one normative source keeps the parser, listener and resolution logic consistent,
and lets reviewers settle wire-level disputes by citation, not opinion.

### II. contract.md Is Binding and Frozen

- `contract.md` defines dnsd's external behaviour. It is frozen: no spec, plan, task or
  implementation change may alter it.
- Specs MUST reference `contract.md` sections by heading (for example
  "contract.md § Responses › Cache") instead of restating them.
- If a spec conflicts with `contract.md`, `contract.md` wins and the spec MUST be corrected.

Rationale: `contract.md` is shared with `Vibe_Name_Service` and is the basis of the black-box
test suite. Restating it invites drift; changing it would invalidate the comparison.

### III. Standard Library Only (NON-NEGOTIABLE)

- Code in `dnsd/` MUST use only the Python 3.11 standard library.
- DNS libraries (dnspython, dnslib and similar) and all other third-party packages are
  forbidden in `dnsd/`.
- DNS libraries and other test dependencies are allowed in `tests/` only, listed in
  `tests/requirements.txt`.

Rationale: the project builds the DNS protocol layer by hand; a library would replace the work
being evaluated. Tests may use dnspython as an independent reference implementation.

### IV. Every Requirement Maps to a Test

- Every functional requirement in a spec MUST name the test(s) in `tests/` that verify it
  in `tests/<file>.py::<test_name>` form.
- A requirement with no test MUST either get a test or be removed from the spec before the
  spec is accepted.
- A requirement is met only when its named tests pass under `pytest tests --impl .`.

Rationale: traceability from requirement to test makes compliance checkable and stops specs
from accumulating unverifiable claims.

### V. Never Crash on Any Input

- The server MUST NOT crash, hang or stop serving on any input it receives while
  running (UDP, TCP, admin API, upstream replies).
- All parsing MUST be bounds-checked before reading: lengths, offsets, label counts and
  compression pointers (including pointer loops).
- Malformed input MUST be handled as `contract.md` specifies (see contract.md § Responses ›
  Malformed and unusual queries). An unhandled exception in a request handler is a defect.

Rationale: a resolver is exposed to untrusted bytes; one bad packet must not take down name
resolution for the host. `tests/test_fuzz.py` exercises this.

### VI. Secure Forwarding Defaults

- Each upstream query MUST use a random 16-bit query ID and a random source port, chosen
  fresh for that query from a cryptographically secure source (`secrets`). Neither may be
  fixed, sequential or reused (contract.md § Responses › Forwarded queries, RFC 5452).
- Upstream replies whose ID does not match the outstanding query MUST be discarded.
- These defaults MUST NOT be configurable.

Rationale: predictable IDs or ports make cache poisoning practical.

### VII. Clean Lint and Security Scan

- Code in `dnsd/` MUST pass `ruff check dnsd` and `bandit -r dnsd` with zero findings.

Rationale: CI enforces both tools; zero findings keeps the gate meaningful.

### VIII. Simplicity

- No abstraction, extension point, option or configuration beyond what `contract.md`
  requires.
- Every new class, layer or setting MUST be traceable to a contract section or a named
  requirement; otherwise it is removed.

Rationale: the contract is fixed and small; generality beyond it is unreviewed surface area.

### IX. Fixed Module Boundaries

- `dnsd/` is divided into these modules: parser, listener, zone, forwarder, cache,
     blocklist, querylog, api, plus `__main__.py` as the entry point.
- The interfaces between modules are defined in the parser/listener spec. They change only
  by amending that spec; other specs reference it and do not redefine those interfaces.
- A module MUST NOT reach into another module's internals.

Rationale: three developers own different modules; a single interface definition lets them
work in parallel without integration surprises.

### X. No Self-Merged AI-Generated Code

- Nobody merges AI-generated code they produced themselves.
- Review follows the rotation Johnny → Daniel → Adam → Johnny: Johnny's code is reviewed by
  Daniel, Daniel's by Adam, Adam's by Johnny.
- The reviewer checks the change against this constitution, the referenced spec and
  `contract.md` before approving. Flaws found are recorded in `docs/audit-log.md`.

Rationale: AI-generated code needs an independent reviewer; a fixed rotation makes sure every
change has one.

## Technical Constraints

- Language and runtime: Python 3.11, standard library only (Principle III).
- Entry point: `python -m dnsd`, with the command line defined in contract.md § Command line.
- Protocols: DNS over UDP and TCP (contract.md § Responses, § Truncation, § TCP) and a JSON
  admin API over HTTP (contract.md § Admin API).
- CI (`.github/workflows/ci.yml`) runs ruff, bandit and the black-box suite on every push. A
  red CI run blocks merge.

## Development Workflow

- Order: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-analyze` → `/speckit-implement`, one spec per feature: parser + listener, zone +
  forwarder, cache, blocklist + admin API. The parser + listener spec comes first because it
  defines the inter-module interfaces (Principle IX).
- Spec Kit feature branches are kept after merge.
- Every Spec Kit call and implementation prompt whose output is committed is logged in
  `docs/prompt-log.md` with an `S-NNN` ID.
- Commit messages follow `<type>(<module>): <what changed>` with `Prompt:` and `Spec:`
  trailers, as described in `README.md`.

## Governance

- This constitution overrides all other project practices except `contract.md`, which it
  makes binding (Principle II).
- Amendments are made through `/speckit-constitution`, need approval from all three team
  members, and are committed with a message stating the version change.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle,
  MINOR for adding a principle or section or materially expanding guidance, PATCH for wording
  fixes.
- Every review (Principle X) and every `/speckit-analyze` run checks compliance with this
  constitution. A violation blocks merge until fixed or until the constitution is amended.

**Version**: 1.0.0 | **Ratified**: 2026-10-31 | **Last Amended**: 2026-10-31
