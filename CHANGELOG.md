# Changelog

All notable changes are documented here in Keep a Changelog format. Versions follow Semantic Versioning.

## 1.0.3

### Changed

- Clarify the App Store title and link AutoPhish directly from its description.
- Pin App Store screenshots to permanent source URLs and add a directly viewable README gallery.
- Document catalogue and screenshot proxy propagation after publication.

## 1.0.2

### Added

- Nextcloud 35 compatibility, verified with pinned installation, upgrade and database smoke checks.

### Changed

- Explain AutoPhish phishing simulations and the Nextcloud group synchronization workflow in the App Store listing.

## 1.0.1

### Added

- Signed, reproducible Nextcloud App Store releases and automatic publication from release tags.
- App Store metadata, privacy disclosures, screenshots and release documentation.
- Compatibility smoke checks for Nextcloud 32, 33 and 34, including PostgreSQL and MariaDB on 34.

### Fixed

- Keep synchronization status labels and values aligned in Nextcloud admin settings.

## 1.0.0

### Added

- Mirror selected Nextcloud groups into dedicated AutoPhish target lists.
- Admin settings, encrypted API-key storage, scheduled and manual synchronization.
- Safe membership reconciliation, concurrency protection and offline cleanup.
