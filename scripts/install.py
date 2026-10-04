"""Fresh-install bootstrap, embedded in the published install.sh."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = 'https://panasms.github.io/updates/'
FINGERPRINT = '495D91EE558DA6CA516EA434BC48F33EC04DFC99'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None,
                          env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive', 'LC_ALL': 'C'}).stdout


def fetch(url, limit):
    require(url.startswith(BASE) or url.startswith('https://github.com/PaNasMs/updates/releases/download/'),
            'Untrusted download location')
    with urllib.request.urlopen(url, timeout=90) as response:
        require(response.url.startswith('https://'), 'Insecure download redirect')
        raw = response.read(limit + 1)
    require(len(raw) <= limit, 'Download exceeds its size limit')
    return raw


def select_release(data, channel, arch, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    require(data.get('schemaVersion') == 1 and data.get('channel') == channel, 'Invalid signed release catalog')
    generated = dt.datetime.fromisoformat(data['generatedAt'])
    expires = dt.datetime.fromisoformat(data['expiresAt'])
    require(generated.tzinfo and expires.tzinfo and generated <= now + dt.timedelta(minutes=5)
            and now < expires and now - generated < dt.timedelta(days=8),
            'Release catalog is expired or system clock is incorrect')
    require(data.get('releases'), f'No {channel} release is published yet. Testing builds require explicit --channel testing.')
    release = data['releases'][0]
    require(re.fullmatch(r'[0-9][A-Za-z0-9.+~:-]{0,120}', release['version']), 'Invalid release version')
    packages = [p for p in release['packages'].get(arch, []) if p['name'] == 'panasms-prototype']
    require(len(packages) == 1, f'No unique core package for {arch}')
    package = packages[0]
    require(re.fullmatch(r'[A-Za-z0-9_.~+-]+\.deb', package['file']) and
            re.fullmatch(r'[a-f0-9]{64}', package['sha256']) and type(package['size']) is int
            and 0 < package['size'] <= 256 * 1024**2, 'Invalid package metadata')
    return release, package


def port_free(port):
    # Connections still closing after a removed panel (an open browser tab) must not block
    # reinstallation: probe the way the panel listens, with address reuse.
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('0.0.0.0', port))
        except OSError:
            return False
    return True


def supported_os(info, arch):
    distro = info.get('ID', '').strip('"')
    version = info.get('VERSION_ID', '').strip('"')
    return (distro in ('debian', 'raspbian') and version == '13' and arch in ('arm64', 'amd64')) or (distro == 'ubuntu' and version == '24.04' and arch == 'amd64')


def wait_ready(opener, url, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with opener.open(url, timeout=5) as response:
                health = json.load(response)
                require(response.status == 200 and health.get('status') == 'ok' and health.get('product') == 'PaNasMs', 'Panel startup health check failed')
                return
        except urllib.error.URLError as error:
            if isinstance(error, urllib.error.HTTPError) and error.code not in (502, 503, 504):
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError('Panel did not become ready within 60 seconds; inspect journalctl -u panasms-core -u panasms-agent') from error
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description='Install PaNasMs and its dependencies on a fresh NAS')
    parser.add_argument('--channel', choices=['stable', 'testing'], default='stable')
    parser.add_argument('--port', type=int, help='Web port (80 for HTTP, 443 with --https)')
    parser.add_argument('--https', action='store_true', help='Enable HTTPS with a locally generated certificate')
    args = parser.parse_args()
    args.port = args.port if args.port is not None else (443 if args.https else 80)
    require(os.geteuid() == 0, 'Run the installer with sudo')
    require(1 <= args.port <= 65535, 'Port must be between 1 and 65535')
    release_info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    arch = run('dpkg', '--print-architecture', capture=True).strip()
    require(supported_os(release_info, arch),
            'Use Debian 13 / Raspberry Pi OS 13 (ARM64 or AMD64), or Ubuntu 24.04 LTS (AMD64); no changes were made')
    require(Path('/run/systemd/system').is_dir(), 'This installer requires a booted systemd system')
    if arch == 'amd64':
        print('AMD64 is experimental: hardware acceptance has been performed on ARM64 only.', flush=True)
    installed = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', 'panasms-prototype'], capture_output=True, text=True)
    require(installed.returncode != 0 or installed.stdout.strip() != 'installed',
            'PaNasMs is already installed. Use Settings > System updates; this installer does not replace a running NAS.')
    require(not run('dpkg', '--audit', capture=True).strip(), 'Repair the interrupted package operation first')
    require(shutil.disk_usage('/').free >= 2 * 1024**3, 'At least 2 GiB of free system disk space is required')
    admins = run('getent', 'group', 'sudo', capture=True).strip().split(':')[-1].split(',')
    require(any(admins), 'Create a regular Linux user in the sudo group before installation')
    require(port_free(args.port), f'Port {args.port} is used by another service. Stop it or choose another port with --port.')
    print(f'Installing PaNasMs ({args.channel}, {arch}), web port {args.port}. Existing disks will not be formatted.', flush=True)
    run('apt-get', 'update')
    run('apt-get', 'install', '--yes', '--no-remove', 'ca-certificates', 'gnupg')
    with tempfile.TemporaryDirectory(prefix='panasms-install-') as folder:
        root = Path(folder)
        (root/'gnupg').mkdir(mode=0o700)
        key = root/'key.asc'; key.write_bytes(fetch(BASE+'panasms-updates.asc', 65536))
        shown = run('gpg', '--batch', '--homedir', str(root/'gnupg'), '--with-colons', '--show-keys', str(key), capture=True)
        fingerprints = [line.split(':')[9] for line in shown.splitlines() if line.startswith('fpr:')]
        require(sum(line.startswith('pub:') for line in shown.splitlines()) == 1 and fingerprints and fingerprints[0] == FINGERPRINT, 'Update signing key fingerprint mismatch')
        run('gpg', '--batch', '--homedir', str(root/'gnupg'), '--output', str(root/'key.gpg'), '--dearmor', str(key))
        catalog = root/'catalog.json'; catalog.write_bytes(fetch(BASE+f'channels/{args.channel}.json', 2*1024**2))
        signature = root/'catalog.asc'; signature.write_bytes(fetch(BASE+f'channels/{args.channel}.json.asc', 16384))
        run('gpgv', '--homedir', str(root/'gnupg'), '--keyring', str(root/'key.gpg'), str(signature), str(catalog))
        release, package = select_release(json.loads(catalog.read_text()), args.channel, arch)
        require(subprocess.run(['dpkg','--compare-versions',release['version'],'ge','0.2.10~']).returncode == 0,
                'This installer requires PaNasMs 0.2.10 or newer; wait for a compatible release in this channel')
        if release_info.get('ID', '').strip('"') == 'ubuntu':
            require(subprocess.run(['dpkg', '--compare-versions', release['version'], 'ge', '0.2.13~']).returncode == 0,
                    'Ubuntu requires PaNasMs 0.2.13 or newer; wait for a compatible release in this channel')
        path = root/package['file']; raw = fetch(package['url'], package['size'])
        require(len(raw) == package['size'] and hashlib.sha256(raw).hexdigest() == package['sha256'], 'Package checksum mismatch')
        path.write_bytes(raw)
        for field, expected in [('Package', 'panasms-prototype'), ('Version', release['version']), ('Architecture', arch)]:
            require(run('dpkg-deb', '-f', str(path), field, capture=True).strip() == expected, 'Package identity mismatch: '+field)
        simulation = run('apt-get', '--simulate', '--no-remove', 'install', str(path), capture=True)
        require(not re.search(r'^Remv ', simulation, re.M), 'Installation would remove existing system packages')
        run('apt-get', 'install', '--yes', '--no-remove', '--no-install-recommends', str(path))
    run('panasms-configure', '--port', str(args.port))
    # Explicit testing selection must also apply to subsequent update checks.
    Path('/etc/panasms/updates.json').write_text(json.dumps({'channel':args.channel,'mode':'notify','hour':3})+'\n')
    if args.https:run('panasms-tls', 'enable')
    run('systemctl', 'is-active', '--quiet', 'panasms-core', 'panasms-agent')
    import ssl
    handlers=[urllib.request.ProxyHandler({})]
    scheme='https' if args.https else 'http'
    if args.https:
        context=ssl.create_default_context(cafile='/etc/panasms/tls.crt');context.check_hostname=False
        handlers.append(urllib.request.HTTPSHandler(context=context))
    wait_ready(urllib.request.build_opener(*handlers), f'{scheme}://127.0.0.1:{args.port}/api/v1/health')
    addresses = run('hostname', '-I', capture=True).split()
    address = next((a for a in addresses if ':' not in a), socket.gethostname())
    print(f'\nReady: {scheme}://{address}'+(f':{args.port}' if args.port != (443 if args.https else 80) else '')+'/')
    print('Sign in with your existing Linux administrator username and password. Cooling is disabled until configured for your hardware.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'Installation stopped: {error}', file=sys.stderr)
        sys.exit(1)
