# -*- coding: utf-8 -*-
path = "scripts/backfill_fund_nav.py"
s = open(path, encoding="utf-8").read()

s = s.replace("import argparse\nimport json\nimport re\nimport sys\nimport time", "import argparse\nimport json\nimport re\nimport sys\nimport threading\nimport time\nfrom concurrent.futures import ThreadPoolExecutor, as_completed")

# 并行抓取：把主循环替换为线程池
old = """        session = requests.Session()
        session.headers.update(UA)
        for index, raw_code in enumerate(codes):
            code = strip_prefix(raw_code)
            if not args.force:
                with connect(cfg.db) as conn, conn.cursor() as cur:
                    cur.execute("SELECT max(trade_date) FROM bp_fund_nav_daily WHERE fund_code = %s", (raw_code,))
                    last = cur.fetchone()[0]
                if last is not None and last >= date.today() - timedelta(days=10):
                    continue
            try:
                response = session.get(URL.format(code=code), timeout=30)
                if response.status_code != 200 or len(response.text) < 500:
                    failed += 1
                    continue
                nav_rows, acc_rows = parse_nav(response.text)
                if not nav_rows:
                    failed += 1
                    continue
                with connect(cfg.db) as conn:
                    conn.autocommit = False
                    upsert_nav(conn, raw_code, nav_rows, acc_rows)
                    conn.commit()
                done += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("fail", raw_code, type(exc).__name__, str(exc)[:100], flush=True)
            if (index + 1) % 100 == 0:
                print("progress", index + 1, "/", len(codes), "ok", done, "fail", failed, flush=True)
            time.sleep(0.15)
"""
new = """        lock = threading.Lock()
        counter = {"done": 0, "failed": 0}

        def worker(raw_code: str) -> None:
            code = strip_prefix(raw_code)
            if not args.force:
                with connect(cfg.db) as conn, conn.cursor() as cur:
                    cur.execute("SELECT max(trade_date) FROM bp_fund_nav_daily WHERE fund_code = %s", (raw_code,))
                    last = cur.fetchone()[0]
                if last is not None and last >= date.today() - timedelta(days=10):
                    return
            try:
                session = requests.Session()
                session.headers.update(UA)
                response = session.get(URL.format(code=code), timeout=30)
                if response.status_code != 200 or len(response.text) < 500:
                    raise RuntimeError("http " + str(response.status_code))
                nav_rows, acc_rows = parse_nav(response.text)
                if not nav_rows:
                    raise RuntimeError("empty nav")
                with connect(cfg.db) as conn:
                    conn.autocommit = False
                    upsert_nav(conn, raw_code, nav_rows, acc_rows)
                    conn.commit()
                with lock:
                    counter["done"] += 1
            except Exception as exc:  # noqa: BLE001
                with lock:
                    counter["failed"] += 1
                    print("fail", raw_code, type(exc).__name__, str(exc)[:80], flush=True)
            finally:
                with lock:
                    total = counter["done"] + counter["failed"]
                    if total % 100 == 0:
                        print("progress", total, "/", len(codes), "ok", counter["done"], "fail", counter["failed"], flush=True)
                time.sleep(0.05)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(worker, code) for code in codes]
            for future in as_completed(futures):
                future.result()
        done = counter["done"]
        failed = counter["failed"]
"""
assert old in s, "loop block missing"
s = s.replace(old, new)
s = s.replace('    parser.add_argument("--fund", type=str, default=None)',
              '    parser.add_argument("--fund", type=str, default=None)\n    parser.add_argument("--workers", type=int, default=8)')
open(path, "w", encoding="utf-8").write(s)
print("parallelized")
