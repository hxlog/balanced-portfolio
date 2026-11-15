# -*- coding: utf-8 -*-
path = "docs/revamp/v3/gen_prototypes.py"
lines = open(path, encoding="utf-8").read().split("\n")
out = []
for i, line in enumerate(lines):
    if line.strip() == "if size >= 180:":
        out.append(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        out.append("        " + nxt.strip())
        # 跳过原下一行（下一轮循环会重复，改为标记）
        lines[i + 1] = None
    elif line is None:
        continue
    else:
        out.append(line)
open(path, "w", encoding="utf-8").write("\n".join(out))
print("fixed indentation")
