# 维护脚本

这些脚本用于数据源排障和资产池维护，不参与 API 运行。

- `check_cookies.py`：检查东财、新浪连接和 Cookie 注入状态。输出会隐藏 Cookie 内容。
- `validate_candidates.py`：验证候选资产代码及可用行情源。
- `gen_seed_sql.py`：把验证结果转换为可审阅的资产种子 SQL。

候选文件 `candidates.json` 与 `validated_candidates.json` 属于本地维护数据，默认不提交。

在项目根目录运行：

```bash
python scripts/check_cookies.py
python scripts/validate_candidates.py candidates.json > validated_candidates.json
python scripts/gen_seed_sql.py validated_candidates.json > asset_seed.sql
```

生成的 SQL 需要人工复核后再合并到 `ddl/schema.sql`。
