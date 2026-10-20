(function (scope) {
'use strict';

const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/** Chart observation is deliberately local: it never changes the selected month or URL. */
function bind({charts, root, palette, finite, fmt, linePath, chartTicks, endpointPositions, synchronizeDates = false}) {
  const cleanups = [], redraws = [], peers = [];
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
    let position = dates.length - 1, pinned = false, activeTouch = null;
    let width = 900, height = chart.compact ? 150 : 300, y, observation;
    const L = 58, R = 16, T = 24, B = 28;
    const color = index => palette[index % palette.length];
    const x = date => L + indexes.get(date) / Math.max(1, dates.length - 1) * (width - L - R);

    function updateObservation() {
      const date = dates[position], cursorX = x(date), mobile = width < 600;
      const font = mobile ? 10 : 11;
      const labelHalf = (font + 5) / 2 + 1;
      const labelMin = T + labelHalf, labelMax = height - B - labelHalf;
      const visible = chart.series.flatMap((series, index) => {
        if (!enabled[index]) return [];
        const value = points[index].get(date);
        return [{index, series, value, y: finite(value) ? y(value) : labelMax}];
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
        if (finite(value)) {
          const pointY = y(value), edge = preferRight ? labelX : labelX + labelWidth;
          output += `<line class="observation-leader" x1="${cursorX}" y1="${pointY}" x2="${edge}" y2="${item.y}" stroke="${color(index)}" stroke-width=".8" opacity=".55"/>`;
          output += `<circle class="dot" data-series="${index}" cx="${cursorX}" cy="${pointY}" r="4" fill="${color(index)}"/>`;
        }
        output += `<g class="observation-label" data-series="${index}" data-date="${escape(date)}" data-value="${finite(value)?value:''}"><rect x="${labelX}" y="${item.y-labelHeight/2}" width="${labelWidth}" height="${labelHeight}" rx="3" fill="var(--panel)" opacity=".96"/><text class="observation-value" x="${textX}" y="${item.y+font*.34}" style="fill:${color(index)};font-size:${font}px;font-weight:650">${escape(label)}</text></g>`;
      }
      observation.innerHTML = output;
      readout.innerHTML = `<strong>${escape(date)}</strong>` + visible.map(({series,index,value}) => `<span><i class="lab-value-dot" style="background:${color(index)}"></i>${escape(series.label)} <b>${fmt(value,chart.kind)}</b></span>`).join('');
      box.dataset.observationDate = date;
      box.dataset.observationPinned = String(pinned);
      svg.setAttribute('aria-label', `${chart.title}. ${date}${pinned?' · 관측일 고정':''}. ${visible.map(({series,value}) => `${series.label} ${fmt(value,chart.kind)}`).join(', ')}. 좌우 화살표로 탐색, Escape로 최신 관측일`);
    }

    const peer = {setDate(date, nextPinned) {
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
          if (finite(point.value)) { lo = Math.min(lo,point.value); hi = Math.max(hi,point.value); }
        }
      });
      if (lo === hi) { lo -= .01; hi += .01; }
      y = value => T + (hi-value)/(hi-lo)*(height-T-B);
      let output = '';
      for (const value of chartTicks(lo,hi,chart.compact?4:5)) {
        const label = chart.kind === 'pct' ? `${(Math.abs(value)<1e-10?0:value*100).toLocaleString('ko-KR',{maximumFractionDigits:Math.abs(hi-lo)>=.1?0:2})}%` : fmt(value);
        output += `<line class="grid ${value===0?'zero':''}" x1="${L}" x2="${width-R}" y1="${y(value)}" y2="${y(value)}"/><text x="${L-8}" y="${y(value)+4}" text-anchor="end">${escape(label)}</text>`;
      }
      output += `<text x="${L}" y="${height-6}">${escape(dates[0])}</text><text x="${width-R}" y="${height-6}" text-anchor="end">${escape(dates.at(-1))}</text>`;
      if (width >= 600) for (const fraction of [.25,.5,.75]) {
        const date = dates[Math.round((dates.length-1)*fraction)];
        output += `<text x="${x(date)}" y="${height-6}" text-anchor="middle">${escape(date.slice(0,7))}</text>`;
      }
      chart.series.forEach((series,index) => {
        if (enabled[index]) output += `<path class="trace" stroke="${color(index)}" d="${linePath(series.points,x,y)}"/>`;
      });
      svg.innerHTML = `<g class="chart-plot">${output}</g><g class="chart-observation" style="pointer-events:none"></g>`;
      observation = svg.querySelector('.chart-observation');
      updateObservation();
    }

    function pointerIndex(event) {
      const bounds = svg.getBoundingClientRect();
      if (!bounds.width || !finite(event.clientX)) return position;
      const svgX = (event.clientX-bounds.left)/bounds.width*width;
      return Math.max(0,Math.min(dates.length-1,Math.round((svgX-L)/(width-L-R)*(dates.length-1))));
    }
    function listen(node,name,handler) {
      node.addEventListener(name,handler);
      cleanups.push(() => node.removeEventListener(name,handler));
    }
    listen(svg,'pointermove',event => {
      if (pinned && (activeTouch === null || event.pointerId !== activeTouch)) return;
      position = pointerIndex(event); observe();
    });
    listen(svg,'pointerdown',event => {
      const next = pointerIndex(event);
      pinned = event.pointerType === 'touch' || !pinned || next !== position;
      position = next;
      if (event.pointerType === 'touch') {
        activeTouch = event.pointerId;
        try { svg.setPointerCapture(event.pointerId); } catch (_) { /* Static SVG and unsupported pointer capture. */ }
      }
      observe();
    });
    for (const name of ['pointerup','pointercancel','lostpointercapture']) listen(svg,name,() => {activeTouch = null;});
    listen(svg,'pointerleave',() => {
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
    for (const button of box.querySelectorAll('.lab-legend [data-series]')) listen(button,'click',() => {
      const index = Number(button.dataset.series);
      if (!Number.isInteger(index) || index < 0 || index >= enabled.length) return;
      enabled[index] = !enabled[index];
      button.setAttribute('aria-pressed',String(enabled[index]));
      draw();
    });
    if (window?.ResizeObserver) {
      const observer = new window.ResizeObserver(() => {
        if (Math.max(280,box.clientWidth||900) !== width || Math.max(100,svg.clientHeight||(chart.compact?150:300)) !== height) draw();
      });
      observer.observe(box); cleanups.push(() => observer.disconnect());
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
if (scope) scope.MomentumCharts = api;
})(typeof window !== 'undefined' ? window : null);
