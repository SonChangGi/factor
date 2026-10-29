const {JSDOM}=require('./integrated_dom_runtime.cjs');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {capitalSeries,strategySeries,refreshNotice}=require('../factor_lab/web/integrated.js');
const web=path.join(__dirname,'../factor_lab/web');
const dates=['2025-02-03','2025-02-04','2025-02-05','2025-02-06','2025-02-07','2025-02-10'];
const nav=[.999,2,null,0,-.1,3].map((value,i)=>({date:dates[i],value}));
const identity={resultId:'audit',inputHash:'b'.repeat(64),codeHash:'c'.repeat(64)};
const factor=(id,label,values=nav)=>({id,label,status:'available',family:'return',definition:{selectionEligible:true},nav:values,drawdown:values.map(p=>({date:p.date,value:p.value==null?null:-.1})),metrics:{cagr:.3,mdd:-.1},holdings:[],history:[]});
const fixture={schemaVersion:'integrated-factor/v1',resultIdentity:identity,generatedAt:'2025-02-11T01:00:00Z',data:{asOf:dates.at(-1),snapshotId:identity.inputHash,requestedCount:2,pricedCount:1,eligibleCount:1,symbols:[{symbol:'A',source:'Yahoo Finance',collectedAt:'2025-02-11T01:00:00Z',status:'eligible'},{symbol:'B',source:'Yahoo Finance',status:'excluded',exclusionReasons:['history_below_252']}]},factors:[factor('MOM12_1','=Formula'),factor('OTHER','Other')],selection:{current:{status:'held',executionStatus:'executed'},history:[{date:'2025-01-31',executionDate:dates[0],holdings:[]}],nav,drawdown:nav.map(p=>({date:p.date,value:p.value==null?null:-.1})),metrics:{cagr:.3},holdings:[],cashWeight:1},comparisons:[{id:'SPY',label:'SPY',nav:[{date:'2016-01-04',value:.5},...dates.map((date,i)=>({date,value:2+i})),{date:'2025-03-01',value:99}]}],settings:{execution_delay_sessions:1}};
const status={schemaVersion:'factor-refresh-status/v1',status:'failed',attempt:{targetDataAsOf:'2025-02-11',sourceCommit:'a'.repeat(40)},lastGood:{dataAsOf:dates.at(-1),...identity,calculationSourceCommit:'d'.repeat(40)}};
const clone=value=>JSON.parse(JSON.stringify(value));
const before=clone(fixture);
const series=strategySeries([{points:nav},{points:fixture.comparisons[0].nav}]);
assert.deepEqual(series[0].points,capitalSeries([{points:nav}])[0].points);
assert(Math.abs(series[0].points[0].value+.001)<1e-12,'strategy retains initial cost');
assert.equal(series[1].points[0].value,0);
assert.deepEqual(series[1].points.map(p=>p.date),dates,'earlier benchmark history and later observations are excluded');
assert.equal(series[1].points.at(-1).value,2.5);
assert.equal(refreshNotice(status,fixture),'02/11 갱신 보류 · 마지막 정상 02/10');
assert.equal(refreshNotice({...status,status:'ok'},fixture),'');
assert.equal(refreshNotice({...status,status:'delayed'},fixture),'02/11 갱신 지연 · 마지막 정상 02/10');
for(const modify of [s=>s.lastGood.resultId='other',s=>s.lastGood.inputHash='other',s=>s.lastGood.codeHash='other',s=>s.lastGood.dataAsOf='2025-02-07',s=>s.attempt.targetDataAsOf=dates.at(-1),s=>s.attempt.sourceCommit='bad',s=>s.lastGood.calculationSourceCommit='bad']){const invalid=clone(status);modify(invalid);assert.equal(refreshNotice(invalid,fixture),'','unmatched, malformed and obsolete operational status stays silent');}
const unknownTarget={...status,attempt:{...status.attempt,targetDataAsOf:null,finishedAtUtc:'2025-02-11T01:01:00Z'}};
assert.equal(refreshNotice(unknownTarget,fixture),'최근 갱신 보류 · 마지막 정상 02/10','new preflight failure remains visible when its target is unknown');
assert.equal(refreshNotice({...unknownTarget,status:'delayed',attempt:{...unknownTarget.attempt,finishedAtUtc:null,startedAtUtc:'2025-02-11T01:01:00Z'}},fixture),'최근 갱신 지연 · 마지막 정상 02/10','unknown target may use a newer started timestamp when finished time is absent');
for(const finishedAtUtc of ['2025-02-11T00:59:59Z',fixture.generatedAt,null,'invalid'])assert.equal(refreshNotice({...unknownTarget,attempt:{...unknownTarget.attempt,finishedAtUtc}},fixture),'','old, equal, missing and invalid unknown-target timestamps cannot mask the current result');
async function setup(query,operation=status){
 const dom=new JSDOM(fs.readFileSync(path.join(web,'integrated.html'),'utf8'),{url:'https://example.test/factor/'+query,runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;let blob,filename;
 w.fetch=async url=>{if(String(url).includes('refresh-status')&&operation instanceof Error)throw operation;return {ok:true,json:async()=>String(url).includes('legacy-definitions')?{rows:[]}:String(url).includes('refresh-status')?operation:fixture};};
 w.URL.createObjectURL=value=>{blob=value;return 'blob:test';};w.URL.revokeObjectURL=()=>{};const anchorClick=w.HTMLAnchorElement.prototype.click;w.HTMLAnchorElement.prototype.click=function(){if(this.download)filename=this.download;else anchorClick.call(this);};
 w.eval(fs.readFileSync(path.join(web,'integrated_charts.js'),'utf8'));w.eval(fs.readFileSync(path.join(web,'integrated.js'),'utf8'));await new Promise(r=>setTimeout(r,15));
 return {dom,w,d:w.document,download:()=>({blob,filename})};
}
const key=(w,svg,value)=>svg.dispatchEvent(new w.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
async function main(){
 let {w,d,download}=await setup('?view=factor&factor=MOM12_1');
 const single=d.querySelector('#single-factor-content .lab-chart-wrap'),svg=single.querySelector('svg'),scale=single.querySelector('[data-chart-scale]');
 key(w,svg,'Home');assert.equal(single.querySelector('.lab-chart-values b').textContent,'-0.10%');
 const url=w.location.href,metrics=d.querySelector('#single-factor-content .lab-metrics').textContent,holding=d.getElementById('single-factor-month').value;
 const linear=svg.querySelector('path.trace').getAttribute('d');scale.value='log';scale.dispatchEvent(new w.Event('change'));
 assert.equal(single.dataset.chartScale,'log');assert.equal(single.querySelector('[data-scale-note]').hidden,false);
 const log=svg.querySelector('path.trace').getAttribute('d');assert.notEqual(log,linear);assert.equal((log.match(/M/g)||[]).length,2,'gaps and nonpositive wealth break the log path');assert(!/NaN|Infinity/.test(svg.innerHTML));
 assert.equal(single.querySelector('.lab-chart-values strong').textContent,dates[0]);assert.equal(single.dataset.observationPinned,'true');assert.equal(single.querySelector('.lab-chart-values b').textContent,'-0.10%');
 key(w,svg,'ArrowRight');key(w,svg,'ArrowRight');key(w,svg,'ArrowRight');assert.equal(single.querySelector('.lab-chart-values b').textContent,'-100.00%');assert.equal(svg.querySelectorAll('.dot').length,0,'zero wealth remains available in readout without an invalid log coordinate');
 assert.equal(w.location.href,url);assert.equal(d.getElementById('single-factor-month').value,holding);assert.equal(d.querySelector('#single-factor-content .lab-metrics').textContent,metrics);assert.equal(d.querySelectorAll('#single-factor-content select[data-chart-scale]').length,1,'only cumulative wealth has a scale control; drawdown remains linear');
 scale.value='linear';scale.dispatchEvent(new w.Event('change'));assert.equal(svg.querySelector('path.trace').getAttribute('d'),linear);
 d.querySelector('[data-view="explore"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));d.querySelector('[data-factor="MOM12_1"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));const detailSVG=d.querySelector('#factor-detail svg');key(w,detailSVG,'Home');assert.equal(d.querySelector('#factor-detail .lab-chart-values b').textContent,'-0.10%','explore and single retain exactly the same original-capital return');
 const search=d.getElementById('factor-search');search.value='Formula';search.dispatchEvent(new w.Event('input'));assert.equal(d.querySelectorAll('#factor-table tbody tr').length,1);d.getElementById('export-factors').click();assert.equal(download().filename,'factors-filtered.csv');const text=await new Promise(resolve=>{const reader=new w.FileReader();reader.onload=()=>resolve(reader.result);reader.readAsText(download().blob);});assert(text.includes('MOM12_1'));assert(!text.includes('OTHER'));assert(text.includes("'=Formula"),'CSV formula-injection protection remains');
 d.querySelector('[data-view="data"]').click();const data=d.getElementById('data-content');assert.equal(data.querySelector('h2').textContent,'입력 데이터 요약');assert(data.querySelector('.lab-data-counts').textContent.includes('가격 보유(벤치마크 포함) 1'));assert(data.textContent.includes('Yahoo Finance'));assert(data.textContent.includes('252일 이력 부족 1'));assert.equal(data.querySelector('.lab-technical').open,false);assert(data.querySelector('.lab-technical').textContent.includes(identity.inputHash));assert.equal(d.getElementById('refresh-status').hidden,false);
 d.querySelector('[data-view="current"]').click();const main=d.querySelector('#current-content .lab-chart-wrap'),mainSVG=main.querySelector('svg');key(w,mainSVG,'Home');assert.deepEqual([...main.querySelectorAll('.lab-chart-values b')].map(n=>n.textContent),['-0.10%','0.00%']);assert.equal(main.querySelector('.lab-chart-values strong').textContent,dates[0]);w.close();
 for(const operation of [null,{...status,status:'ok'},new Error('offline'),{...status,lastGood:{...status.lastGood,resultId:'old'}}]){const ctx=await setup('?view=current',operation);assert.equal(ctx.d.getElementById('refresh-status').hidden,true);assert.equal(ctx.d.getElementById('result-state').textContent,'보유');assert.equal(ctx.d.getElementById('app-message').hidden,true);ctx.w.close();}
 assert.deepEqual(fixture,before,'display conversion and filtering never mutate financial source data');
 console.log('PASS audit UI: cost-inclusive single/explore/main with aligned benchmark period, linear/log wealth gaps and zero/negative wealth, unchanged observation/holdings/metrics/URL, filtered secure CSV, data-first summary and matched optional operational status');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
