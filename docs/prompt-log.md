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
