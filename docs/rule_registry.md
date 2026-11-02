# Rule registry

`src/atlas/domain/rules.py` provides an immutable, versioned registry for financial-system rules and simulator assumptions.

- Every entry has a stable rule ID, positive version, scope, and summary.
- New versions are append-only and strictly increasing per rule ID.
- `official_source` entries require a source title, HTTPS URL, and retrieval date; publication date is retained when known.
- `simulator_assumption` entries require an explicit rationale and cannot be labeled as official-source-backed.
- The current default registry is `atlas-rules-v1` and contains only `atlas.account.available_resources@1`, an internal accounting convention.

No Fedwire, CHIPS, FedNow, RTP, or ISO 20022 rule is currently registered or implemented. Before adding one, verify the primary source, record its publication/effective date and retrieval date, describe the modeled rule and any simplification, and add tests for the behavior.
