# Code audit log

Owner: Adam. Everyone adds entries when a review or test catches something in AI output.

| ID | Module | Found by | Category | Issue | Resolution | Prompt / commit |
|---|---|---|---|---|---|---|
| SA-001 | querylog, api | review | compliance | Feature 004 built outside the Spec Kit workflow: no plan, tasks or analyze; no prompts logged; constitution Principle X (1.1.1) names Johnny as builder of all remaining features | Accepted (time constraints, all 244 tests pass); documented in README and prompt log | PR #5 (6cad020–7c0b59c) |

Category guide:
- **security**: predictable transaction IDs, fixed source port, accepting responses with the wrong ID, crash on malformed input
- **logic**: NXDOMAIN vs NODATA mixed up, TTL not decremented, CNAME not followed, wrong AA/RA flags
- **compliance**: anything that breaks an RFC 1035 rule or `contract.md`
