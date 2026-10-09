# PaNasMs system updates

This repository publishes the signed APT channels and the one-command installer for
[PaNasMs](https://github.com/PaNasMs/panasms), a browser panel for a Linux NAS. A scheduled
GitHub Actions workflow imports verified core builds, signs the channel metadata and deploys it
to GitHub Pages at https://panasms.github.io/updates/. The first stable release is 0.2.15.

[Project website](https://panasms.github.io/) ·
[Installation guide](https://panasms.github.io/docs/setup/install/) ·
[Installation and recovery lifecycle](https://github.com/PaNasMs/panasms/blob/main/documentation/system-updates.md)

## Install

On a fresh supported system that has a regular Linux user with a password in the `sudo` group:

```sh
curl -fsSL https://panasms.github.io/updates/install.sh | sudo bash
```

The installer uses the stable channel and stops if that channel is empty. For preview builds, run
`sudo bash -s -- --channel testing` instead of `sudo bash`. Other options are `--port` (default 80,
or 443 with `--https`) and `--https`, which enables HTTPS with a locally generated certificate.

The installer accepts Debian 13 and Raspberry Pi OS 13 on ARM64 or AMD64, and Ubuntu 24.04 LTS on
AMD64. Armbian 26.8 (Debian 13) has been tested on a Raspberry Pi 5. AMD64 has been tested only in
virtual machines, and the installer prints a warning about it. Before it changes anything, it checks for a booted systemd
system, at least 2 GiB free on `/`, a free web port, a clean `dpkg` state and no existing PaNasMs
installation. It verifies the signing key fingerprint, the channel catalog signature and every
package checksum, and stops if APT would remove an existing package. On a Raspberry Pi 5 it also
installs the `panasms-cooling` package from the same release. It does not format disks.

An existing installation updates from Settings > System updates in the panel. The installer refuses
to replace a running NAS.

## Channels

- `stable` comes from successful `vMAJOR.MINOR.PATCH` tag builds in PaNasMs/panasms. The tag pins
  component commits in `release-lock.json`.
- `testing` comes from successful pushes to `main` in PaNasMs/panasms, PaNasMs/backend or
  PaNasMs/frontend.

Pull requests, feature branches and failed or incomplete builds never reach a channel.

## Manual APT setup

Download [`panasms-updates.asc`](panasms-updates.asc) and check its fingerprint against a trusted
source:

`495D 91EE 558D A6CA 516E A434 BC48 F33E C04D FC99`

Save the key as `/etc/apt/keyrings/panasms-updates.asc` and add a deb822 source:

```
Types: deb
URIs: https://panasms.github.io/updates/
Suites: stable
Components: main
Signed-By: /etc/apt/keyrings/panasms-updates.asc
```

Use `Suites: testing` for preview builds. System dependencies still come from the distribution
repositories.

The panel does not add a global APT source. It verifies the signed channel manifest, downloads the
packages and installs them as local files through APT. Selecting a channel does not install an
update or authorize a downgrade.

## How publishing works

`.github/workflows/publish.yml` runs at minutes 4, 19, 34 and 49 of every hour (GitHub may delay
scheduled runs) and on manual dispatch. It runs `scripts/publish.py`, which:

- reads successful `build.yml` runs and their artifacts from PaNasMs/panasms, backend and frontend
  with this workflow's own token, so the build repositories need no write access here;
- requires both the ARM64 and AMD64 artifacts and checks their channel, version, source commits,
  run URL, SHA-256 hashes and Debian `Package`, `Version` and `Architecture` fields;
- accepts only the `panasms-prototype` (core) and `panasms-cooling` packages;
- skips any version that is not newer than the current one in the channel;
- creates a GitHub release per version and fails if an existing release would change;
- keeps the two latest versions per channel on Pages and records them in `state.json`;
- signs `Release`, `InRelease` and `channels/<channel>.json`, which expire after seven days, so
  each run re-signs them.

`scripts/install.py` is the installer source. The publisher wraps it in a shell bootstrap and
serves it as `install.sh`.

Run the tests locally with:

```sh
python3 -m unittest discover -s tests -p '*_test.py' -v
```

Pull requests run the same tests and do not publish.

## Security

Only this repository holds the `UPDATE_SIGNING_KEY` Actions secret. The publisher refuses to sign
if that key does not match `panasms-updates.asc`. The core package ships the same public key, so
rotating the key requires an explicit trust update on every NAS. Checksums alone are not
signatures, and published version bytes never change.

Third-party module repositories cannot publish system updates. GitHub holds no NAS credentials,
and the publisher never connects to a NAS.

## License

PolyForm Noncommercial 1.0.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
