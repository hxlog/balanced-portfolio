# -*- coding: utf-8 -*-
path = "scripts/research_mvi.py"
s = open(path, encoding="utf-8").read()

s = s.replace("def latest_score(panel: pd.DataFrame, fwd: pd.Series):",
              "def latest_score(panel: pd.DataFrame, fwd: pd.Series, fallback_w=None):")
s = s.replace("    w = best.x if best is not None else np.full(5, 0.2)",
              "    w = best.x if best is not None else (np.asarray(fallback_w) if fallback_w is not None else np.full(5, 0.2))")
s = s.replace('for seed in range(5):\n        w0 = np.full(5, 0.2) + np.random.default_rng(seed).normal(0, 0.03, 5)',
              'for seed in range(12):\n        w0 = np.full(5, 0.2) + np.random.default_rng(seed).normal(0, 0.06, 5)')
s = s.replace("    latest = latest_score(panel, fwd)",
              "    last_ok = [f for f in folds if f.get('ok')]\n    fallback = None\n    if last_ok:\n        fb = last_ok[-1].get('weights_a') or {}\n        fallback = [float(fb.get(k, 0.2)) for k in FACTORS]\n    latest = latest_score(panel, fwd, fallback)")
s = s.replace('out_dir = "/opt/balanced-portfolio/docs/index-valuation"',
              'out_dir = "/opt/balanced-portfolio/docs/index-valuation"\n    os.makedirs(out_dir, exist_ok=True)')
s = s.replace("import json\nimport math\nimport sys", "import json\nimport math\nimport os\nimport sys")
open(path, "w", encoding="utf-8").write(s)
print("patched latest/fallback/output dir")
