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
