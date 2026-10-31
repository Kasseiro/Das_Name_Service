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
