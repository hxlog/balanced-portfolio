# -*- coding: utf-8 -*-
path = "docs/revamp/v3/gen_prototypes.py"
lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
for i, line in enumerate(lines):
    if "p.append('<text x=\"'+str(cx)+'\" y=\"'+str(cy-2)" in line:
        lines[i] = "    p.append('<text x=\"'+str(cx)+'\" y=\"'+str(cy-2)+'\" text-anchor=\"middle\" font-size=\"10\" fill=\"'+T(th,'muted')+'\">'+title+' \u00b7 '+sub+'</text>')"
    elif "p.append('<text x=\"'+str(cx-r-2)" in line:
        lines[i] = "    p.append('<text x=\"'+str(cx-r-2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+left+'</text>')"
    elif "p.append('<text x=\"'+str(cx+r+2)" in line:
        lines[i] = "    p.append('<text x=\"'+str(cx+r+2)+'\" y=\"'+str(cy+16)+'\" text-anchor=\"middle\" font-size=\"9\" fill=\"'+T(th,'muted')+'\">'+right+'</text>')"
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("done")
