import contextlib
import importlib.util
from pathlib import Path
import io
import tempfile
import unittest
from unittest import mock
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


def build(id, **changes):
    return {'id': id, 'event': 'push', 'status': 'completed', 'conclusion': 'success',
            'path': '.github/workflows/build.yml', 'head_branch': 'main', 'head_sha': '2cb553e0000', **changes}


class BuildSelection(unittest.TestCase):
    def select(self, runs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            selected = p.select_candidates('backend', runs)
        return [run['id'] for _, run in selected], out.getvalue()

    def test_build_missing_from_status_filtered_list_is_selected(self):
        queries = []
        def api(path, data=None):
            queries.append(path)
            if 'status=success' in path:
                return {'workflow_runs': [build(45579709000)]}
            return {'workflow_runs': [build(45579709018), build(45579709000)]}
        with mock.patch.object(p, 'api', api), contextlib.redirect_stdout(io.StringIO()):
            selected = p.list_candidates('backend')
        self.assertEqual([run['id'] for _, run in selected], [45579709018, 45579709000])
        self.assertEqual(len(queries), 1)
        self.assertNotIn('status=', queries[0])
        self.assertIn('event=push', queries[0])

    def test_in_progress_build_before_finished_build(self):
        ids, log = self.select([build(2, status='in_progress', conclusion=None), build(1)])
        self.assertEqual(ids, [1])
        self.assertIn('Skipping backend build 2 ', log)
        self.assertIn('not completed (status in_progress)', log)
        self.assertIn('Considering backend build 1 ', log)

    def test_queued_build_with_stale_success_is_not_selected(self):
        ids, log = self.select([build(3, status='queued')])
        self.assertEqual(ids, [])
        self.assertIn('not completed (status queued)', log)

    def test_unsuccessful_conclusions_are_skipped_with_reason(self):
        ids, log = self.select([build(5, conclusion='failure'), build(4, conclusion='cancelled'), build(3)])
        self.assertEqual(ids, [3])
        self.assertIn('build 5 ', log)
        self.assertIn('conclusion is failure', log)
        self.assertIn('conclusion is cancelled', log)

    def test_ineligible_builds_are_skipped_with_reason(self):
        ids, log = self.select([build(6, head_branch='feature'), build(7, event='pull_request')])
        self.assertEqual(ids, [])
        self.assertEqual(log.count('not a push build of main or a release tag'), 2)
