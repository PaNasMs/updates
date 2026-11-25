import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock

s = importlib.util.spec_from_file_location('publish', Path(__file__).parents[1] / 'scripts/publish.py')
p = importlib.util.module_from_spec(s); s.loader.exec_module(p)


class ImportSkipReason(unittest.TestCase):
    def test_build_without_artifacts_logs_skip_reason(self):
        run = {'id': 45579709018, 'run_attempt': 1, 'event': 'push', 'status': 'completed',
               'conclusion': 'success', 'path': '.github/workflows/build.yml',
               'head_branch': 'main', 'head_sha': '2cb553e0000'}
        out = io.StringIO()
        with mock.patch.object(p, 'api', lambda path, data=None: {'artifacts': []}), contextlib.redirect_stdout(out):
            p.import_run('backend', run, {})
        # Criterion 2: every considered build is logged with the reason it was skipped or imported.
        self.assertIn('45579709018', out.getvalue(), 'import_run dropped the build without logging a reason')


if __name__ == '__main__':
    unittest.main()
