let data = null,
    busy = false;
const CHART_MARGIN = {
    left: 12,
    right: 82,
    top: 12,
    bottom: 30
};
const $ = id => document.getElementById(id);
const num = (v, d = 2) => v == null ? '—' : Number(v).toLocaleString('zh-CN', {
    minimumFractionDigits: d,
    maximumFractionDigits: d
});

function prepare(id) {
    const c = $(id),
        r = c.getBoundingClientRect(),
        dpi = devicePixelRatio || 1;
    c.width = Math.round(r.width * dpi);
    c.height = Math.round(r.height * dpi);
    const x = c.getContext('2d');
    x.scale(dpi, dpi);
    return [x, r.width, r.height]
}

function chart(id, rows, type) {
    const [x, w, h] = prepare(id);
    if (!rows.length) {
        x.fillStyle = '#8b9bb4';
        x.fillText('正在补齐历史行情…', 20, 40);
        return
    }
    const {
        left,
        right,
        top,
        bottom
    } = CHART_MARGIN, pw = w - left - right, ph = h - top - bottom, n = rows.length, slots = (rows[n - 1].time - rows[0].time) / 60000 + 1, dx = pw / slots, xAt = i => left + ((rows[i].time - rows[0].time) / 60000 + .5) * dx;
    let min, max;
    if (type === 'price') {
        min = Math.min(...rows.map(r => r.low));
        max = Math.max(...rows.map(r => r.high))
    } else if (type === 'volume') {
        min = 0;
        max = Math.max(...rows.map(r => r.volume))
    } else {
        const v = rows.flatMap(r => [r.dif, r.dea, r.hist]).filter(v => v != null);
        min = Math.min(0, ...v);
        max = Math.max(0, ...v)
    }
    const pad = (max - min || 1) * .08;
    if (type !== 'volume') min -= pad;
    max += pad;
    const y = v => top + (max - v) / (max - min || 1) * ph;
    x.font = '11px system-ui';
    for (let j = 0; j < 4; j++) {
        const v = min + (max - min) * j / 3,
            yy = y(v);
        x.strokeStyle = '#243046';
        x.beginPath();
        x.moveTo(left, yy);
        x.lineTo(w - right, yy);
        x.stroke();
        x.fillStyle = '#8b9bb4';
        x.fillText(num(v, type === 'macd' ? 3 : 2), w - right + 8, yy + 4)
    }
    rows.forEach((r, i) => {
        const xx = xAt(i),
            up = r.close >= r.open;
        x.strokeStyle = x.fillStyle = up ? '#39d5b1' : '#f27689';
        if (type === 'price') {
            x.setLineDash(r.confirmed ? [] : [2, 2]);
            x.beginPath();
            x.moveTo(xx, y(r.high));
            x.lineTo(xx, y(r.low));
            x.stroke();
            const yy = Math.min(y(r.open), y(r.close));
            x.globalAlpha = r.confirmed ? 1 : .55;
            x.fillRect(xx - dx * .3, yy, Math.max(1, dx * .6), Math.max(1, Math.abs(y(r.close) - y(r.open))));
            x.globalAlpha = 1;
            x.setLineDash([])
        } else if (type === 'volume') {
            x.globalAlpha = .65;
            x.fillRect(xx - dx * .3, y(r.volume), Math.max(1, dx * .6), y(0) - y(r.volume));
            x.globalAlpha = 1
        } else if (r.hist != null) {
            x.fillStyle = r.hist >= 0 ? '#39d5b1' : '#f27689';
            x.fillRect(xx - dx * .3, Math.min(y(0), y(r.hist)), Math.max(1, dx * .6), Math.max(1, Math.abs(y(0) - y(r.hist))))
        }
    });
    if (type === 'macd') {
        for (const [key, color] of [
                ['dif', '#74a7ff'],
                ['dea', '#f5cc79']
            ]) {
            x.strokeStyle = color;
            x.beginPath();
            let active = false;
            rows.forEach((r, i) => {
                if (r[key] == null) {
                    active = false;
                    return
                }
                const xx = xAt(i);
                if (!active) x.moveTo(xx, y(r[key]));
                else x.lineTo(xx, y(r[key]));
                active = true
            });
            x.stroke()
        }
    }
    x.fillStyle = '#8b9bb4';
    x.textAlign = 'center';
    for (let i = 0; i < 4; i++) {
        const k = Math.floor((n - 1) * i / 3),
            xx = xAt(k);
        x.fillText(new Date(rows[k].time).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit'
        }), xx, h - 5);
        x.strokeStyle = '#263247';
        x.setLineDash([2, 4]);
        x.beginPath();
        x.moveTo(xx, top);
        x.lineTo(xx, h - bottom);
        x.stroke();
        x.setLineDash([])
    }
}
let hover = null;
const chartIds = ['priceChart', 'volume', 'macd'];

function clearHover() {
    hover = null;
    $('crossVertical').style.display = $('crossHorizontal').style.display = $('chartTooltip').style.display = 'none';
    $('inspect').textContent = '将鼠标移到图表上，查看同一分钟的价格、成交量和 MACD。'
}

function renderHover() {
    if (!hover || !data?.candles.length) return;
    const row = data.candles.find(r => r.time === hover.time);
    if (!row) {
        clearHover();
        return
    }
    const group = $('marketChart').getBoundingClientRect(),
        price = $('priceChart').getBoundingClientRect(),
        last = $('macd').getBoundingClientRect(),
        active = $(hover.id).getBoundingClientRect(),
        {
            left,
            right,
            top,
            bottom
        } = CHART_MARGIN,
        rows = data.candles,
        slots = (rows[rows.length - 1].time - rows[0].time) / 60000 + 1,
        dx = (price.width - left - right) / slots,
        xx = price.left - group.left + left + ((row.time - rows[0].time) / 60000 + .5) * dx;
    Object.assign($('crossVertical').style, {
        display: 'block',
        left: xx + 'px',
        top: (price.top - group.top + top) + 'px',
        height: (last.bottom - bottom - price.top - top) + 'px'
    });
    Object.assign($('crossHorizontal').style, {
        display: 'block',
        left: (active.left - group.left + left) + 'px',
        top: (active.top - group.top + Math.max(top, Math.min(active.height - bottom, hover.y))) + 'px',
        width: (active.width - left - right) + 'px'
    });
    const items = [
        ['时间', new Date(row.time).toLocaleString('zh-CN', {
            hour12: false
        })],
        ['状态', row.confirmed ? '已收盘' : '未收盘 · MACD 暂不可用'],
        ['开', num(row.open)],
        ['高', num(row.high)],
        ['低', num(row.low)],
        ['收', num(row.close)],
        ['成交量', num(row.volume, 6)],
        ['DIF', num(row.dif, 6)],
        ['DEA', num(row.dea, 6)],
        ['MACD Hist', num(row.hist, 6)]
    ];
    $('inspect').replaceChildren(...items.map(([label, value]) => {
        const item = document.createElement('span');
        item.append(label + ' ');
        const strong = document.createElement('strong');
        strong.textContent = value;
        item.append(strong);
        return item
    }));
    $('chartTooltip').textContent = items.filter(([label]) => !['开', '高', '低'].includes(label)).map(([label, value]) => label + '  ' + value).join('\n');
    Object.assign($('chartTooltip').style, {
        display: 'block',
        left: Math.max(8, Math.min(innerWidth - 276, hover.clientX + 16)) + 'px',
        top: Math.max(8, Math.min(innerHeight - 220, hover.clientY + 16)) + 'px'
    });
}
$('marketChart').addEventListener('pointermove', event => {
    if (!data?.candles.length) return;
    const id = chartIds.find(id => {
        const r = $(id).getBoundingClientRect();
        return event.clientY >= r.top && event.clientY <= r.bottom
    });
    if (!id) {
        clearHover();
        return
    }
    const r = $(id).getBoundingClientRect(),
        {
            left,
            right,
            top,
            bottom
        } = CHART_MARGIN,
        px = event.clientX - r.left,
        py = event.clientY - r.top;
    if (px < left || px > r.width - right || py < top || py > r.height - bottom) {
        clearHover();
        return
    }
    const rows = data.candles,
        slots = (rows[rows.length - 1].time - rows[0].time) / 60000 + 1,
        target = rows[0].time + (Math.round((px - left) / (r.width - left - right) * slots - .5)) * 60000;
    const row = rows.reduce((best, row) => Math.abs(row.time - target) < Math.abs(best.time - target) ? row : best, rows[0]);
    hover = {
        time: row.time,
        id,
        y: py,
        clientX: event.clientX,
        clientY: event.clientY
    };
    renderHover()
});
$('marketChart').addEventListener('pointerleave', clearHover);

function draw() {
    if (!data) return;
    chart('priceChart', data.candles, 'price');
    chart('volume', data.candles, 'volume');
    chart('macd', data.candles, 'macd');
    renderHover()
}
async function refresh() {
    if (busy) return;
    busy = true;
    try {
        const response = await fetch('/api/dashboard?symbol=' + encodeURIComponent($('symbol').value), {
                cache: 'no-store'
            }),
            d = await response.json();
        if (!response.ok) throw Error(d.error || '服务响应异常');
        data = d;
        if (d.ticker) {
            const t = d.ticker,
                change = t.open_24h ? 100 * (t.last_price / t.open_24h - 1) : 0;
            $('price').textContent = num(t.last_price);
            $('change').textContent = `24h ${change>=0?'+':''}${num(change)}%`;
            $('change').className = 'detail ' + (change >= 0 ? 'up' : 'down');
            $('high').textContent = num(t.high_24h);
            $('low').textContent = '最低 ' + num(t.low_24h);
            $('turnover').textContent = num(t.volume_quote_24h / 1e6) + ' M'
        }
        $('count').textContent = num(d.count, 0);
        const recent = [...d.candles].reverse().find(r => r.confirmed && r.hist != null);
        for (const [id, key] of [
                ['z', 'hist_z'],
                ['slope', 'hist_slope_pct'],
                ['accel', 'hist_accel_pct'],
                ['zl', 'zl_hist']
            ]) $(id).textContent = num(recent?.[key], 6);
        const stale = !d.state.last_success_ms || Date.now() - d.state.last_success_ms > 30000;
        $('status').textContent = d.state.error ? '● 采集重试中' : stale ? '● 首次同步中' : '● 实时采集中';
        $('status').style.color = stale || d.state.error ? '#f5cc79' : '#39d5b1';
        $('error').style.display = d.state.error || d.gaps ? 'block' : 'none';
        $('error').textContent = d.state.error || '检测到历史缺口，指标仅使用最新连续片段';
        $('updated').textContent = d.state.last_success_ms ? '最近采集 ' + new Date(d.state.last_success_ms).toLocaleString('zh-CN') : '正在首次补齐历史数据';
        draw()
    } catch (e) {
        $('status').textContent = '● 连接中断';
        $('error').style.display = 'block';
        $('error').textContent = e.message
    } finally {
        busy = false
    }
}
$('symbol').onchange = () => {
    clearHover();
    refresh()
};
$('refresh').onclick = refresh;
window.addEventListener('resize', draw);
refresh();
setInterval(refresh, 5000);