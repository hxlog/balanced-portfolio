S.basketA=function(){return `
<div class="between"><div><h1>风险平价 · 一篮子资产（变体 A：表格）</h1><div class="sub">不按象限划分 · 直接给定一篮子 · 与四象限共用再平衡 / 集中度 / 回看窗口参数</div></div><div class="row"><span class="btn">保存为组合</span><span class="btn pri">开始回测</span></div></div>
<div class="panel" style="margin-top:14px"><h3>优化方法<span class="mini">6 种</span></h3><div class="toolbar"><div class="seg"><span class="on">风险平价</span><span>最大夏普</span><span>最大 Sortino</span><span>最小方差</span><span>等权</span><span>风险预算</span></div><span class="btn">高级参数</span></div>
<div class="toolbar" style="margin-top:10px"><span class="mut">再平衡阈值</span><span class="chip">偏离 5pp 触发</span><span class="mut">单资产上限</span><span class="chip">40%</span><span class="mut">回看窗口</span><span class="seg"><span>1 年</span><span class="on">3 年</span><span>5 年</span></span><span class="mut">最小历史</span><span class="chip">250 交易日</span></div></div>
<div class="grid2" style="margin-top:14px"><div class="panel"><h3>篮子资产与目标权重<span class="mini">9 只</span></h3>
<table style="border:0;margin:0"><thead><tr><th>资产</th><th>类别</th><th>目标权重</th><th>风险贡献</th><th>边际风险</th><th>调整</th></tr></thead><tbody>
${[["沪深300","000300","股票",18.4,18.1,0.98],["中证500","000905","股票",14.2,14.6,1.03],["中证红利","000922","股票",11.8,11.2,0.95],["黄金 ETF","518880","商品",12.6,12.9,1.02],["原油基金","161129","商品",8.4,8.1,0.96],["十年国债","10Y","债券",16.2,16.4,1.01],["短融 ETF","511360","债券",7.1,7.0,0.99],["纳指 ETF","513100","海外",7.3,7.6,1.04],["恒生 ETF","159920","海外",4.0,4.1,1.02]].map(function(r){return `<tr><td><span class="nm">${r[0]}</span><span class="cd">${r[1]}</span></td><td><span class="pill p-vio">${r[2]}</span></td><td class="num">${r[3]}%</td><td class="num">${r[4]}%</td><td class="num">${r[5]}</td><td><input type="range" min="0" max="40" value="${Math.round(r[3])}" style="width:76px"></td></tr>`}).join("")}
</tbody></table></div>
<div><div class="panel"><h3>组合预估<span class="mini">按 3 年窗口</span></h3><div class="dl" style="margin-top:6px"><div><div class="kk">预期年化</div><div class="vv num up">+7.8%</div></div><div><div class="kk">年化波动</div><div class="vv num">9.4%</div></div><div><div class="kk">夏普</div><div class="vv num">0.66</div></div><div><div class="kk">最大回撤</div><div class="vv num down">-14.2%</div></div></div></div>
<div class="panel" style="margin-top:12px"><h3>风险贡献分布<span class="mini">越均匀越接近理想平价</span></h3>
${[["股票",44.4],["债券",23.4],["商品",21.0],["海外",11.2]].map(function(a){return `<div class="wrow"><span class="wn">${a[0]}</span><span class="wb"><i style="width:${a[1]}%"></i></span><span class="wv num">${a[1]}%</span></div>`}).join("")}
<div class="note" style="margin-top:12px">若追求更严格平价，可开启「分组风险预算」：如股票 25% / 债券 35% / 商品 25% / 海外 15%。</div></div>
<div class="panel" style="margin-top:12px"><h3>再平衡历史<span class="mini">模拟 3 年</span></h3><table style="border:0;margin:0"><tbody><tr><td>2026-11-13</td><td class="num">偏离 6.2pp</td><td><span class="pill p-mid">已触发</span></td></tr><tr><td>2026-08-21</td><td class="num">偏离 5.4pp</td><td><span class="pill p-mid">已触发</span></td></tr><tr><td>2026-03-05</td><td class="num">偏离 5.1pp</td><td><span class="pill p-mid">已触发</span></td></tr></tbody></table></div></div></div>`}

S.basketB=function(){return `
<div class="between"><div><h1>风险平价 · 一篮子资产（变体 B：分组卡片）</h1><div class="sub">按类别分组管理 · 权重滑杆实时联动 · 可对分组设风险预算</div></div><div class="row"><span class="btn">保存为组合</span><span class="btn pri">开始回测</span></div></div>
<div class="toolbar" style="margin-top:12px"><div class="seg"><span class="on">风险平价</span><span>最大夏普</span><span>最大 Sortino</span><span>最小方差</span><span>等权</span><span>风险预算</span></div><span class="chip">再平衡 5pp</span><span class="chip">集中度 40%</span><span class="chip">窗口 3 年</span></div>
<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:14px">
<div class="panel"><h3>股票<span class="mini">权重 44.4% · 风险贡献 44.4%</span></h3>
${[["沪深300 000300",18.4],["中证500 000905",14.2],["中证红利 000922",11.8]].map(function(a){return `<div style="padding:6px 0"><div style="display:flex;justify-content:space-between"><span class="nm">${a[0]}</span><b class="num">${a[1]}%</b></div><input type="range" min="0" max="40" value="${a[1]}" style="width:100%;margin-top:6px"></div>`}).join("")}</div>
<div class="panel"><h3>债券<span class="mini">权重 23.3% · 风险贡献 23.4%</span></h3>
${[["十年国债 10Y",16.2],["短融 ETF 511360",7.1]].map(function(a){return `<div style="padding:6px 0"><div style="display:flex;justify-content:space-between"><span class="nm">${a[0]}</span><b class="num">${a[1]}%</b></div><input type="range" min="0" max="40" value="${a[1]}" style="width:100%;margin-top:6px"></div>`}).join("")}</div>
<div class="panel"><h3>商品<span class="mini">权重 21.0% · 风险贡献 21.0%</span></h3>
${[["黄金 ETF 518880",12.6],["原油基金 161129",8.4]].map(function(a){return `<div style="padding:6px 0"><div style="display:flex;justify-content:space-between"><span class="nm">${a[0]}</span><b class="num">${a[1]}%</b></div><input type="range" min="0" max="40" value="${a[1]}" style="width:100%;margin-top:6px"></div>`}).join("")}</div>
<div class="panel"><h3>海外<span class="mini">权重 11.2% · 风险贡献 11.2%</span></h3>
${[["纳指 ETF 513100",7.3],["恒生 ETF 159920",4.0]].map(function(a){return `<div style="padding:6px 0"><div style="display:flex;justify-content:space-between"><span class="nm">${a[0]}</span><b class="num">${a[1]}%</b></div><input type="range" min="0" max="40" value="${a[1]}" style="width:100%;margin-top:6px"></div>`}).join("")}</div></div>
<div class="grid2e" style="margin-top:14px"><div class="panel"><h3>组合预估</h3><div class="dl"><div><div class="kk">预期年化</div><div class="vv num up">+7.8%</div></div><div><div class="kk">波动</div><div class="vv num">9.4%</div></div><div><div class="kk">夏普</div><div class="vv num">0.66</div></div><div><div class="kk">回撤</div><div class="vv num down">-14.2%</div></div></div></div>
<div class="panel"><h3>校验<span class="mini">约束检查</span></h3><div class="v num">100.0%</div><div class="kv"><span>债券下限 <b>20%</b> 满足</span><span>单资产上限 <b>40%</b> 满足</span></div></div></div>`}

S.cryptoA=function(){return `
<div class="between"><div><h1>加密货币合约看板（变体 A：总览）</h1><div class="sub">USDT 永续 · 659 个合约 · 5 分钟刷新 · 数据源 Binance Futures</div></div><div class="row"><span class="seg"><span class="on">5 分钟</span><span>15 分钟</span><span>1 小时</span><span>1 天</span></span><span class="btn">仅 Top 140 流动性</span></div></div>
<div class="cards" style="margin-top:14px">
<div class="card"><div class="k">未平仓量（全市场）</div><div class="v num">$18.24B</div><div class="kv"><span>24h <b class="up">+3.4%</b></span></div></div>
<div class="card"><div class="k">全市场多空账户比</div><div class="v num">1.42</div><div class="kv"><span>30 天分位 <b>72%</b></span></div></div>
<div class="card"><div class="k">主动买卖比</div><div class="v num">0.96</div><div class="kv"><span>30 天分位 <b>41%</b></span></div></div>
<div class="card"><div class="k">BTC 资金费率</div><div class="v num up">+0.0110%</div><div class="kv"><span>年化 <b>+9.6%</b></span><span>4h 后结算</span></div></div></div>
<div class="panel" style="margin-top:14px"><h3>合约明细<span class="mini">按未平仓量排序</span></h3>
<table style="border:0;margin:0"><thead><tr><th>合约</th><th>最新价</th><th>24h</th><th>未平仓量</th><th>OI 24h</th><th>多空账户比</th><th>分位</th><th>主动买卖比</th><th>资金费率</th><th>下次结算</th></tr></thead><tbody>
${[["BTCUSDT",104382.5,1.24,"$6.12B",2.1,1.38,68,0.97,"+0.0110%"],["ETHUSDT",3421.8,-0.86,"$3.44B",-1.2,1.52,74,0.94,"+0.0088%"],["SOLUSDT",172.4,2.98,"$1.02B",5.4,1.61,81,1.08,"-0.0042%"],["BNBUSDT",604.2,0.42,"$0.61B",0.8,1.22,55,0.99,"+0.0100%"],["XRPUSDT",2.31,-1.42,"$0.58B",-3.1,1.44,63,0.91,"+0.0100%"],["DOGEUSDT",0.1834,3.11,"$0.42B",7.2,1.71,86,1.12,"-0.0061%"]].map(function(r){return `<tr><td><span class="nm">${r[0]}</span></td><td class="num">${r[1].toLocaleString()}</td><td>${chg(r[2])}</td><td class="num">${r[3]}</td><td>${chg(r[4])}</td><td class="num">${r[5]}</td><td class="num ${pctCls(r[6])}">${r[6]}%</td><td class="num">${r[7]}</td><td class="num ${r[8].indexOf("-")===0?"down":"up"}">${r[8]}</td><td class="mini">4h 12m</td></tr>`}).join("")}
</tbody></table></div>
<div class="grid2e" style="margin-top:14px"><div class="panel"><h3>多空比分布<span class="mini">Top 20 合约</span></h3><div style="margin-top:8px">${spark(520,140,51,"#0ea5e9",true)}</div><div class="legend"><span><i style="background:#0ea5e9"></i>多空账户比</span><span><i style="background:#f59e0b"></i>大户持仓比</span></div></div>
<div class="panel"><h3>资金费率热力<span class="mini">正=多头付费</span></h3><div style="display:grid;grid-template-columns:repeat(8,1fr);gap:5px;margin-top:8px">${Array.from({length:24}).map(function(_,i){var v=(Math.sin(i)*0.5+0.5);return "<div style=\"height:26px;border-radius:5px;background:rgba(14,165,233,"+(0.15+v*0.7).toFixed(2)+")\"></div>"}).join("")}</div><div class="mini" style="margin-top:6px">蓝色越深表示多头拥挤度越高</div></div></div>`}

S.cryptoB=function(){return `
<div class="between"><div><h1>BTCUSDT <span class="mut" style="font-size:13px;font-weight:400">永续 · Binance · 5m</span></h1><div class="sub">合约微观结构 · 未平仓量 / 多空比 / 主动买卖 / 资金费率 · 分位窗口 1h / 4h / 1d / 7d / 30d</div></div><div class="quote"><span class="p num">104,382.5</span>${chg(1.24)}</div></div>
<div class="grid3" style="grid-template-columns:210px 1.7fr 1fr"><div class="tl" style="height:500px;border-radius:12px;border:1px solid var(--bd)"><div class="s"><input placeholder="搜索合约"></div>
${[["BTCUSDT",104382.5,1.24],["ETHUSDT",3421.8,-0.86],["SOLUSDT",172.4,2.98],["BNBUSDT",604.2,0.42],["XRPUSDT",2.31,-1.42],["DOGEUSDT",0.1834,3.11],["ADAUSDT",0.912,0.11],["AVAXUSDT",28.4,-0.54]].map(function(r,i){return `<div class="it ${i===0?"on":""}"><div><div class="n">${r[0]}</div><div class="c">OI $6.12B</div></div><div style="text-align:right"><div class="num">${r[1].toLocaleString()}</div><div class="mini">${chg(r[2])}</div></div></div>`}).join("")}</div>
<div><div class="panel"><h3>价格与未平仓量<span class="seg"><span class="on">5m</span><span>15m</span><span>1h</span><span>4h</span><span>1d</span></span></h3><div style="margin-top:10px">${spark(600,180,61,"#0ea5e9",true)}</div><div class="legend"><span><i style="background:#0ea5e9"></i>价格（右轴）</span><span><i style="background:#f59e0b"></i>未平仓量（左轴）</span></div></div>
<div class="panel" style="margin-top:12px"><h3>5 分钟微结构<span class="mini">最近 4 个桶</span></h3><table style="border:0;margin:0"><thead><tr><th>时间</th><th>价格</th><th>OI</th><th>主动买/卖</th><th>多空账户比</th></tr></thead><tbody>
${[["11-14 16:35",104382,6.12,0.97,1.38],["11-14 16:30",104355,6.11,1.02,1.39],["11-14 16:25",104401,6.13,0.94,1.37],["11-14 16:20",104290,6.09,1.05,1.36]].map(function(r){return `<tr><td class="mini">${r[0]}</td><td class="num">${r[1].toLocaleString()}</td><td class="num">$${r[2]}B</td><td class="num">${r[3]}</td><td class="num">${r[4]}</td></tr>`}).join("")}</tbody></table></div></div>
<div><div class="panel"><h3>多空账户比<span class="mini">当前 1.38</span></h3><div class="prog"><i style="width:68%"></i><u style="left:68%"></u></div><div class="dl" style="margin-top:12px"><div><div class="kk">1h</div><div class="vv num">72%</div></div><div><div class="kk">4h</div><div class="vv num">65%</div></div><div><div class="kk">1d</div><div class="vv num">58%</div></div><div><div class="kk">30d</div><div class="vv num">68%</div></div></div></div>
<div class="panel" style="margin-top:12px"><h3>大户持仓比<span class="mini">当前 1.12</span></h3><div class="prog"><i style="width:44%"></i><u style="left:44%"></u></div><div class="mini" style="margin-top:8px">大户与散户方向分歧时，历史上更易出现趋势反转（统计观察，不构成策略）</div></div>
<div class="panel" style="margin-top:12px"><h3>资金费率</h3><table style="border:0;margin:0"><tbody><tr><td>当前</td><td class="num up">+0.0110%</td></tr><tr><td>7 日均值</td><td class="num up">+0.0084%</td></tr><tr><td>下次结算</td><td class="num">4h 12m</td></tr><tr><td>30 天最高</td><td class="num up">+0.0310%</td></tr></tbody></table></div></div></div>
<div class="panel" style="margin-top:14px"><h3>分位统计<span class="mini">5 个指标 × 5 个窗口 · 基于已闭合 5m 数据</span></h3>
<table style="border:0;margin:0"><thead><tr><th>指标</th><th>当前</th><th>1h</th><th>4h</th><th>1d</th><th>7d</th><th>30d</th><th>均值(30d)</th><th>±1σ</th></tr></thead><tbody>
<tr><td>多空账户比</td><td class="num">1.38</td><td class="num">72%</td><td class="num">65%</td><td class="num">58%</td><td class="num">61%</td><td class="num up">68%</td><td class="num">1.29</td><td class="num">0.34</td></tr>
<tr><td>大户持仓比</td><td class="num">1.12</td><td class="num">44%</td><td class="num">39%</td><td class="num">46%</td><td class="num">43%</td><td class="num">44%</td><td class="num">1.09</td><td class="num">0.21</td></tr>
<tr><td>主动买卖比</td><td class="num">0.97</td><td class="num">48%</td><td class="num">52%</td><td class="num">45%</td><td class="num">49%</td><td class="num">41%</td><td class="num">1.01</td><td class="num">0.12</td></tr>
<tr><td>未平仓量($B)</td><td class="num">6.12</td><td class="num">81%</td><td class="num">76%</td><td class="num">69%</td><td class="num">64%</td><td class="num up">72%</td><td class="num">5.44</td><td class="num">0.68</td></tr>
<tr><td>资金费率</td><td class="num">0.011%</td><td class="num">63%</td><td class="num">58%</td><td class="num">55%</td><td class="num">51%</td><td class="num">49%</td><td class="num">0.008%</td><td class="num">0.006</td></tr>
</tbody></table></div>`}

S.api=function(){return `
<div class="between"><div><h1>数据 API 接入中心</h1><div class="sub">REST + Bearer Token · Excel Power Query 直连 · Python SDK · 可选 HMAC 签名</div></div><div class="row"><span class="btn">申请 Token</span><span class="btn pri">查看 OpenAPI</span></div></div>
<div class="grid2" style="margin-top:16px"><div>
<div class="panel"><h3>1. 认证<span class="mini">Bearer + 可选 HMAC</span></h3><div class="code">Authorization: Bearer bp_live_7f9c...a1
X-BP-Timestamp: 1763107200
X-BP-Nonce: 8f2c1d
X-BP-Sign: HMAC-SHA256(body, secret)   <b># 可选</b></div><div class="mini" style="margin-top:8px">Token 仅创建时明文返回一次，服务端存 SHA-256 摘要；可设 scopes（quotes / valuation / percentile）与过期时间。</div></div>
<div class="panel" style="margin-top:12px"><h3>2. Excel 直连（Power Query）<span class="mini">Q16 选型 A</span></h3><div class="code"><em>// 数据 → 获取数据 → 其他源 → 空查询 → 高级编辑器</em>
let
  Url = <b>"https://api.example.com/api/v1/index/valuation"</b>,
  Q = [codes=<b>"000300,930641"</b>, start=<b>"2024-01-01"</b>,
       end=<b>"2024-12-31"</b>, window=<b>"5y"</b>],
  Res = Json.Document(Web.Contents(Url, [
          Query=Q,
          Headers=[Authorization=<b>"Bearer bp_live_..."</b>]])),
  Tbl = Table.FromRecords(Res[data])
in Tbl</div></div>
<div class="panel" style="margin-top:12px"><h3>3. Python SDK</h3><div class="code"><em>from</em> bpdata <em>import</em> Client
c = Client(token=<b>"bp_live_..."</b>)

em = c.daily(codes=[<b>"600036"</b>,<b>"000300"</b>], start=<b>"2024-01-01"</b>, adjust=<b>"hfq"</b>)

yld = c.valuation(codes=[<b>"000300"</b>], window=<b>"10y"</b>,
                  fields=[<b>"pe"</b>,<b>"pb"</b>,<b>"dividend_yield"</b>,<b>"erp"</b>])
<em># 返回 DataFrame，含 value / percentile / mean / sd1 / sd2 / sd3</em></div></div>
</div><div>
<div class="panel"><h3>4. 端点一览<span class="mini">/api/v1</span></h3><table style="border:0;margin:0"><thead><tr><th>方法</th><th>路径</th><th>说明</th></tr></thead><tbody>
<tr><td>GET</td><td class="cd">/market/daily</td><td class="mini">日行情 · adjust=bfq/qfq/hfq</td></tr>
<tr><td>GET</td><td class="cd">/index/valuation</td><td class="mini">PE/PB/股息率/ERP + 区间统计</td></tr>
<tr><td>GET</td><td class="cd">/index/percentile</td><td class="mini">分位 / 均值 / ±1σ ±2σ ±3σ</td></tr>
<tr><td>GET</td><td class="cd">/index/detail</td><td class="mini">简介 / 成分 / 跟踪基金</td></tr>
<tr><td>GET</td><td class="cd">/market/bond-yield</td><td class="mini">十年期国债收益率</td></tr>
<tr><td>GET</td><td class="cd">/crypto/futures</td><td class="mini">合约微观指标与分位</td></tr>
</tbody></table></div>
<div class="panel" style="margin-top:12px"><h3>5. 响应结构<span class="mini">统一信封</span></h3><div class="code">{
  <b>"data"</b>: [ { <b>"trade_date"</b>: <b>"2024-12-31"</b>,
              <b>"close"</b>: 4016.29, <b>"pe_ttm"</b>: 20.47,
              <b>"pe_basis"</b>: <b>"equal_weight_ttm"</b>,
              <b>"source"</b>: <b>"pingan"</b> } ],
  <b>"meta"</b>: { <b>"code"</b>: <b>"000300"</b>, <b>"adjust"</b>: <b>"hfq"</b>, <b>"rows"</b>: 244,
            <b>"as_of"</b>: <b>"2026-11-13"</b>, <b>"source_mix"</b>: [<b>"pingan"</b>,<b>"csindex"</b>] },
  <b>"error"</b>: null
}</div></div>
<div class="panel" style="margin-top:12px"><h3>6. 限频与配额</h3><div class="dl"><div><div class="kk">标准</div><div class="vv num">60/min</div></div><div><div class="kk">批量行数上限</div><div class="vv num">50,000</div></div><div><div class="kk">单次日期间隔</div><div class="vv num">20 年</div></div><div><div class="kk">CSV</div><div class="vv num">支持</div></div></div><div class="note" style="margin-top:10px">SQL 风格查询（可选）：<b>GET /api/v1/query?fields=close,pe_ttm&amp;codes=000300</b>，与 Excel 用户习惯对齐。</div></div>
</div></div>`}

var GROUPS=[
{g:"指数估值",items:[["home","估值首页（卡片流）"],["d1","详情 · D1 左图右指标"],["d2","详情 · D2 上下堆叠"],["d3","详情 · D3 三栏终端"],["cons","详情 Tab · 成分与业绩"],["etf","详情 Tab · ETF 资金"]]},
{g:"资产管理与组合",items:[["stockA","股票三复权 · A 行内"],["stockB","股票三复权 · B 卡片"],["basketA","篮子风险平价 · A 表格"],["basketB","篮子风险平价 · B 分组"]]},
{g:"加密与开放接口",items:[["cryptoA","合约看板 · A 总览"],["cryptoB","合约看板 · B 微观"],["api","对外 API 接入中心"]]}];
function mount(id){var it=[];for(var i=0;i<GROUPS.length;i++){it.push("<div class=\"g\">"+GROUPS[i].g+"</div>");for(var j=0;j<GROUPS[i].items.length;j++){var x=GROUPS[i].items[j];it.push("<a data-k=\""+x[0]+"\" class=\""+(id===x[0]?"on":"")+"\">"+x[1]+"</a>")}}document.getElementById("rail").innerHTML=it.join("");var as=document.querySelectorAll("#rail a");for(var k=0;k<as.length;k++){as[k].onclick=function(){mount(this.dataset.k)}}document.getElementById("main").innerHTML=S[id]();window.scrollTo(0,0)}
mount("home");
var sws=document.querySelectorAll("#sw span");for(var z=0;z<sws.length;z++){sws[z].onclick=function(){for(var q=0;q<sws.length;q++)sws[q].classList.remove("on");this.classList.add("on");document.body.className=this.dataset.c==="cn"?"cn-red":""}}
</script></body></html>