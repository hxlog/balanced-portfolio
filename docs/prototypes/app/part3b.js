S.cons=function(){return `
<div class="between"><div><h1>中证中药 <span class="mut" style="font-size:13px;font-weight:400">930641</span></h1><div class="sub">成分与业绩 · 权重每月首个交易日更新</div></div><div class="row"><span class="seg"><span class="on">申万一级</span><span>中证一级</span></span></div></div>
<div class="tabs"><div>指数指标</div><div class="on">成分与业绩</div><div>ETF 资金</div></div>
<div class="grid2"><div class="panel"><h3>成分股权重<span class="mini">39 只 · 前 10 合计 58.4%</span></h3>
<table style="border:0;margin:0"><thead><tr><th>代码</th><th>名称</th><th>权重</th><th>PE</th><th>当日涨跌</th></tr></thead><tbody>
${[["SZ000538","云南白药",10.76,24.1,-0.42],["SH600436","片仔癀",10.71,38.6,0.31],["SZ000423","东阿阿胶",6.31,22.4,-1.05],["SH600085","同仁堂",5.02,19.8,0.12],["SZ000999","华润三九",4.92,17.2,-0.68],["SZ000623","吉林敖东",4.71,14.9,0.44],["SZ002317","众生药业",4.38,41.2,-2.11],["SH600332","白云山",4.03,13.1,0.06]].map(function(a){return `<tr><td class="cd">${a[0]}</td><td class="nm">${a[1]}</td><td class="num">${a[2]}%</td><td class="num">${a[3]}</td><td>${chg(a[4])}</td></tr>`}).join("")}
</tbody></table></div><div><div class="panel"><h3>一级行业权重<span class="mini">医药生物 100%</span></h3><div class="wrow"><span class="wn">医药生物</span><span class="wb"><i style="width:100%"></i></span><span class="wv num">100%</span></div></div>
<div class="panel" style="margin-top:12px"><h3>业绩增长中位数<span class="mini">滚动同比 · 季度</span></h3><div style="margin-top:6px">${spark(430,120,31,"#0ea5e9",false)}</div><div class="legend"><span><i style="background:#0ea5e9"></i>净利润同比</span><span><i style="background:#94a3b8"></i>营业收入同比</span></div>
<div class="dl" style="margin-top:10px"><div><div class="kk">最新单季净利增速</div><div class="vv num up">+9.91%</div></div><div><div class="kk">营收增速</div><div class="vv num down">-2.58%</div></div><div><div class="kk">ROE TTM</div><div class="vv num">8.63%</div></div><div><div class="kk">ROA TTM</div><div class="vv num">5.52%</div></div></div></div></div></div>
<div class="panel" style="margin-top:14px"><h3>财务与估值序列<span class="mini">年度 / 最新季报</span></h3>
<table style="margin:0"><thead><tr><th>年度</th><th>净利润(亿)</th><th>净利润增速</th><th>ROE</th><th>ROA</th></tr></thead><tbody>
<tr><td>2022</td><td class="num">265.49</td><td class="num down">-13.37%</td><td class="num">8.47%</td><td class="num">5.40%</td></tr>
<tr><td>2023</td><td class="num">356.15</td><td class="num up">+27.19%</td><td class="num">10.85%</td><td class="num">6.89%</td></tr>
<tr><td>2024</td><td class="num">301.06</td><td class="num down">-14.33%</td><td class="num">9.15%</td><td class="num">5.85%</td></tr>
<tr><td>2025</td><td class="num">315.60</td><td class="num up">+1.12%</td><td class="num">9.69%</td><td class="num">6.23%</td></tr>
<tr><td>2026 Q3</td><td class="num">—</td><td class="num down">-3.60%</td><td class="num">8.63%</td><td class="num">5.52%</td></tr>
</tbody></table></div>`}

S.etf=function(){return `
<div class="between"><div><h1>中证中药 <span class="mut" style="font-size:13px;font-weight:400">930641</span></h1><div class="sub">ETF 资金 · 净申购与折溢价 · 数据来源：交易所每日申赎清单 + 基金公告</div></div><div class="row"><span class="seg"><span class="on">近 20 日</span><span>近 60 日</span></span></div></div>
<div class="tabs"><div>指数指标</div><div>成分与业绩</div><div class="on">ETF 资金</div></div>
<div class="cards" style="margin-top:14px">
<div class="card"><div class="k">跟踪 ETF 合计规模</div><div class="v num">31.38 亿</div><div class="kv"><span>较上周 <b class="up">+1.24 亿</b></span></div></div>
<div class="card"><div class="k">今日合计净申购</div><div class="v num down">-2,004 万</div><div class="kv"><span>净申购率 <b class="down">-0.64%</b></span></div></div>
<div class="card"><div class="k">近 5 日累计净申购</div><div class="v num up">+8,120 万</div><div class="kv"><span>连续流入 <b>3 日</b></span></div></div>
<div class="card"><div class="k">平均折溢价率</div><div class="v num">-0.31%</div><div class="kv"><span>最高 <b>+0.12%</b></span><span>最低 <b>-0.89%</b></span></div></div></div>
<div class="panel" style="margin-top:14px"><h3>净申购跟踪<span class="mini">柱=净申购额（亿元）· 线=累计份额（亿份）</span></h3><div style="margin-top:10px">${spark(1050,170,41,"#0ea5e9",true)}</div></div>
<div class="panel" style="margin-top:14px"><h3>ETF 申购明细<span class="mini">2026-11-13 与 2026-11-12</span></h3>
<table style="border:0;margin:0"><thead><tr><th>名称 / 代码</th><th>净申购额</th><th>净申购率</th><th>净资产</th><th>折溢价率</th><th>前一日净申购</th><th>前一日净资产</th></tr></thead><tbody>
<tr><td><span class="nm">汇添富中证中药ETF</span><span class="cd">560080</span></td><td class="num down">-1,247.35 万</td><td class="num down">-0.59%</td><td class="num">20.89 亿</td><td class="num down">-0.26%</td><td class="num up">+124.10 万</td><td class="num">21.06 亿</td></tr>
<tr><td><span class="nm">鹏华中证中药ETF</span><span class="cd">159647</span></td><td class="num down">-757.27 万</td><td class="num down">-0.90%</td><td class="num">8.35 亿</td><td class="num down">-0.10%</td><td class="num down">-89.33 万</td><td class="num">8.45 亿</td></tr>
<tr><td><span class="nm">银华中证中药ETF</span><span class="cd">561510</span></td><td class="num">+0.00</td><td class="num">0.00%</td><td class="num">2.14 亿</td><td class="num">+0.02%</td><td class="num">+0.00</td><td class="num">2.14 亿</td></tr>
</tbody></table></div>`}

S.stockA=function(){return `
<div class="between"><div><h1>构建组合 · 股票资产（变体 A：行内复权）</h1><div class="sub">同一只股票三种复权口径并存 · 默认后复权（全收益）· 收益/波动随口径即时切换</div></div><div class="row"><span class="btn">+ 添加资产</span><span class="btn pri">下一步：权重</span></div></div>
<div class="note" style="margin-top:14px">三种口径来自同一数据源的三条独立序列，主键为 <b>股票代码 + 数据源 + 复权口径 + 交易日</b>，互不覆盖。</div>
<div class="panel" style="margin-top:14px"><h3>资产列表<span class="mini">4 / 12 · 已按后复权优先排序</span></h3>
<table style="border:0;margin:0"><thead><tr><th>资产</th><th>复权口径</th><th>最新价</th><th>当日</th><th>近 1 年</th><th>年化波动</th><th>数据区间</th><th></th></tr></thead><tbody>
${[["招商银行","600036","银行","后复权",42.36,0.42,18.4,0.214,"2015-01-05 至今"],["顺丰控股","002352","物流","后复权",48.12,-0.86,12.1,0.268,"2017-02-24 至今"],["牧原股份","002714","养殖","不复权",39.88,1.24,-6.7,0.352,"2014-01-28 至今"],["工商银行","601398","银行","前复权",6.92,0.14,9.8,0.162,"2015-01-05 至今"]].map(function(r){return `<tr><td><span class="nm">${r[0]}</span><span class="cd">${r[1]} · ${r[2]}</span></td><td><span class="seg" style="transform:scale(.94);transform-origin:left"><span class="${r[3]==="后复权"?"on":""}">后复权</span><span class="${r[3]==="前复权"?"on":""}">前复权</span><span class="${r[3]==="不复权"?"on":""}">不复权</span></span></td><td class="num">${r[4]}</td><td>${chg(r[5])}</td><td>${chg(r[6])}</td><td class="num">${(r[7]*100).toFixed(1)}%</td><td class="mini">${r[8]}</td><td><span class="btn sm">移除</span></td></tr>`}).join("")}
</tbody></table></div>
<div class="grid2e" style="margin-top:14px"><div class="panel"><h3>口径差异提示<span class="mini">同一资产三种口径</span></h3>
<table style="border:0;margin:0"><thead><tr><th>口径</th><th>近 1 年</th><th>近 3 年</th><th>年化波动</th><th>说明</th></tr></thead><tbody>
<tr><td>后复权（全收益）</td><td class="num up">+18.4%</td><td class="num up">+42.1%</td><td class="num">21.4%</td><td class="mini">含分红再投，回测默认</td></tr>
<tr><td>前复权</td><td class="num up">+17.9%</td><td class="num up">+40.8%</td><td class="num">21.3%</td><td class="mini">适合看当前价格</td></tr>
<tr><td>不复权</td><td class="num up">+16.2%</td><td class="num up">+35.6%</td><td class="num">21.7%</td><td class="mini">含除权缺口，不建议回测</td></tr>
</tbody></table></div><div class="panel"><h3>批量设置<span class="mini">新增股票时的默认值</span></h3><div style="margin-top:8px" class="sub">新增股票默认抓取三种口径，组合内默认选择「后复权」。可在设置中修改默认口径。</div>
<div class="toolbar"><span class="btn">全选后复权</span><span class="btn">按类别设默认</span><span class="btn">批量重新拉取</span></div>
<div class="warn" style="margin-top:12px">全 A 股 × 3 口径首拉约 2~3 小时；日增量按 1800 只活跃股估算约 12 分钟。若限频超阈值将自动回退到「沪深300+中证500+中证1000」优先级队列。</div></div></div>`}

S.stockB=function(){return `
<div class="between"><div><h1>构建组合 · 股票资产（变体 B：三口径卡片）</h1><div class="sub">在「添加资产」时就把口径选清楚 · 一屏看清三种口径的收益与波动差异</div></div><div class="row"><span class="btn pri">确认添加</span></div></div>
<div class="panel" style="margin-top:14px"><h3>选择资产<span class="mini">搜索：600036</span></h3>
<div class="row" style="margin-top:8px"><span class="chip"><i></i>招商银行 600036</span><span class="chip">顺丰控股 002352</span><span class="chip">牧原股份 002714</span></div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:14px">
<div class="card" style="border-color:#bae6fd;box-shadow:0 0 0 3px #e0f2fe"><div class="k"><span>后复权（全收益）</span><span class="pill p-low">推荐</span></div><div class="v num">42.36</div><div class="kv"><span>近 1 年 <b class="up">+18.4%</b></span><span>波动 <b>21.4%</b></span></div><div style="margin-top:10px">${spark(240,54,7,"#0ea5e9",true)}</div></div>
<div class="card"><div class="k"><span>前复权</span></div><div class="v num">41.98</div><div class="kv"><span>近 1 年 <b class="up">+17.9%</b></span><span>波动 <b>21.3%</b></span></div><div style="margin-top:10px">${spark(240,54,8,"#8b5cf6",true)}</div></div>
<div class="card"><div class="k"><span>不复权</span></div><div class="v num">40.72</div><div class="kv"><span>近 1 年 <b class="up">+16.2%</b></span><span>波动 <b>21.7%</b></span></div><div style="margin-top:10px">${spark(240,54,9,"#94a3b8",true)}</div></div></div>
<div class="grid2e" style="margin-top:14px"><div class="panel"><h3>已选资产</h3><table style="border:0;margin:0"><tbody>
<tr><td><span class="nm">招商银行</span><span class="cd">600036</span></td><td><span class="pill p-low">后复权</span></td><td><span class="btn sm">切换</span></td></tr>
<tr><td><span class="nm">顺丰控股</span><span class="cd">002352</span></td><td><span class="pill p-low">后复权</span></td><td><span class="btn sm">切换</span></td></tr>
<tr><td><span class="nm">牧原股份</span><span class="cd">002714</span></td><td><span class="pill p-mid">不复权</span></td><td><span class="btn sm">切换</span></td></tr>
</tbody></table></div><div class="panel"><h3>口径说明</h3><div class="sub" style="line-height:1.9">后复权：以最早价格为基准向后调整，包含分红再投资，适合回测与长期收益比较。<br>前复权：以最新价格为基准向前调整，适合看当前价与历史价的关系。<br>不复权：原始成交价，含除权除息缺口，仅用于核对行情。</div></div></div>`}