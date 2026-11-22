# -*- coding: utf-8 -*-
"""B 期：BP_行情 工作表（10Y 国债收益率 + 宽基指数 PE/PB/股息率/ERP + 5 年分位）。"""
import os, sys
import win32com.client as win32

TOKEN = ""  # 运行时从 --token 或环境变量 BP_EXCEL_TOKEN 读取
BASE_URL = "https://xushilu.com"

M_BOND = '''let
    Config = Excel.CurrentWorkbook(){[Name="BpConfig"]}[Content],
    BaseUrl = Config{0}[Value],
    Token = Config{1}[Value],
    Resp = Web.Contents(BaseUrl & "/api/v1/market/bond-yield", [Headers=[#"Authorization"="Bearer " & Token, #"Accept"="application/json"], ManualStatusHandling={400,401,403,404,422,429,500,502,503,504}]),
    Json = Json.Document(Resp),
    Data = Json[data],
    T = if List.IsEmpty(Data) then #table({"date","value","unit","source"}, {}) else Table.FromRecords(Data),
    Typed = Table.TransformColumnTypes(T, {{"date", type date}, {"value", type number}}),
    Sorted = Table.Sort(Typed, {{"date", Order.Descending}}),
    Latest = Table.FirstN(Sorted, 1)
in
    Latest'''

M_VALUATION = '''let
    Config = Excel.CurrentWorkbook(){[Name="BpConfig"]}[Content],
    BaseUrl = Config{0}[Value],
    Token = Config{1}[Value],
    Codes = "000300,930641,000905,000016",
    Now = Date.From(DateTime.LocalNow()),
    StartDate = Date.ToText(Date.AddYears(Now, -1), "yyyy-MM-dd"),
    EndDate = Date.ToText(Now, "yyyy-MM-dd"),
    Headers = [#"Authorization"="Bearer " & Token, #"Accept"="application/json"],
    ValResp = Web.Contents(BaseUrl & "/api/v1/index/valuation", [Headers=Headers, Query=[codes=Codes, start=StartDate, end=EndDate, fields="pe_ttm,pb,dividend_yield_ttm,erp"], ManualStatusHandling={400,401,403,404,422,429,500,502,503,504}]),
    ValData = Json.Document(ValResp)[data],
    ValT = Table.FromRecords(ValData),
    ValTyped = Table.TransformColumnTypes(ValT, {{"date", type date}}),
    Grouped = Table.Group(ValTyped, {"code"}, {{"rows", each Table.FirstN(Table.Sort(_, {{"date", Order.Descending}}), 1)}}),
    Latest = Table.ExpandTableColumn(Grouped, "rows", {"date", "pe_ttm", "pb", "dividend_yield_ttm", "erp"}),
    PctResp = Web.Contents(BaseUrl & "/api/v1/index/percentile", [Headers=Headers, Query=[codes=Codes, metrics="pe_ttm,pb", windows="5y"], ManualStatusHandling={400,401,403,404,422,429,500,502,503,504}]),
    PctData = Json.Document(PctResp)[data],
    PctT = Table.FromRecords(PctData),
    Pct5 = Table.SelectRows(PctT, each [window] = "5y"),
    PctSorted = Table.Sort(Pct5, {{"as_of", Order.Descending}}),
    PctDedup = Table.Distinct(PctSorted, {"code", "metric"}),
    PctSmall = Table.SelectColumns(PctDedup, {"code", "metric", "pct"}),
    PctWide = Table.Pivot(PctSmall, List.Distinct(PctSmall[metric]), "metric", "pct", each List.First(_)),
    PctA = Table.AddColumn(PctWide, "pe_pct_5y", each Record.FieldOrDefault(_, "pe_ttm", null)),
    PctB = Table.AddColumn(PctA, "pb_pct_5y", each Record.FieldOrDefault(_, "pb", null)),
    PctRenamed = Table.SelectColumns(PctB, {"code", "pe_pct_5y", "pb_pct_5y"}),
    PctJoined = Table.NestedJoin(Latest, {"code"}, PctRenamed, {"code"}, "pct", JoinKind.LeftOuter),
    PctFlat = Table.ExpandTableColumn(PctJoined, "pct", {"pe_pct_5y", "pb_pct_5y"}),
    Names = #table({"code", "name"}, {{"000300", "沪深300"}, {"930641", "中证A500"}, {"000905", "中证500"}, {"000016", "上证50"}}),
    NameJoined = Table.NestedJoin(PctFlat, {"code"}, Names, {"code"}, "nm", JoinKind.LeftOuter),
    WithNames = Table.ExpandTableColumn(NameJoined, "nm", {"name"}),
    Result = Table.SelectColumns(WithNames, {"code", "name", "date", "pe_ttm", "pb", "dividend_yield_ttm", "erp", "pe_pct_5y", "pb_pct_5y"}),
    Sorted = Table.Sort(Result, {{"code", Order.Ascending}})
in
    Sorted'''


def drop_sheet(wb, name):
    try:
        ws = wb.Worksheets(name)
        ws.Visible = -1
        ws.Delete()
    except Exception:
        pass


def drop_query(wb, name):
    try:
        wb.Queries(name).Delete()
    except Exception:
        pass


def add_qt(wb, ws, query_name, m_code, cell):
    drop_query(wb, query_name)
    wb.Queries.Add(query_name, m_code, "balanced-portfolio " + query_name)
    conn = "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location=" + query_name + ';Extended Properties=""'
    qt = ws.QueryTables.Add(Connection=conn, Destination=ws.Range(cell))
    qt.CommandType = 2
    qt.CommandText = ["SELECT * FROM [" + query_name + "]"]
    qt.BackgroundQuery = False
    qt.Name = query_name + "_qt"
    qt.Refresh(False)
    qt.RefreshOnFileOpen = True
    qt.EnableRefresh = True
    qt.SaveData = True
    qt.RefreshPeriod = 0
    return qt


def main():
    path = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    attach = "--attach" in sys.argv
    global TOKEN, BASE_URL
    token = None
    base_url = "https://xushilu.com"
    for extra in sys.argv[1:]:
        if extra.startswith("--token="):
            token = extra.split("=", 1)[1]
        elif extra.startswith("--base-url="):
            base_url = extra.split("=", 1)[1]
    TOKEN = token or os.environ.get("BP_EXCEL_TOKEN", "").strip()
    if not TOKEN:
        raise SystemExit("缺少 API token：传 --token=bp_live_... 或设置环境变量 BP_EXCEL_TOKEN")
    BASE_URL = base_url.rstrip("/")
    if attach:
        app = win32.GetActiveObject("Excel.Application")
        app.DisplayAlerts = False
        wb = None
        for i in range(1, app.Workbooks.Count + 1):
            if app.Workbooks(i).Name.lower() == os.path.basename(path).lower():
                wb = app.Workbooks(i)
        if wb is None:
            raise SystemExit("workbook not open")
    else:
        app = win32.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(path)
    try:
        wb.Queries.FastCombine = True
        drop_sheet(wb, "BP_行情")
        ws = wb.Worksheets.Add()
        ws.Name = "BP_行情"
        ws.Range("A1").Value = "Balanced Portfolio · 行情与估值（Power Query 自动刷新）"
        ws.Range("A1").Font.Bold = True
        ws.Range("A1").Font.Size = 14
        ws.Range("A3").Value = "一、宏观指标"
        ws.Range("A3").Font.Bold = True
        bond = add_qt(wb, ws, "bp_bond_yield", M_BOND, "A4")
        ws.Range("A7").Value = "二、宽基指数估值（最新值 + 5 年分位）"
        ws.Range("A7").Font.Bold = True
        val = add_qt(wb, ws, "bp_index_valuation", M_VALUATION, "A8")
        # 数字格式
        ws.Range("B5:B5").NumberFormat = "0.0000"
        ws.Range("D9:E12").NumberFormat = "0.00"
        ws.Range("F9:G12").NumberFormat = '0.00"%"'
        ws.Range("H9:I12").NumberFormat = '0.00"%"'
        ws.Range("C9:C12").NumberFormat = "yyyy-mm-dd"
        ws.Columns("A").ColumnWidth = 12
        ws.Columns("B").ColumnWidth = 12
        ws.Columns("C").ColumnWidth = 12
        ws.Columns("D:I").ColumnWidth = 12
        ws.Range("A15").Value = "说明：债券收益率为 10Y 国债到期收益率（单位见 unit 列）；分位为近 5 年窗口、0~100% 口径。"
        ws.Range("A15").Font.Italic = True
        ws.Range("A15").Font.Color = 0x808080
        ws.Rows("5").RowHeight = 20
        ws.Range("A4").Select()
        app.CalculateFullRebuild()
        wb.Save()
        print("SAVED")
    finally:
        if not attach:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
            try:
                app.Quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
