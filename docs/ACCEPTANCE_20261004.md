# Acceptance gate — 2026-10-04

Status: local regression and HTTP credential boundary verified; real Emby/Telegram lifecycle acceptance BLOCKED by missing dedicated integration configuration. Do not merge or deploy based on this gate alone.

The pre-fix audit head was 1d89071961fe157451c19303385237d694735a54. Its existing 45 tests and six core smoke groups passed again in an isolated source snapshot. No production application, account or database was changed.

## Credential transport correction

The Emby client previously duplicated its API key into the URL query, logged raw upstream response bodies and exception strings, and followed redirects while carrying its custom authentication header. An upstream error or cross-origin redirect could expose credentials.

Authentication now uses X-Emby-Token only, redirects are refused, and failures log HTTP status or exception class without response body, URL, query or secret-bearing exception text. Configure the canonical Emby URL directly; a redirect response is an actionable configuration failure, not permission to forward credentials to another origin.

Four deterministic regressions failed before the correction and pass after it. They use a real, ephemeral localhost HTTP server for header/query authentication, 200 JSON/204 responses, body-reflecting failures and cross-origin redirects, plus a controlled connection exception. All keys and user data in these tests are fixtures. This transport test is not a connection to a real Emby deployment.

## Release prerequisites

- Configure a dedicated test Emby administrator API key and server URL; verify a safe non-administrator user template. Do not reuse a subscriber playback token or an unrelated Bot token.
- Configure a dedicated Telegram test Bot and owner-only private test destination. Back up an existing test DB with SQLite backup plus integrity_check; otherwise initialize a new isolated DB and verify old-schema migration on a copy.
- Use unique fixture accounts to verify create/password/template policy, expiry disable, renewal re-enable, administrator-ban preservation, duplicate redemption and private credential delivery failure. Test deletion must be limited to accounts created by this acceptance run.
- Keep Bot, scheduler and Web in one process sharing one Database instance; no multi-worker or multi-replica deployment. Account locks are process-local.
- Verify scoped rollback against the pre-change source/config/database backup, preserving newer owner changes. Do not reset an unrelated production checkout.

No dedicated EP Emby/Telegram configuration, running EP service/container or EP production database was identified in the inspected AWS/LA project locations. This is a scoped inventory result, not proof that no instance exists elsewhere. External lifecycle tests remain NOT RUN. A getMe response or mock test cannot substitute for actual delivery and lifecycle verification.
