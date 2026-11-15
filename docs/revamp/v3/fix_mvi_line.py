# -*- coding: utf-8 -*-
path = "docs/revamp/v3/gen_prototypes.py"
lines = open(path, encoding="utf-8").read().split("\n")
new_line = (
    "      '<div class=\"col-4\">'+card(th,\"\u5e02\u573a\u4f30\u503c\u6307\u6570 MVI\",'<div class=\"mvi-dual\">'"
    "+'<div class=\"mvi-gauge\">'+gauge(th,27,150,'\u4f30\u503c\u5206','\u8d8a\u4f4e\u8d8a\u4fbf\u5b9c','0 \u4fbf\u5b9c','100 \u8d35')"
    "+'<div class=\"mvi-label\"><b>27</b><span class=\"muted\">\u4f30\u503c\u5206 \u00b7 \u4f4e\u4f30\u533a</span></div></div>'"
    "+'<div class=\"mvi-gauge\">'+gauge(th,68,150,'\u98ce\u9669\u5206','\u8d8a\u9ad8\u8d8a\u5371\u9669','0 \u5b89\u5168','100 \u5371\u9669')"
    "+'<div class=\"mvi-label\"><b>68</b><span class=\"muted\">\u98ce\u9669\u5206 \u00b7 \u504f\u9ad8</span></div></div>'"
    "+'</div><div class=\"muted small\" style=\"margin:6px 0 8px\">\u4f30\u503c\u5206\u4f4e + \u98ce\u9669\u5206\u4f4e = \u5b89\u5168\u8fb9\u9645\u9ad8\uff1b"
    "\u4e24\u5206\u6570\u7531 PE/PB/\u80a1\u606f/ERP/ROE \u5206\u4f4d\u4e0e\u6ce2\u52a8\u7387/\u56de\u64a4\u56e0\u5b50\u5408\u6210\uff0c\u6bcf\u65e5\u5237\u65b0\u3002</div>'"
    "+'<div class=\"mvi-side\" style=\"display:none\">'"
    "+'<div class=\"zone\">\u4f30\u503c\u5206 27 / \u98ce\u9669\u5206 68</div></div>"
    "<div class=\"spark\">'+spark(th,[62,55,48,51,44,38,35,30,33,28,27],190,34,T(th,'accent2'))+'</div>"
    "<div class=\"muted small\" style=\"margin-bottom:8px\">MVI \u4f30\u503c\u5206\u8fd1 5 \u5e74</div><div class=\"factors\">'+factors+'</div>',"
    "desc=\"\u53cc\u6307\u6570\u4eea\u8868\u76d8 \u00b7 \u6eda\u52a8 3 \u5e74\u8bad\u7ec3 \u00b7 \u6bcf\u65e5\u5237\u65b0\","
    "right='<span class=\"pill\">\u4f30\u503c\u5206 27 / \u98ce\u9669\u5206 68</span>')+'</div></div>'"
)
for i, line in enumerate(lines):
    if "\u5e02\u573a\u4f30\u503c\u6307\u6570 MVI" in line and "card(th" in line:
        lines[i] = new_line
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("replaced mvi line")
