# AutoPhish integration for Nextcloud

[AutoPhish](https://autophish.io) is a phishing simulation platform that helps organizations test how employees respond to simulated phishing emails.

This integration supports Nextcloud phishing simulation workflows by keeping AutoPhish recipient lists up to date with selected Nextcloud groups. Map groups to dedicated target lists and synchronize memberships on a schedule or manually. Create campaigns, send simulations and review results in AutoPhish; this Nextcloud app handles recipient synchronization and does not provision AutoPhish accounts.

Supported baseline: **Nextcloud 32–35, PHP 8.3+** (within Nextcloud's supported PHP range). License: [AGPL-3.0-or-later](license.md). Install **AutoPhish** (`integration_autophish`) from Nextcloud’s Apps administration through the [App Store](https://apps.nextcloud.com/apps/integration_autophish). The [release pipeline](docs/releasing.md) signs, verifies and publishes version tags automatically after the owner configures its credentials. Manual installation remains available as a fallback; local development builds are explicitly labelled `-unsigned`.

## Install and configure

1. Download `integration_autophish-<version>.tar.gz` and its SHA-256 file from [Releases](https://github.com/LorenzLoesch/nextcloud_autophish_plugin/releases). Compare `sha256sum` with the published checksum. Extract into your configured writable Nextcloud app directory, normally `custom_apps/`, so `custom_apps/integration_autophish/appinfo/info.xml` exists. Set ownership to your Nextcloud service account.
2. As that service account, run `php occ app:enable integration_autophish` from the Nextcloud directory. Enablement needs no AutoPhish credentials and makes no AutoPhish call.
3. In AutoPhish, create an existing API key assigned to the intended company with **`targets:read` and `targets:write`**. Copy the company ID. Verify the email domains of intended recipients in AutoPhish before syncing. The app cannot grant scopes, change company assignments, or verify domains for you.
4. Open **Administration settings → Additional settings → AutoPhish**. Set the HTTPS AutoPhish origin, company ID and key. Save, then test access/load available lists.
5. Select a Nextcloud group and an existing ordinary dedicated list, or create a named empty list. Confirm the mirror behavior: a later successful sync removes list memberships absent from that group, including manual additions. Each mapping needs a distinct destination list. Graph/AD-managed and pseudonymous lists are rejected. Other lists and historical results are preserved.
6. Set the sync interval (5 minutes to 24 hours). Configure Nextcloud [system cron](https://docs.nextcloud.com/server/32/admin_manual/configuration_server/background_jobs_configuration.html). Run `php occ integration_autophish:sync` for a manual sync and inspect the result in settings. Cron and the command use the same lock and reconciliation service.

An API key is encrypted in Nextcloud app configuration with Nextcloud's crypto service. It is never returned to the settings page after saving. Protect Nextcloud's database and server secret together, including backups. This integration has no container-local persistence.

## Data flow

| Data sent to AutoPhish | Purpose |
| --- | --- |
| Bearer API key and `X-Company-Id` | Authenticate and select the explicitly assigned company |
| Administrator's chosen list label | Create a dedicated list when requested |
| Enabled selected group members' primary emails, trimmed/lowercased | Compare and add list memberships |
| Available display names, on new additions only | Populate name fields; preserve existing canonical names |
| Returned list/membership IDs and idempotency keys | Read and mutate only the mapped list |

Group/user IDs, configuration, mapping IDs, pending operation keys and aggregate run status stay in Nextcloud. There is no wider directory export, phone export, telemetry or customer data in logs. Destination reads retrieve member email/name fields from the mapped lists to compute the diff.

## Operation and errors

The app reads the entire source group and every destination page, adds missing members in bounded batches, verifies additions, then removes stale **list memberships**. It never calls company-wide deletion or hard-delete APIs. A confirmed empty group can empty its list. Missing/invalid/ambiguous source email, failed reads or additions block removals. Disabled/deleted mappings do no work; removing a mapping leaves remote members intact. Email changes add the new address before removing the old membership. Existing names are not synchronized.

The status page shows last run, last success, aggregate counts and safe error categories. Fix the cause and rerun; retries converge from current state. Each run has a five-minute operation deadline with a ten-minute owner lease. Very large lists must fit complete reads within that deadline; partial reads never trigger removal. A crashed owner expires automatically, and the next run resumes from the current membership diff. Common errors:

- **Authentication/company/scopes:** check key expiry/revocation, assigned company ID and both target scopes.
- **Validation/domain:** verify recipient domains and usable primary email addresses. Invalid source records block pruning rather than silently emptying a list.
- **Unsupported destination:** choose an ordinary, unmasked list without a directory sync mapping.
- **Rate limit/in-progress:** the client uses bounded `Retry-After` handling. If it exhausts retries, allow the next cron run or rerun manually.
- **Network/provider:** check HTTPS connectivity/certificates. Redirects are refused; configure the final origin directly.
- **Busy/configuration changed:** let the current sync finish, then retry settings or the command. Settings and sync share a lock.

An uncertain list-creation operation retains its idempotency key locally for a retry. Resolve it promptly, within the provider's idempotency retention window; after expiry, inspect existing lists before creating again to avoid duplicates.

## Update and remove

Back up Nextcloud configuration/database. Replace the app directory with the new release (remove old runtime files, preserve filesystem ownership) and run `php occ upgrade`, then confirm `php occ app:list` and the settings status. Same-origin/company configuration is retained during updates. Do not disable the app as an update step.

**Disabling as well as removing this app invokes Nextcloud's uninstall repair hook and clears its local key, settings, mappings, status, pending operations and scheduled job.** An already in-flight HTTP request may finish; cancelled work cannot start another request or recreate cleared local state. Re-enabling requires configuration again. Run `php occ app:remove integration_autophish` to remove it. No network connection is required for local cleanup. Remote lists, memberships and the externally created AutoPhish key remain under administrator control; delete/revoke them separately if desired. The app never claims remote cleanup occurred.

## Development and verification

Use PHP 8.3 and Node 24 (JavaScript syntax checks only). `composer install`, `npm ci`, `npm run lint`, `npm test`, `npm run build`. Tests mock every SaaS call. The archive uses an explicit runtime allowlist, deterministic timestamps/order/permissions and ships plain JavaScript/CSS without dev dependencies. `NEXTCLOUD_MAJOR=35 bash scripts/smoke-nextcloud.sh` selects the version (32, 33, 34 or 35) for disposable install, upgrade, cron/command and concurrent offline cleanup checks with SQLite (default: 32). CI tests all four majors, plus `NEXTCLOUD_MAJOR=35 NEXTCLOUD_SMOKE_DB=pgsql` and `NEXTCLOUD_MAJOR=35 NEXTCLOUD_SMOKE_DB=mysql` for PostgreSQL and MariaDB. See [release checks and signing tests](docs/releasing.md#local-checks). Docker is required for smoke checks; no live tenant is needed.

See [configuration](docs/configuration.md), [API client](docs/api-client.md) and [synchronization](docs/synchronization.md) for concise implementation behavior. Development docs/tests are in source only, outside the installable archive.
