import importlib.util
from pathlib import Path
import io
import tempfile
import unittest
import zipfile
s=importlib.util.spec_from_file_location('publish',Path(__file__).parents[1]/'scripts/publish.py')
p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
class Publication(unittest.TestCase):
    def test_only_successful_main_and_root_version_tags(self):
        run={'event':'push','conclusion':'success','path':'.github/workflows/build.yml','head_branch':'main'}
        self.assertTrue(p.eligible('backend',run))
        for changes in ({'event':'pull_request'},{'head_branch':'feature'},{'conclusion':'failure'}):self.assertFalse(p.eligible('backend',{**run,**changes}))
        self.assertTrue(p.eligible('panasms',{**run,'head_branch':'v0.3.0'}))
        self.assertFalse(p.eligible('backend',{**run,'head_branch':'v0.3.0'}))
    def test_no_downgrade(self):
        self.assertFalse(p.newer('0.3.0~dev.20260921120000.1.1','0.3.0~dev.20260921130000.2.1'))
        self.assertTrue(p.newer('0.3.0','0.3.0~dev.20260921130000.2.1'))
    def test_no_artifact_traversal(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('../outside','bad')
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError):p.extract(raw.getvalue(),Path(d))

    def test_stable_bridge_survives_skipped_releases(self):
        bridge = {'version': '0.2.35'}
        old = {'version': '0.2.34'}
        releases = [old]
        for version in ['0.2.35', '0.2.36', '0.2.37', '0.2.38']:
            releases = p.retained_releases('stable', {'version': version}, releases)
            self.assertIn(bridge, releases)
        self.assertEqual([row['version'] for row in releases], ['0.2.38', '0.2.37', '0.2.35'])
        self.assertIsNone(p.retained_releases('stable', {'version': '0.2.36'}, [old]))

    def test_deferred_stable_runs_import_in_version_order(self):
        runs = [('panasms', {'head_branch': 'v' + version})
                for version in ('0.2.38', '0.2.37', '0.2.36', '0.2.35')]
        releases = [{'version': '0.2.34'}]
        for _, run in sorted(runs, key=p.publication_order):
            releases = p.retained_releases('stable', {'version': run['head_branch'][1:]}, releases)
        self.assertEqual([row['version'] for row in releases], ['0.2.38', '0.2.37', '0.2.35'])
