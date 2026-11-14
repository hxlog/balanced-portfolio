S.home=function(){return `
<div class="between"><div><h1>指数估值</h1><div class="sub">521 只指数 · PE / PB / 股息率 / 风险溢价 · 每日 21:00 更新 · 数据截至 2026-11-13</div></div>
<div class="row"><span class="btn">按分位排序</span><span class="btn pri">导出快照</span></div></div>
<div class="sect"><h2>全市场估值<h1 class="hint">全 A 股等权中位数 · 分位自 2015 起 · 来源：东财 + 自建归档</h1></h2>
<div class="cards">
<div class="card"><div class="k"><span>全市场</span><span class="pill p-mid">中性</span></div><div class="v num">44.43</div><div class="kv"><span>PE 分位 <b class="num">68.30%</b></span><span>PB <b class="num">2.61</b></span><span>分位 <b class="num">38.12%</b></span></div></div>
<div class="card"><div class="k"><span>主板</span></div><div class="v num">34.65</div><div class="kv"><span>PE 分位 <b class="num">56.73%</b></span><span>PB <b class="num">2.15</b></span><span>分位 <b class="num">16.43%</b></span></div></div>
<div class="card"><div class="k"><span>创业板</span></div><div class="v num">59.95</div><div class="kv"><span>PE 分位 <b class="num">66.78%</b></span><span>PB <b class="num">3.14</b></span><span>分位 <b class="num">21.98%</b></span></div></div>
<div class="card"><div class="k"><span>科创板</span></div><div class="v num">70.22</div><div class="kv"><span>PE 分位 <b class="num">-</b></span><span>PB <b class="num">3.54</b></span><span>分位 <b class="num">-</b></span></div></div>
</div></div>
<div class="sect"><h2>宽基指数<h1 class="hint">8 只核心宽基 · 点击进入详情</h1></h2><div style="margin-top:10px">${tbl(R)}</div></div>
<div class="sect"><h2>全部指数估值<h1 class="hint">共 521 只</h1></h2>
<div class="toolbar"><div class="seg"><span class="on">全部</span><span>宽基</span><span>行业</span><span>主题</span><span>策略</span></div><span class="btn">PE 分位升序</span><span class="btn">有 ETF 跟踪</span><span class="btn">仅看有估值数据</span></div>
<div style="margin-top:10px">${tbl(R.concat(R.slice(2,10)))}</div></div>`}

S.d1=function(){return `
<div class="between"><div><h1>中证中药 <span class="mut" style="font-size:13px;font-weight:400">930641 · 主题 · 中证</span></h1>
<div class="sub">以中证全指为样本空间 · 基日 2004-12-31 · 基点 1000 · 价格指数 · 39 只成分股 · 总市值 6490 亿</div></div>
<div style="text-align:right"><div class="num" style="font-size:27px;font-weight:660">8,458.56</div><div>${chg(-0.29)}<span class="mut" style="font-size:11px;margin-left:8px">2026-11-13</span></div></div></div>
<div class="tabs"><div class="on">指数指标</div><div>成分与业绩</div><div>ETF 资金</div></div>
<div class="grid2"><div class="panel"><h3>估值与点位<span class="seg"><span class="on">近 10 年</span><span>近 5 年</span><span>上市以来</span></span></h3>
<div style="margin-top:12px">${spark(820,300,13,"#0ea5e9",true)}</div>
<div class="legend"><span><i style="background:#0ea5e9"></i>指数点位（右轴）</span><span><i style="background:#f59e0b"></i>PE-TTM（左轴）</span><span><i style="background:#94a3b8"></i>机会值 / 危险值</span></div>
<div style="margin-top:10px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px">
<div><div class="mini">PE 分位</div><div class="num" style="font-size:15px;font-weight:600;margin-top:2px">13.68%</div></div><div><div class="mini">PE 均值</div><div class="num" style="font-size:15px;font-weight:600;margin-top:2px">34.55</div></div><div><div class="mini">+1σ / -1σ</div><div class="num" style="font-size:15px;font-weight:600;margin-top:2px">43.7 / 25.4</div></div><div><div class="mini">5 年最小 / 最大</div><div class="num" style="font-size:15px;font-weight:600;margin-top:2px">19.69 / 79.61</div></div></div>
</div><div><div class="panel"><h3>PE 分位<span class="pill p-low">低估</span></h3>
<div class="prog"><i style="width:13.7%"></i><u style="left:13.7%"></u></div>
<div style="display:flex;justify-content:space-between;margin-top:7px" class="mini"><span>0%</span><span>20% 28.29</span><span>50% 32.24</span><span>80% 40.65</span><span>100%</span></div></div>
<div class="panel" style="margin-top:12px"><h3>核心指标<span class="mini">近 10 年分位</span></h3>
<table style="border:0;margin:0"><tbody>
<tr><td>PB</td><td class="num">2.02</td><td class="num up">2.72%</td><td class="num mut">均值 3.07</td></tr>
<tr><td>股息率 TTM</td><td class="num">3.68%</td><td class="num">4.98%</td><td class="num mut">均值 2.85%</td></tr>
<tr><td>风险溢价</td><td class="num up">+2.07%</td><td class="num">61.2%</td><td class="num mut">10Y 国债 1.61%</td></tr>
<tr><td>ROE (TTM)</td><td class="num">8.63%</td><td class="num">43.1%</td><td class="num mut">ROA 5.52%</td></tr>
</tbody></table></div>
<div class="panel" style="margin-top:12px"><h3>成分股权重<span class="mini">前 8 合计 50.83%</span></h3>
${[["云南白药",10.76],["片仔癀",10.71],["东阿阿胶",6.31],["同仁堂",5.02],["华润三九",4.92],["吉林敖东",4.71],["众生药业",4.38],["白云山",4.03]].map(function(a){return `<div class="wrow"><span class="wn">${a[0]}</span><span class="wb"><i style="width:${a[1]/11*100}%"></i></span><span class="wv num">${a[1]}%</span></div>`}).join("")}
</div></div></div>`}

S.d2=function(){return `
<div class="between"><div><h1>中证中药 <span class="mut" style="font-size:13px;font-weight:400">930641</span></h1><div class="sub">主题 · 中证 · 39 只成分股 · 价格指数</div></div>
<div class="quote"><span class="p num">8,458.56</span>${chg(-0.29)}</div></div>
<div class="panel" style="margin-top:14px"><h3>估值与点位<span class="seg"><span class="on">近 10 年</span><span>近 5 年</span><span>上市以来</span></span></h3>
<div>${spark(1200,240,13,"#0ea5e9",true)}</div><div class="legend"><span><i style="background:#0ea5e9"></i>指数点位</span><span><i style="background:#f59e0b"></i>PE-TTM</span></div></div>
<div class="cards" style="margin-top:12px">
<div class="card"><div class="k">PE 分位</div><div class="v num">13.68%</div><div class="prog"><i style="width:13.7%"></i><u style="left:13.7%"></u></div></div>
<div class="card"><div class="k">PE (TTM)</div><div class="v num">23.27</div><div class="kv"><span>均值 <b>34.55</b></span><span>最低 <b>19.69</b></span></div></div>
<div class="card"><div class="k">股息率 TTM</div><div class="v num">3.68%</div><div class="kv"><span>分位 <b>4.98%</b></span><span>均值 <b>2.85%</b></span></div></div>
<div class="card"><div class="k">风险溢价</div><div class="v num up">+2.07%</div><div class="kv"><span>10Y 国债 <b>1.61%</b></span><span>分位 <b>61.2%</b></span></div></div></div>
<div class="tabs"><div class="on">指数指标</div><div>成分与业绩</div><div>ETF 资金</div></div>
<div class="grid2e"><div class="panel"><h3>区间统计</h3><table style="border:0;margin:0"><thead><tr><th>区间</th><th>PE 分位</th><th>均值</th><th>+1σ</th><th>-1σ</th><th>股息率</th><th>风险溢价</th></tr></thead><tbody>
<tr><td>近 1 年</td><td class="num">12.4%</td><td class="num">25.6</td><td class="num">31.2</td><td class="num">20.1</td><td class="num">3.42%</td><td class="num up">+1.81%</td></tr>
<tr><td>近 3 年</td><td class="num">9.8%</td><td class="num">27.1</td><td class="num">34.8</td><td class="num">19.4</td><td class="num">3.55%</td><td class="num up">+1.94%</td></tr>
<tr><td>近 5 年</td><td class="num">13.7%</td><td class="num">29.2</td><td class="num">38.5</td><td class="num">19.9</td><td class="num">3.61%</td><td class="num up">+2.00%</td></tr>
<tr><td>近 10 年</td><td class="num">18.2%</td><td class="num">34.6</td><td class="num">43.7</td><td class="num">25.4</td><td class="num">3.48%</td><td class="num up">+1.87%</td></tr>
</tbody></table></div><div class="panel"><h3>极限跌幅水位<span class="mini">距历史最高 -53.00%</span></h3><div class="dl" style="margin-top:6px"><div><div class="kk">70 水位线</div><div class="vv num">5,399.48</div><div class="mini">距收盘 -36.17%</div></div><div><div class="kk">80 水位线</div><div class="vv num">3,599.65</div><div class="mini">距收盘 -57.44%</div></div></div>
<div style="margin-top:10px">${spark(420,80,21,"#94a3b8",true)}</div></div></div>`}

S.d3=function(){return `
<div style="display:flex;justify-content:space-between;align-items:flex-end"><div><h1>估值终端</h1><div class="sub">左选标的 · 中间看图 · 右侧指标 · 支持键盘上下切换</div></div><div class="row"><span class="btn">加入对比</span><span class="btn pri">加入回测</span></div></div>
<div class="grid3"><div class="tl" style="height:520px;border-radius:12px;border:1px solid var(--bd)"><div class="s"><input placeholder="搜索代码 / 名称"></div>
${R.map(function(r,i){return `<div class="it ${i===8?"on":""}"><div><div class="n">${r[0]}</div><div class="c">${r[1]}</div></div><div style="text-align:right"><div class="num">${r[5]}</div><div class="mini ${pctCls(r[6])}">${r[6]===-1?"-":r[6]+"%"}</div></div></div>`}).join("")}</div>
<div><div class="panel"><h3>中证中药 930641<span class="mini">2026-11-13</span></h3><div class="quote" style="margin:6px 0 10px"><span class="p num">8,458.56</span>${chg(-0.29)}</div><div>${spark(620,180,13,"#0ea5e9",true)}</div>
<div class="tabs" style="margin-top:8px"><div class="on">估值</div><div>成分</div><div>ETF</div></div>
<div style="margin-top:10px">${spark(620,90,5,"#8b5cf6",false)}</div><div class="legend"><span><i style="background:#8b5cf6"></i>PE 历史（周频）</span></div></div></div>
<div><div class="panel"><h3>估值分位</h3><div class="prog"><i style="width:13.7%"></i><u style="left:13.7%"></u></div><div class="dl" style="margin-top:14px"><div><div class="kk">PE</div><div class="vv num">23.27</div></div><div><div class="kk">分位</div><div class="vv num">13.68%</div></div><div><div class="kk">PB</div><div class="vv num">2.02</div></div><div><div class="kk">分位</div><div class="vv num">2.72%</div></div></div></div>
<div class="panel" style="margin-top:12px"><h3>风险与服务</h3><div class="dl"><div><div class="kk">年化波动(1Y)</div><div class="vv num">1.20%</div></div><div><div class="kk">夏普(1Y)</div><div class="vv num">-0.95</div></div><div><div class="kk">最大回撤</div><div class="vv num down">-53.0%</div></div><div><div class="kk">发布以来</div><div class="vv num down">-42.33%</div></div></div></div>
<div class="panel" style="margin-top:12px"><h3>跟踪 ETF<span class="mini">3 只</span></h3><table style="border:0;margin:0"><tbody><tr><td>560080</td><td class="num">20.89 亿</td></tr><tr><td>159647</td><td class="num">8.35 亿</td></tr><tr><td>561510</td><td class="num">2.14 亿</td></tr></tbody></table></div></div>
</div>`}