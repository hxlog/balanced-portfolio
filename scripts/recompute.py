from bp_api import db, tasks
from bp_api.settings import load_settings

s = load_settings()
db.init_pool(s)

with db.get_conn() as conn:
    cur = conn.cursor()
    # 获取所有非 running 的组合
    cur.execute('SELECT portfolio_id FROM bp_portfolio WHERE status != %s', ('running',))
    pids = [r[0] for r in cur.fetchall()]
    # 重置状态
    cur.execute("UPDATE bp_portfolio SET status='pending', error=NULL WHERE status IN ('done','error')")
    cur.execute('DELETE FROM bp_portfolio_update_state')
    conn.commit()
    print(f'共 {len(pids)} 个组合待重跑')

# 逐个回测（同步串行，避免资源争抢）
for pid in pids:
    print(f'回测 portfolio_id={pid} ...')
    tasks.run_backtest_background(pid, s)

db.close_pool()
print('全部完成')