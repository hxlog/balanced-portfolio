# -*- coding: utf-8 -*-
path = "scripts/research_mvi.py"
s = open(path, encoding="utf-8").read()
s = s.replace("if len(train) < 80 or len(test) < 12:", "if len(train) < 60 or len(test) < 12:")
s = s.replace(
"""    test = test[test_valid]
    if len(train) < 60 or len(test) < 12:""",
"""    test = test[test_valid]
    train = train.dropna()
    test = test.dropna()
    if len(train) < 60 or len(test) < 12:""")
open(path, "w", encoding="utf-8").write(s)
print("patched dropna/threshold")
