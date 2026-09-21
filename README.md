# PaNasMs system updates

Signed APT channels for Debian 13 and Raspberry Pi OS based on Debian 13, ARM64 and AMD64.

- `testing`: successful pushes to `main` in PaNasMs/panasms, backend or frontend.
- `stable`: successful `vMAJOR.MINOR.PATCH` tags in PaNasMs/panasms, with component commits pinned in `release-lock.json`.
- Pull requests, feature branches, unsuccessful or incomplete builds are never published.

The importer runs every 15 minutes (GitHub may delay scheduled workflows). It uses read access to public build artifacts, avoiding cross-repository write credentials. Publication is serialized and older versions cannot replace newer versions. Releases retain immutable packages; Pages carries the two latest versions per channel. Release signatures and channel manifests expire after seven days and are refreshed by the publisher.

## Repository

Base URL: https://panasms.github.io/updates/

Download `panasms-updates.asc` and verify its fingerprint through a trusted source before installation:

`495D 91EE 558D A6CA 516E A434 BC48 F33E C04D FC99`

For manual APT configuration, install this key in `/etc/apt/keyrings/panasms-updates.asc`, then use a deb822 source with `Types: deb`, `URIs: https://panasms.github.io/updates/`, `Suites: stable` (or `testing`), `Components: main`, and `Signed-By: /etc/apt/keyrings/panasms-updates.asc`.

The panel's update service manages its own source and transaction settings. Selecting a channel does not itself install an update or authorize a downgrade. System dependencies still come from the distribution repositories.

## Security and operations

Only this repository holds the `UPDATE_SIGNING_KEY` Actions secret. The public key is also shipped in the NAS package. Key rotation requires an explicit trust update. Checksums alone are not signatures. Published version bytes must not change.

The publisher checks both architecture builds, their component identities, package hashes and Debian metadata. Third-party module sources cannot publish system updates. No NAS credentials are held in GitHub. The publisher never connects to a NAS.

License: PolyForm Noncommercial 1.0.0; see LICENSE.
