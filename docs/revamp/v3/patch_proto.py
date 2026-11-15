# -*- coding: utf-8 -*-
import io, sys
path = "docs/revamp/v3/gen_prototypes.py"
s = open(path, encoding="utf-8").read()
orig = s

s = s.replace('table_head="#f8fafc", hover="#f1f5f9"),', 'table_head="#f8fafc", hover="#f1f5f9", fs="14px", gap="18px", pad="20px"),')
s = s.replace("def T(th, k): return THEMES[th][k]", "def T(th, k): return THEMES[th][k]\n\ndef CS(th):\n    return 1.16 if th == 'a' else 1.0")
s = s.replace("font-size:13px;line-height:1.5}", "font-size:var(--fs,13px);line-height:1.55;}")
s = s.replace("gap:14px;margin-bottom:14px}", "gap:var(--gap,14px);margin-bottom:var(--gap,14px)}")
s = s.replace("padding:14px;min-width:0;margin-bottom:14px}", "padding:var(--pad,14px);min-width:0;margin-bottom:var(--gap,14px)}")
s = s.replace("def band(th):\n    W,H=720,205", "def band(th):\n    W,H=720,int(205*CS(th))")
s = s.replace("def scatter(th):\n    W,H=640,215", "def scatter(th):\n    W,H=640,int(215*CS(th))")
s = s.replace("def matrix(th, kind):\n    W,H=450,190", "def matrix(th, kind):\n    W,H=450,int(190*CS(th))")
s = s.replace("def hist(th):\n    W,H=400,160", "def hist(th):\n    W,H=400,int(160*CS(th))")
s = s.replace("def gauge(th, score=27, size=210):", "def gauge(th, score=27, size=210, title='MVI', sub='越低越便宜', left='0 便宜', right='100 贵'):")
s = s.replace(">MVI · 越低越便宜</text>", ">" + "|TITLE|" + "</text>").replace("'+str(cx)+'\" y=\"'+str(cy-2)+'\" text-anchor=\"middle\" font-size=\"10\" fill=\"'+T(th,'muted')+'\">" + "|TITLE|", "'+str(cx)+'\" y=\"'+str(cy-2)+'\" text-anchor=\"middle\" font-size=\"10\" fill=\"'+T(th,'muted')+'\">'+title+' · '+sub")
s = s.replace(">0 便宜</text>", ">" + "|LEFT|" + "</text>").replace("'+str(cx-r-2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">" + "|LEFT|", "'+str(cx-r-2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+left")
s = s.replace(">100 贵</text>", ">" + "|RIGHT|" + "</text>").replace("'+str(cx+r+2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">" + "|RIGHT|", "'+str(cx+r+2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+right")

# 双仪表 MVI：定位旧卡片片段（从 market valuation 卡的开始到结束）
start = s.find('"市场估值指数 MVI"')
if start != -1:
    seg_start = s.rfind('+card(th,', 0, start)
    seg_end = s.find("+ '</div></div>'", start)
    if seg_end != -1:
        new_seg = (
            "+card(th,\"市场估值指数 MVI\",'<div class=\"mvi-dual\">'"
            "+'<div class=\"mvi-gauge\">'+gauge(th,27,150,'估值分','越低越便宜','0 便宜','100 贵')+'<div class=\"mvi-label\"><b>27</b><span class=\"muted\">估值分 · 低估区</span></div></div>'"
            "+'<div class=\"mvi-gauge\">'+gauge(th,68,150,'风险分','越高越危险','0 安全','100 危险')+'<div class=\"mvi-label\"><b>68</b><span class=\"muted\">风险分 · 偏高</span></div></div>'"
            "+'</div><div class=\"muted small\" style=\"margin:6px 0 8px\">估值分低 + 风险分低 = 安全边际高；两分数由 PE/PB/股息/ERP/ROE 分位与波动率/回撤因子合成，每日刷新。</div>'"
            "+'<div class=\"spark\">'+spark(th,[62,55,48,51,44,38,35,30,33,28,27],190,34,T(th,'accent2'))+'</div>'"
            "+'<div class=\"muted small\" style=\"margin-bottom:8px\">MVI 估值分近 5 年</div><div class=\"factors\">'+factors+'</div>',desc=\"双指数仪表盘 · 滚动 3 年训练 · 每日刷新\",right='<span class=\"pill\">估值分 27 / 风险分 68</span>')"
        )
        s = s[:seg_start] + new_seg + s[seg_end:]

s = s.replace(".legend{display:flex", ".mvi-dual{display:flex;gap:10px;margin-bottom:4px}.mvi-gauge{flex:1;min-width:0;text-align:center}.mvi-label{display:flex;flex-direction:column;margin-top:-6px}.mvi-label b{font-family:var(--num_font);font-size:16px}.legend{display:flex")

open(path, "w", encoding="utf-8").write(s)
print("changed:", s != orig)
print("dual:", "mvi-dual" in s, "tokens:", "fs=\"14px\"" in s)
