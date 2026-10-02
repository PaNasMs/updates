import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1]/'scripts/install.py')
i = importlib.util.module_from_spec(spec); spec.loader.exec_module(i)

class Installer(unittest.TestCase):
    def catalog(self):
        now=dt.datetime.now(dt.timezone.utc)
        return {'schemaVersion':1,'channel':'stable','generatedAt':now.isoformat(),
                'expiresAt':(now+dt.timedelta(days=7)).isoformat(),'releases':[{'version':'1.0.0','packages':{'arm64':[
                    {'name':'panasms-prototype','file':'core.deb','size':123,'sha256':'a'*64}]}}]}
    def test_selects_only_core_for_host_architecture(self):
        release, package=i.select_release(self.catalog(),'stable','arm64')
        self.assertEqual(package['name'],'panasms-prototype')
        with self.assertRaises(RuntimeError):i.select_release(self.catalog(),'stable','amd64')
    def test_rejects_expired_future_wrong_channel_and_empty(self):
        for key,value in [('expiresAt','2000-01-01T00:00:00+00:00'),('generatedAt','2100-01-01T00:00:00+00:00'),('channel','testing'),('releases',[])]:
            data=self.catalog();data[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):i.select_release(data,'stable','arm64')
    def test_rejects_unsafe_paths_and_checksum(self):
        for key,value in [('file','../core.deb'),('size',-1),('sha256','bad')]:
            data=self.catalog();data['releases'][0]['packages']['arm64'][0][key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):i.select_release(data,'stable','arm64')

    def test_published_shell_runs_help_without_root_or_side_effects(self):
        import subprocess
        publisher_spec=importlib.util.spec_from_file_location('publisher',Path(__file__).parents[1]/'scripts/publish.py')
        publisher=importlib.util.module_from_spec(publisher_spec);publisher_spec.loader.exec_module(publisher)
        result=subprocess.run(['bash','-s','--','--help'],input=publisher.render_installer(),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--channel',result.stdout)
        self.assertIn('--https',result.stdout)
