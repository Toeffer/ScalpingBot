# Phase 0 threat model

**Status:** Required security artifact for Phase 0  
**Scope:** Repository bootstrap and safety controls; no broker connectivity  
**Last reviewed:** 2026-08-03  
**Architecture references:** §15 and Phase 0 in §21

## 1. Security objective

Phase 0 must establish controls that make unsafe extension difficult and
visible. The principal safety claim is narrow: this revision cannot connect to
IBKR or submit an order, defaults to simulation, rejects paper and live startup,
rejects malformed configuration, avoids binary floating-point financial input,
redacts known sensitive data from structured logs, and preserves a kill-switch
latch across restarts.

Phase 0 is not production-ready. It does not authenticate an operator, verify a
broker account, reconcile positions, provide a PostgreSQL journal, or implement
the independent live gates required by architecture §15.4. Those missing
controls are reasons for live denial, not deferred warnings.

## 2. Assets to protect

- Future broker credentials, session material, and account identifiers.
- The guarantee that no unauthorized live order can be created.
- Risk limits, environment identity, configuration integrity, and emergency
  state.
- Audit and log confidentiality and integrity.
- Source, lockfile, CI configuration, build artifacts, and review evidence.
- Host, database, notification, and deployment credentials introduced later.
- Availability of the safety controls themselves.

No real account data or credentials are valid test fixtures.

## 3. Actors and trust boundaries

Relevant actors are an authorized developer, an authorized operator, a
mistaken or malicious insider, a compromised dependency or developer tool, an
attacker with filesystem access, an attacker controlling configuration input,
and an automated coding agent that weakens a control to complete a task.

The current trust boundaries are:

1. Version-controlled source and reviewed configuration versus untrusted local
   environment variables and files.
2. Typed application code versus the mutable kill-switch state directory.
3. Structured event fields versus the log sink and its readers.
4. Locked project inputs versus package indexes and third-party build tools.
5. Pull-request code versus protected CI and reviewer approval.

Broker, database, network, administrative-command, and production-host
boundaries are outside the Phase-0 runtime because those integrations do not
exist yet.

## 4. Threats and controls

| Threat | Phase-0 controls | Residual risk / required next control |
| --- | --- | --- |
| Accidental live activation | Simulation default; explicit environment enum; profile/environment match; unconditional live denial even with live_enabled=true; no live run script | Later phases must implement and independently test every §15.4 gate |
| Hidden broker access | No IBKR dependency, adapter, socket, or order interface; AST and dependency tests prohibit known IBKR packages | Review transitive dependencies and network behavior as adapters are introduced |
| Configuration typo or smuggled key | Frozen nested models use extra=forbid; safe YAML parser; input size bound; symlink rejection; checked-in schema and canonical configuration hash | Signed production configuration and controlled reload are later controls |
| Financial precision loss | Quoted decimal-only inputs; Decimal values; process-start context pin; local financial contexts; invalid/divide-by-zero/overflow/float traps | Database NUMERIC round-trip tests arrive with persistence |
| Log leakage | Structured facade; recursive sensitive-key redaction; account, token, credential, URL, email, and private-key pattern filters; exception-message redaction tests | Redaction is pattern-based and cannot recognize every secret; log access control and tamper resistance remain deployment duties |
| Kill-switch reset on restart | Atomic durable file, strict versioned schema, UTC audit history, global startup check, explicit clear method, no timer or automatic clear | File storage is single-host and not a substitute for the PostgreSQL journal or authenticated operator workflow |
| Kill-switch state corruption | Size bound, strict JSON schema, symlink rejection, atomic replace and fsync; corruption raises a categorized failure | Host loss and disk failure need replicated persistence, monitoring, and runbooks |
| Dependency substitution or compromise | Exact production pins, complete uv lock with hashes, reviewed runtime licence policy, frozen install in CI, pip-audit, Dependabot, and static analysis | Registry compromise and malicious-but-unflagged releases remain possible; release signing and SBOM are later hardening |
| Secret committed to Git | Ignore rules, detect-secrets pre-commit/CI gate, and an ephemeral synthetic-secret self-test | History rewriting and credential rotation are required if a real secret is ever committed |
| CI workflow tampering | Minimal permissions, pinned action commits, frozen dependency sync, separate security gates | Repository administrators remain trusted; protected branches and required reviewers must be configured on the hosting service |
| Denial of service through oversized input | Configuration and emergency-state size limits; bounded parsing surface | Event/log rate limits and bounded queues arrive with runtime services |
| Automated contributor weakens safety | Binding AGENT.md rules; architecture tests; control-focused tests; review requirement for security, risk, broker, and deployment changes | Human review and branch protection are organizational controls and cannot be enforced solely in this repository |

## 5. Kill-switch trust decision

The Phase-0 kill switch uses a local JSON document because there is no database
yet. Writes use a same-directory temporary file, flush and fsync before atomic
replacement, and restrict permissions where the operating system supports it.
The file has a versioned strict schema, revision counter, active records, and
append-only action history. A repeated latch for the same scope is idempotent.

This design protects against ordinary process crashes and restarts. It does not
provide multi-process locking, remote durability, or strong protection against
an administrator who can rewrite the filesystem. Before paper execution, the
authoritative latch must move to transactional persistent storage while startup
continues to fail closed when that storage is unavailable.

## 6. Secrets and test data

Phase 0 accepts no broker credential fields. Future secret values must be
referenced through an OS key store or managed secret manager and must never be
accepted as command-line arguments. Tests construct realistic secret patterns
from fragments at runtime so the repository itself does not contain a scanner
exception. The scanner self-test creates an ephemeral synthetic key, requires
the scanner to reject it, and does not print the value.

If a real secret is exposed, stop the affected service, revoke or rotate the
credential, preserve the incident evidence, remove the value from active
history using an approved procedure, and review logs and artifacts for further
exposure. Merely deleting the current file is not remediation.

## 7. Verification and review triggers

The threat model must be reviewed whenever a broker, database, network listener,
secret provider, administrative command, remote log sink, new dependency, or
live gate is added; after every security incident; and for every release.

Phase-0 verification includes strict configuration tests, independent live
denial, durable latch restart tests, corruption failure, realistic log-redaction
fixtures, decimal context assertions, a no-broker architecture test,
secret-scanner self-test, static analysis, dependency audit, schema drift check,
and frozen dependency installation.

