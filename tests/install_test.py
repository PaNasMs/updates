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

    def test_port_probe_ignores_closing_connections(self):
        import socket
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0)); server.listen(); port = server.getsockname()[1]
            self.assertFalse(i.port_free(port))
            client = socket.create_connection(('127.0.0.1', port)); accepted = server.accept()[0]
            accepted.close(); client.close()
        # The listener is gone; its closed connection lingers in TIME-WAIT.
        self.assertTrue(i.port_free(port))
    def test_supported_os_matrix(self):
        for distro,version,arch,expected in [('debian','13','amd64',True),('raspbian','13','arm64',True),('ubuntu','24.04','amd64',True),('ubuntu','24.04','arm64',False),('ubuntu','22.04','amd64',False),('other','13','amd64',False),('debian','12','amd64',False)]:
            with self.subTest(distro=distro,version=version,arch=arch):
                self.assertEqual(i.supported_os({'ID':distro,'VERSION_ID':version},arch),expected)

    def test_waits_for_http_listener_after_systemd_start(self):
        import io
        from unittest.mock import Mock,patch
        opener=Mock()
        response=io.BytesIO(b'{"product":"PaNasMs","status":"ok"}');response.status=200
        opener.open.side_effect=[i.urllib.error.URLError(ConnectionRefusedError()),response]
        with patch.object(i.time,'sleep') as sleep:
            i.wait_ready(opener,'http://localhost/api/v1/health')
        self.assertEqual(opener.open.call_count,2);sleep.assert_called_once_with(1)

    def test_readiness_timeout_and_wrong_product(self):
        import io
        from unittest.mock import Mock
        opener=Mock();opener.open.side_effect=i.urllib.error.URLError('refused')
        with self.assertRaisesRegex(RuntimeError,'did not become ready'):i.wait_ready(opener,'http://localhost',timeout=0)
        response=io.BytesIO(b'{"product":"Other","status":"ok"}');response.status=200
        opener.open.side_effect=None;opener.open.return_value=response
        with self.assertRaisesRegex(RuntimeError,'health check failed'):i.wait_ready(opener,'http://localhost')

    def test_pi5_requires_signed_native_cooling_package(self):
        release, core = i.select_release(self.catalog(), 'stable', 'arm64')
        self.assertEqual(i.installation_packages(release, core, 'arm64', False), [core])
        with self.assertRaises(RuntimeError): i.installation_packages(release, core, 'arm64', True)
        cooling = {**core, 'name':'panasms-cooling', 'file':'cooling.deb', 'architecture':'arm64'}
        release['packages']['arm64'].append(cooling)
        self.assertEqual(i.installation_packages(release, core, 'arm64', True), [core, cooling])
        cooling['architecture']='all'
        with self.assertRaises(RuntimeError): i.installation_packages(release, core, 'arm64', True)
        cooling['architecture']='arm64'; cooling['file']='../cooling.deb'
        with self.assertRaises(RuntimeError): i.installation_packages(release, core, 'arm64', True)

    def test_hardware_detection_does_not_enable_unrelated_gpio(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); model=root/'proc/device-tree/model';model.parent.mkdir(parents=True)
            self.assertFalse(i.needs_cooling('arm64',root))
            model.write_text('Raspberry Pi 5 Model B Rev 1.0\0')
            self.assertTrue(i.needs_cooling('arm64',root))
            self.assertFalse(i.needs_cooling('amd64',root))
            model.write_text('Generic ARM SBC')
            self.assertFalse(i.needs_cooling('arm64',root))
