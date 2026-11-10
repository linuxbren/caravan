const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
class El {constructor(){this.children=[];this.disabled=false;this._text='';}set textContent(t){this._text=t;this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join(' ');}append(e){this.children.push(e);}replaceChildren(...es){this._text='';this.children=es;}}
(async()=>{
 const button=new El(),out=new El(),requests=[];const error=process.argv[2]==='error';
 const data={nodes:[{label:'Mini <not HTML>',interfaces:[{interface:'en2',addresses:['169.254.1.2'],kind:'thunderbolt'}]}],graph:{edges:[{source:'a',target:'b',source_interface:'en2',address:'169.254.1.3'}],warning:'Candidates only'}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../../proxy/web/thunderbolt.js'),'utf8'),{document:{getElementById:id=>id==='thunderboltInspect'?button:out,createElement:()=>new El()},fetch:async(...args)=>{requests.push(args);return {ok:!error,json:async()=>error?{error:'offline'}:data};}});
 assert.equal(requests.length,0);await button.onclick();assert.equal(requests.length,1);assert.equal(requests[0].length,1);assert.equal(requests[0][0],'/api/thunderbolt');assert.equal(button.disabled,false);
 assert.match(out.textContent,error?/offline.*not changed/:/candidate only/);if(!error)assert.match(out.textContent,/Mini <not HTML>/);
})().catch(e=>{console.error(e);process.exit(1)});
