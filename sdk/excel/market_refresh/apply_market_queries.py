# -*- coding: utf-8 -*-
"""给 Investment.xlsx 注入 Power Query 行情查询与 XLOOKUP 公式（COM 自动化）。"""
import os, sys, time, shutil
import win32com.client as win32

TOKEN = ""  # 运行时从 --token 或环境变量 BP_EXCEL_TOKEN 读取
BASE_URL = "https://xushilu.com"
FILE = sys.argv[1]

M_LAST = '''let
    Config = Excel.CurrentWorkbook(){[Name="BpConfig"]}[Content],
    BaseUrl = Config{0}[Value],
    Token = Config{1}[Value],
    Holdings = Excel.CurrentWorkbook(){[Name="持仓"]}[Content],
    Codes = List.Distinct(List.Transform(Table.Column(Holdings, "代码"), each Text.From(_))),
    Param = Text.Combine(Codes, ","),
    Resp = Web.Contents(BaseUrl & "/api/v1/market/last", [Headers=[#"Authorization"="Bearer " & Token, #"Accept"="application/json"], Query=[codes=Param, adjust="bfq"], ManualStatusHandling={400,401,403,404,422,429,500,502,503,504}]),
    Json = Json.Document(Resp),
    Data = Json[data],
    Table0 = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(Table0, "Column1", {"code","market","currency","kind","name","date","close","prev_close","pct","adjust","source","status"}),
    WithRaw = Table.AddColumn(Expanded, "code_raw", each Text.BeforeDelimiter([code], ".")),
    Reordered = Table.ReorderColumns(WithRaw, {"code_raw","code","market","currency","kind","name","date","close","prev_close","pct","adjust","source","status"}),
    Typed = Table.TransformColumnTypes(Reordered, {{"date", type date}, {"close", type number}, {"prev_close", type number}, {"pct", type number}}),
    NonEmpty = Table.SelectRows(Typed, each [close] <> null)
in
    NonEmpty'''

M_FX = '''let
    Config = Excel.CurrentWorkbook(){[Name="BpConfig"]}[Content],
    BaseUrl = Config{0}[Value],
    Token = Config{1}[Value],
    Resp = Web.Contents(BaseUrl & "/api/v1/market/fx", [Headers=[#"Authorization"="Bearer " & Token, #"Accept"="application/json"], Query=[pairs="USD/CNY,HKD/CNY,USD/HKD,USD/SGD"], ManualStatusHandling={400,401,403,404,422,429,500,502,503,504}]),
    Json = Json.Document(Resp),
    Data = Json[data],
    Table0 = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(Table0, "Column1", {"pair","base","quote","date","price","source"}),
    Typed = Table.TransformColumnTypes(Expanded, {{"date", type date}, {"price", type number}})
in
    Typed'''


def get_sheet(wb, name):
    try:
        return wb.Worksheets(name)
    except Exception:
        return None


def drop_sheet(wb, name):
    ws = get_sheet(wb, name)
    if ws is not None:
        ws.Visible = -1
        ws.Delete()


def drop_query(wb, name):
    try:
        wb.Queries(name).Delete()
    except Exception:
        pass


def add_query_table(wb, sheet_name, query_name, m_code):
    """建隐藏数据表 + QueryTable 绑定 Power Query，刷新后隐藏。"""
    drop_sheet(wb, sheet_name)
    drop_query(wb, query_name)
    q = wb.Queries.Add(query_name, m_code, "balanced-portfolio " + query_name)
    ws = wb.Worksheets.Add()
    ws.Name = sheet_name
    conn = "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location=" + query_name + ';Extended Properties=""'
    qt = ws.QueryTables.Add(Connection=conn, Destination=ws.Range("A1"))
    qt.CommandType = 2  # xlCmdSql
    qt.CommandText = ["SELECT * FROM [" + query_name + "]"]
    qt.BackgroundQuery = False
    qt.Name = query_name + "_qt"
    qt.Refresh(False)
    qt.RefreshOnFileOpen = True
    qt.EnableRefresh = True
    qt.SaveData = True
    qt.PreserveFormatting = True
    qt.RefreshPeriod = 0
    # 连接级"打开文件时刷新"
    try:
        for i in range(1, wb.Connections.Count + 1):
            c = wb.Connections(i)
            try:
                if c.Type == 1:
                    c.OLEDBConnection.RefreshOnFileOpen = True
                    c.OLEDBConnection.BackgroundQuery = False
            except Exception:
                pass
    except Exception:
        pass
    return ws, qt


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    file_path = args[0]
    attach = "--attach" in flags
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
    backup_path = None
    for flag in flags:
        if flag.startswith("--backup="):
            backup_path = flag.split("=", 1)[1]
    if attach:
        app = win32.GetActiveObject("Excel.Application")
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        target = os.path.normcase(os.path.abspath(file_path))
        base_name = os.path.basename(file_path).lower()
        wb = None
        for i in range(1, app.Workbooks.Count + 1):
            candidate = app.Workbooks(i)
            full = str(candidate.FullName or "")
            if os.path.normcase(os.path.abspath(full)) == target or candidate.Name.lower() == base_name:
                wb = candidate
                break
        if wb is None:
            raise SystemExit("workbook not open in Excel: " + file_path)
        if not wb.Saved:
            wb.Save()
    else:
        app = win32.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        wb = app.Workbooks.Open(file_path)
    if backup_path:
        wb.SaveCopyAs(backup_path)
        print("backup written:", backup_path)
    try:
        print("sheets:", [wb.Worksheets(i).Name for i in range(1, wb.Worksheets.Count + 1)])
        # 关闭隐私级别合并检查（工作簿级；等效于 数据→查询选项→隐私→忽略隐私级别）
        try:
            wb.Queries.FastCombine = True
            print("FastCombine:", wb.Queries.FastCombine)
        except Exception as exc:
            print("FastCombine unavailable:", str(exc)[:200])

        # 1) 隐藏配置表 BpConfig（BaseUrl / Token）
        drop_sheet(wb, "BP_Config")
        cfg = wb.Worksheets.Add()
        cfg.Name = "BP_Config"
        cfg.Range("A1").Value = "Key"
        cfg.Range("B1").Value = "Value"
        cfg.Range("A2").Value = "BaseUrl"
        cfg.Range("B2").Value = BASE_URL
        cfg.Range("A3").Value = "Token"
        cfg.Range("B3").Value = TOKEN
        cfg.Range("A1:B3").Font.Bold = False
        lo_cfg = cfg.ListObjects.Add(1, cfg.Range("A1:B3"), None, 1)
        lo_cfg.Name = "BpConfig"
        print("config table:", cfg.ListObjects(1).Name)

        # 2) 两个 Power Query 数据表
        add_query_table(wb, "BP_Quotes", "bp_market_last", M_LAST)
        add_query_table(wb, "BP_FX", "bp_fx", M_FX)
        print("quotes header:", [wb.Worksheets("BP_Quotes").Cells(1, c).Value for c in range(1, 14)])
        print("fx header:", [wb.Worksheets("BP_FX").Cells(1, c).Value for c in range(1, 7)])

        # 3) 持仓表：行情日期列 + 现价 XLOOKUP
        hold = wb.Worksheets("持仓")
        lo = hold.ListObjects("持仓")
        headers = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]
        print("holdings headers:", headers)
        if "行情日期" not in headers:
            col = lo.ListColumns.Add()
            col.Name = "行情日期"
        col_map = {lo.ListColumns(i).Name: i for i in range(1, lo.ListColumns.Count + 1)}
        code_col = col_map["代码"]
        price_col = col_map["现价"]
        date_col = col_map["行情日期"]
        first_row = lo.Range.Row + 1
        for offset in range(lo.ListRows.Count):
            r = first_row + offset
            hold.Cells(r, price_col).Formula = '=IFERROR(XLOOKUP($B%d,BP_Quotes!$A$2:$A$201,BP_Quotes!$H$2:$H$201),"")' % r
            hold.Cells(r, date_col).Formula = '=IFERROR(XLOOKUP($B%d,BP_Quotes!$A$2:$A$201,BP_Quotes!$G$2:$G$201),"")' % r
        # 缺行情时 H..L 不应变成 #VALUE!（保留空白，汇总 SUBTOTAL 会忽略）
        for offset in range(lo.ListRows.Count):
            r = first_row + offset
            hold.Cells(r, 8).Formula = '=IFERROR($E%d*$G%d,"")' % (r, r)
            hold.Cells(r, 9).Formula = '=IFERROR(IF($D%d="HKD",$H%d*Accounts!$J$5,$H%d),"")' % (r, r, r)
            hold.Cells(r, 10).Formula = '=IFERROR($G%d/$F%d-1,"")' % (r, r)
            hold.Cells(r, 11).Formula = '=IFERROR(($G%d-$F%d)*$E%d,"")' % (r, r, r)
            hold.Cells(r, 12).Formula = '=IFERROR(IF($D%d="HKD",$K%d*Accounts!$J$5,$K%d),"")' % (r, r, r)
            hold.Cells(r, price_col).NumberFormat = "0.000"
            hold.Cells(r, date_col).NumberFormat = "yyyy-mm-dd"
        print("holdings formulas set; G2=", hold.Cells(first_row, price_col).Formula)

        # 4) Accounts Forex：修好币种对 + 价格/日期 XLOOKUP
        acc = wb.Worksheets("Accounts")
        forex = None
        for i in range(1, acc.ListObjects.Count + 1):
            if acc.ListObjects(i).Name == "Forex":
                forex = acc.ListObjects(i)
        if forex is None:
            raise RuntimeError("Forex 表未找到")
        pairs = ["USD/SGD", "USD/HKD", "USD/CNY", "HKD/CNY"]
        for idx, pair in enumerate(pairs):
            cell = acc.Range("I%d" % (2 + idx))
            cell.ClearContents()
            cell.Value2 = pair
            acc.Range("J%d" % (2 + idx)).Formula = '=IFERROR(XLOOKUP($I%d,BP_FX!$A$2:$A$20,BP_FX!$E$2:$E$20),"")' % (2 + idx)
            acc.Range("K%d" % (2 + idx)).Formula = '=IFERROR(XLOOKUP($I%d,BP_FX!$A$2:$A$20,BP_FX!$D$2:$D$20),"")' % (2 + idx)
        # 扩展 Forex 表到 K 列并加表头
        if forex.ListColumns.Count < 3:
            acc.Range("K1").Value = "日期"
            forex.Resize(acc.Range("I1:K5"))
        print("forex:", [acc.Range("I%d" % i).Value for i in range(2, 6)], [acc.Range("J%d" % i).Value for i in range(2, 6)])

        # 5) 条件格式：数据日期落后于本表最新日期时高亮现价（陈旧提醒）
        last_row = first_row + lo.ListRows.Count - 1
        price_range = hold.Range("G%d:G%d" % (first_row, last_row))
        price_range.FormatConditions.Delete()
        stale = price_range.FormatConditions.Add(2, None, '=$M%d<MAX($M$%d:$M$%d)' % (first_row, first_row, last_row))
        stale.Interior.Color = 0x00A5FF  # 橙
        stale.Font.Bold = True
        hold.Range("A%d" % (last_row + 2)).Value = (
            "说明：现价/行情日期由 Power Query 自动刷新（数据源 balanced-portfolio，不复权收盘价）；"
            "打开工作簿即刷新，也可按 Ctrl+Alt+F5 手动刷新。"
        )
        hold.Range("A%d" % (last_row + 2)).Font.Italic = True
        hold.Range("A%d" % (last_row + 2)).Font.Color = 0x808080

        # 6) 计算 + 隐藏数据/配置表
        app.CalculateFullRebuild()
        for name in ("BP_Config", "BP_Quotes", "BP_FX"):
            wb.Worksheets(name).Visible = 0
        wb.Worksheets("持仓").Activate()
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
