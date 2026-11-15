# -*- coding: utf-8 -*-
"""生成 3 套 v3 高保真 HTML 原型（浅色工作台/深色终端/分析师风）。纯静态+内联SVG。"""
from __future__ import annotations
import math, os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

THEMES = {
 "a": dict(name="浅色工作台", bg="#f6f7f9", panel="#ffffff", panel2="#fbfcfd", text="#0f172a", muted="#64748b",
   border="#e2e8f0", accent="#4f46e5", accent2="#0ea5e9", accent_soft="#eef2ff", up="#dc2626", down="#16a34a",
   warn="#d97706", grid="#eef2f7", nav="#ffffff", nav_text="#334155", radius="14px",
   shadow="0 1px 2px rgba(15,23,42,.06), 0 8px 24px -16px rgba(15,23,42,.18)",
   font="-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
   head_font="-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif",
   num_font="'SF Mono','JetBrains Mono',Consolas,monospace", chip_on="#4f46e5", chip_on_text="#ffffff",
   table_head="#f8fafc", hover="#f1f5f9"),
 "b": dict(name="深色终端", bg="#0a0d12", panel="#10151d", panel2="#0d1218", text="#e6edf6", muted="#7d8da4",
   border="#1e2836", accent="#2dd4bf", accent2="#60a5fa", accent_soft="#0f2a2a", up="#f87171", down="#34d399",
   warn="#fbbf24", grid="#17202c", nav="#0d1218", nav_text="#aebccd", radius="10px",
   shadow="0 0 0 1px rgba(45,212,191,.05), 0 18px 40px -24px rgba(0,0,0,.9)",
   font="-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif",
   head_font="-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif",
   num_font="'JetBrains Mono','SF Mono',Consolas,monospace", chip_on="#2dd4bf", chip_on_text="#04110f",
   table_head="#0f161f", hover="#141c27"),
 "c": dict(name="分析师风", bg="#f7f4ee", panel="#fffdf8", panel2="#fbf8f1", text="#1e1b16", muted="#7a7166",
   border="#e4dcce", accent="#1f4e5f", accent2="#b45309", accent_soft="#e9f0f2", up="#b91c1c", down="#15803d",
   warn="#b45309", grid="#efe9dd", nav="#fffdf8", nav_text="#3f3a32", radius="4px",
   shadow="0 1px 0 rgba(30,27,22,.06), 0 10px 30px -22px rgba(30,27,22,.35)",
   font="Georgia,'Source Han Serif SC','Songti SC',serif",
   head_font="Georgia,'Source Han Serif SC','Songti SC',serif",
   num_font="'SF Mono','JetBrains Mono',Consolas,monospace", chip_on="#1f4e5f", chip_on_text="#fffdf8",
   table_head="#f3eee3", hover="#f3eee3"),
}

def T(th, k): return THEMES[th][k]

def spark(th, vals, w=240, h=46, color=None):
    lo, hi = min(vals), max(vals); span = (hi-lo) or 1
    pts = [(4+i*(w-8)/(len(vals)-1), h-5-(v-lo)/span*(h-10)) for i,v in enumerate(vals)]
    return ('<svg viewBox="0 0 '+str(w)+' '+str(h)+'" width="100%" height="'+str(h)+'" preserveAspectRatio="none">'
      '<polyline fill="none" stroke="'+(color or T(th,'accent'))+'" stroke-width="1.6" points="'+' '.join(str(round(x,1))+','+str(round(y,1)) for x,y in pts)+'"/></svg>')

def gauge(th, score=27, size=210):
    cx, cy, r = size/2, size/2+18, size/2-12
    z = [(0,20,"#16a34a"),(20,40,"#65a30d"),(40,60,"#eab308"),(60,80,"#f97316"),(80,100,"#dc2626")]
    if th=="b": z=[(0,20,"#34d399"),(20,40,"#a3e635"),(40,60,"#fbbf24"),(60,80,"#fb923c"),(80,100,"#f87171")]
    if th=="c": z=[(0,20,"#15803d"),(20,40,"#65a30d"),(40,60,"#b45309"),(60,80,"#c2410c"),(80,100,"#b91c1c")]
    p=[]
    for lo,hi,c in z:
        a0=math.pi-lo/100*math.pi; a1=math.pi-hi/100*math.pi
        x0,y0=cx+r*math.cos(a0),cy-r*math.sin(a0); x1,y1=cx+r*math.cos(a1),cy-r*math.sin(a1)
        p.append('<path d="M '+str(round(x0,2))+' '+str(round(y0,2))+' A '+str(r)+' '+str(r)+' 0 0 1 '+str(round(x1,2))+' '+str(round(y1,2))+'" stroke="'+c+'" stroke-width="16" fill="none"/>')
    a=math.pi-score/100*math.pi; nx,ny=cx+(r-6)*math.cos(a),cy-(r-6)*math.sin(a)
    p.append('<line x1="'+str(cx)+'" y1="'+str(cy)+'" x2="'+str(round(nx,2))+'" y2="'+str(round(ny,2))+'" stroke="'+T(th,'text')+'" stroke-width="2.4" stroke-linecap="round"/>')
    p.append('<circle cx="'+str(cx)+'" cy="'+str(cy)+'" r="5" fill="'+T(th,'text')+'"/>')
    p.append('<text x="'+str(cx)+'" y="'+str(cy-18)+'" text-anchor="middle" font-size="30" font-weight="700" fill="'+T(th,'text')+'" font-family="'+T(th,'head_font')+'">'+str(score)+'</text>')
    p.append('<text x="'+str(cx)+'" y="'+str(cy-2)+'" text-anchor="middle" font-size="10" fill="'+T(th,'muted')+'">MVI · 越低越便宜</text>')
    p.append('<text x="'+str(cx-r-2)+'" y="'+str(cy+16)+'" text-anchor="middle" font-size="9" fill="'+T(th,'muted')+'">0 便宜</text>')
    p.append('<text x="'+str(cx+r+2)+'" y="'+str(cy+16)+'" text-anchor="middle" font-size="9" fill="'+T(th,'muted')+'">100 贵</text>')
    return '<svg viewBox="0 0 '+str(size)+' '+str(size-16)+'" width="100%" height="'+str(size-16)+'">'+''.join(p)+'</svg>'

def band(th):
    W,H=720,205
    vals=[13.0,13.2,12.9,13.4,14.1,13.8,13.2,12.6,12.1,11.9,11.4,11.0,10.9,11.3,11.6,12.2,12.0,12.4,12.1,12.0,12.3,12.6,12.9,13.1,13.3,13.6,13.2,13.4,13.9,13.7,13.2,12.8,12.6,12.5,12.9,13.2,13.4]
    lo,hi=9.8,14.8; step=W/(len(vals)-1); p=[]
    pts=[(i*step, 26+(hi-v)/(hi-lo)*(H-50)) for i,v in enumerate(vals)]
    for k in range(5):
        y=26+k*(H-50)/4
        p.append('<line x1="0" x2="'+str(W)+'" y1="'+str(round(y,1))+'" y2="'+str(round(y,1))+'" stroke="'+T(th,'grid')+'"/>')
        p.append('<text x="'+str(W-2)+'" y="'+str(round(y-4,1))+'" text-anchor="end" font-size="9" fill="'+T(th,'muted')+'">'+str(round(hi-k*(hi-lo)/4,2))+'</text>')
    p.append('<polygon points="0,'+str(H)+' '+str(round(pts[0][0],1))+','+str(round(pts[0][1],1))+' '+' '.join(str(round(x,1))+','+str(round(y,1)) for x,y in pts)+' '+str(W)+','+str(H)+'" fill="'+T(th,'accent')+'" opacity="0.07"/>')
    p.append('<polyline points="'+' '.join(str(round(x,1))+','+str(round(y,1)) for x,y in pts)+'" fill="none" stroke="'+T(th,'accent')+'" stroke-width="1.9"/>')
    for lvl,label in ((14.1,'P80'),(12.6,'P50'),(11.4,'P20')):
        y=26+(hi-lvl)/(hi-lo)*(H-50)
        p.append('<line x1="0" x2="'+str(W)+'" y1="'+str(round(y,1))+'" y2="'+str(round(y,1))+'" stroke="'+T(th,'warn')+'" stroke-dasharray="3 4"/>')
        p.append('<text x="6" y="'+str(round(y-4,1))+'" font-size="9" fill="'+T(th,'muted')+'">'+label+'</text>')
    return '<svg viewBox="0 0 '+str(W)+' '+str(H)+'" width="100%" height="'+str(H)+'">'+''.join(p)+'</svg>'

def scatter(th):
    W,H=640,215; pts=[(0.62,6.1),(0.68,5.4),(0.71,5.1),(0.74,4.8),(0.78,4.9),(0.80,4.2),(0.83,4.4),(0.86,4.0),(0.88,3.9),(0.9,3.6),(0.92,3.2),(0.95,3.4),(1.02,2.6),(1.1,2.4),(1.2,1.9),(1.3,2.2),(2.0,4.1),(2.3,3.6),(2.6,3.2)]
    cols=[T(th,'accent'),T(th,'accent2'),T(th,'warn'),T(th,'muted')]; p=[]
    for k in range(4):
        y=18+k*(H-40)/3; p.append('<line x1="0" x2="'+str(W)+'" y1="'+str(round(y,1))+'" y2="'+str(round(y,1))+'" stroke="'+T(th,'grid')+'"/>')
    for i,(x,y) in enumerate(pts):
        cx=30+(x-0.5)/2.2*(W-50); cy=18+(6.5-y)/5.5*(H-40); r=5+(i%4)*1.6
        p.append('<circle cx="'+str(round(cx,1))+'" cy="'+str(round(cy,1))+'" r="'+str(r)+'" fill="'+cols[i%4]+'" opacity="0.6" stroke="#fff" stroke-width="1"/>')
    p.append('<line x1="30" y1="'+str(round(18+(6.5-2.2)/5.5*(H-40),1))+'" x2="'+str(W-20)+'" y2="'+str(round(18+(6.5-3.6)/5.5*(H-40),1))+'" stroke="#ef4444" stroke-width="1.4" stroke-dasharray="5 4"/>')
    p.append('<text x="34" y="14" font-size="9" fill="'+T(th,'muted')+'">y = 0.009x + 1.857 · R² = 0.047</text>')
    return '<svg viewBox="0 0 '+str(W)+' '+str(H)+'" width="100%" height="'+str(H)+'">'+''.join(p)+'</svg>'

def hist(th):
    W,H=400,160; bars=[3,6,10,16,24,31,27,20,13,8,4,2]; mx=max(bars); p=[]; bw=(W-20)/len(bars)
    for i,b in enumerate(bars):
        h=(H-30)*b/mx; x=10+i*bw+2; y=H-14-h
        p.append('<rect x="'+str(round(x,1))+'" y="'+str(round(y,1))+'" width="'+str(round(bw-4,1))+'" height="'+str(round(h,1))+'" rx="2" fill="'+T(th,'accent')+'" opacity="'+str(round(0.25+0.6*b/mx,2))+'"/>')
    p.append('<line x1="8" y1="'+str(H-14)+'" x2="'+str(W-8)+'" y2="'+str(H-14)+'" stroke="'+T(th,'border')+'"/>')
    p.append('<text x="10" y="12" font-size="9" fill="'+T(th,'muted')+'">日收益率分布 · 偏度 -0.31 · 峰度 4.2</text>')
    return '<svg viewBox="0 0 '+str(W)+' '+str(H)+'" width="100%" height="'+str(H)+'">'+''.join(p)+'</svg>'

def matrix(th, kind):
    W,H=450,190; p=[]
    pts=[(8,4.1),(14,3.2),(20,3.6),(26,2.8),(32,2.4),(38,3.9),(44,2.9),(50,2.6),(56,1.9),(63,2.2),(70,1.7),(76,1.6),(82,2.0),(88,1.4)] if kind=='pb' else [(9,5),(10,8),(12,10),(13,12),(15,14),(17,11),(19,15),(22,9),(25,13),(29,16),(34,18),(41,12),(48,20),(60,15)]
    reg='y = -0.021x + 3.42 · R² = 0.212' if kind=='pb' else 'y = 0.31x + 4.9 · R² = 0.318 (log 轴)'
    for k in range(4):
        y=16+k*(H-34)/3; p.append('<line x1="0" x2="'+str(W)+'" y1="'+str(round(y,1))+'" y2="'+str(round(y,1))+'" stroke="'+T(th,'grid')+'"/>')
    for i,(x,y) in enumerate(pts):
        cx=24+x/100*(W-40); cy=16+(20-y)/19*(H-34)
        p.append('<circle cx="'+str(round(cx,1))+'" cy="'+str(round(cy,1))+'" r="'+str(4+(i%3))+'" fill="'+T(th,'accent')+'" opacity="0.55"/>')
    p.append('<text x="30" y="12" font-size="9" fill="'+T(th,'muted')+'">'+reg+'</text>')
    return '<svg viewBox="0 0 '+str(W)+' '+str(H)+'" width="100%" height="'+str(H)+'">'+''.join(p)+'</svg>'

def chip(th, label, active):
    base="display:inline-flex;align-items:center;padding:5px 11px;border-radius:999px;font-size:12px;border:1px solid "+T(th,'border')+";"
    if active: return '<span style="'+base+'background:'+T(th,'chip_on')+';color:'+T(th,'chip_on_text')+';border-color:'+T(th,'chip_on')+';">'+label+'</span>'
    return '<span style="'+base+'color:'+T(th,'muted')+';">'+label+'</span>'

def card(th, title, body, desc="", right=""):
    return ('<section class="card"><div class="card-head"><div><h3>'+title+'</h3>'+(('<p class="desc">'+desc+'</p>') if desc else '')+'</div>'+(right or '')+'</div>'+body+'</section>')

def kpi(th, label, value, sub="", tone="text"):
    color=T(th,'text') if tone=='text' else T(th,tone)
    return '<div class="kpi"><div class="kpi-label">'+label+'</div><div class="kpi-value" style="color:'+color+'">'+value+'</div>'+(('<div class="kpi-sub">'+sub+'</div>') if sub else '')+'</div>'

def table(th, headers, rows):
    head=''.join('<th style="text-align:'+('left' if i==0 else 'right')+'">'+h+'</th>' for i,h in enumerate(headers))
    body=''
    for row in rows:
        body+='<tr>'+''.join('<td class="'+('num' if i>0 else '')+'" style="text-align:'+('left' if i==0 else 'right')+'">'+c+'</td>' for i,c in enumerate(row))+'</tr>'
    return '<div class="table-wrap"><table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>'

IDX=[("沪深300","000300","宽基","4,016.28","-0.68%","13.42","74.4%","1.33","32.4%","3.01%","1.40%","2,632.78","23"),
("中证A500","000510","宽基","4,842.51","-1.17%","15.51","51.2%","1.50","28.0%","2.73%","1.12%","1,998.94","18"),
("上证50","000016","宽基","2,880.12","-0.42%","11.71","93.1%","1.23","50.0%","3.53%","1.02%","1,206.31","9"),
("中证500","000905","宽基","6,024.88","-1.32%","27.43","64.1%","2.01","74.0%","1.64%","0.96%","1,023.77","12"),
("中证红利","000922","策略","5,918.40","-0.81%","7.62","31.2%","0.86","22.5%","5.12%","3.21%","632.10","12"),
("红利低波","H30269","策略","7,204.66","-0.55%","6.98","26.4%","0.79","18.1%","5.66%","3.74%","937.89","14"),
("中证1000","000852","宽基","7,180.33","-1.84%","37.89","56.1%","1.99","19.0%","1.29%","-0.12%","812.44","10"),
("科创50","000688","宽基","1,082.55","-2.31%","58.42","81.2%","4.62","69.8%","0.62%","-1.80%","1,580.22","9")]

def tab_valuation(th):
    metrics=chip(th,"PE",False)+chip(th,"PB",False)+chip(th,"股息率",False)+chip(th,"风险溢价",False)
    windows=chip(th,"1 年",False)+chip(th,"3 年",False)+chip(th,"5 年",True)+chip(th,"10 年",False)+chip(th,"全历史",False)
    factors=''
    for name,val,direction,weight in [("PE 分位",74,"负向","12%"),("PB 分位",32,"负向","8%"),("股息率分位",68,"正向","34%"),("ERP 分位",88,"正向","28%"),("ROE 分位",46,"正向","18%")]:
        color=T(th,'up') if val>60 else T(th,'accent')
        factors+=('<div class="factor"><div class="factor-top"><span>'+name+'</span><span class="muted">'+direction+' · 权重 '+weight+'</span></div><div class="bar"><div style="width:'+str(val)+'%;background:'+color+';"></div></div><div class="factor-bottom"><span class="num">'+str(val)+'%</span><span class="muted">历史分位</span></div></div>')
    rows=[[('<b>'+n+'</b> <span class="muted num">'+c+'</span> <span class="tag">'+cat+'</span>'),'<span class="num">'+cl+'</span>','<span class="num" style="color:'+T(th,'down')+'">'+chg+'</span>','<span class="num">'+pe+'</span>','<span class="num">'+pep+'</span>','<span class="num">'+pb+'</span>','<span class="num">'+pbp+'</span>','<span class="num">'+dv+'</span>','<span class="num">'+erp+'</span>','<span class="num">'+au+' 亿</span>','<span class="num muted">'+fc+' 只</span>'] for n,c,cat,cl,chg,pe,pep,pb,pbp,dv,erp,au,fc in IDX]
    return ('<div class="toolbar"><div class="title-block"><h1>指数估值</h1><p class="muted">Valuation Band · 市场估值指数 · 多窗口分位</p></div><div class="toolbar-right"><div class="seg">'+windows+'</div></div></div>'
      '<div class="grid">'
      '<div class="col-8">'+card(th,"沪深300 · Valuation Band",'<div class="seg" style="margin-bottom:8px">'+metrics+'</div>'+band(th)+'<div class="caption"><span class="num">当前 13.42x</span><span class="muted">周线</span><span class="num">分位 74.4%</span><span class="num muted">样本 262 点</span><span class="num muted">均值 12.56x · 中位数 12.30x</span></div>',desc="PE · 5 年窗口 · 指标切换在右上角")+'</div>'
      '<div class="col-4">'+card(th,"市场估值指数 MVI",'<div class="mvi">'+gauge(th,27)+'<div class="mvi-side"><div class="zone">低估区 · 27 / 100</div><div class="muted small">PE/PB 低分位 + 股息/ERP 高分位 → 便宜</div><div class="spark">'+spark(th,[62,55,48,51,44,38,35,30,33,28,27],210,38,T(th,'accent2'))+'</div><div class="muted small">MVI 近 5 年</div></div></div><div class="factors">'+factors+'</div>',desc="0=极度低估 · 100=极度高估 · 每日刷新",right='<span class="pill">滚动 3 年训练</span>')+'</div></div>'
      '<div class="grid"><div class="col-6">'+card(th,"红利指数吸引力",scatter(th),desc="股息率 × PB · 自适应坐标轴 · 回归线 + R²")+'</div><div class="col-6">'+card(th,"估值矩阵 · PB 分位 × 股息率",matrix(th,'pb'),desc="PB 分位窗口：5 年 · 气泡=基金规模")+'</div></div>'
      '<div class="grid"><div class="col-6">'+card(th,"估值矩阵 · ROE × PE",matrix(th,'roe'),desc="log 轴 · 回归线 + R² + 行业均值线")+'</div><div class="col-6">'+card(th,"全市场估值结构",'<div class="kpi-grid">'+kpi(th,"全市场 PE","21.4","近 5 年 68% 分位","warn")+kpi(th,"全市场 PB","2.03","52% 分位")+kpi(th,"全市场 ROE","8.6%","46% 分位")+kpi(th,"风险溢价","2.41%","88% 分位","down")+'</div>',desc="MVI 因子拆解 · 替代原「全市场截面」")+'</div></div>'
      '<div class="section-head"><h2>指数列表</h2><div class="muted small">默认仅有 ETF/基金 · 按基金规模降序</div></div>'
      '<div class="chips">'+chip(th,"有 ETF/基金",True)+chip(th,"全部",False)+chip(th,"宽基",False)+chip(th,"行业",False)+chip(th,"主题",False)+chip(th,"策略",False)+'<span class="search">搜索指数 / 代码</span></div>'
      + table(th,["指数","收盘","今日","PE","PE 分位","PB","PB 分位","股息率","ERP","基金规模","基金数"],rows))

def tab_detail(th):
    holdings=[("1","600519","贵州茅台","白酒","4.42%","1,468.00","0.62%"),("2","300750","宁德时代","电池","3.18%","412.50","-1.20%"),("3","601318","中国平安","保险","2.86%","62.31","-0.44%"),("4","600036","招商银行","银行","2.61%","46.80","0.21%"),("5","000333","美的集团","家电","2.35%","78.90","-0.83%")]
    hrows=[[r,'<b>'+n+'</b> <span class="muted num">'+c+'</span>',ind,w,p,ch] for r,c,n,ind,w,p,ch in holdings]
    funds=[("510300","华泰柏瑞沪深300ETF","1,068.79 亿","0.15%","0.05%","2012-05-04","-11.44%","-11.69%","21.4%","-18.2%","0.08%","0.42"),("510310","易方达沪深300ETF","826.40 亿","0.15%","0.05%","2013-07-01","-11.38%","-11.62%","21.2%","-17.9%","0.06%","0.55"),("510330","华夏沪深300ETF","512.66 亿","0.50%","0.10%","2012-12-25","-11.61%","-11.84%","21.8%","-18.6%","0.12%","0.31")]
    frows=[['<b>'+n+'</b> <span class="muted num">'+c+'</span>',au,fe,cu,es,'<span style="color:'+T(th,'up')+'">'+r12+'</span>',yt,vo,md,te,ir] for c,n,au,fe,cu,es,r12,yt,vo,md,te,ir in funds]
    return ('<div class="toolbar"><div class="title-block"><h1>沪深300 <span class="muted num">000300</span></h1><p class="muted">估值日期 2026-11-14 · 成分披露 2026-11-14 · 跟踪基金 23 只 · 市值加权</p></div><div class="toolbar-right"><div class="seg">'+chip(th,"PE",True)+chip(th,"PB",False)+chip(th,"股息率",False)+chip(th,"风险溢价",False)+'</div></div></div>'
      '<div class="grid"><div class="col-8">'
      + card(th,"估值带",band(th),desc="PE · 5 年 · 当前 13.42x",right='<span class="pill">标准差 2σ</span>')
      + card(th,"描述统计 · 日收益率分布",'<div class="grid inner"><div class="col-7">'+hist(th)+'</div><div class="col-5"><div class="stat-grid">'+kpi(th,"年化波动率","21.4%")+kpi(th,"Beta（vs 沪深300）","1.00")+kpi(th,"Pearson","1.000")+kpi(th,"Spearman","0.998")+'</div><div class="muted small">基准：沪深300 · 可切换</div></div></div>')
      + card(th,"成分股 · 2026-11-14 披露",table(th,["#","成分股","行业","权重","最新价","涨跌幅"],hrows),desc="排名第一列 · 前 10 权重")
      + '</div><div class="col-4">'
      + card(th,"分位矩阵",'<div class="matrix"><div class="m-grid">'+''.join('<div><b>'+v+'%</b><span class="muted">'+w+'</span></div>' for v,w in [("15","1年"),("62","3年"),("74","5年"),("74","10年"),("74","全历史")])+'</div></div>',desc="4 指标 × 5 窗口")
      + card(th,"跟踪基金 · 指标与对比",table(th,["基金","规模","管理费","托管费","成立","近1年","YTD","波动","回撤","跟踪误差","IR"],frows),desc="规模降序 · 最多选 5 只对比",right='<span class="pill">+ 基金对比</span>')
      + card(th,"指数画像",'<div class="profile">基日 2004-12-31 · 基点 1,000 · 加权方式 市值加权 · 发布机构 中证指数<br><span class="muted">简介：沪深300由沪深市场中规模最大、流动性最好的300只股票组成……</span></div>')
      + '</div></div>')

def tab_crypto(th):
    C=[("BTCUSDT","108,420.5","-1.24%","32,410,000,000","2.1%","0.0100%","88%","1.42","1.18","0.62","0.042%"),("ETHUSDT","4,028.6","-2.08%","21,880,000,000","3.4%","0.0100%","91%","1.66","1.31","0.58","0.061%"),("SOLUSDT","198.42","-3.66%","6,120,000,000","6.8%","0.0100%","82%","1.21","0.94","0.57","0.083%"),("BNBUSDT","1,028.4","-0.92%","2,410,000,000","1.2%","0.0100%","76%","1.05","1.12","0.54","0.034%"),("XRPUSDT","3.182","-4.11%","1,880,000,000","9.2%","0.0100%","94%","0.88","1.42","0.61","0.052%")]
    rows=[['<b>'+c+'</b>',p,'<span style="color:'+T(th,'up')+'">'+chg+'</span>',oi,oic,f,fp,ls,tls,tk,ba] for c,p,chg,oi,oic,f,fp,ls,tls,tk,ba in C]
    oi_sp=spark(th,[120,132,128,140,150,146,160,172,168,180,176,190],320,70)
    return ('<div class="toolbar"><div class="title-block"><h1>加密货币看板</h1><p class="muted">合约监控 · 大户 vs 全市场因子 · 现货相关性</p></div><div class="toolbar-right"><div class="seg">'+chip(th,"24H",False)+chip(th,"7D",True)+chip(th,"30D",False)+'</div></div></div>'
      '<div class="grid">'+kpi(th,"总 OI 名义值","12,345,678,901","USD · 37 个合约")+kpi(th,"加权多空比","1.18","账户数比 · 按 OI 加权")+kpi(th,"加权资金费率","0.0100%","30 日分位 88%","warn")+kpi(th,"24h OI 变化","+3.2%","偏多头增仓")+kpi(th,"Smart Money 乖离","+0.24","大户持仓比 − 全市场账户比","down")+'</div>'
      '<div class="grid"><div class="col-8">'+card(th,"合约监控",table(th,["合约","标记价","24h","OI 名义","OI 变化","资金费率","费率 30d 分位","多空账户比","大户持仓比","Taker 比","基差"],rows),desc="全部列可排序 · 大户数据 = Binance 公开 topLongShortAccountRatio / PositionRatio")+'</div>'
      '<div class="col-4">'+card(th,"BTCUSDT · 大户 vs 全市场",'<div class="legend"><span>大户持仓比 1.31</span><span>全市场账户比 1.18</span><span>乖离 +0.13</span></div>'+spark(th,[1.1,1.2,1.15,1.3,1.25,1.35,1.31,1.4,1.36,1.42,1.38,1.44],300,80,T(th,'accent2'))+oi_sp,desc="近 30 日走势 · 色块=资金费率分位")+'</div></div>'
      '<div class="grid"><div class="col-6">'+card(th,"OI 与价格",oi_sp,desc="OI 上升 + 价格上升 = 增仓上行")+'</div><div class="col-6">'+card(th,"资金费率历史",spark(th,[0.01,0.012,0.009,0.014,0.02,0.017,0.015,0.011,0.013,0.016,0.01,0.01],300,80,T(th,'warn'))+'<div class="muted small">分位带 P20/P50/P80 · 当前 88%：多头拥挤</div>',desc="8h 资金费率 · 30 日分位")+'</div></div>'
      '<div class="section-head"><h2>BTC 相关性</h2><div class="muted small">黄金 / 标普500 / 纳斯达克100 / DXY · 90 日滚动</div></div>'
      + card(th,"90 日滚动相关性",spark(th,[0.3,0.42,0.35,0.5,0.46,0.55,0.6,0.52,0.48,0.58,0.62,0.57],900,110),desc="BTC vs 黄金 · BTC vs NDX · BTC vs DXY"))

def tab_assets(th):
    A=[("沪深300","000300","指数","最新 2026-11-14","不复权/前复权/后复权","✓"),("贵州茅台","600519","股票","最新 2026-11-14","不复权/前复权/后复权","✓"),("宁德时代","300750","股票","最新 2026-11-14","不复权/前复权/后复权","✓"),("华泰柏瑞沪深300ETF","510300","基金","最新 2026-11-14","不复权/前复权/后复权","✓"),("中证红利","000922","指数","最新 2026-11-14","不复权/前复权/后复权","✓"),("易方达蓝筹精选","005827","基金","最新 2026-11-13","不复权","✓"),("BTC-USD","BTC","加密","最新 2026-11-15","原生","✓")]
    rows=[[('<b>'+n+'</b> <span class="muted num">'+c+'</span>'),ty,la,ad,ok] for n,c,ty,la,ad,ok in A]
    return ('<div class="toolbar"><div class="title-block"><h1>资产池</h1><p class="muted">股票 / 指数 / 基金 / ETF 统一搜索 · 全量 ETL · 复权口径中文化</p></div><div class="toolbar-right"><span class="search big">搜索代码 / 名称 / 拼音</span></div></div>'
      '<div class="grid">'+kpi(th,"股票","5,412","全 A 股")+kpi(th,"指数","521","含 ETF 覆盖")+kpi(th,"基金","12,196","ETF + 联接 + 场外")+kpi(th,"行情覆盖","98.6%","最近交易日")+'</div>'
      '<div class="chips">'+chip(th,"全部",True)+chip(th,"股票",False)+chip(th,"指数",False)+chip(th,"基金",False)+chip(th,"仅看有数据",True)+'<span class="muted small" style="margin-left:auto">复权口径：不复权/前复权/后复权 ⓘ 回测默认后复权</span></div>'
      + card(th,"资产池",table(th,["标的","类型","最新行情","复权口径","数据完整"],rows),desc="搜索与资产池合并为统一入口"))

def tab_otc(th):
    params=[("标的","沪深300"),("估值日","2021-03-15"),("到期日","2022-03-15"),("敲出障碍","100%"),("敲入障碍","75%"),("票息","20% 年化"),("波动率","35%"),("无风险利率","2%"),("分红率","0%")]
    prow=''.join('<div class="p-row"><span>'+k+'</span><b>'+v+'</b></div>' for k,v in params)
    checks=[("雪球 MC vs 金标","-22,196.61","-22,171.23","0.11%"),("凤凰 MC vs 金标","32,118.60","32,055.99","0.20%"),("障碍 MC vs 金标","16,810.11","16,819.88","-0.06%"),("气囊解析 vs QuantLib","16,389.46","16,390.07","0.004%")]
    crows=[[n,s,m,e,'<span style="color:'+T(th,'down')+'">通过</span>'] for n,s,m,e in checks]
    return ('<div class="toolbar"><div class="title-block"><h1>场外衍生品定价</h1><p class="muted">雪球 / 凤凰 / 气囊 / 障碍 · MC + 解析 + 数值积分 · 金标对账</p></div><div class="toolbar-right"><span class="pill success">验证通过 · 金标 4/4</span></div></div>'
      '<div class="grid"><div class="col-4">'+card(th,"条款与参数",'<div class="seg">'+chip(th,"雪球",True)+chip(th,"凤凰",False)+chip(th,"气囊",False)+chip(th,"障碍",False)+'</div>'+prow+'<div class="cta">开始定价</div>')+'</div>'
      '<div class="col-8">'+card(th,"定价结果",'<div class="grid inner"><div class="col-6"><div class="pv">-22,196.61</div><div class="muted">买方 PV · 名义 100 万 · 100 万条路径</div><div class="metrics"><span>标准误 12.4</span><span>耗时 1.8s</span><span>Delta 2,167</span></div></div><div class="col-6">'+spark(th,[150,145,138,132,126,118,112,108,104,100],300,80)+'<div class="muted small">MC 收敛：10万→100万→1000万，标准误按 1/√n 下降</div></div></div>')+'</div></div>'
      + card(th,"金标对账（镒链测试文档 2021 系列）",table(th,["测试案例","系统值（金标）","我们 MC","相对误差","结论"],crows),desc="双时钟：折现 BUS252 + 票息 ACT365；复算固定参考日历"))

TABS=[("valuation","指数估值",tab_valuation),("detail","指数详情",tab_detail),("crypto","加密看板",tab_crypto),("assets","资产池",tab_assets),("otc","场外定价",tab_otc)]

CSS="""*{box-sizing:border-box}html,body{margin:0;padding:0}body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;line-height:1.5}a{color:inherit;text-decoration:none}.shell{max-width:1600px;margin:0 auto;padding:0 28px 64px}.nav{position:sticky;top:0;z-index:20;background:var(--nav);border-bottom:1px solid var(--border)}.nav-inner{max-width:1600px;margin:0 auto;display:flex;align-items:center;gap:22px;padding:0 28px;height:58px}.brand{display:flex;align-items:center;gap:9px;font-weight:700;letter-spacing:-.2px}.logo{width:26px;height:26px;border-radius:7px;background:var(--accent);color:var(--chip_on_text);display:grid;place-items:center;font-size:12px;font-weight:800}.nav-tabs{display:flex;gap:4px;margin-left:8px}.nav-tab{padding:7px 11px;border-radius:7px;color:var(--nav_text);font-size:13px;cursor:pointer}.nav-tab.active{background:var(--accent_soft);color:var(--accent);font-weight:600}.nav-right{margin-left:auto;display:flex;align-items:center;gap:10px;color:var(--nav_text);font-size:12px}.tab-panel{display:none;padding-top:20px}.tab-panel.active{display:block;animation:fade .28s ease}@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}.toolbar{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:16px}.title-block h1{margin:0;font-size:26px;letter-spacing:-.4px;font-family:var(--head_font)}.title-block p{margin:3px 0 0}.muted{color:var(--muted)}.small{font-size:11px}.num{font-family:var(--num_font);font-variant-numeric:tabular-nums}.seg{display:inline-flex;flex-wrap:wrap;gap:2px;background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:3px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-bottom:14px}.grid.inner{margin-bottom:0}.col-8{grid-column:span 8}.col-6{grid-column:span 6}.col-4{grid-column:span 4}.col-7{grid-column:span 7}.col-5{grid-column:span 5}.col-3{grid-column:span 3}.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:14px;min-width:0;margin-bottom:14px}.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px}.card h3{margin:0;font-size:14px;font-family:var(--head_font)}.card .desc{margin:2px 0 0;font-size:11px;color:var(--muted)}.pill{display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid var(--border);font-size:10px;color:var(--muted);background:var(--panel2);white-space:nowrap}.pill.success{color:var(--down);border-color:var(--down)}.caption{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}.caption .num{color:var(--text)}.kpi-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.kpi{background:var(--panel2);border:1px solid var(--border);border-radius:calc(var(--radius) - 4px);padding:10px 12px}.kpi-label{font-size:11px;color:var(--muted)}.kpi-value{font-family:var(--num_font);font-size:20px;font-weight:700;letter-spacing:-.4px}.kpi-sub{font-size:10px;color:var(--muted);margin-top:2px}.mvi{display:flex;gap:16px;align-items:center}.mvi>svg{width:46%;flex:none}.zone{font-weight:700;color:var(--down);font-size:16px}.spark{margin-top:8px}.factors{display:grid;gap:8px;margin-top:12px}.factor-top{display:flex;justify-content:space-between;font-size:11px}.factor-bottom{display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-top:2px}.bar{height:6px;border-radius:999px;background:var(--grid);margin-top:4px;overflow:hidden}.bar>div{height:100%;border-radius:999px}.chips{display:flex;align-items:center;flex-wrap:wrap;margin:8px 0 10px;gap:6px}.search{margin-left:10px;padding:6px 12px;border:1px solid var(--border);border-radius:8px;color:var(--muted);background:var(--panel);font-size:11px}.search.big{padding:9px 16px;font-size:12px;min-width:300px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;padding:7px 8px;font-weight:500;color:var(--muted);background:var(--table_head);border-bottom:1px solid var(--border);white-space:nowrap;font-size:11px}td{padding:7px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}tbody tr:hover{background:var(--hover)}.tag{font-size:10px;color:var(--muted);border:1px solid var(--border);border-radius:999px;padding:1px 6px;margin-left:4px}.section-head{display:flex;align-items:baseline;justify-content:space-between;margin:18px 0 4px}.section-head h2{margin:0;font-size:17px;font-family:var(--head_font)}.matrix .m-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.matrix .m-grid>div{background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:8px;text-align:center;font-size:11px}.matrix .m-grid b{display:block;font-family:var(--num_font);font-size:13px}.legend{display:flex;gap:14px;font-size:11px;color:var(--muted);margin-bottom:6px}.stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.profile{font-size:12px;line-height:1.7}.p-row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px dashed var(--grid);font-size:12px}.p-row span{color:var(--muted)}.cta{margin-top:12px;background:var(--accent);color:var(--chip_on_text);text-align:center;padding:9px;border-radius:8px;font-weight:600;font-size:12px}.pv{font-family:var(--num_font);font-size:32px;font-weight:700;letter-spacing:-.6px}.metrics{display:flex;gap:14px;margin-top:8px;font-size:11px;color:var(--muted)}@media(max-width:1100px){.col-8,.col-6,.col-4,.col-7,.col-5,.col-3{grid-column:span 12}.mvi{flex-direction:column}}"""

def render(th):
    tokens=''.join('--'+k+':'+v+';\n' for k,v in THEMES[th].items() if k!='name')
    nav=''.join('<div class="nav-tab'+((' active') if i==0 else '')+'" data-tab="'+key+'">'+label+'</div>' for i,(key,label,_) in enumerate(TABS))
    panels=''
    for i,(key,label,fn) in enumerate(TABS):
        panels+='<section class="tab-panel'+((' active') if i==0 else '')+'" id="panel-'+key+'"><div class="shell">'+fn(th)+'</div></section>'
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Balanced Portfolio · v3 原型 '+THEMES[th]['name']+'</title><style>:root{'+tokens+'}'+CSS+'</style></head><body>'
      '<div class="nav"><div class="nav-inner"><div class="brand"><span class="logo">BP</span>Balanced Portfolio</div><div class="nav-tabs">'+nav+'</div><div class="nav-right"><span class="muted">v3 原型 · '+THEMES[th]['name']+'</span><span class="pill">1600px</span></div></div></div>'
      +panels
      +'<script>document.querySelectorAll(".nav-tab").forEach(function(el){el.addEventListener("click",function(){document.querySelectorAll(".nav-tab").forEach(function(x){x.classList.remove("active")});document.querySelectorAll(".tab-panel").forEach(function(x){x.classList.remove("active")});el.classList.add("active");document.getElementById("panel-"+el.dataset.tab).classList.add("active");window.scrollTo({top:0,behavior:"smooth"});})});</script></body></html>')

def main():
    for th,name in [("a","proto-a-light.html"),("b","proto-b-dark.html"),("c","proto-c-analyst.html")]:
        html=render(th); path=os.path.join(OUT_DIR,name)
        open(path,"w",encoding="utf-8").write(html)
        print(name,len(html),"bytes")

if __name__=="__main__":
    main()
