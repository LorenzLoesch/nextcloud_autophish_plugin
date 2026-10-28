# Releasing AutoPhish for Nextcloud

The release workflow builds everything in GitHub Actions. After the one-time owner setup, pushing a version tag on `main` creates a verified, signed GitHub Release and publishes it to the Nextcloud App Store. No developer machine participates in the build or signing process.

## One-time owner setup

Lorenz is responsible for the Nextcloud developer account, application registration, signing certificate and GitHub secrets. The app ID and certificate CN must both be `integration_autophish`.

1. Create an RSA-4096 key and CSR in a trusted environment, following [Nextcloud's code-signing instructions](https://docs.nextcloud.com/server/stable/developer_manual/app_publishing_maintenance/code_signing.html). Request an app certificate through `nextcloud/app-certificate-requests`. Keep the unencrypted PEM private key only in the password manager and GitHub Actions secrets; do not add it to this repository or an agent workspace.
2. Register the app and issued certificate in the App Store developer account. Obtain an API token from the account settings.
3. In repository Settings → Secrets and variables → Actions, add repository secrets `APP_PRIVATE_KEY` (unencrypted PEM) and `APP_CERTIFICATE` (issued PEM certificate). Both signing jobs need these repository secrets.
4. Create the GitHub environment `appstore` and add its secret `APPSTORE_TOKEN`. Restrict its deployment refs to release tags. Leave required reviewers disabled for fully automatic publication; a reviewer may be added later if manual approval is desired.
5. Optionally set the repository variable `PUBLISH_PRERELEASES=true`. Without it, beta/RC tags create a signed GitHub prerelease but skip the store. Missing `APPSTORE_TOKEN` also skips store publication and catalogue verification, with a visible job summary; it does not claim a successful store release.

No signing key is passed as a Docker environment variable or command argument. Jobs write the key and certificate using `printf '%s'` under `umask 077` in a temporary directory, mount them read-only, and remove the directory and disposable container on exit. Do not enable shell tracing in these scripts.

## Cut a release

1. Update `appinfo/info.xml`, `package.json` and the root/package version entries in `package-lock.json` to the same version. Add a non-empty `## X.Y.Z` section to `CHANGELOG.md`, following Keep a Changelog. Supported versions are `X.Y.Z`, `X.Y.Z-beta.N` and `X.Y.Z-rc.N`.
2. Run the checks below and merge the change to `main`. Keep screenshot URLs on `main` reachable before publishing.
3. From an up-to-date checkout of `main`, create and push the tag:

   ```sh
   git pull --ff-only
   git tag -a v1.0.1 -m 'Release 1.0.1'
   git push origin v1.0.1
   ```

   Use the next unused version for subsequent releases. Tagging an unmerged commit or a version different from the metadata fails verification before any publication.
4. Review the Actions summary, the four GitHub assets and the App Store listing. On a disposable Nextcloud 35 instance, install `integration_autophish` from the store and run `occ integrity:check-app integration_autophish`; successful verification prints nothing. This live acceptance remains necessary for the first release once the owner has configured the real certificate and account.

## What the workflow verifies

`ci.yml` is reusable from the tag workflow. It runs PHP/JavaScript tests, release guardrail tests, the official XSD, changelog/version checks and two byte-identical unsigned builds. The smoke matrix is pinned in `scripts/nextcloud-matrix.json`: Nextcloud 32, 33, 34 and 35 with SQLite, plus PostgreSQL and MariaDB (`mysql` driver) on 35. Tests include installation, upgrade, cron/command execution, persisted sync state, concurrent disable and removal. All AutoPhish calls are mocked.

Metadata must be covered by the matrix and `max-version` must not exceed the current stable major reported by the official App Store platform API plus one. Adding a major means adding its verified official image digest, extending the smoke coverage, and passing the tests before advertising it. A pinned digest never updates itself.

The schema is downloaded over HTTPS and cached in `.cache/appstore/info.xsd`; delete that file to refresh it locally. CI starts with a fresh schema. Unlike the store's XSLT preprocessing, direct XSD validation also requires correct element order and rejects unknown elements.

The release workflow then:

1. Stages only runtime files and generates `appinfo/signature.json` with `occ integrity:sign-app` in an isolated official Nextcloud container. The stage and signing inputs are mounted read-only; signing uses an internal copy.
2. Creates a deterministic tarball, installs it in the same disposable container, enables the app and checks its integrity. It requires both the signature file and an empty, successful integrity-check result. It builds twice and compares the complete signed archives.
3. Signs the final tarball with SHA-512/RSA and immediately verifies that signature using the certificate's public key.
4. Creates a GitHub Release with exactly four assets:
   - `integration_autophish-X.Y.Z.tar.gz`
   - `integration_autophish-X.Y.Z.tar.gz.sha256`
   - `integration_autophish-X.Y.Z.tar.gz.sha512`
   - `integration_autophish-X.Y.Z.tar.gz.sig`
5. Waits up to two minutes for the public HTTPS asset, compares its bytes, then submits the download URL and base64 signature to the store with `nightly: false`. HTTP 200 and 201 succeed; validation errors print the response and fail the job.
6. Polls the public catalogue for the exact version, non-nightly flag and compatibility range. This read-only step does not need the store token. Beta/RC versions use the store's beta channel automatically.

Only the GitHub Release job has `contents: write`. The store publication job uses the `appstore` environment. Forks and PRs have only unsigned artifacts and test keys; signing/publication jobs are restricted to the upstream repository's tag workflow.

The two signatures have distinct purposes. Nextcloud verifies `signature.json` after installation; the store verifies the signature over the final archive. Both use the same app key/certificate. Nextcloud's current internal implementation uses deterministic RSA-PSS with zero-length salt; the external `openssl dgst -sha512 -sign` signature uses deterministic PKCS#1 v1.5. Sorting, normalized archive metadata and `gzip -n` keep the complete archive reproducible with the same inputs and certificate.

## Local checks

Requires PHP 8.3 with XML/OpenSSL extensions, Composer, Node 24, Python 3, Docker, OpenSSL, curl, GNU tar/gzip and `xmllint` (`libxml2-utils` on Debian/Ubuntu).

```sh
composer install
npm ci
npm run lint
npm test
bash scripts/validate-info.sh
npm run build
cp dist/integration_autophish-1.0.2-unsigned.tar.gz /tmp/autophish-first.tar.gz
npm run build
cmp /tmp/autophish-first.tar.gz dist/integration_autophish-1.0.2-unsigned.tar.gz
NEXTCLOUD_MAJOR=32 npm run smoke
NEXTCLOUD_MAJOR=33 npm run smoke
NEXTCLOUD_MAJOR=34 npm run smoke
NEXTCLOUD_MAJOR=35 npm run smoke
NEXTCLOUD_MAJOR=35 NEXTCLOUD_SMOKE_DB=pgsql npm run smoke
NEXTCLOUD_MAJOR=35 NEXTCLOUD_SMOKE_DB=mysql npm run smoke
bash tests/release/signing.sh
```

Use the current version in archive names. Unsigned builds are always named `-unsigned` and cannot be published by this pipeline. `RELEASE_ARCHIVE` can select a specific archive for smoke tests.

The signing test generates a temporary CA and app key, replaces the trust root only in a disposable test image, checks two identical signed archives and release signatures, and then verifies that the unmodified official image rejects the same untrusted certificate. Production scripts contain no trust bypass, and the test artifacts are never uploaded. The real Nextcloud-issued certificate is tested only in the tag workflow.

## Recover a failed release

Use **Re-run failed jobs** on the original tag workflow. If store publication failed after GitHub succeeded, rerun publication and verification; do not rebuild or replace the release assets. If catalogue propagation is delayed, rerun verification. HTTP 400 includes the store's validation explanation.

GitHub publication is resumable: existing assets must match byte-for-byte and are never overwritten. It refuses unexpected assets or differing contents. A draft created by a failed attempt can be completed on rerun. For a code/metadata correction after publication, create a new version rather than moving a released tag.

An owner can remove a bad store release using `DELETE https://apps.nextcloud.com/api/v1/apps/integration_autophish/releases/X.Y.Z` with the `Authorization: Token …` header. This is a manual destructive recovery action, not an automatic workflow step. It does not remove GitHub assets or uninstall existing installations. Consult the [store API documentation](https://nextcloudappstore.readthedocs.io/en/stable/api/restapi.html) before doing so.

## Rotate signing material

Generate a replacement key/CSR in the owner's trusted environment. Submit a PR to `nextcloud/app-certificate-requests` replacing the app's existing CSR and follow the maintainers' certificate-replacement instructions. Register the replacement certificate and update both GitHub signing secrets together.

**Registering a replacement app certificate deletes the existing App Store releases.** Plan the replacement and republication before rotating. Retain the prior key/certificate securely in the password manager until recovery is complete. Never silently re-sign and overwrite an existing GitHub release asset. See [App Store certificate maintenance](https://nextcloudappstore.readthedocs.io/en/stable/developer.html).
