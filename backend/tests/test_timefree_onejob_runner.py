"""Runner control and rendered-contract validation with fake Docker boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('onejob_runner',ROOT/'scripts/timefree_onejob_runner.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
IDENT='a'*32


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

        # Any accidental real command fails before it can reach Docker or a daemon.
        real_run = subprocess.run
        def syntax_only(args, **kwargs):
            if args != ['bash', '-n', str(ROOT/'scripts/timefree-onejob-acceptance.sh')]:
                raise AssertionError('unexpected real subprocess')
            return real_run(args, **kwargs)
        patcher=patch.object(subprocess,'run',side_effect=syntax_only)
        patcher.start();self.addCleanup(patcher.stop)

    def rendered_fixture(self):
        service = {
            'image': 'fixture:revision', 'user': '10001:20000', 'restart': 'no',
            'read_only': True, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'],
            'entrypoint': ['python', '-m', 'radioflix.timefree.acceptance'],
            'command': ['--accept-job', IDENT],
            'environment': {'RFRIENDS_ENABLE_WRITES': '0',
                            'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '1',
                            'RADIOFLIX_TIMEFREE_BOOT_MODE': 'enabled'},
            'networks': {'acceptance-egress': {}},
            'volumes': [{'type': 'volume' if target == '/data' else 'bind',
                         'source': 'database' if target == '/data' else '/fixture'+target,
                         'target': target, 'read_only': target not in ('/data', '/timefree')}
                        for target in ('/data', '/timefree', '/recordings',
                                       '/native-reservations', '/native-timefree', '/approval.json')],
        }
        return service, {'services': {'timefree-acceptance': service},
                         'volumes': {'database': {'name': 'radioflix_radioflix-reservations'}},
                         'networks': {'acceptance-egress': {'driver': 'bridge'}}}

    def test_dedicated_service_contract(self):
        service,data=self.rendered_fixture()
        # Exercise the runner's pure validation using already-rendered fixture JSON.
        with patch.object(runner,'docker',side_effect=lambda *a, **kw:
                          subprocess.CompletedProcess([],0,json.dumps(data),'')):
            _,_,validated,_=runner.render('fixture:revision',IDENT,self.path/'approval.json')
            self.assertEqual(validated,service)
            for key,value in (('user','0:0'), ('ports',[8000]), ('privileged',True)):
                with self.subTest(key=key):
                    service,data=self.rendered_fixture()
                    service[key]=value
                    with self.assertRaisesRegex(ValueError,'unsafe_compose'):
                        runner.render('fixture:revision',IDENT,self.path/'approval.json')

    def setup_fake(self, *, failure=False, unknown=False):
        service,data=self.rendered_fixture()
        self.calls=[];self.approval_created=False;self.executed=False;self.final=False
        self.before={'timefree-worker':{'image':'sha256:fixture'},'backend':{'image':'sha256:fixture'}}
        def command(args,**kwargs):
            if args[:2]==['git','rev-parse']:return subprocess.CompletedProcess(args,0,'f'*40+'\n','')
            if args[:2]==['git','status']:return subprocess.CompletedProcess(args,0,'','')
            raise AssertionError('unexpected command')
        def docker(*args,**kwargs):
            self.calls.append(args)
            if args[:2]==('image','inspect'):
                return subprocess.CompletedProcess(args,0,json.dumps([{'Config':{'Labels':{'org.opencontainers.image.revision':'f'*40}}}]),'')
            if args[0]=='ps':return subprocess.CompletedProcess(args,0,'','')
            if args[0]=='network' and args[1]=='ls':return subprocess.CompletedProcess(args,0,'','')
            if args[0]=='run':
                self.assertIn('none',args);self.assertIn('--read-only',args)
                self.assertIn('os.fchown(f,10001,20000)',args[-1])
                p=self.path/'approval.json';p.write_text(json.dumps({'job_id':IDENT,'approved':True}));p.chmod(0o600)
                self.approval_created=True
                return subprocess.CompletedProcess(args,0,'','')
            if args[0]=='compose':
                self.assertIn('--no-deps',args);self.assertIn('--rm',args)
                self.assertTrue(self.approval_created)
                self.assertEqual((self.path/'approval.json').stat().st_mode&0o777,0o600)
                self.executed=True
                return subprocess.CompletedProcess(args,1 if failure else 0,'','')
            raise AssertionError('unexpected docker command')
        def probe(*args,final=False,**kw):
            if unknown:raise ValueError('unknown_job')
            self.final=final
            return {'job_id':IDENT,'job_count':1,'state':('failed' if failure else 'completed') if final else 'queued',
                    'limits':{'duration':300,'max_wire_requests':73}}
        for name,value in [('command',command),('docker',docker),('safety',lambda:self.before),
                ('probe',probe),('smoke',lambda:None),('render',lambda *a: (['compose'],os.environ,service,data))]:
            patcher=patch.object(runner,name,side_effect=value);patcher.start();self.addCleanup(patcher.stop)

    def test_dry_run_never_creates_approval_or_executes(self):
        self.setup_fake()
        self.assertEqual(runner.run(IDENT,self.path),0)
        self.assertFalse(self.executed);self.assertFalse(self.approval_created)
        self.assertFalse((self.path/'owner.json').exists())

    def test_execution_cleanup_and_exit_code(self):
        self.setup_fake()
        self.assertEqual(runner.run(IDENT,self.path,execute=True),0)
        self.assertTrue(self.executed);self.assertTrue(self.final)
        self.assertFalse((self.path/'approval.json').exists())
        self.assertFalse(any('up' in c or 'restart' in c or 'build' in c for c in self.calls))

    def test_failed_capture_still_cleans_up(self):
        self.setup_fake(failure=True)
        self.assertEqual(runner.run(IDENT,self.path,execute=True),1)
        self.assertFalse((self.path/'approval.json').exists())

    def test_unknown_job_never_creates_approval(self):
        self.setup_fake(unknown=True)
        with self.assertRaises(ValueError):runner.run(IDENT,self.path,execute=True)
        self.assertFalse(self.executed);self.assertFalse(self.approval_created)

    def test_invalid_id_rejected_before_docker(self):
        with patch.object(runner,'docker',side_effect=AssertionError('must not call')):
            with self.assertRaises(ValueError):runner.run('not-an-id',self.path)

    def test_cleanup_refuses_foreign_container(self):
        (self.path/'owner.json').write_text(json.dumps({'name':'radioflix-accept-'+IDENT,'nonce':'b'*32}))
        with patch.object(runner,'docker',return_value=subprocess.CompletedProcess([],0,'container\n','')) as docker,patch.object(
                runner,'inspect',return_value={'Config':{'Labels':{runner.OWNER:'foreign'}}}):
            with self.assertRaises(ValueError):runner.cleanup(self.path)
            self.assertEqual(docker.call_count,1)

    def test_shell_syntax(self):
        subprocess.run(['bash','-n',str(ROOT/'scripts/timefree-onejob-acceptance.sh')],check=True)
