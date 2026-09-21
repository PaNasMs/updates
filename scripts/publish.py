#!/usr/bin/env python3
import base64
import datetime as dt
import email.utils
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

REPO = 'PaNasMs/updates'
BASE = 'https://panasms.github.io/updates/'
ALLOWED = {'panasms-prototype', 'panasms-cooling'}


def command(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def api(path, data=None):
    args = ['gh', 'api', path]
    if data is not None:args += ['--method', 'PUT', '--input', '-']
    return json.loads(command(*args, input=json.dumps(data).encode() if data is not None else None))


def newer(version, previous):
    return not previous or subprocess.run(['dpkg','--compare-versions',version,'gt',previous],check=False).returncode == 0


def eligible(repo, run):
    if run['event'] != 'push' or run['conclusion'] != 'success' or run['path'] != '.github/workflows/build.yml':return False
    branch = run['head_branch']
    return branch == 'main' or (repo == 'panasms' and bool(re.fullmatch(r'v\d+\.\d+\.\d+',branch)))


def extract(raw, folder):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 256*1024*1024:raise ValueError('Artifact too large')
        for item in archive.infolist():
            if item.filename != Path(item.filename).name or not re.fullmatch(r'[A-Za-z0-9_.~+-]+',item.filename):raise ValueError('Invalid artifact path')
            (folder/item.filename).write_bytes(archive.read(item))


def validate(meta, repo, run, arch):
    expected = 'stable' if run['head_branch'].startswith('v') else 'testing'
    if meta.get('channel') != expected:raise ValueError('Channel mismatch')
    if meta['architecture'] != arch or meta['product'] != 'PaNasMs':raise ValueError('Product mismatch')
    component = 'build' if repo == 'panasms' else repo
    if meta['sources'][component]['commit'] != run['head_sha']:raise ValueError('Source mismatch')
    if meta['run'] != f"https://github.com/PaNasMs/{repo}/actions/runs/{run['id']}":raise ValueError('Run mismatch')
    if expected == 'stable' and meta['version'] != run['head_branch'][1:]:raise ValueError('Tag mismatch')
    if expected == 'testing' and not re.fullmatch(r'\d+\.\d+\.\d+~dev\.\d{14}\.\d+\.\d+',meta['version']):raise ValueError('Testing version mismatch')


def import_run(repo, run, state):
    artifacts = api(f"repos/PaNasMs/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")['artifacts']
    folders, manifests = {}, {}
    for arch in ('arm64','amd64'):
        name = f"panasms-debian13-{arch}-{run['id']}-{run['run_attempt']}"
        matches = [x for x in artifacts if x['name']==name and not x['expired']]
        if len(matches)!=1:return
        folder = Path('downloads')/name
        folder.mkdir(parents=True,exist_ok=True)
        extract(command('gh','api',f"repos/PaNasMs/{repo}/actions/artifacts/{matches[0]['id']}/zip"),folder)
        meta = json.loads((folder/'build-manifest.json').read_text())
        if meta.get('channel') not in ('stable','testing'):return
        validate(meta,repo,run,arch)
        manifests[arch], folders[arch] = meta, folder
    first = manifests['arm64']
    for key in ('sources','version','createdAt','channel'):
        if first[key] != manifests['amd64'][key]:raise ValueError('Architecture source mismatch')
    channel, version = first['channel'], first['version']
    entries = state.get(channel,[])
    if entries and not newer(version,entries[0]['version']):return
    tag = 'v'+version if channel=='stable' else f"testing-{run['id']}-{run['run_attempt']}"
    packages, uploads = {}, []
    for arch,folder in folders.items():
        packages[arch] = []
        for item in manifests[arch]['packages']:
            file = item['file']
            if not re.fullmatch(r'[A-Za-z0-9_.~+-]+\.deb',file):raise ValueError('Invalid package name')
            path=folder/file
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Package hash mismatch')
            name=command('dpkg-deb','-f',str(path),'Package').decode().strip()
            package_version=command('dpkg-deb','-f',str(path),'Version').decode().strip()
            package_arch=command('dpkg-deb','-f',str(path),'Architecture').decode().strip()
            if name not in ALLOWED or package_version!=version or package_arch not in (arch,'all'):raise ValueError('Package identity mismatch')
            packages[arch].append({**item,'name':name,'version':version,'size':path.stat().st_size,'url':f'https://github.com/{REPO}/releases/download/{tag}/{file}'})
            uploads.append(str(path))
        if not any(p['name']=='panasms-prototype' for p in packages[arch]):raise ValueError('Missing core package')
        manifest=folder/f'{arch}-build-manifest.json'
        manifest.write_text(json.dumps(manifests[arch],indent=2)+'\n');uploads.append(str(manifest))
    entry={'version':version,'channel':channel,'createdAt':first['createdAt'],'run':first['run'],'sources':first['sources'],'tag':tag,'packages':packages,'rollbackCompatible':True,'requiresReboot':False}
    probe=subprocess.run(['gh','release','view',tag,'--repo',REPO],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if probe.returncode:
        command('gh','release','create',tag,*uploads,'--repo',REPO,'--title',f'PaNasMs {version}','--notes',f"Verified ARM64 and AMD64 packages. Source build: {first['run']}",*(['--prerelease'] if channel=='testing' else []))
    else:
        check=Path(tempfile.mkdtemp())
        try:
            command('gh','release','download',tag,'--repo',REPO,'--dir',str(check))
            for path in uploads:
                if Path(path).read_bytes() != (check/Path(path).name).read_bytes():raise ValueError('Published release is immutable')
        finally:shutil.rmtree(check)
    state[channel]=[entry,*entries][:2]


def sign(path):
    command('gpg','--batch','--yes','--armor','--detach-sign',str(path))


def build_site(state):
    site=Path('site');site.mkdir(exist_ok=True)
    shutil.copy2('panasms-updates.asc',site)
    now=dt.datetime.now(dt.timezone.utc)
    for channel in ('stable','testing'):
        root=site/'dists'/channel
        for arch in ('arm64','amd64'):
            pool=site/'pool'/channel/arch;pool.mkdir(parents=True,exist_ok=True)
            for entry in state.get(channel,[]):
                tag=entry['tag']
                for p in entry['packages'][arch]:
                    dest=pool/p['file']
                    if not dest.exists():command('gh','release','download',tag,'--repo',REPO,'--pattern',p['file'],'--dir',str(pool))
                    if hashlib.sha256(dest.read_bytes()).hexdigest()!=p['sha256']:raise ValueError('Archived package hash mismatch')
            binary=root/'main'/('binary-'+arch);binary.mkdir(parents=True,exist_ok=True)
            packages=command('dpkg-scanpackages','--multiversion',str(pool.relative_to(site)),cwd=site)
            (binary/'Packages').write_bytes(packages)
            import gzip
            (binary/'Packages.gz').write_bytes(gzip.compress(packages,mtime=0))
        release=command('apt-ftparchive','release',str(root)).decode()
        # apt-ftparchive emits its own Date; keep a single canonical Date.
        release='\n'.join(x for x in release.splitlines() if not x.startswith('Date:'))+'\n'
        (root/'Release').write_text(f'Origin: PaNasMs\nLabel: PaNasMs\nSuite: {channel}\nCodename: {channel}\nArchitectures: arm64 amd64\nComponents: main\nDate: {email.utils.format_datetime(now)}\nValid-Until: {email.utils.format_datetime(now+dt.timedelta(days=7))}\n'+release)
        command('gpg','--batch','--yes','--clearsign','--output',str(root/'InRelease'),str(root/'Release'))
        command('gpg','--batch','--yes','--armor','--detach-sign','--output',str(root/'Release.gpg'),str(root/'Release'))
        feed=site/'channels'/f'{channel}.json';feed.parent.mkdir(exist_ok=True)
        feed.write_text(json.dumps({'schemaVersion':1,'channel':channel,'generatedAt':now.isoformat(),'expiresAt':(now+dt.timedelta(days=7)).isoformat(),'releases':state.get(channel,[])},indent=2)+'\n')
        sign(feed)
    (site/'index.html').write_text('<!doctype html><html lang="en"><title>PaNasMs updates</title><h1>PaNasMs system updates</h1><p>Signed stable and testing APT repositories. See <a href="https://github.com/PaNasMs/updates">setup instructions</a>.</p></html>')


def main():
    state_file=Path('state.json');state=json.loads(state_file.read_text()) if state_file.exists() else {}
    previous=json.dumps(state,sort_keys=True)
    candidates=[]
    for repo in ('panasms','backend','frontend'):
        for run in api(f'repos/PaNasMs/{repo}/actions/workflows/build.yml/runs?event=push&status=success&per_page=10')['workflow_runs']:
            if eligible(repo,run):candidates.append((repo,run))
    for repo,run in sorted(candidates,key=lambda x:x[1]['created_at'],reverse=True):
        known=[r for rows in state.values() for r in rows]
        if any(r['run'].endswith('/'+str(run['id'])) for r in known):continue
        if not run['head_branch'].startswith('v') and state.get('testing') and run['created_at'] <= state['testing'][0]['createdAt']:continue
        import_run(repo,run,state)
    with tempfile.TemporaryDirectory() as home:
        os.environ['GNUPGHOME']=home
        command('gpg','--batch','--import',input=os.environ.pop('UPDATE_SIGNING_KEY').encode())
        exported=command('gpg','--batch','--armor','--export')
        if exported != Path('panasms-updates.asc').read_bytes():raise ValueError('Signing key mismatch')
        build_site(state)
    if json.dumps(state,sort_keys=True)!=previous:
        args={'message':'Record published system update versions','content':base64.b64encode((json.dumps(state,indent=2)+'\n').encode()).decode(),'branch':'main'}
        if state_file.exists():args['sha']=api(f'repos/{REPO}/contents/state.json')['sha']
        api(f'repos/{REPO}/contents/state.json',args)


if __name__=='__main__':main()
