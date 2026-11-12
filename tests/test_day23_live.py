"""Live clean-install follow-up: portable inventory, production JS and defaults."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ('agent', 'proxy'):
    sys.path.insert(0, str(ROOT / folder))
import model_inventory as inv
import web_catalog as catalog
import web_nodes
import web_settings as settings
import tuned_settings as tuned
from test_model_inventory import _write_fake_mlx

HTML = (ROOT/'proxy/web/index.html').read_text()


class FreshInventoryTests(unittest.TestCase):
    def rows(self, models):
        node = dict(id='local', label='My Mac', role='lead', models=models)
        return catalog.build_entries_from_inventories(node_inventories=[node], nodes=[node])

    def test_metadata_only_legacy_starter_is_not_a_settings_model(self):
        with tempfile.TemporaryDirectory() as td:
            tree = _write_fake_mlx(Path(td), 'mlx-community--Qwen3-30B-A3B-4bit')
            for shard in tree.glob('*.safetensors'):
                shard.unlink()
            (tree/'caravan-placement.json').write_text(json.dumps(dict(mode='one', node_ids=['exo1'])))
            models = inv.inventory_payload(roots=[td])['models']
            self.assertTrue(models)  # genuine repro: metadata tree is in inventory
            self.assertFalse(next(iter(models.values()))['downloaded'])
            self.assertEqual(self.rows(models), [])

    def test_downloading_weights_adds_same_starter_to_settings(self):
        with tempfile.TemporaryDirectory() as td:
            _write_fake_mlx(Path(td), 'mlx-community--Qwen3-30B-A3B-4bit')
            models = inv.inventory_payload(roots=[td])['models']
            self.assertTrue(next(iter(models.values()))['downloaded'])
            self.assertEqual(len(self.rows(models)), 1)

    def test_partial_real_weights_stay_visible_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            tree = _write_fake_mlx(Path(td), 'test--Partial')
            next(tree.glob('*.safetensors')).unlink()
            rows = self.rows(inv.inventory_payload(roots=[td])['models'])
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]['usable'])
            self.assertTrue(rows[0]['disabled_reason'])

    def test_old_peer_inventory_and_explicit_dev_paths_remain_supported(self):
        rows = self.rows({'test/Old':dict(path='~/.exo/models/test--Old', full_ok=True, kind='full')})
        self.assertEqual(rows[0]['lead_path'], '~/.exo/models/test--Old')
        self.assertTrue(rows[0]['usable'])

    def test_no_config_has_no_lab_ssh_defaults(self):
        with tempfile.TemporaryDirectory() as td, patch.object(settings, 'CONFIG_PATH', Path(td)/'missing'):
            self.assertEqual(web_nodes.nodes_from_config(), [dict(id='local',label='My Mac',role='lead',host='local')])

    def test_gguf_capacity_step_uses_gguf_fit_and_automatic_recommendation(self):
        import web_server
        app=SimpleNamespace(nodes=lambda:{'nodes':[dict(id='local',role='lead',ram={'total_gb':32,'available_gb':24})]})
        handler=web_server.make_handler(app).__new__(web_server.make_handler(app))
        handler._json=lambda code,out:(code,out)
        code,out=handler._api_picker_placement({'source':'gguf','weights_gb':4})
        self.assertEqual(code,200)
        self.assertTrue(out['default_id'])
        code,out=handler._api_picker_placement({'source':'gguf','weights_gb':1000})
        self.assertFalse(out['default_id'])

    def test_existing_dev_config_legacy_fallback_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.toml';p.write_text('[defaults]\nself_tune="off"\n')
            with patch.object(settings, 'CONFIG_PATH', p):
                self.assertEqual(web_nodes.nodes_from_config(), web_nodes.DEFAULT_NODES)


class FreshTuningTests(unittest.TestCase):
    def worker_enabled(self, lead_args, env=None):
        # Execute the production parser's no-learn declarations and the actual
        # worker enable expression without importing MLX on a Linux host.
        tree=ast.parse((ROOT/'agent/mlx_worker.py').read_text())
        ap=argparse.ArgumentParser()
        scope={'os':os,'ap':ap}
        with patch.dict(os.environ, env or {}, clear=True):
            for name in ('_learn_env','_learn_off'):
                node=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
                exec(compile(ast.Module(body=[node],type_ignores=[]),'<worker-parser>','exec'),scope)
            node=next(n for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.args and isinstance(n.value.args[0],ast.Constant) and n.value.args[0].value=='--no-learn')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<worker-parser>','exec'),scope)
            args,_=ap.parse_known_args(lead_args)
        expr=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='_learn_enabled' for t in n.targets))
        return eval(compile(ast.Expression(expr),'<worker-enabled>','eval'),{'args':args})

    def test_fresh_config_enabled_before_any_learned_winners(self):
        with tempfile.TemporaryDirectory() as td, patch.object(settings,'CONFIG_PATH',Path(td)/'missing'):
            fresh=settings.normalize({})
            self.assertEqual(fresh['self_tune'],'auto')
            self.assertTrue(all(v=='auto' for v in fresh.values()))
            lead,_=settings.to_args(fresh)
            self.assertTrue(self.worker_enabled(lead))
            r=tuned.resolve_startup(model_dir=td,spanned=False,path=Path(td)/'unlearned.json',day9_packer_layers=None,day9_pipeline_chats=1,day9_guess_ahead=None,explicit={})
            self.assertIsNotNone(r['entry'])
        self.assertIn("'self_tune = \"auto\"'",(ROOT/'scripts/install.sh').read_text())

    def test_existing_off_and_worker_environment_opt_out_are_preserved(self):
        lead,_=settings.to_args({'self_tune':'off'})
        self.assertFalse(self.worker_enabled(lead))
        lead,_=settings.to_args({})
        self.assertFalse(self.worker_enabled(lead,{'CARAVAN_NO_LEARN':'1'}))
        self.assertEqual(settings.normalize({'guess_ahead':'off','self_tune':'off'})['guess_ahead'],'off')

    def test_on_label_survives_active_status_rendering(self):
        block=HTML[HTML.index('  function renderActive('):HTML.index('  function fmtMin(')]
        self.assertIn('o.id === "self_tune"',block)
        self.assertIn('"Off (config)" : "On"',block)
        self.assertIn('Caravan learns from your chats and remembers faster settings for each model. Pinned choices stay yours.',HTML)


@unittest.skipUnless(shutil.which('node'),'Node needed for executable production UI regressions')
class LiveUiTests(unittest.TestCase):
    def js(self, script):
        result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def model_script(self, body):
        start=HTML.index('  let modelsInflight = null;')
        end=HTML.index('  window.refreshCaravanModels = refreshModels;')
        return '''const assert=require('assert/strict');
const state={}; let payload={models:[],current:null}; let renders=0,requests=0;
const sel={value:'',children:[],onchange:null,appendChild(o){this.children.push(o);if(o.selected||!this.value)this.value=o.value;}};
Object.defineProperty(sel,'innerHTML',{set(v){this.children=[];this.value='';}});
const $=id=>sel;
const document={createElement:()=>({dataset:{}})};
let api=async()=>{requests++;return payload;};
function renderPlace(){renders++;} function renderOpts(){} async function loadOpts(){}
''' + HTML[start:end] + '\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exit(1)});'

    def test_new_download_appears_without_changing_selection(self):
        self.js(self.model_script('''payload={models:[{id:'a',name:'A',usable:true}]};await refreshModels();sel.value='a';
payload={models:[{id:'b',name:'B',usable:true},{id:'a',name:'A',usable:true}],current:'b'};
await refreshModels();assert.equal(sel.value,'a');assert.deepEqual(sel.children.map(o=>o.value),['b','a']);
const before=renders;await refreshModels();assert.equal(renders,before);'''))

    def test_selection_changed_in_flight_and_overlap_are_preserved(self):
        self.js(self.model_script('''let done;api=()=>{requests++;return new Promise(r=>done=r);};
const one=refreshModels(),two=refreshModels();assert.equal(requests,1);sel.value='b';
done({models:[{id:'a',name:'A',usable:true},{id:'b',name:'B',usable:true}],current:'a'});
await Promise.all([one,two]);assert.equal(sel.value,'b');'''))

    def test_removed_selection_falls_back_and_empty_inventory_clears_rows(self):
        self.js(self.model_script('''sel.value='gone';payload={models:[{id:'a',name:'A',usable:true},{id:'b',name:'B',usable:true}],current:'b'};
await refreshModels();assert.equal(sel.value,'b');payload={models:[]};await refreshModels();assert.deepEqual(state.modelRows,{});assert.equal(sel.value,'');'''))

    def test_visible_poll_events_hidden_pause_and_no_overlap(self):
        code=HTML[HTML.index('  let listsInflight = null,'):HTML.index('  document.getElementById("btnCloseTopo").addEventListener')]
        self.js('''const assert=require('assert/strict');const window=new EventTarget();const document=new EventTarget();
global.CustomEvent=class extends Event {constructor(type,opts={}){super(type);this.detail=opts.detail;}};
document.visibilityState='visible';document.getElementById=()=>({classList:{contains:()=>true}});
let count=0, disk=0, node=0, done;let timers=new Map(),tid=0;
const setInterval=(f,ms)=>{timers.set(++tid,{f,ms});return tid;};const clearInterval=id=>timers.delete(id);
window.refreshCaravanModels=()=>{count++;return new Promise(r=>done=r);};window.refreshDisk=async()=>{disk++;};async function pollNodes(){node++;}
''' + code + '''
(async()=>{assert.equal(count,1);assert.equal([...timers.values()][0].ms,5000);
window.dispatchEvent(new Event('caravan-models-changed'));assert.equal(count,1);
done();await new Promise(setImmediate);window.dispatchEvent(new Event('caravan-models-changed'));assert.equal(count,2);
done();await new Promise(setImmediate);document.visibilityState='hidden';document.dispatchEvent(new Event('visibilitychange'));assert.equal(timers.size,0);
window.dispatchEvent(new Event('caravan-models-changed'));assert.equal(count,2);
document.visibilityState='visible';document.dispatchEvent(new Event('visibilitychange'));assert.equal(count,3);done();await new Promise(setImmediate);
window.dispatchEvent(new CustomEvent('caravan-worker-status',{detail:{worker:{model_id:'new',status:'ready'}}}));assert.equal(count,4);done();await new Promise(setImmediate);
window.dispatchEvent(new CustomEvent('caravan-worker-status',{detail:{worker:{model_id:'new',status:'ready'}}}));assert.equal(count,4);assert.equal(disk,4);assert.equal(node,4);
})().catch(e=>{console.error(e);process.exit(1)});''')

    def test_pairing_returns_to_same_quant_with_fresh_nodes_and_selection(self):
        code=HTML[HTML.index('    async function choosePlacement('):HTML.index('    function placementStep(')]
        self.js('''const assert=require('assert/strict');const window=new EventTarget();let steps=0, resumed=false;
const state={searchSeq:0};const q={repo_id:'test/SameQuant',weights_gb:42};const anchor={};const $=()=>({classList:{remove(){}},hidden:false});
async function placementStep(place,quant,a,keep){assert.equal(quant,q);assert.equal(a,anchor);steps++;if(steps===1)return {addMac:true,keep:'one:old'};assert.deepEqual(place.options,['old','new']);assert.equal(keep,'one:old');return 'split:new';}
window.openCaravanPairing=()=>setImmediate(()=>window.dispatchEvent(new Event('caravan-pairing-complete')));
function openPicker(opts){assert.equal(opts.resume,true);resumed=true;}
async function api(path,opts){assert.equal(path,'/api/picker/placement');assert.deepEqual(JSON.parse(opts.body),{weights_gb:42,repo_id:'test/SameQuant'});return {options:['old','new']};}
''' + code + '''
(async()=>{assert.equal(await choosePlacement({options:['old']},q,anchor),'split:new');assert.equal(steps,2);assert.equal(resumed,true);})().catch(e=>{console.error(e);process.exit(1)});''')

    def test_no_fit_and_no_options_still_offer_add_mac(self):
        code=HTML[HTML.index('    function placementStep('):HTML.index('    function fmtBytes(')]
        self.js('''const assert=require('assert/strict');const buttons={};let rendered='';let selected=null;
const el={remove(){},addEventListener(){},scrollIntoView(){},querySelector:()=>selected};
Object.defineProperty(el,'innerHTML',{set(html){rendered=html;}});
const document={querySelectorAll:()=>[],createElement:()=>el};const $=id=>buttons[id]||(buttons[id]={appendChild(){},focus(){}});
function escapeHtml(s){return s;}function placeButtonLabel(){return 'Download';}
''' + code + '''
(async()=>{const result=placementStep({options:[],fit:{color:'red'}},{repo_id:'test/Big'},null,null);
assert.match(rendered,/id="btnPlaceAddMac" class="primary"/);assert.match(rendered,/needs more memory/);assert.equal(buttons.btnPlaceGo.disabled,true);
buttons.btnPlaceAddMac.onclick();assert.deepEqual(await result,{addMac:true,keep:null});})().catch(e=>{console.error(e);process.exit(1)});''')

    def test_all_side_drawers_third_width_pairing_exception_and_mobile(self):
        self.assertGreaterEqual(HTML.count('width: clamp(320px, 33vw, 640px)'),3)
        self.assertNotIn('#topoDrawer { width:min(880px',HTML)
        self.assertIn('#topoDrawer.pairing-open { width:min(880px,94vw)',HTML)
        self.assertIn('.drawer, .drawer-left, #settingsDrawer, #topoDrawer { width:100vw',HTML)
        self.assertIn('.pairing-columns { grid-template-columns:1fr; }',HTML)

    def test_download_completion_crosses_iife_boundary(self):
        self.assertNotIn('typeof refreshModels === "function"',HTML)
        job=HTML[HTML.index('    async function pollJob('):HTML.index('    function diskLocation(')]
        self.assertIn('caravan-models-changed',job)
        self.assertIn('window.refreshCaravanModels = refreshModels',HTML)
        pairing=(ROOT/'proxy/web/pairing.js').read_text()
        self.assertIn("CustomEvent('caravan-pairing-complete')",pairing)


if __name__=='__main__':unittest.main()
