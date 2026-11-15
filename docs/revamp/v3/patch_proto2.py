# -*- coding: utf-8 -*-
import re
path = "docs/revamp/v3/gen_prototypes.py"
s = open(path, encoding="utf-8").read()
orig = s

# 1) theme A density tokens
s = s.replace('table_head="#f8fafc", hover="#f1f5f9"),',
              'table_head="#f8fafc", hover="#f1f5f9", fs="14px", gap="18px", pad="20px"),')

# 2) CS helper
s = s.replace("def T(th, k): return THEMES[th][k]",
              "def T(th, k): return THEMES[th][k]\n\ndef CS(th):\n    return 1.16 if th == 'a' else 1.0")

# 3) CSS variables
s = s.replace("font-size:13px;line-height:1.5}", "font-size:var(--fs,13px);line-height:1.55;}")
s = s.replace("gap:14px;margin-bottom:14px}", "gap:var(--gap,14px);margin-bottom:var(--gap,14px)}")
s = s.replace("padding:14px;min-width:0;margin-bottom:14px}", "padding:var(--pad,14px);min-width:0;margin-bottom:var(--gap,14px)}")

# 4) chart heights
for old, new in [("W,H=720,205", "W,H=720,int(205*CS(th))"),
                 ("W,H=640,215", "W,H=640,int(215*CS(th))"),
                 ("W,H=450,190", "W,H=450,int(190*CS(th))"),
                 ("W,H=400,160", "W,H=400,int(160*CS(th))")]:
    s = s.replace(old, new)

# 5) gauge signature + labels
s = s.replace("def gauge(th, score=27, size=210):",
              "def gauge(th, score=27, size=210, title='MVI', sub='\u8d8a\u4f4e\u8d8a\u4fbf\u5b9c', left='0 \u4fbf\u5b9c', right='100 \u8d35'):")
lines = s.split("\n")
for i, line in enumerate(lines):
    if 'p.append(' in line and 'text-anchor="middle" font-size="10"' in line and 'score' not in line:
        lines[i] = "    p.append('<text x=\"'+str(cx)+'\" y=\"'+str(cy-2)+'\" text-anchor=\"middle\" font-size=\"10\" fill=\"'+T(th,'muted')+'\">'+title+' \u00b7 '+sub+'</text>')"
    elif 'p.append(' in line and 'text-anchor="middle" font-size="9"' in line and 'cx-r-2' in line:
        lines[i] = "    p.append('<text x=\"'+str(cx-r-2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+left+'</text>')"
    elif 'p.append(' in line and 'text-anchor="middle" font-size="9"' in line and 'cx+r+2' in line:
        lines[i] = "    p.append('<text x=\"'+str(cx+r+2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+right+'</text>')"
s = "\n".join(lines)

# 6) dual MVI gauges: replace the mvi card body
mvi_title = "\u5e02\u573a\u4f30\u503c\u6307\u6570 MVI"
start = s.find('card(th,"' + mvi_title + '"')
if start != -1:
    seg_start = s.rfind("+ '<div class=\"col-4\">'", 0, start)
    if seg_start == -1:
        seg_start = s.rfind("'<div class=\"col-4\">'", 0, start)
    seg_end = s.find("+ '</div></div>'", start)
    if seg_start != -1 and seg_end != -1:
        g = "gauge(th,27,150,'\u4f30\u503c\u5206','\u8d8a\u4f4e\u8d8a\u4fbf\u5b9c','0 \u4fbf\u5b9c','100 \u8d35')"
        g2 = "gauge(th,68,150,'\u98ce\u9669\u5206','\u8d8a\u9ad8\u8d8a\u5371\u9669','0 \u5b89\u5168','100 \u5371\u9669')"
        new_body = (
            "+card(th,\"" + mvi_title + "\",'<div class=\"mvi-dual\">'"
            "+'<div class=\"mvi-gauge\">'+" + g + "+'<div class=\"mvi-label\"><b>27</b><span class=\"muted\">"
            "\u4f30\u503c\u5206 \u00b7 \u4f4e\u4f30\u533a</span></div></div>'"
            "+'<div class=\"mvi-gauge\">'+" + g2 + "+'<div class=\"mvi-label\"><b>68</b><span class=\"muted\">"
            "\u98ce\u9669\u5206 \u00b7 \u504f\u9ad8</span></div></div>'"
            "+'</div><div class=\"muted small\" style=\"margin:6px 0 8px\">"
            "\u4f30\u503c\u5206\u4f4e + \u98ce\u9669\u5206\u4f4e = \u5b89\u5168\u8fb9\u9645\u9ad8\uff1b"
            "\u4e24\u5206\u6570\u7531 PE/PB/\u80a1\u606f/ERP/ROE \u5206\u4f4d\u4e0e\u6ce2\u52a8\u7387/\u56de\u64a4\u56e0\u5b50\u5408\u6210\uff0c\u6bcf\u65e5\u5237\u65b0\u3002</div>'"
            "+'<div class=\"spark\">'+spark(th,[62,55,48,51,44,38,35,30,33,28,27],190,34,T(th,'accent2'))+'</div>'"
            "+'<div class=\"muted small\" style=\"margin-bottom:8px\">MVI \u4f30\u503c\u5206\u8fd1 5 \u5e74</div><div class=\"factors\">'+factors+'</div>',"
            "desc=\"\u53cc\u6307\u6570\u4eea\u8868\u76d8 \u00b7 \u6eda\u52a8 3 \u5e74\u8bad\u7ec3 \u00b7 \u6bcf\u65e5\u5237\u65b0\","
            "right='<span class=\"pill\">\u4f30\u503c\u5206 27 / \u98ce\u9669\u5206 68</span>')"
        )
        s = s[:seg_start] + new_body + s[seg_end:]

# 7) dual gauge CSS
s = s.replace(".legend{display:flex",
              ".mvi-dual{display:flex;gap:10px;margin-bottom:4px}.mvi-gauge{flex:1;min-width:0;text-align:center}"
              ".mvi-label{display:flex;flex-direction:column;margin-top:-6px}.mvi-label b{font-family:var(--num_font);font-size:16px}"
              ".legend{display:flex")

open(path, "w", encoding="utf-8").write(s)
print("changed:", s != orig, "dual:", "mvi-dual" in s, "fs token:", 'fs="14px"' in s, "cs:", "CS(th)" in s)
