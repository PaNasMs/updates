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
