const {JSDOM} = require('./integrated_dom_runtime.cjs');
const assert = require('node:assert/strict');
const {bind} = require('../momentum_factor_lab/web/integrated_charts.js');
const {finite = value => typeof value === 'number' && Number.isFinite(value),fmt,linePath,chartTicks,endpointPositions} = require('../momentum_factor_lab/web/integrated.js');

const dates = ['2026-09-28','2026-09-29','2026-09-30','2026-10-01'];
const series = [
  {label:'모형 전략',points:dates.map((date,i) => ({date,value:[0,.1,null,.3][i]}))},
  {label:'SPY',points:dates.map((date,i) => ({date,value:[0,.05,.1,.2][i]}))},
  {label:'QQQ',points:[{date:dates[0],value:0},{date:dates[1],value:.05},{date:dates[3],value:.2}]},
];
const dom = new JSDOM(`<div id="view-current"><select id="month"><option>2026-09-30</option></select><div id="chart-one" class="lab-chart-wrap"><div class="lab-legend">${series.map((s,i) => `<button data-series="${i}" aria-pressed="true">${s.label}</button>`).join('')}</div><svg class="lab-chart" tabindex="0"></svg><div class="lab-chart-values"></div></div><div id="chart-two" class="lab-chart-wrap"><div class="lab-legend"><button data-series="0" aria-pressed="true">낙폭</button></div><svg class="lab-chart compact" tabindex="0"></svg><div class="lab-chart-values"></div></div></div>`,{url:'https://example.test/momentum/?view=current&month=2026-09-30&factor=LOGADV63',pretendToBeVisual:true});
const {window:w} = dom, d = w.document, box = d.getElementById('chart-one'), svg = box.querySelector('svg');
let width = 900;
Object.defineProperty(box,'clientWidth',{get:() => width});
Object.defineProperty(svg,'clientHeight',{value:300});
svg.getBoundingClientRect = () => ({left:80,width:width/2,top:0,height:150});
const second = d.getElementById('chart-two');
Object.defineProperty(second,'clientWidth',{get:() => width});
const api = bind({charts:[{id:'chart-one',series,kind:'pct',title:'누적성과'},{id:'chart-two',series:[{label:'낙폭',points:dates.map((date,i)=>({date,value:-i*.1}))}],kind:'pct',compact:true,title:'낙폭'}],root:d.getElementById('view-current'),palette:['#3182f6','#7c3aed','#008768'],finite,fmt,linePath,chartTicks,endpointPositions});
const originalURL = w.location.href, originalMonth = d.getElementById('month').value;
const values = () => [...box.querySelectorAll('.lab-chart-values b')].map(node => node.textContent);
const date = () => box.querySelector('.observation-date').textContent;
function pointer(name,index,extra={}) {
  const clientX = 80+(58+index/(dates.length-1)*(width-58-16))/2;
  const event = new w.MouseEvent(name,{clientX,bubbles:true});
  for (const [key,value] of Object.entries(extra)) Object.defineProperty(event,key,{value});
  svg.dispatchEvent(event);
}
function key(value) {svg.dispatchEvent(new w.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));}
function assertLabelsInside() {
  const rectangles = [...svg.querySelectorAll('.observation-label rect')];
  rectangles.forEach(rect => {
    const x=Number(rect.getAttribute('x')), y=Number(rect.getAttribute('y'));
    assert(x>=58 && x+Number(rect.getAttribute('width'))<=width-16,'value tag stays inside horizontal plot bounds');
    assert(y>=24 && y+Number(rect.getAttribute('height'))<=272,'value tag stays inside vertical plot bounds');
  });
  const ys = rectangles.map(rect=>({start:Number(rect.getAttribute('y')),end:Number(rect.getAttribute('y'))+Number(rect.getAttribute('height'))})).sort((a,b)=>a.start-b.start);
  for(let i=1;i<ys.length;i++) assert(ys[i].start>=ys[i-1].end,'value tags do not overlap');
}

assert.equal(date(),dates[3]);
assert.deepEqual(values(),['30.00%','20.00%','20.00%']);
assert.equal(svg.querySelectorAll('.endpoint-label').length,0,'no static final-value labels remain');
const trace = svg.querySelector('path.trace'), path = trace.getAttribute('d');
pointer('pointermove',1);
assert.equal(date(),dates[1]);
assert.deepEqual(values(),['10.00%','5.00%','5.00%']);
assert.equal(svg.querySelector('path.trace'),trace,'hover preserves the static plot DOM');
assert.equal(trace.getAttribute('d'),path);
assert([...svg.querySelectorAll('.observation-label')].every(node=>node.dataset.date===dates[1]));
assertLabelsInside();
assert.equal(second.querySelector('.observation-date').textContent,dates[3],'observation is local to the active chart');

pointer('pointermove',2);
assert.deepEqual(values(),['—','10.00%','—'],'null and absent observations are not filled forward');
assert.equal(svg.querySelectorAll('.dot').length,1);
assert.equal(svg.querySelector('[data-series="0"].observation-label').dataset.value,'');
assertLabelsInside();
pointer('pointerleave',2);
assert.equal(date(),dates[3],'unpinned hover resets to the latest date on pointer leave');
pointer('pointerdown',1);
assert.equal(box.dataset.observationPinned,'true');
pointer('pointermove',0);
pointer('pointerleave',0);
assert.equal(date(),dates[1],'click pin persists on hover and pointer leave');
assert(svg.getAttribute('aria-label').includes('관측일 고정'));
key('Escape');
assert.equal(date(),dates[3]);
assert.equal(box.dataset.observationPinned,'false');

key('Home'); assert.equal(date(),dates[0]);
key('ArrowRight'); assert.equal(date(),dates[1]);
key('ArrowLeft'); assert.equal(date(),dates[0]);
key('ArrowLeft'); assert.equal(date(),dates[0]);
key('End'); assert.equal(date(),dates[3]);
key('ArrowRight'); assert.equal(date(),dates[3]);
key('Home');
const legend=box.querySelector('.lab-legend [data-series="0"]');
legend.click();
assert.equal(legend.getAttribute('aria-pressed'),'false');
assert.equal(svg.querySelectorAll('path.trace').length,2);
assert.equal(svg.querySelectorAll('.observation-label').length,2);
assert.deepEqual(values(),['0.00%','0.00%']);
assert.equal(date(),dates[0]);
width=390; w.dispatchEvent(new w.Event('resize'));
assert.equal(svg.getAttribute('viewBox'),'0 0 390 300');
assert.equal(date(),dates[0]);
assert.equal(legend.getAttribute('aria-pressed'),'false');
assert([...svg.querySelectorAll('.observation-value')].every(node=>node.textContent==='0.00%'),'mobile value tags stay concise while the full labels remain in the readout');
assertLabelsInside();
legend.click();
key('Escape');
const stableSVG = box.querySelector('svg');
pointer('pointerdown',0,{pointerType:'touch',pointerId:7});
pointer('pointermove',1,{pointerType:'touch',pointerId:7});
assert.equal(date(),dates[1],'touch drag follows observations');
pointer('pointerup',1,{pointerType:'touch',pointerId:7});
pointer('pointerleave',1,{pointerType:'touch',pointerId:7});
assert.equal(date(),dates[1],'touch selection remains pinned after release');
assert.equal(box.querySelector('svg'),stableSVG,'pointer capture target survives value updates');
assert.equal(w.location.href,originalURL,'chart observation never writes URL state');
assert.equal(d.getElementById('month').value,originalMonth,'chart observation never changes the holdings month');

box.querySelectorAll('.lab-legend button').forEach(button=>button.click());
assert.equal(svg.querySelectorAll('path.trace').length,0);
assert.equal(svg.querySelectorAll('.observation-label').length,0);
assert.equal(svg.querySelectorAll('.dot').length,0);
assert.equal(box.querySelector('.lab-chart-values').textContent,dates[1]);
api.redraw();
const frozen=svg.innerHTML;
api.destroy();
key('Home'); pointer('pointermove',3); legend.click(); width=768; w.dispatchEvent(new w.Event('resize'));
assert.equal(svg.innerHTML,frozen,'destroy detaches pointer, keyboard, legend and resize listeners');
dom.window.close();
const compactDOM = new JSDOM('<div id="compact" class="lab-chart-wrap"><svg></svg><div class="lab-chart-values"></div></div>',{pretendToBeVisual:true});
const compactBox = compactDOM.window.document.getElementById('compact'), compactSVG=compactBox.querySelector('svg');
Object.defineProperty(compactBox,'clientWidth',{value:390});
Object.defineProperty(compactSVG,'clientHeight',{value:130});
const compact = bind({charts:[{id:'compact',series:Array.from({length:5},(_,i)=>({label:`계열 ${i}`,points:[{date:dates[0],value:-.1}]})),kind:'pct',compact:true,title:'낙폭'}],root:compactDOM.window.document,palette:['#3182f6'],finite,fmt,linePath,chartTicks,endpointPositions});
const compactRects = [...compactSVG.querySelectorAll('.observation-label rect')];
assert.equal(compactRects.length,5);
compactRects.forEach((rect,i)=>{const top=Number(rect.getAttribute('y')),bottom=top+Number(rect.getAttribute('height'));assert(top>=24 && bottom<=102,'five labels fit the compact mobile plot');if(i)assert(top>=Number(compactRects[i-1].getAttribute('y'))+Number(compactRects[i-1].getAttribute('height')),'compact mobile value tags do not overlap');});
compact.destroy();compactDOM.window.close();

function synchronizedPeers() {
  const chartMarkup = id => `<div id="${id}" class="lab-chart-wrap"><div class="lab-legend"><button data-series="0" aria-pressed="true">계열</button></div><svg tabindex="0"></svg><div class="lab-chart-values"></div></div>`;
  const dom = new JSDOM(`<div id="active"><select id="factor-month"><option>2026-09-30</option></select>${['performance','drawdown','partial'].map(chartMarkup).join('')}</div><div id="hidden" hidden>${chartMarkup('outside')}</div>`,{url:'https://example.test/momentum/?view=fixed&factor=LOGADV63&factorMonth=2026-09-30',pretendToBeVisual:true});
  const w=dom.window,d=w.document, active=d.getElementById('active');
  const chartDates={performance:dates,drawdown:dates,partial:[dates[0],dates[1],dates[3]],outside:dates};
  const charts=Object.entries(chartDates).map(([id,calendar])=>({id,series:[{label:id,points:calendar.map(date=>({date,value:id==='performance'&&date===dates[2]?null:dates.indexOf(date)*(id==='drawdown'?-.1:.1)}))}],kind:'pct',title:id}));
  for(const box of active.querySelectorAll('.lab-chart-wrap')) {
    Object.defineProperty(box,'clientWidth',{value:900});
    box.querySelector('svg').getBoundingClientRect=()=>({left:0,width:900});
  }
  const api=bind({charts,root:active,palette:['#3182f6'],finite,fmt,linePath,chartTicks,endpointPositions,synchronizeDates:true});
  const box=id=>d.getElementById(id), svg=id=>box(id).querySelector('svg'), date=id=>box(id).dataset.observationDate, pinned=id=>box(id).dataset.observationPinned;
  const pointer=(id,name,index,extra={})=>{const event=new w.MouseEvent(name,{clientX:58+index/(chartDates[id].length-1)*(900-58-16),bubbles:true});for(const [key,value]of Object.entries(extra))Object.defineProperty(event,key,{value});svg(id).dispatchEvent(event);};
  const key=(id,value)=>svg(id).dispatchEvent(new w.KeyboardEvent('keydown',{key:value,bubbles:true}));
  const url=w.location.href, month=d.getElementById('factor-month').value;
  pointer('performance','pointermove',2);
  assert.equal(date('drawdown'),dates[2],'performance hover moves the drawdown cursor to the same trading date');
  assert.equal(box('performance').querySelector('.lab-chart-values b').textContent,'—');
  assert.equal(box('drawdown').querySelector('.lab-chart-values b').textContent,'-20.00%','each chart reads its own same-date value');
  assert.equal(date('partial'),dates[3],'a peer with no exact date is unchanged instead of selecting a nearest date');
  assert.equal(pinned('drawdown'),'false');
  pointer('performance','pointermove',1);
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[1]));
  pointer('performance','pointerleave',1);
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[3]&&pinned(id)==='false'),'hover leave resets exact-date peers together');
  pointer('performance','pointerdown',0);
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[0]&&pinned(id)==='true'),'click propagates the observation and pin state');
  pointer('drawdown','pointerleave',0);
  assert.equal(date('performance'),dates[0]);
  key('drawdown','ArrowRight');
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[1]&&pinned(id)==='true'),'keyboard navigation on the peer updates both directions');
  key('drawdown','ArrowRight');
  assert.equal(date('performance'),dates[2]);
  assert.equal(date('partial'),dates[1],'missing-date peer retains its original pinned observation');
  key('drawdown','Escape');
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[3]&&pinned(id)==='false'),'Escape synchronizes the latest observation and unpins peers');
  key('drawdown','Home'); assert.equal(date('performance'),dates[0]);
  key('performance','End'); assert.equal(date('drawdown'),dates[3]);
  key('drawdown','Escape');
  pointer('performance','pointerdown',0,{pointerType:'touch',pointerId:8});
  pointer('performance','pointermove',1,{pointerType:'touch',pointerId:8});
  pointer('performance','pointerup',1,{pointerType:'touch',pointerId:8});
  assert(['performance','drawdown','partial'].every(id=>date(id)===dates[1]&&pinned(id)==='true'),'touch drag synchronizes the peer observation');
  assert.equal(box('outside').querySelector('svg').innerHTML,'','a chart outside the active root is neither bound nor synchronized');
  assert.equal(w.location.href,url);
  assert.equal(d.getElementById('factor-month').value,month);
  api.destroy();dom.window.close();
}
synchronizedPeers();
console.log('PASS interactive chart DOM: dynamic value tags/dots/date/readout, missing observations, separated in-plot labels, hover reset/click pin/touch drag, keyboard, legends, resize, static plot reuse and state isolation');
console.log('PASS synchronized peers: exact-date performance/drawdown values, pointer/click/touch/keyboard/Escape/leave pin states, unmatched-date preservation and active-root isolation');
