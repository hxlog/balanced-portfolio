#!/usr/bin/env bash
cd /opt/balanced-portfolio
.venv/bin/python - <<'PY'
import importlib.util
for m in ("pandas", "scipy", "numpy", "sklearn", "statsmodels"):
    print(m, bool(importlib.util.find_spec(m)))
PY
