(function (scope) {
'use strict';

const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/** Chart observation is deliberately local: it never changes the selected month or URL. */
function bind({charts, root, palette, finite, fmt, linePath, chartTicks, endpointPositions, synchronizeDates = false}) {
  const cleanups = [], redraws = [], peers = [];
  const comparing=root.id==='view-compare';
  const document = root.ownerDocument || root;
  const window = document.defaultView;
  let destroyed = false;

  for (const chart of charts) {
    const box = [...root.querySelectorAll('.lab-chart-wrap')].find(node => node.id === chart.id);
    if (!box) continue;
    const svg = box.querySelector('svg'), readout = box.querySelector('.lab-chart-values');
    if (!svg || !readout) continue;
    const dates = [...new Set(chart.series.flatMap(series => series.points.map(point => point.date)))].sort();
    if (!dates.length) continue;
    const indexes = new Map(dates.map((date, index) => [date, index]));
    const points = chart.series.map(series => new Map(series.points.map(point => [point.date, point.value])));
    const enabled = chart.series.map(() => true);
    let position = dates.length - 1, pinned = false, hovering = false, activeTouch = null, scale = 'linear';
    let viewStart=0,viewEnd=dates.length-1,pan=null;
    const plottable = value => finite(value) && (scale !== 'log' || value > -1);
    const transform = value => scale === 'log' ? Math.log1p(value) : value;
    const inverse = value => scale === 'log' ? Math.expm1(value) : value;
    let width = 900, height = chart.compact ? 150 : 300, y, observation;
    const L = 58, R = 16, T = 24, B = 28;
    const color = index => palette[index % palette.length];
    const x = date => L + (indexes.get(date)-viewStart) / Math.max(1, viewEnd-viewStart) * (width - L - R);

    function updateObservation() {
      const date = dates[position], cursorX = x(date), mobile = width < 600;
      const font = mobile ? 10 : 11;
      const labelHalf = (font + 5) / 2 + 1;
      const labelMin = T + labelHalf, labelMax = height - B - labelHalf;
      const visible = chart.series.flatMap((series, index) => {
        if (!enabled[index]) return [];
        const value = points[index].get(date);
        return [{index, series, value, y: plottable(value) ? y(value) : labelMax}];
      });
      const gap = Math.min(font + 7, (labelMax - labelMin) / Math.max(1, visible.length - 1));
      const labels = endpointPositions(visible, labelMin, labelMax, gap);
      let output = `<line class="cursor" x1="${cursorX}" x2="${cursorX}" y1="${T}" y2="${height-B}"/>`;
      const dateWidth = 82, dateX = Math.max(L + dateWidth / 2, Math.min(width - R - dateWidth / 2, cursorX));
      output += `<rect class="observation-date-background" x="${dateX-dateWidth/2}" y="3" width="${dateWidth}" height="17" rx="3" fill="var(--panel)"/>`;
      output += `<text class="observation-date" x="${dateX}" y="15" text-anchor="middle" style="font-size:11px;font-weight:650">${escape(date)}</text>`;

      for (const item of labels) {
        const {index, series, value} = item;
        const valueText = fmt(value, chart.kind);
        let label = mobile ? valueText : `${series.label} ${valueText}`;
        // SVG text measurement is unavailable in static DOM tests. This conservative
        // estimate also reserves full-width glyphs used by Korean factor names.
        const textWidth = text => [...text].reduce((sum, c) => sum + (c.charCodeAt(0) > 255 ? font : font * .64), 0);
        const available = width-L-R-16;
        if (textWidth(label) > available) {
          let name = series.label;
          while (name.length && textWidth(`${name}… ${valueText}`) > available) name = name.slice(0,-1);
          label = name ? `${name}… ${valueText}` : valueText;
        }
        const measured = textWidth(label);
        const labelWidth = Math.min(width - L - R - 4, Math.max(30, measured + 12));
        const preferRight = cursorX + labelWidth + 14 <= width - R;
        const labelX = Math.max(L + 2, Math.min(width - R - labelWidth - 2, preferRight ? cursorX + 12 : cursorX - labelWidth - 12));
        const textX = labelX + 6, labelHeight = font + 5;
        if (plottable(value)) {
          const pointY = y(value), edge = preferRight ? labelX : labelX + labelWidth;
          output += `<line class="observation-leader" x1="${cursorX}" y1="${pointY}" x2="${edge}" y2="${item.y}" stroke="${color(index)}" stroke-width=".8" opacity=".55"/>`;
          output += `<circle class="dot" data-series="${index}" cx="${cursorX}" cy="${pointY}" r="4" fill="${color(index)}"/>`;
        }
        output += `<g class="observation-label" data-series="${index}" data-date="${escape(date)}" data-value="${finite(value)?value:''}"><rect x="${labelX}" y="${item.y-labelHeight/2}" width="${labelWidth}" height="${labelHeight}" rx="3" fill="var(--panel)" opacity=".96"/><text class="observation-value" x="${textX}" y="${item.y+font*.34}" style="fill:${color(index)};font-size:${font}px;font-weight:650">${escape(label)}</text></g>`;
      }
      observation.innerHTML = output;
      observation.style.display=position<viewStart||position>viewEnd||(!pinned&&!hovering)?'none':'';
      readout.innerHTML = `<strong>${escape(date)}</strong>` + visible.map(({series,index,value}) => `<span><i class="lab-value-dot" style="background:${color(index)}"></i>${escape(series.label)} <b>${fmt(value,chart.kind)}</b></span>`).join('');
      box.dataset.observationDate = date;
      box.dataset.observationPinned = String(pinned);
      svg.setAttribute('aria-label', `${chart.title}. ${date}${pinned?' · 관측일 고정':''}. ${visible.map(({series,value}) => `${series.label} ${fmt(value,chart.kind)}`).join(', ')}. 좌우 화살표로 탐색, Escape로 최신 관측일`);
    }

    const peer = {setVisible(label,visible){const i=chart.series.findIndex(s=>s.label===label);if(i<0)return;enabled[i]=visible;const button=box.querySelector(`[data-series="${i}"]`);button?.setAttribute('aria-pressed',String(visible));const control=button?.nextElementSibling;if(control?.classList.contains('qr-visibility')){control.setAttribute('aria-pressed',String(visible));control.textContent=visible?'숨기기':'표시';}draw();},setViewport(start,end){viewStart=Math.max(0,Math.min(dates.length-2,Math.round(start*(dates.length-1))));viewEnd=Math.max(viewStart+1,Math.min(dates.length-1,Math.round(end*(dates.length-1))));draw();},setDate(date, nextPinned) {
      // Synchronized charts must observe the exact same trading date. A peer
      // without that date keeps its own observation; it is never interpolated.
      const index = indexes.get(date);
      if (index === undefined) return;
      position = index;
      pinned = nextPinned;
      updateObservation();
    }};
    peers.push(peer);
    function observe() {
      updateObservation();
      if (synchronizeDates) for (const other of peers) {
        if (other !== peer) other.setDate(dates[position], pinned);
      }
    }

    function draw() {
      if (destroyed) return;
      width = Math.max(280, box.clientWidth || 900);
      height = Math.max(100, svg.clientHeight || (chart.compact ? 150 : 300));
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      let lo = 0, hi = 0;
      chart.series.forEach((series, index) => {
        if (enabled[index]) for (const point of series.points) {
          if (indexes.get(point.date)>=viewStart&&indexes.get(point.date)<=viewEnd&&plottable(point.value)) { const value = transform(point.value); lo = Math.min(lo,value); hi = Math.max(hi,value); }
        }
      });
      if (lo === hi) { lo -= .01; hi += .01; }
      y = value => T + (hi-transform(value))/(hi-lo)*(height-T-B);
      let output = '';
      for (const tick of chartTicks(lo,hi,chart.compact?4:5)) {
        const value = inverse(tick);
        const label = chart.kind === 'pct' ? `${window.QuantFormat.number(Math.abs(value)<1e-10?0:value*100)}%` : fmt(value);
        output += `<line class="grid ${value===0?'zero':''}" x1="${L}" x2="${width-R}" y1="${y(value)}" y2="${y(value)}"/><text x="${L-8}" y="${y(value)+4}" text-anchor="end">${escape(label)}</text>`;
      }
      output += `<text x="${L}" y="${height-6}">${escape(dates[viewStart])}</text><text x="${width-R}" y="${height-6}" text-anchor="end">${escape(dates[viewEnd])}</text>`;
      if (width >= 600) for (const fraction of [.25,.5,.75]) {
        const date = dates[Math.round(viewStart+(viewEnd-viewStart)*fraction)];
        output += `<text x="${x(date)}" y="${height-6}" text-anchor="middle">${escape(date.slice(0,7))}</text>`;
      }
      chart.series.forEach((series,index) => {
        if (enabled[index]) output += `<path class="trace" data-qr-series-id="${index}" stroke="${color(index)}" d="${linePath(dates.slice(viewStart,viewEnd+1).map(date => {const value=points[index].get(date);return {date,value:plottable(value)?value:null};}),x,y)}"/>`;
      });
      svg.innerHTML = `<g class="chart-plot">${output}</g><g class="chart-observation" style="pointer-events:none"></g>`;
      observation = svg.querySelector('.chart-observation');
      box.dataset.chartScale = scale;
      box.dataset.viewportStart=dates[viewStart];box.dataset.viewportEnd=dates[viewEnd];
      const reset=box.querySelector('[data-viewport-reset]');if(reset)reset.hidden=viewStart===0&&viewEnd===dates.length-1;
      updateObservation();
    }

    function pointerIndex(event) {
      const bounds = svg.getBoundingClientRect();
      if (!bounds.width || !finite(event.clientX)) return position;
      const svgX = (event.clientX-bounds.left)/bounds.width*width;
      return Math.max(0,Math.min(dates.length-1,Math.round(viewStart+(svgX-L)/(width-L-R)*(viewEnd-viewStart))));
    }
    function listen(node,name,handler,options) {
      node.addEventListener(name,handler,options);
      cleanups.push(() => node.removeEventListener(name,handler));
    }
    listen(svg,'pointermove',event => {
      hovering = true;
      if (pinned && (activeTouch === null || event.pointerId !== activeTouch)) return;
      position = pointerIndex(event); observe();
    });
    listen(svg,'pointerdown',event => {
      const next = pointerIndex(event);
      pinned = event.pointerType === 'touch' || !pinned || next !== position;
      position = next;
      if (event.pointerType === 'touch') {
        activeTouch = event.pointerId;
        /* QuantRange captures only after a real drag, preserving taps on series. */
      }
      observe();
    });
    for (const name of ['pointerup','pointercancel','lostpointercapture']) listen(svg,name,() => {activeTouch = null;});
    listen(svg,'pointerleave',() => {
      hovering = false;
      if (!pinned) { position = dates.length-1; observe(); }
    });
    listen(svg,'keydown',event => {
      if (!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Escape') {position = dates.length-1; pinned = false;}
      else {
        position = event.key === 'Home' ? 0 : event.key === 'End' ? dates.length-1 : Math.max(0,Math.min(dates.length-1,position+(event.key==='ArrowRight'?1:-1)));
        pinned = true;
      }
      observe();
    });
    for (const button of box.querySelectorAll('.lab-legend [data-series]')) {
      const index=Number(button.dataset.series);if(!Number.isInteger(index))continue;
      button.setAttribute('aria-label',chart.series[index].label+' 표시 전환');
      function toggle(){
        if(enabled[index]&&enabled.filter(Boolean).length===1)return;
        enabled[index]=!enabled[index];button.setAttribute('aria-pressed',String(enabled[index]));
        if(range){range.config.series=rangeSeries.filter((s,i)=>enabled[i]);range.clear();}
        draw();
        if(comparing){for(const other of peers)if(other!==peer)other.setVisible(chart.series[index].label,enabled[index]);root.querySelectorAll('[data-compare-series]').forEach(row=>{if(row.dataset.compareSeries===chart.series[index].label)row.hidden=!enabled[index];});}
      }
      listen(button,'click',toggle);
    }
    const scaleControl = box.querySelector('[data-chart-scale]');
    if (chart.wealth && scaleControl) listen(scaleControl,'change',() => {
      scale = scaleControl.value === 'log' ? 'log' : 'linear';
      const note = box.querySelector('[data-scale-note]');
      if (note) note.hidden = scale !== 'log';
      draw();
    });
    if (window?.ResizeObserver) {
      const observer = new window.ResizeObserver(() => {
        if (Math.max(280,box.clientWidth||900) !== width || Math.max(100,svg.clientHeight||(chart.compact?150:300)) !== height) draw();
      });
      observer.observe(box); cleanups.push(() => observer.disconnect());
    }
    const rangeSeries=chart.series.map((s,i)=>({id:String(i),label:s.label,color:color(i),measure:chart.kind==='pct'?'pp':'absolute',scale:chart.kind==='pct'?100:1,unit:chart.kind==='pct'?'%':'',points:s.points.map(p=>({key:p.date,value:p.value}))}));
    const hitSeries=event=>{const matrix=svg.getScreenCTM();if(!matrix)return null;let best=null,distance=9;chart.series.forEach((series,index)=>{if(!enabled[index])return;let previous=null;for(const date of dates){const value=points[index].get(date);if(!plottable(value)){previous=null;continue}const b=new DOMPoint(x(date),y(value)).matrixTransform(matrix),a=previous||b,dx=b.x-a.x,dy=b.y-a.y,t=Math.max(0,Math.min(1,((event.clientX-a.x)*dx+(event.clientY-a.y)*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(event.clientX-a.x-t*dx,event.clientY-a.y-t*dy);if(d<distance){distance=d;best=String(index)}previous=b}});return best};
    const createRange=()=>window.QuantRange?.svg({id:'factor-'+chart.id,element:svg,host:box,hitSeries,currentIndex:()=>position,onSeriesRequest:(id,ctx)=>{if(ctx.mode==='point'&&Number.isInteger(ctx.index)){position=ctx.index;pinned=true;observe()}},onReset:()=>{position=dates.length-1;pinned=false;observe()},onSeriesFocus:id=>{if(comparing)return;for(const b of box.querySelectorAll('.lab-legend [data-series]'))b.setAttribute('aria-pressed',String(b.dataset.series===id))},domain:dates.map(key=>({key,label:key})),series:rangeSeries,x:i=>x(dates[i]),plotTop:T,plotBottom:()=>height-B});
    let range=null;cleanups.push(()=>range?.destroy());
    {
      box.classList.add('qe-direct-chart');
      const controls=box.querySelector('.lab-chart-controls')||box.insertBefore(document.createElement('div'),svg);controls.classList.add('lab-chart-controls');
      const options=document.createElement('details');options.className='qe-chart-options';const summary=document.createElement('summary');summary.textContent='···';summary.setAttribute('aria-label','차트 옵션');options.append(summary);controls.append(options);
      const scaleLabel=box.querySelector('.lab-scale-control');if(scaleLabel)options.append(scaleLabel);
      for(const [label,mult] of [['확대',.8],['축소',1.25]]){const action=document.createElement('button');action.type='button';action.className='lab-button secondary';action.textContent=label;options.append(action);listen(action,'click',()=>{zoom(mult,(viewStart+viewEnd)/2);options.open=false;svg.focus();});}
      const analysis=document.createElement('button');analysis.type='button';analysis.className='lab-button secondary';analysis.textContent='구간 분석';options.append(analysis);
      listen(analysis,'click',()=>{if(range){range.destroy();range=null;analysis.textContent='구간 분석';options.append(analysis);options.open=true;summary.focus();}else{range=createRange();if(!range)return;range.config.series=rangeSeries.filter((s,i)=>enabled[i]);analysis.textContent='분석 종료';controls.append(analysis);options.open=false;svg.focus();}});
      cleanups.push(()=>{if(scaleLabel)controls.append(scaleLabel);options.remove();analysis.remove();});
      const reset=document.createElement('button');reset.type='button';reset.className='lab-button secondary';reset.textContent='전체 보기';reset.dataset.viewportReset='';reset.hidden=true;box.querySelector('.lab-chart-controls').append(reset);cleanups.push(()=>reset.remove());
      function viewport(start,end){const span=Math.max(1,Math.min(dates.length-1,end-start));viewStart=Math.max(0,Math.min(dates.length-1-span,Math.round(start)));viewEnd=Math.min(dates.length-1,Math.round(viewStart+span));draw();if(comparing)for(const other of peers)if(other!==peer)other.setViewport(viewStart/(dates.length-1),viewEnd/(dates.length-1));}
      function zoom(mult,anchor=position){const span=Math.max(Math.min(10,dates.length-1),Math.min(dates.length-1,(viewEnd-viewStart)*mult));const ratio=(anchor-viewStart)/(viewEnd-viewStart||1);viewport(anchor-span*ratio,anchor+span*(1-ratio));}
      listen(reset,'click',()=>{viewport(0,dates.length-1);svg.focus();});
      listen(svg,'wheel',event=>{event.preventDefault();if(event.shiftKey){const delta=(viewEnd-viewStart)*Math.sign(event.deltaY)*.12;viewport(viewStart+delta,viewEnd+delta);}else zoom(event.deltaY<0?.8:1.25,pointerIndex(event));},{passive:false});
      listen(svg,'keydown',event=>{if(!['+','=','-','0'].includes(event.key))return;event.preventDefault();if(event.key==='0')viewport(0,dates.length-1);else zoom(event.key==='-'?1.25:.8,(viewStart+viewEnd)/2);});
      listen(svg,'dblclick',()=>viewport(0,dates.length-1));
      listen(svg,'pointerdown',event=>{if(range||viewEnd-viewStart===dates.length-1)return;pan={x:event.clientX,start:viewStart,end:viewEnd};svg.setPointerCapture?.(event.pointerId);});
      listen(svg,'pointermove',event=>{if(!pan||!event.buttons||range)return;const dx=(event.clientX-pan.x)/(svg.getBoundingClientRect().width||width)*(pan.end-pan.start);viewport(pan.start-dx,pan.end-dx);});
      for(const name of ['pointerup','pointercancel','lostpointercapture'])listen(svg,name,()=>{pan=null;});
    }
    redraws.push(draw);
    draw();
  }

  function redraw() {if (!destroyed) redraws.forEach(draw => draw());}
  if (window) {
    window.addEventListener('resize',redraw);
    cleanups.push(() => window.removeEventListener('resize',redraw));
  }
  return {redraw,destroy() {destroyed = true; cleanups.splice(0).forEach(cleanup => cleanup());}};
}

const api = {bind};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (scope) { scope.FactorCharts = api; scope.MomentumCharts = api; }
})(typeof window !== 'undefined' ? window : null);

/* Quant design engine 0.4.0 foundation, bundled into the presentation allowlist. */
if (typeof document !== 'undefined') {
(function(){
const designDefaults=Object.freeze({density:'comfortable',corners:'soft',accent:'cyan'});
const designPresets=Object.freeze({density:['comfortable','compact'],corners:['soft','square'],accent:['cyan','blue','violet']});
function validateDesign(config){for(const [key,value] of Object.entries(config)){if(!designPresets[key]?.includes(value))throw new TypeError(`지원하지 않는 디자인 토큰: ${key}=${value}`);}return {...designDefaults,...config};}
function resolveDesign(theme,base,config){const accents={dark:{cyan:'#69d3cf',blue:'#84b9fa',violet:'#c1a7ff'},light:{cyan:'#007e79',blue:'#255fb5',violet:'#7351b7'}};const accent=accents[theme][config.accent];return {...base,accent,palette:[accent,...base.palette.slice(1)],'card-inset':config.density==='compact'?'20px':'24px','card-inset-mobile':config.density==='compact'?'16px':'18px','card-radius':config.corners==='square'?'4px':'12px','control-radius':config.corners==='square'?'3px':'7px','section-gap':config.density==='compact'?'16px':'22px'};}
function contrastRatio(foreground,background){const luminance=hex=>{if(!/^#[0-9a-f]{6}$/i.test(hex))throw new TypeError('6자리 HEX가 필요합니다.');const channels=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;};const a=luminance(foreground),b=luminance(background);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);}
function mixColor(a,b,weight){const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));const x=rgb(a),y=rgb(b);return '#'+x.map((v,i)=>Math.round(v*(1-weight)+y[i]*weight).toString(16).padStart(2,'0')).join('');}
const themes = Object.freeze({dark:{bg:'#101416',surface:'#171d20',raised:'#20282c',text:'#edf3f2',muted:'#a6b4b6',border:'#364247',accent:'#69d3cf',positive:'#78c6a3',negative:'#ee9298',palette:['#69d3cf','#dcb878','#9ca9ee','#dd9bc3','#92bb83','#76afd9']},light:{bg:'#f2f5f4',surface:'#ffffff',raised:'#e9efed',text:'#172725',muted:'#536762',border:'#c6d3ce',accent:'#007e79',positive:'#227b53',negative:'#b44150',palette:['#007e79','#966515','#6556ab','#a5487d','#537e35','#356fab']}});
const root=document.documentElement;
function apply(){const theme=root.dataset.theme==='dark'?'dark':'light';const resolved=resolveDesign(theme,themes[theme],designDefaults);if(window.quantDesignPalette)window.quantDesignPalette.splice(0,window.quantDesignPalette.length,...resolved.palette);else window.quantDesignPalette=[...resolved.palette];root.dataset.qeTheme=theme;root.dataset.quantEngineVersion='0.4.0';for(const [key,value] of Object.entries(resolved))if(key!=='palette')root.style.setProperty('--qe-'+key,value);}
const applyTokens=apply;function applyAliases(){applyTokens();for(const element of [root,document.body])for(const [alias,token] of Object.entries({'qd-bg':'bg','qd-surface':'surface','qd-surface-2':'raised','qd-text':'text','qd-muted':'muted','qd-border':'border','qd-accent':'accent','bg':'bg','panel':'surface','surface':'raised','text':'text','ink':'text','muted':'muted','line':'border','accent':'accent'}))element.style.setProperty('--'+alias,'var(--qe-'+token+')','important');}applyAliases();new MutationObserver(applyAliases).observe(root,{attributes:true,attributeFilter:['data-theme']});
})();


}
