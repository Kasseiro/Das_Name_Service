<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0
Bump rationale: MINOR. Principle X's review rule is redefined for the current team, and the
CI merge gate gains a narrowly scoped exception for deferred tests. No principle is removed.

Modified principles:
- X. No Self-Merged AI-Generated Code (title unchanged): the Johnny → Daniel → Adam rotation is
  replaced by: Johnny builds all remaining features, Daniel reviews every PR before merge.
  Rationale updated to match (rotation no longer exists).

Modified sections:
- Technical Constraints: a red CI run still blocks merge, except for failures in tests the
  feature's spec lists as deferred to a later feature (spec § Verification status); the
  reviewer checks that every failure is one of those.
- Governance: amendments need approval from the active team members (Johnny and Daniel),
  not all three.

Added sections: none
Removed sections: none

Templates: not modified (they read the constitution at runtime).

Follow-up TODOs:
- Principle IX's rationale still refers to three developers owning different modules; left
  unchanged per the scope of this amendment.
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

Rationale: fixed boundaries and a single interface definition let each feature be specified, 
built and reviewed on its own without integration surprises.

### X. No Self-Merged AI-Generated Code

- Johnny builds all remaining features.
- Daniel reviews every PR before merge.
- Nobody merges AI-generated code they produced themselves.
- The reviewer checks the change against this constitution, the referenced spec and
  `contract.md` before approving. Flaws found are recorded in `docs/audit-log.md`.

Rationale: AI-generated code needs an independent reviewer; a fixed reviewer for every PR
makes sure every change has one.

## Technical Constraints

- Language and runtime: Python 3.11, standard library only (Principle III).
- Entry point: `python -m dnsd`, with the command line defined in contract.md § Command line.
- Protocols: DNS over UDP and TCP (contract.md § Responses, § Truncation, § TCP) and a JSON
  admin API over HTTP (contract.md § Admin API).
- CI (`.github/workflows/ci.yml`) runs ruff, bandit and the black-box suite on every push. A
  red CI run blocks merge, except for failures in tests that the feature's spec lists as
  deferred to a later feature (spec § Verification status). The reviewer checks that every
  failure is one of those.

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
- Amendments are made through `/speckit-constitution`, need approval from the active team
  members (Johnny and Daniel), and are committed with a message stating the version change.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle,
  MINOR for adding a principle or section or materially expanding guidance, PATCH for wording
  fixes.
- Every review (Principle X) and every `/speckit-analyze` run checks compliance with this
  constitution. A violation blocks merge until fixed or until the constitution is amended.

**Version**: 1.1.0 | **Ratified**: 2026-10-31 | **Last Amended**: 2026-11-01
