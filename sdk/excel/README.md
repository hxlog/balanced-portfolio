# Excel Power Query 模板：指数估值（最近 521 个交易日）

本目录提供可复制的 Power Query M 查询：

- `bp_valuation.pq`：完整查询文件；
- 本文档：分步操作说明 + M 模板全文。

查询调用 `GET /api/v1/index/valuation`，默认拉取 `930641` 最近 3 年数据，
再截取**最近 521 个交易日**，输出 `code, date, pe_ttm, pb, dividend_yield_ttm, erp`
六列。适用于 Excel 2016+ / Microsoft 365（Power Query 内置版本）。

> API 的 JSON 响应使用统一信封 `{"data", "meta", "error"}`；本模板会先校验
> `error` 和 HTTP 状态，再把 `data` 展开成表。返回日期字段名是 `date`，
> 不是 `trade_date`。

---

## 1. 前置准备

1. 向管理员申请 API Token（形如 `bp_live_...`），并确保它有 **`valuation`** scope。
2. 确认能访问 `https://xushilu.com`（公司代理/防火墙需放行）。
3. Token 不要直接写进要分发的 Excel 文件；建议用下面的「Token 参数化」方式。

---

## 2. 分步说明

### 第 1 步：新建空查询

Excel 菜单：

**数据** → **获取数据** → **来自其他源** → **空查询**。

### 第 2 步：打开高级编辑器

在 Power Query 编辑器里点击 **主页** → **高级编辑器**。

### 第 3 步：粘贴 M 查询

删除编辑器中的默认内容，粘贴下面「M 模板全文」，然后：

- 把 `Token` 改成你的 `bp_live_...`；
- 按需修改 `IndexCode`、`FieldList`、`TopRows`；
- 点击 **完成**。

### 第 4 步：处理凭据

第一次刷新时 Excel 可能弹出凭据窗口：

- 选择 **匿名**（Anonymous）——Token 已经在 `Authorization` 请求头中；
- 不需要在 Excel 里再填一次 Token。

如果提示 `We couldn't authenticate with the credentials provided`，通常也是
凭据类型选错：到 **数据** → **获取数据** → **数据源设置**，选中
`https://xushilu.com`，编辑权限，改为「匿名」。

### 第 5 步：处理隐私级别（可选）

如果刷新时报 `Formula.Firewall`：

**数据** → **获取数据** → **查询选项** → **隐私** →
勾选「忽略隐私级别设置」（或把该数据源的隐私级别设为「无」）。

### 第 6 步：上载到工作表

**主页** → **关闭并上载** → **关闭并上载至...** → 选择「表」和位置。

成功后应得到：

- **521 行**（当最近 3 年有足够交易日时）；
- 6 列：`code`、`date`、`pe_ttm`、`pb`、`dividend_yield_ttm`、`erp`；
- `date` 为日期类型，其余数值列除 `code` 外为数字类型。

### 第 7 步：验证行数

在 Power Query 编辑器左侧选中 `Result` 查询，状态栏会显示行数；也可以在
空白查询里执行：

```m
Table.RowCount(bp_valuation)
```

（把 `bp_valuation` 换成你的查询名。）

### 第 8 步：刷新

**数据** → **全部刷新**。API 按日更新，建议每天收盘确认后刷新一次即可。
如果刷新频率较高，注意默认配额约 **60 请求/分钟**；触发 429 时请稍后重试。

---

## 3. Token 参数化（推荐）

不要把 Token 硬编码在要分发的文件里。任选一种：

### 方式 A：Power Query 参数

1. 新建一个空查询，命名为 `BpToken`，内容只有一行：

   ```m
   "bp_live_REPLACE_WITH_YOUR_TOKEN"
   ```

2. 在主查询中把：

   ```m
   Token = "bp_live_REPLACE_WITH_YOUR_TOKEN",
   ```

   改成：

   ```m
   Token = BpToken,
   ```

### 方式 B：读取工作表中的命名单元格

1. 在 Excel 中新建一张表（例如 `Config`），把 Token 放在某个单元格；
2. 选中该单元格，在名称框中命名为 `BpToken`；
3. 主查询中写：

   ```m
   Token = Excel.CurrentWorkbook(){[Name="BpToken"]}[Content]{0}[Column1],
   ```

> 分发给他人时，建议让每人使用自己的 Token，或部署到受控的刷新网关。

---

## 4. M 模板全文

```m
// bp_valuation.pq
// 用途：在 Excel Power Query 中拉取指数日频估值，保留最近 521 个交易日。
// 使用：Excel →「数据」→「获取数据」→「来自其他源」→「空查询」→「高级编辑器」，
//       粘贴本文件内容，把 Token 换成你的 bp_live_...，然后「关闭并上载」。
// 认证：Token 放在 Authorization 请求头中；Excel 询问凭据时选择「匿名」。
// 接口：GET https://xushilu.com/api/v1/index/valuation
let
    // ===== 1. 参数（按需修改） =====
    BaseUrl = "https://xushilu.com",
    Token = "bp_live_REPLACE_WITH_YOUR_TOKEN",
    IndexCode = "930641",
    FieldList = "pe_ttm,pb,dividend_yield_ttm,erp",
    TopRows = 521,
    EndDate = Date.From(DateTime.LocalNow()),
    StartDate = Date.AddYears(EndDate, -3),

    // ===== 2. 发起请求 =====
    Url = BaseUrl & "/api/v1/index/valuation",
    Query = [
        codes = IndexCode,
        start = Date.ToText(StartDate, "yyyy-MM-dd"),
        end = Date.ToText(EndDate, "yyyy-MM-dd"),
        fields = FieldList
    ],
    Response = Web.Contents(
        Url,
        [
            Headers = [
                #"Authorization" = "Bearer " & Token,
                #"Accept" = "application/json"
            ],
            Query = Query,
            ManualStatusHandling = {400, 401, 403, 404, 422, 429, 500, 502, 503, 504}
        ]
    ),

    // ===== 3. 解析统一信封 {data, meta, error} =====
    StatusCode = Value.Metadata(Response)[Response.Status],
    Raw = Text.FromBinary(Response, TextEncoding.Utf8),
    Parsed = Json.Document(Raw),
    ErrorRecord = Record.FieldOrDefault(Parsed, "error", null),
    Data =
        if ErrorRecord <> null then
            error Error.Record(
                "BpApiError",
                Record.FieldOrDefault(ErrorRecord, "message", "API 返回错误"),
                [
                    status = StatusCode,
                    code = Record.FieldOrDefault(ErrorRecord, "code", "unknown"),
                    body = Raw
                ]
            )
        else if StatusCode < 200 or StatusCode >= 300 then
            error Error.Record(
                "BpHttpError",
                "HTTP " & Text.From(StatusCode),
                [status = StatusCode, body = Raw]
            )
        else
            Record.FieldOrDefault(Parsed, "data", null),
    DataList = if Data = null then {} else Data,

    // ===== 4. JSON 数组 -> 表 =====
    ExpectedColumns = {"code", "date", "pe_ttm", "pb", "dividend_yield_ttm", "erp"},
    Expanded =
        if List.IsEmpty(DataList) then
            #table(ExpectedColumns, {})
        else
            Table.ExpandRecordColumn(
                Table.FromList(
                    DataList,
                    Splitter.SplitByNothing(),
                    null,
                    null,
                    ExtraValues.Error
                ),
                "Column1",
                ExpectedColumns
            ),
    Typed = Table.TransformColumnTypes(
        Expanded,
        {
            {"code", type text},
            {"date", type date},
            {"pe_ttm", type number},
            {"pb", type number},
            {"dividend_yield_ttm", type number},
            {"erp", type number}
        }
    ),

    // ===== 5. 取最近 521 个交易日（输出升序） =====
    SortedDesc = Table.Sort(Typed, {{"date", Order.Descending}}),
    Latest521 = Table.FirstN(SortedDesc, TopRows),
    Result = Table.Sort(Latest521, {{"date", Order.Ascending}})
in
    Result
```

---

## 5. 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `BaseUrl` | `https://xushilu.com` | API 主域名，不要带 `/api/v1` |
| `Token` | 占位符 | `bp_live_...`，需要 `valuation` scope |
| `IndexCode` | `930641` | 指数代码；多个代码可用逗号分隔，如 `"930641,000300"` |
| `FieldList` | 四个估值字段 | 可选 `pe_ttm`、`pb`、`dividend_yield_ttm`、`erp` |
| `TopRows` | `521` | 最终保留的最新交易日数量 |
| `EndDate` | 今天 | 自动取 `DateTime.LocalNow()` 的日期 |
| `StartDate` | 3 年前 | 用于限制请求量；再从中截取最近 521 行 |

> 若把 `IndexCode` 改成多个代码，最终仍是「全部代码合计最近 521 行」。
> 如需每个代码各取 521 行，请把查询按 `code` 分组后分别 `Table.FirstN`。

---

## 6. 输出列

| 列名 | 类型 | 说明 |
|---|---|---|
| `code` | 文本 | 指数代码 |
| `date` | 日期 | 交易日（ISO `YYYY-MM-DD`） |
| `pe_ttm` | 数字 | 滚动市盈率 |
| `pb` | 数字 | 市净率 |
| `dividend_yield_ttm` | 数字 | 滚动股息率 |
| `erp` | 数字 | 股权风险溢价 |

---

## 7. 常见错误

| 现象 | 原因 / 处理 |
|---|---|
| 401 `unauthorized` | Token 缺失、错误、过期或已撤销；重新签发并替换 `Token` |
| 403 `forbidden` | Token 缺少 `valuation` scope；让管理员补 scope |
| 404 `unknown_code` | 指数代码不存在；检查 `IndexCode` |
| 422 `invalid_date` / `invalid_range` | 日期不是 `YYYY-MM-DD`，或 `start > end` |
| 429 限频 | 默认约 60 请求/分钟；等待后重试。Power Query 不会自动重试 |
| 5xx | 服务端临时错误；稍后刷新 |
| `DataSource.Error` + 401 | 凭据类型不是「匿名」，或 Token 失效 |
| `Formula.Firewall` | 忽略隐私级别，或把 `https://xushilu.com` 的隐私级别设为「无」 |
| 结果为空表 | 代码/日期区间内无数据；先放宽日期范围验证 |
| 某列不存在 | API 返回字段与 `ExpectedColumns` 不一致；同步修改展开列 |

> 错误码含义见仓库根目录 `docs/API.md` 第 6 节。不要依赖错误 message 文本。

---

## 8. 可选：CSV 模式

接口支持 `?format=csv`（UTF-8 BOM）。CSV 不带 JSON 信封，适合大体量下载，
但错误响应仍是 JSON，所以下面的查询只适合成功路径：

```m
let
    Token = "bp_live_REPLACE_WITH_YOUR_TOKEN",
    Response = Web.Contents(
        "https://xushilu.com/api/v1/index/valuation",
        [
            Headers = [#"Authorization" = "Bearer " & Token],
            Query = [
                codes = "930641",
                start = "2022-01-01",
                end = "2024-12-31",
                fields = "pe_ttm,pb",
                #"format" = "csv"
            ],
            ManualStatusHandling = {400, 401, 403, 404, 422, 429, 500, 502, 503, 504}
        ]
    ),
    Csv = Csv.Document(
        Response,
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(
        Promoted,
        {{"date", type date}, {"pe_ttm", type number}, {"pb", type number}}
    )
in
    Typed
```

> 日常使用建议保持默认 JSON 模式，以便统一处理 401/403/429 等错误。

---

## 9. 安全建议

- 不要把含 Token 的工作簿上传到公共网盘或提交到 git；
- 为 Excel 单独签发一个只含 `valuation` scope 的 Token，便于审计和撤销；
- Token 泄露后立即让管理员撤销并重新签发；
- 大批量历史数据优先缩小日期范围，而不是反复刷新被截断的结果。
