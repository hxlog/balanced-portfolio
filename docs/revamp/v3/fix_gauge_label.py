# -*- coding: utf-8 -*-
path = "docs/revamp/v3/gen_prototypes.py"
lines = open(path, encoding="utf-8").read().split("\n")
for i, line in enumerate(lines):
    if "p.append(" in line and "+title+' \u00b7 '+sub+'</text>'" in line:
        lines[i] = "    if size >= 180:\n" + line
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("patched label condition")
