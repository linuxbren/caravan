"""Clean-install regression tests: no Macs, network, engines or model weights."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ('agent', 'proxy', 'tools'):
    sys.path.insert(0, str(ROOT / folder))
import llama_runtime as L
import gguf_sets as Sets
import gguf_split as G
import web_picker as P
import caravan as CLI
import caravan_path as PathSetup
import caravan_service as Service
import service_config as SC


class RuntimeTests(unittest.TestCase):
    def archive(self, folder, *, unsafe=False, missing=False):
        file=folder/'runtime.tgz'
        with tarfile.open(file, 'w:gz') as tar:
            names=['llama-server', 'ggml-rpc-server', 'libggml-rpc.dylib']
            if missing:names.pop()
            if unsafe:names.append('../../escape')
            for name in names:
                data=b'RPC-enabled test executable'
                info=tarfile.TarInfo('llama-test/'+name);info.size=len(data);info.mode=0o755
                tar.addfile(info, io.BytesIO(data))
        return file

    def install_fixture(self, *, unsafe=False, missing=False, bad_hash=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);home=Path(tmp.name)
        archive=self.archive(home,unsafe=unsafe,missing=missing)
        pin=dict(version='test',url='https://example.invalid/release',sha256='0'*64 if bad_hash else hashlib.sha256(archive.read_bytes()).hexdigest())
        return home,archive,pin

    def test_hash_verified_before_extracting(self):
        home,archive,pin=self.install_fixture(bad_hash=True)
        with patch.object(L,'PIN',pin), self.assertRaisesRegex(ValueError,'safety check'):
            L.ensure(home,lambda u,p:shutil.copyfile(archive,p))
        self.assertFalse((home/'.caravan/runtime/llama/test').exists())

    def test_valid_install_is_idempotent_and_preferred(self):
        home,archive,pin=self.install_fixture()
        with patch.object(L,'PIN',pin):
            dest=L.ensure(home,lambda u,p:shutil.copyfile(archive,p))
            self.assertTrue(L.ready(home));self.assertEqual(L.bin_dir(home),dest)
            self.assertEqual(L.ensure(home,Mock(side_effect=AssertionError('redownload'))),dest)

    def test_unsafe_archive_refused(self):
        home,archive,pin=self.install_fixture(unsafe=True)
        with patch.object(L,'PIN',pin),self.assertRaisesRegex(ValueError,'Unsafe'):
            L.ensure(home,lambda u,p:shutil.copyfile(archive,p))
        self.assertFalse((home/'.caravan/runtime/llama/test').exists())

    def test_rpc_library_required(self):
        home,archive,pin=self.install_fixture(missing=True)
        with patch.object(L,'PIN',pin),self.assertRaisesRegex(ValueError,'missing'):
            L.ensure(home,lambda u,p:shutil.copyfile(archive,p))

    def test_existing_incomplete_engine_not_destroyed(self):
        with tempfile.TemporaryDirectory() as h:
            p=L.location(h);p.mkdir(parents=True);(p/'keep').write_text('keep')
            with self.assertRaisesRegex(ValueError,'incomplete'):L.ensure(h)
            self.assertEqual((p/'keep').read_text(),'keep')

    def test_pin_is_immutable_official_release(self):
        self.assertIn('/ggml-org/llama.cpp/releases/download/'+L.PIN['version']+'/', L.PIN['url'])
        self.assertRegex(L.PIN['sha256'],r'^[a-f0-9]{64}$')
        self.assertIn('macos-arm64.tar.gz',L.PIN['url'])

    def test_every_role_installs_engine_and_update_reuses_installer(self):
        script=(ROOT/'scripts/install.sh').read_text()
        self.assertIn('run "$VENV/bin/python" "$REPO/agent/llama_runtime.py"',script)
        self.assertLess(script.index('llama_runtime.py'),script.index('if [ "$ROLE" = lead ]; then\n  KIND=web'))
        self.assertIn('"--update", "--role", role', (ROOT/'tools/caravan.py').read_text())
        self.assertIn('runtime/llama/',G.rpc_start_command())
        self.assertIn('CARAVAN_RPC_BIN',G.rpc_start_command())


class MultipartTests(unittest.TestCase):
    def sizes(self, n=6):
        return {f'UD-Q4/model-{i:05d}-of-{n:05d}.gguf':100_000_000+i for i in range(1,n+1)}

    def test_selecting_part_six_resolves_all_parts_in_order(self):
        sizes=self.sizes();parts=Sets.members(list(sizes)[-1],sizes)
        self.assertEqual(parts,list(sizes));self.assertIn('00001',parts[0])

    def test_missing_part_refused(self):
        sizes=self.sizes();del sizes[list(sizes)[2]]
        with self.assertRaisesRegex(ValueError,'missing'):Sets.members(list(sizes)[-1],sizes)

    def test_picker_groups_parts_and_totals_real_size(self):
        sizes=self.sizes();files=[dict(rfilename=n,size=s) for n,s in sizes.items()]
        with patch.object(P,'_fetch_repo_blobs',return_value=dict(gguf_files=files)):
            rows=P._enrich_sizes([dict(repo_id='test/GLM-GGUF',source='gguf')])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['gguf_file'],list(sizes)[0]);self.assertEqual(rows[0]['weights_gb'],round(sum(sizes.values())/1e9,2))

    def test_scan_only_complete_sets_and_summed_size(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for i in range(1,4):
                with (root/f'model-{i:05d}-of-00003.gguf').open('wb') as f:f.truncate(60_000_000)
            rows=G.scan_local([root]);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['size_gb'],.18)
            self.assertTrue(rows[0]['path'].endswith('00001-of-00003.gguf'))
            (root/'model-00002-of-00003.gguf').unlink();self.assertEqual(G.scan_local([root]),[])

    def test_staged_downloads_not_in_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);hidden=root/'.gguf-downloads';hidden.mkdir()
            with (hidden/'model.gguf').open('wb') as f:f.truncate(60_000_000)
            self.assertEqual(G.scan_local([root]),[])

    def test_fetch_verifies_all_parts_before_publishing(self):
        import mlx_split_fetch as F
        sizes=self.sizes(3);a=SimpleNamespace(repo='test/model',gguf_file=list(sizes)[-1],dry_run=False,no_progress=True)
        with tempfile.TemporaryDirectory() as d,patch.object(F,'file_sizes',return_value=sizes):
            root=Path(d)
            def fetch(repo,stage,names,sz,token):
                for name in names:
                    p=stage/name;p.parent.mkdir(parents=True,exist_ok=True)
                    with p.open('wb') as f:f.truncate(sz[name])
            with patch.object(F,'_range_fetch_all',side_effect=fetch),contextlib.redirect_stdout(io.StringIO()):F._fetch_gguf(a,root,None)
            receipt=json.loads((root/'caravan-gguf-source.json').read_text())
            self.assertEqual(receipt['files'],sizes);self.assertEqual(receipt['filename'],list(sizes)[0]);self.assertEqual(len(G.scan_local([root])),1)

    def test_truncated_download_not_published(self):
        import mlx_split_fetch as F
        sizes={'a.gguf':100};a=SimpleNamespace(repo='test/model',gguf_file='a.gguf',dry_run=False,no_progress=True)
        def fetch(repo,d,names,sz,token):(d/'a.gguf').write_bytes(b'short')
        with tempfile.TemporaryDirectory() as d,patch.object(F,'file_sizes',return_value=sizes),patch.object(F,'_range_fetch_all',side_effect=fetch),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,'incomplete'):F._fetch_gguf(a,Path(d),None)
            self.assertFalse((Path(d)/'a.gguf').exists())


class AutomaticPickerTests(unittest.TestCase):
    def setUp(self):
        import web_server
        self.nodes=[dict(id='lead',role='lead',label='1st node',host='local'),dict(id='peer',role='packer',label='2nd node',host='peer')]
        live=[dict(n,ram=dict(total_gb=20,available_gb=16)) for n in self.nodes]
        self.app=SimpleNamespace(configured_nodes=lambda:self.nodes,nodes=lambda:dict(nodes=live),mgr=SimpleNamespace(repo=str(ROOT)))
        self.h=object.__new__(web_server.make_handler(self.app));self.h._json=lambda code,out:(code,out)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root_patch=patch.object(G,'GGUF_ROOTS',[self.root]);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.body=dict(repo_id='test/model',source='gguf',gguf_file='a.gguf')

    def download(self,files,**kwargs):
        self.start=Mock(return_value=dict(id='job'))
        with patch.object(P,'_fetch_repo_blobs',return_value=dict(gguf_files=files)),patch.object(P,'start_download',self.start),patch.object(P,'_job_set'):
            return self.h._api_picker_download(dict(self.body,**kwargs))

    def test_small_model_skips_share_planner(self):
        with patch('web_gguf_shares.preview',side_effect=AssertionError('must not split')):
            status,out=self.download([dict(rfilename='a.gguf',size=1_000_000_000)])
        self.assertEqual(status,200);self.assertEqual(out['stages'],1);self.assertEqual(out['job']['load_id'],'gguf/a')

    def test_unsupported_architecture_automatically_downloads_whole(self):
        import gguf_share_download as D
        with patch('web_gguf_shares.preview',side_effect=D.UnsupportedLayout('whole file')):
            status,out=self.download([dict(rfilename='a.gguf',size=20_000_000_000)])
        self.assertEqual(status,200);self.assertEqual(out['stages'],1);self.start.assert_called_once()

    def test_no_custom_engine_automatically_uses_standard_engine(self):
        with patch('web_gguf_shares.preview',return_value=dict(safe=True)),patch('gguf_runtime.current',side_effect=FileNotFoundError):
            status,out=self.download([dict(rfilename='a.gguf',size=20_000_000_000)])
        self.assertEqual(status,200);self.assertEqual(out['stages'],1)

    def test_multipart_skips_share_planner_and_loads_first(self):
        self.body['gguf_file']='a-00002-of-00002.gguf'
        with patch('web_gguf_shares.preview',side_effect=AssertionError('must not split multipart')):
            status,out=self.download([dict(rfilename=f'a-{i:05d}-of-00002.gguf',size=10_000_000_000) for i in (1,2)])
        self.assertEqual(status,200);self.assertEqual(out['job']['load_id'],'gguf/a-00001-of-00002')
        self.assertEqual(out['totals']['full'],20_000_000_000)

    def test_missing_part_rejects_before_start(self):
        self.body['gguf_file']='a-00002-of-00002.gguf'
        status,out=self.download([dict(rfilename=self.body['gguf_file'],size=1_000_000_000)])
        self.assertEqual(status,400);self.start.assert_not_called()

    def test_downloaded_gguf_catalog_and_load_prompt_agree(self):
        from web_server import App
        with (self.root/'a.gguf').open('wb') as f:f.truncate(60_000_000)
        entries=App.gguf_entries(self.app,[dict(n,ram=dict(total_gb=20)) for n in self.nodes])
        entry=next(e for e in entries if e['id']=='gguf/a');self.assertTrue(entry['usable'])
        self.app.list_loadable_models=lambda:entries;self.app.optimizer=SimpleNamespace(snapshot=lambda:dict(running=False))
        self.app.mgr.switch=Mock(return_value=dict(status='starting_lead'))
        status,out=self.h._api_load(dict(model_id='gguf/a'));self.assertEqual(status,200)
        self.assertEqual(self.app.mgr.switch.call_args.kwargs['entry']['lead_path'],str(self.root/'a.gguf'))

    def test_downloaded_mlx_shows_in_settings_and_loads_by_repo_id(self):
        import model_inventory as inv
        import web_catalog as catalog
        from test_model_inventory import _write_fake_mlx
        model = _write_fake_mlx(self.root, 'mlx-community--Tiny-4bit')
        inventory = inv.inventory_payload(roots=[self.root])
        live = [dict(self.nodes[0], ram=dict(total_gb=20, available_gb=16))]
        entries = catalog.build_entries_from_inventories(node_inventories=[dict(id='lead', label='1st node', role='lead', models=inventory['models'])], nodes=live, fit_nodes=live, include_unusable=True)
        entry = next(e for e in entries if e['hf'] == 'mlx-community/Tiny-4bit')
        self.assertTrue(entry['usable'])
        self.app.list_loadable_models=lambda:entries
        self.app.optimizer=SimpleNamespace(snapshot=lambda:dict(running=False))
        self.app.mgr.switch=Mock(return_value=dict(status='starting_lead'))
        status,out=self.h._api_load(dict(model_id='mlx-community/Tiny-4bit'))
        self.assertEqual(status,200)
        self.assertEqual(self.app.mgr.switch.call_args.kwargs['entry']['lead_path'],str(model))

    def test_load_failure_returned_with_reason(self):
        self.app.list_loadable_models=lambda:[];self.app.optimizer=SimpleNamespace(snapshot=lambda:dict(running=False))
        self.app.mgr.switch=Mock(side_effect=RuntimeError('Not enough free memory. Close other apps.'))
        status,out=self.h._api_load(dict(model_id='model'));self.assertEqual(status,400);self.assertIn('Close other apps',out['error'])


class PathAndStatusTests(unittest.TestCase):
    def test_profile_idempotence_and_removal_preserve_user_content(self):
        with tempfile.TemporaryDirectory() as h:
            home=Path(h);p=home/'.zprofile';p.write_text('# my settings\nexport EDITOR=vi\n')
            PathSetup.configure(home=home);once=p.read_text();PathSetup.configure(home=home)
            self.assertEqual(p.read_text(),once);self.assertEqual(once.count(PathSetup.START),1)
            PathSetup.configure('remove',home);self.assertEqual(p.read_text(),'# my settings\nexport EDITOR=vi\n')

    def test_bash_login_shell_gets_block_too(self):
        with tempfile.TemporaryDirectory() as h:
            PathSetup.configure(home=h,shell='/bin/bash');PathSetup.configure(home=h,shell='/bin/bash')
            for name in ('.zprofile','.bash_profile'):self.assertEqual((Path(h)/name).read_text().count(PathSetup.START),1)

    def test_linked_profile_not_overwritten(self):
        with tempfile.TemporaryDirectory() as h:
            home=Path(h);target=home/'other';target.write_text('keep');(home/'.zprofile').symlink_to(target)
            with self.assertRaises(ValueError):PathSetup.configure(home=h)
            self.assertEqual(target.read_text(),'keep')

    def test_incomplete_marked_block_refused(self):
        with tempfile.TemporaryDirectory() as h:
            p=Path(h)/'.zprofile';p.write_text(PathSetup.START+'\nkeep')
            with self.assertRaises(ValueError):PathSetup.configure(home=h)
            self.assertTrue(p.read_text().endswith('keep'))

    def status(self,data=None,missing=False,network_error=False):
        response=Mock();response.__enter__=Mock(return_value=io.StringIO(json.dumps(data)));response.__exit__=Mock(return_value=False)
        with patch.object(Service,'stored',side_effect=ValueError('missing') if missing else None,return_value=dict(port=8190)),patch.object(Service,'assert_owned'),patch.object(CLI.urllib.request,'urlopen',side_effect=OSError('offline') if network_error else None,return_value=response),contextlib.redirect_stdout(io.StringIO()) as out:
            result=CLI.main(['status'])
        self.assertEqual(len(out.getvalue().splitlines()),1)
        return result,out.getvalue().strip()

    def test_running_status_one_line(self):self.assertEqual(self.status(dict(worker=dict(status='idle'))),(0,'Caravan is running'))
    def test_stopped_status_has_fix(self):
        result,text=self.status(network_error=True);self.assertEqual(result,1);self.assertIn('caravan start',text)
    def test_missing_setup_status_has_fix(self):
        result,text=self.status(missing=True);self.assertEqual(result,1);self.assertIn('install command again',text)
    def test_model_error_status_is_one_line(self):
        result,text=self.status(dict(worker=dict(error='Not enough\nmemory')));self.assertEqual(result,1);self.assertIn('Not enough memory',text)


class StartupAndDiscoveryTests(unittest.TestCase):
    def test_explicit_backup_preserves_bytes_and_unloads_only_owned_label(self):
        import plistlib
        with tempfile.TemporaryDirectory() as h:
            plan=SC.make_plan(kind='web',home=h,repo=str(ROOT),python=sys.executable)
            paths=SC.paths(plan);paths['plist'].parent.mkdir(parents=True)
            old=SC.render(plan);old['ProgramArguments'][1]='/old/caravan/proxy/web_server.py'
            raw=plistlib.dumps(old);paths['plist'].write_bytes(raw)
            run=Mock(return_value=SimpleNamespace(returncode=0))
            with contextlib.redirect_stdout(io.StringIO()):Service.backup_old_service(plan,run)
            saved=list((Path(h)/'.caravan/service-backups').glob('*/*.plist'))
            self.assertEqual(saved[0].read_bytes(),raw);self.assertFalse(paths['plist'].exists())
            self.assertEqual(run.call_args.args[0],['bootout',Service.domain()+'/'+plan['label']])

    def test_unrelated_command_not_backed_up_or_stopped(self):
        import plistlib
        with tempfile.TemporaryDirectory() as h:
            plan=SC.make_plan(kind='web',home=h,repo=str(ROOT),python=sys.executable)
            paths=SC.paths(plan);paths['plist'].parent.mkdir(parents=True)
            old=SC.render(plan);old['ProgramArguments']=['/bin/echo','unrelated'];paths['plist'].write_bytes(plistlib.dumps(old));run=Mock()
            with self.assertRaisesRegex(ValueError,'verified'):Service.backup_old_service(plan,run)
            run.assert_not_called();self.assertTrue(paths['plist'].exists())

    def test_optional_tailscale_bad_output_silent(self):
        from discovery import tailscale
        for output in ('not JSON','','[]','null'):
            with patch.object(tailscale,'_find_binary',return_value='tailscale'),patch.object(tailscale.subprocess,'run',return_value=SimpleNamespace(stdout=output)),contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(tailscale.get_peers(),[]);self.assertEqual(out.getvalue(),'')


class UiContractTests(unittest.TestCase):
    def test_no_hidden_download_option_and_quant_is_download(self):
        text=(ROOT/'proxy/web/index.html').read_text()
        self.assertNotIn('ggufFullFallback',text);self.assertIn('btn.innerHTML = `Download ',text)
        self.assertIn('Could not load:',text);self.assertIn('e.error || e.message',text)
        self.assertIn('not downloaded',text)

    def test_topology_add_card_banner_and_pairing_columns(self):
        text=(ROOT/'proxy/web/index.html').read_text()
        self.assertIn('class="ghost add-mac-card"',text);self.assertIn('+ Add a Mac',text)
        self.assertIn('Have another Mac? Add it to run bigger models.',text)
        self.assertIn('caravan-add-mac-dismissed',text);self.assertIn('count !== 1 || dismissed',text)
        self.assertNotIn('href="/pairing">Add Macs',text)
        self.assertIn('id="pairingPanel"',text)
        for file in ('index.html','pairing.html'):
            html=(ROOT/'proxy/web'/file).read_text();self.assertIn('pairing-columns',html)
            self.assertIn('On the new Mac',html);self.assertIn('On your first Mac',html)
        css=(ROOT/'proxy/web/pairing.css').read_text()
        self.assertIn('grid-template-columns:1fr 1fr',css);self.assertIn('@media(max-width:640px)',css)
        self.assertIn('--bg: #050504',css);self.assertNotIn('@import',css)
        js=(ROOT/'proxy/web/pairing.js').read_text()
        self.assertIn('nodeCard-',js);self.assertIn('Remove this Mac',js);self.assertIn('X-Caravan-Pairing',js)

    def test_inline_and_pairing_javascript_parse(self):
        import re
        if not shutil.which('node'):self.skipTest('node not installed')
        text=(ROOT/'proxy/web/index.html').read_text()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'inline.js';p.write_text('\n'.join(re.findall(r'<script>(.*?)</script>',text,re.S)))
            for script in (p,ROOT/'proxy/web/pairing.js'):
                result=subprocess.run(['node','--check',str(script)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)


class FullUninstallTests(unittest.TestCase):
    def setup_jobs(self, home):
        import plistlib
        import caravan_uninstall as U
        jobs=[]
        for name,kind in [('web','web'),('proxy','proxy')]:
            plan=SC.make_plan(kind=kind,name=name,home=str(home),repo=str(ROOT),python=sys.executable)
            paths=SC.paths(plan);paths['plist'].parent.mkdir(parents=True,exist_ok=True)
            paths['config'].parent.mkdir(parents=True,exist_ok=True)
            paths['plist'].write_bytes(plistlib.dumps(SC.render(plan)))
            paths['config'].write_text(json.dumps(plan));jobs.append(paths['plist'])
        model=home/'.caravan/models/keep.gguf';model.parent.mkdir(parents=True);model.write_text('keep')
        watchdog=home/'Library/LaunchAgents/com.caravan.remote-access.tailscale-watchdog.plist';watchdog.write_text('not managed')
        PathSetup.configure(home=home)
        return jobs,model,watchdog

    def test_default_removes_all_jobs_data_path_but_keeps_watchdog(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d,patch.object(Service,'check_platform'),patch.object(U,'workers',return_value={}):
            home=Path(d);jobs,model,watchdog=self.setup_jobs(home)
            run=Mock(return_value=SimpleNamespace(returncode=0))
            result=U.uninstall(home,run=run,yes=True)
            self.assertTrue(all(not p.exists() for p in jobs));self.assertFalse(model.exists());self.assertTrue(watchdog.exists())
            self.assertNotIn(PathSetup.START,(home/'.zprofile').read_text());self.assertIn('all Caravan data removed',result)
            self.assertEqual(len([c for c in run.call_args_list if c.args[0][0]=='bootout']),2)

    def test_everything_requires_confirmation_before_any_changes(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d,patch.object(Service,'check_platform'):
            home=Path(d);jobs,model,watchdog=self.setup_jobs(home);run=Mock()
            self.assertIn('Cancelled',U.uninstall(home,confirm=lambda p:'no',run=run))
            self.assertTrue(all(p.exists() for p in jobs));self.assertTrue(model.exists());run.assert_not_called()

    def test_confirmed_everything_only_removes_managed_root(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d,patch.object(Service,'check_platform'),patch.object(U,'workers',return_value={}):
            home=Path(d);jobs,model,watchdog=self.setup_jobs(home)
            U.uninstall(home,confirm=lambda p:'yes',run=Mock(return_value=SimpleNamespace(returncode=1)))
            self.assertFalse((home/'.caravan').exists());self.assertTrue(watchdog.exists())

    def test_unrelated_prefixed_job_not_removed(self):
        import caravan_uninstall as U
        import plistlib
        with tempfile.TemporaryDirectory() as d,patch.object(Service,'check_platform'),patch.object(U,'workers',return_value={}):
            home=Path(d);jobs,model,watchdog=self.setup_jobs(home)
            alien=watchdog.parent/'com.caravan.v3.unrelated.plist';alien.write_bytes(plistlib.dumps(dict(Label=alien.stem,ProgramArguments=['/bin/echo','hi'])))
            result=U.uninstall(home,yes=True,run=Mock(return_value=SimpleNamespace(returncode=1)))
            self.assertTrue(alien.exists());self.assertIn('Unverified',result)

    def test_pid_reuse_does_not_stop_unrelated_process(self):
        import caravan_uninstall as U
        send=Mock();self.assertFalse(U.stop_exact(123,'expected',inspect=lambda p:'different',send=send));send.assert_not_called()
        inspect=Mock(side_effect=['expected','different']);send=Mock()
        U.stop_exact(123,'expected',inspect=inspect,send=send,pause=lambda x:None)
        self.assertEqual(send.call_count,1)

    def test_only_exact_repo_worker_paths_owned_not_name_sweeps(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d:
            rows=f'101 python3 {ROOT}/agent/mlx_worker.py --port 8194\n102 python3 /other/agent/mlx_worker.py --port 8194\n103 /bin/sh -c python3 {ROOT}/agent/mlx_worker.py\n104 /Library/Frameworks/Python.framework/Python {ROOT}/agent/mlx_worker.py --port 8194'
            found=U.workers(Path(d),{ROOT},listing=rows,inspect=lambda p:'')
            self.assertEqual(set(found),{101,104})

    def test_no_remote_commands_in_uninstaller(self):
        text=(ROOT/'tools/caravan_uninstall.py').read_text()
        self.assertNotIn('subprocess.run(["ssh"',text)
        self.assertNotIn('pkill',text)


class SshUninstallMarkersTests(unittest.TestCase):
    def test_only_exact_marked_ssh_entries_removed(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);ssh=home/'.ssh';ssh.mkdir()
            peer='a'*32
            keep='Host my-server\n  HostName example.test\n'
            (ssh/'config').write_text(keep+f'# BEGIN caravan-pair:{peer}\nHost caravan-peer\n# END caravan-pair:{peer}\n')
            (ssh/'known_hosts').write_text('my-server ssh-ed25519 keep\n'+f'caravan ssh-ed25519 own # caravan-pair:{peer}\n')
            (ssh/'authorized_keys').write_text('ssh-ed25519 keep\n'+f'restrict ssh-ed25519 own # caravan-pair:{peer}\n')
            changes=dict((p.name,text) for p,text in U.marked_ssh_edits(home))
            self.assertEqual(changes['config'],keep)
            self.assertEqual(changes['known_hosts'],'my-server ssh-ed25519 keep\n')
            self.assertEqual(changes['authorized_keys'],'ssh-ed25519 keep\n')
            self.assertIn('# BEGIN caravan-pair:',(ssh/'config').read_text()) # preview only

    def test_malformed_ssh_marker_refuses(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);(home/'.ssh').mkdir();(home/'.ssh/config').write_text('# BEGIN caravan-pair:'+'a'*32+'\nkeep')
            with self.assertRaisesRegex(ValueError,'Incomplete'):U.marked_ssh_edits(home)

    def test_size_and_reminder_in_single_confirmation(self):
        import caravan_uninstall as U
        with tempfile.TemporaryDirectory() as d,patch.object(Service,'check_platform'):
            home=Path(d);root=home/'.caravan';root.mkdir();(root/'keep').write_bytes(b'x'*1000)
            confirm=Mock(return_value='n');run=Mock()
            result=U.uninstall(home,confirm=confirm,run=run)
            prompt=confirm.call_args.args[0]
            self.assertIn('GB total',prompt);self.assertIn('Remove paired Macs first',prompt);self.assertIn('models, settings',prompt)
            run.assert_not_called();self.assertIn('Cancelled',result)


class StartupIdentityHardeningTests(unittest.TestCase):
    def test_shell_mentioning_worker_is_not_owned(self):
        import caravan_uninstall as U
        import plistlib
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);path=home/'com.caravan.v3.web.plist'
            path.write_bytes(plistlib.dumps(dict(Label=path.stem,WorkingDirectory=str(ROOT),ProgramArguments=['/bin/echo',str(ROOT/'proxy/web_server.py')])))
            self.assertIsNone(U.owned_plist(path,home))

    def test_generated_plist_has_installation_marker(self):
        plan=SC.make_plan(kind='web',repo=str(ROOT),python=sys.executable)
        self.assertEqual(SC.render(plan)['Comment'],'Caravan managed service v3')
