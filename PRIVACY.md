# Privacy behavior and limits

Client planning, contacts, consent, revisions and registered assets stay in local agency storage. Optional local-text drafting sends selected fields only to the configured loopback runtime. Optional ASR processes the private asset in a local CPU subprocess. Online Research is disabled by default and makes explicit allowlisted requests. Existing media providers retain their separate selected-provider behavior.

Privacy & Retention provides:

- One editable retention policy per client, review age, purpose and legal hold. Retention review lists actual old records; no automatic deletion runs.
- Client-specific ZIP portability export: current records, revisions, references, audit, research originals, all registered file versions and checksum manifest. The 128 MB export is separate from full agency backup/restore.
- Explicit erasure preview with counts, client version and a review token. Any intervening recorded change invalidates that review. The operator must type DELETE CLIENT followed by the exact client ID. Legal holds and active jobs block erasure.
- Erasure removes the client's active SQLite data and research originals; registered files shared by another client's current or historical asset are retained. It returns any file cleanup failures for manual action. A non-identifying deletion event remains. Erasure was tested only against isolated temporary clients.

Prior backups, exported ZIPs, downloaded/browser-local copies and independent Image/GIF/Video Studio files remain outside client erasure. The preview explicitly explains this boundary. Rotate or remove those copies separately; no forensic disk erasure or legal-compliance certification is claimed. Archive retains history and differs from erasure.

Contact consent requires source/purpose/evidence for a grant. The server timestamps changes; immutable revision history retains withdrawals. Suppression, unsubscribe, unknown consent and archived state override segment membership. Explicit CSV imports cannot grant consent. Test-kit recipient snapshots are recomputed at export; old downloaded lists cannot be recalled. Delivery infrastructure and a functioning unsubscribe service are separate responsibilities.

Protect database, backups, exports and logs through OS storage/access controls. Full backups include ALL clients. Clear site data/localStorage when retiring a shared workstation. No hosted AI, email sender, remote tracker or public publishing service is introduced by these workflows. Multi-user permissions and authenticated client review are not implemented. Apply an organizational/legal process before processing real marketing lists.
