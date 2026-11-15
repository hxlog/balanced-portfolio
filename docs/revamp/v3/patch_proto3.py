# -*- coding: utf-8 -*-
import subprocess
path = "docs/revamp/v3/gen_prototypes.py"
subprocess.run(["git", "checkout", "--", path], check=True)
s = open(path, encoding="utf-8").read()
orig = s

# density tokens
s = s.replace('table_head="#f8fafc", hover="#f1f5f9"),',
              'table_head="#f8fafc", hover="#f1f5f9", fs="14px", gap="18px", pad="20px"),')
s = s.replace("def T(th, k): return THEMES[th][k]",
              "def T(th, k): return THEMES[th][k]\n\ndef CS(th):\n    return 1.16 if th == 'a' else 1.0")
s = s.replace("font-size:13px;line-height:1.5}", "font-size:var(--fs,13px);line-height:1.55;}")
s = s.replace("gap:14px;margin-bottom:14px}", "gap:var(--gap,14px);margin-bottom:var(--gap,14px)}")
s = s.replace("padding:14px;min-width:0;margin-bottom:14px}", "padding:var(--pad,14px);min-width:0;margin-bottom:var(--gap,14px)}")
for old, new in [("W,H=720,205", "W,H=720,int(205*CS(th))"),
                 ("W,H=640,215", "W,H=640,int(215*CS(th))"),
                 ("W,H=450,190", "W,H=450,int(190*CS(th))"),
                 ("W,H=400,160", "W,H=400,int(160*CS(th))")]:
    s = s.replace(old, new)

# gauge signature
s = s.replace("def gauge(th, score=27, size=210):",
              "def gauge(th, score=27, size=210, title='MVI', sub='\u8d8a\u4f4e\u8d8a\u4fbf\u5b9c', left='0 \u4fbf\u5b9c', right='100 \u8d35'):")

lines = s.split("\n")
for i, line in enumerate(lines):
    if 'p.append(' in line and 'text-anchor="middle" font-size="10"' in line and 'str(score)' not in line:
        lines[i] = "    p.append('<text x=\"'+str(cx)+'\" y=\"'+str(cy-2)+'\" text-anchor=\"middle\" font-size=\"10\" fill=\"'+T(th,'muted')+'\">'+title+' \u00b7 '+sub+'</text>')"
    elif 'p.append(' in line and 'text-anchor="middle" font-size="9"' in line and 'cx-r-2' in line:
        lines[i] = "    p.append('<text x=\"'+str(cx-r-2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+left+'</text>')"
    elif 'p.append(' in line and 'text-anchor="middle" font-size="9"' in line and 'cx+r+2' in line:
        lines[i] = "    p.append('<text x=\"'+str(cx+r+2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+right+'</text>')"
s = "\n".join(lines)

# dual gauges via exact markers
start_marker = '\'<div class="mvi">\''
end_marker = '\'</div><div class="factors">\''
a = s.find(start_marker)
b = s.find(end_marker, a)
if a != -1 and b != -1:
    new_markup = (
        "'<div class=\"mvi-dual\">'"
        "+'<div class=\"mvi-gauge\">'+gauge(th,27,150,'\u4f30\u503c\u5206','\u8d8a\u4f4e\u8d8a\u4fbf\u5b9c','0 \u4fbf\u5b9c','100 \u8d35')"
        "+'<div class=\"mvi-label\"><b>27</b><span class=\"muted\">\u4f30\u503c\u5206 \u00b7 \u4f4e\u4f30\u533a</span></div></div>'"
        "+'<div class=\"mvi-gauge\">'+gauge(th,68,150,'\u98ce\u9669\u5206','\u8d8a\u9ad8\u8d8a\u5371\u9669','0 \u5b89\u5168','100 \u5371\u9669')"
        "+'<div class=\"mvi-label\"><b>68</b><span class=\"muted\">\u98ce\u9669\u5206 \u00b7 \u504f\u9ad8</span></div></div>'"
        "+'</div><div class=\"muted small\" style=\"margin:6px 0 8px\">\u4f30\u503c\u5206\u4f4e + \u98ce\u9669\u5206\u4f4e = \u5b89\u5168\u8fb9\u9645\u9ad8\uff1b"
        "\u4e24\u5206\u6570\u7531 PE/PB/\u80a1\u606f/ERP/ROE \u5206\u4f4d\u4e0e\u6ce2\u52a8\u7387/\u56de\u64a4\u56e0\u5b50\u5408\u6210\uff0c\u6bcf\u65e5\u5237\u65b0\u3002</div>'"
        "+'<div class=\"mvi-side\" style=\"display:none\">'"
    )
    s = s[:a] + new_markup + s[b:]

s = s.replace(".legend{display:flex",
              ".mvi-dual{display:flex;gap:10px;margin-bottom:4px}.mvi-gauge{flex:1;min-width:0;text-align:center}"
              ".mvi-label{display:flex;flex-direction:column;margin-top:-6px}.mvi-label b{font-family:var(--num_font);font-size:16px}"
              ".legend{display:flex")

open(path, "w", encoding="utf-8").write(s)
print("changed:", s != orig, "len:", len(s), "dual:", "mvi-dual" in s)
