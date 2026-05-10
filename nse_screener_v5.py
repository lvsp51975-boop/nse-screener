"""
NSE EMA 9/21 Crossover + Fundamental Screener v5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEATURES:
  - EMA 9/21 crossover on NSE 500 stocks
  - Fundamental filters (ROE, D/E, Promoter, PE, Margin, RevGrowth)
  - Entry, Stop Loss, TP1, TP2 (ATR-based)
  - Auto Email every 1 hr (Gmail)
  - Auto Telegram message every 1 hr (FREE)
  - HTML dashboard + CSV output

TELEGRAM SETUP (one time - FREE):
  1. Open Telegram app on phone
  2. Search: @BotFather → click Start
  3. Send: /newbot
  4. Give name: NSEScreener
  5. Give username: nse_screener_mybot (must end in 'bot')
  6. Copy the TOKEN shown (looks like: 7123456789:AAHxxx...)
  7. Now search: @userinfobot → click Start → it shows your Chat ID
  8. Paste TOKEN and CHAT_ID below

EMAIL SETUP (one time):
  1. Go to https://myaccount.google.com/apppasswords
  2. Create App Password → name it NSEScreener
  3. Paste 16-char password below

INSTALL:
  pip install yfinance pandas numpy schedule requests beautifulsoup4 lxml

RUN:
  python nse_screener_v5.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import schedule
import time
import datetime
import sys
import requests
import warnings
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════
#   ★  EDIT THESE 4 LINES ONLY  ★
# ════════════════════════════════════════════════

EMAIL_APP_PASSWORD  = "itya xzhd gsxe icve"   # Gmail App Password
TELEGRAM_TOKEN      = "8698605766:AAGuLAeqe4UpIW1l9vrolnOyS-iTMg5pGjo"   # From @BotFather
TELEGRAM_CHAT_ID    = "2008289132"     # From @userinfobot

# ════════════════════════════════════════════════

# Email config
EMAIL_ENABLED   = True
EMAIL_TO        = "lvsp51975@gmail.com"
EMAIL_FROM      = "lvsp51975@gmail.com"

# Telegram config
TELEGRAM_ENABLED = True

# Screener config
REFRESH_MINUTES = 60
OUTPUT_CSV      = "nse_results.csv"
OUTPUT_HTML     = "nse_results.html"
EMA_FAST        = 9
EMA_SLOW        = 21
ATR_PERIOD      = 14
PRICE_PERIOD    = "90d"
BATCH_SIZE      = 10
SL_ATR_MULT     = 1.5
TP1_RR          = 1.5
TP2_RR          = 3.0
SL_SWING_BARS   = 5

# Fundamental filters
F = {
    "roe_min":       0.15,
    "de_max":        50,
    "promoter_min":  50,
    "pe_max_factor": 1.0,
    "profit_margin": 0.08,
    "rev_growth":    0.10,
}

SECTOR_PE = {
    "Technology":         28,
    "Financial Services": 18,
    "Consumer Defensive": 45,
    "Healthcare":         25,
    "Basic Materials":    12,
    "Energy":             12,
    "Industrials":        25,
    "Consumer Cyclical":  30,
    "Real Estate":        30,
    "Communication":      25,
    "Utilities":          18,
}

# ─── SYMBOL LIST ─────────────────────────────────────────────────────────────
def get_nse500_symbols():
    print("  Downloading NSE 500 list...")
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        col = [c for c in df.columns if "symbol" in c.lower()][0]
        symbols = [f"{s.strip()}.NS" for s in df[col].dropna().tolist()]
        print(f"  ✓ Loaded {len(symbols)} NSE 500 stocks")
        return symbols
    except Exception as e:
        print(f"  [!] NSE list failed: {e} — using fallback 50")
        return get_fallback_symbols()

def get_fallback_symbols():
    syms = [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
        "SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI",
        "TITAN","BAJFINANCE","WIPRO","HCLTECH","ULTRATECH","NESTLEIND",
        "POWERGRID","NTPC","ONGC","JSWSTEEL","TATASTEEL","TATAMOTORS",
        "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","BAJAJFINSV","ADANIENT",
        "ADANIPORTS","HINDALCO","COALINDIA","TECHM","GRASIM","INDUSINDBK",
        "EICHERMOT","HEROMOTOCO","BPCL","VEDL","SHREECEM","PIDILITIND",
        "DABUR","MARICO","BRITANNIA","HAVELLS","MUTHOOTFIN","CHOLAFIN"
    ]
    return [f"{s}.NS" for s in syms]

# ─── ATR ─────────────────────────────────────────────────────────────────────
def calc_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

# ─── TRADE LEVELS ────────────────────────────────────────────────────────────
def calc_trade_levels(df, close_price):
    try:
        atr_val   = float(calc_atr(df, ATR_PERIOD).iloc[-1])
        swing_sl  = float(df["Low"].iloc[-(SL_SWING_BARS+1):-1].min())
        atr_sl    = close_price - (SL_ATR_MULT * atr_val)
        sl        = max(swing_sl, atr_sl)
        if sl >= close_price:
            sl = close_price - (SL_ATR_MULT * atr_val)
        risk    = close_price - sl
        tp1     = close_price + (risk * TP1_RR)
        tp2     = close_price + (risk * TP2_RR)
        return {
            "entry":    round(close_price, 2),
            "sl":       round(sl, 2),
            "tp1":      round(tp1, 2),
            "tp2":      round(tp2, 2),
            "atr":      round(atr_val, 2),
            "risk_pct": round((risk / close_price) * 100, 2),
            "tp1_pct":  round(((tp1 - close_price) / close_price) * 100, 2),
            "tp2_pct":  round(((tp2 - close_price) / close_price) * 100, 2),
            "rr1": TP1_RR, "rr2": TP2_RR,
        }
    except:
        return {"entry": round(close_price,2), "sl":None,"tp1":None,"tp2":None,
                "atr":None,"risk_pct":None,"tp1_pct":None,"tp2_pct":None,
                "rr1":TP1_RR,"rr2":TP2_RR}

# ─── EMA CROSSOVER ───────────────────────────────────────────────────────────
def calc_ema_crossover(symbols):
    print(f"\n  Calculating EMA {EMA_FAST}/{EMA_SLOW} crossovers...")
    crossover_stocks = []
    batches = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]

    for idx, batch in enumerate(batches):
        try:
            raw = yf.download(batch, period=PRICE_PERIOD, interval="1d",
                              group_by="ticker", auto_adjust=True,
                              progress=False, threads=True, timeout=30)
        except:
            continue

        print(f"    EMA scan: {int((idx+1)/len(batches)*100)}%...", end="\r")

        for sym in batch:
            try:
                df = raw if len(batch)==1 else (
                    raw[sym] if sym in raw.columns.get_level_values(0) else None)
                if df is None or len(df) < EMA_SLOW + ATR_PERIOD + 5:
                    continue
                close    = df["Close"].dropna()
                ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
                ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
                if (ema_fast.iloc[-1] > ema_slow.iloc[-1] and
                    ema_fast.iloc[-2] < ema_slow.iloc[-2]):
                    cp = float(close.iloc[-1])
                    crossover_stocks.append({
                        "symbol_yf": sym,
                        "symbol":    sym.replace(".NS",""),
                        "close":     round(cp, 2),
                        "ema9":      round(float(ema_fast.iloc[-1]), 2),
                        "ema21":     round(float(ema_slow.iloc[-1]), 2),
                        **calc_trade_levels(df, cp),
                    })
            except:
                continue
        time.sleep(0.3)

    print(f"\n  ✓ EMA crossover stocks: {len(crossover_stocks)}")
    return crossover_stocks

# ─── FUNDAMENTALS ────────────────────────────────────────────────────────────
def get_fundamentals(stock):
    try:
        info    = yf.Ticker(stock["symbol_yf"]).info
        roe     = info.get("returnOnEquity")
        de      = info.get("debtToEquity")
        margin  = info.get("profitMargins")
        rev_g   = info.get("revenueGrowth")
        insider = info.get("heldPercentInsiders")
        sector  = info.get("sector","Unknown")
        return {
            **stock,
            "name":         info.get("longName", stock["symbol_yf"]),
            "sector":       sector,
            "pe":           info.get("trailingPE"),
            "roe_pct":      round(roe*100,1)    if roe     else None,
            "de_ratio":     round(de/100,2)      if de      else None,
            "net_margin":   round(margin*100,1)  if margin  else None,
            "rev_growth":   round(rev_g*100,1)   if rev_g   else None,
            "promoter_pct": round(insider*100,1) if insider else None,
            "sector_pe":    SECTOR_PE.get(sector, 25),
            "raw_roe":roe,"raw_de":de,"raw_margin":margin,
            "raw_rev_g":rev_g,"raw_insider":insider,
        }
    except Exception as e:
        return {**stock, "error": str(e)}

# ─── FILTERS ─────────────────────────────────────────────────────────────────
def apply_filters(stocks):
    passed = []
    for d in stocks:
        if "error" in d: continue
        checks = {
            "ROE>15%":      (d.get("raw_roe")     is not None and d["raw_roe"]    > F["roe_min"]),
            "D/E<0.5":      (d.get("raw_de")      is not None and d["raw_de"]     < F["de_max"]),
            "Promoter>50%": (d.get("raw_insider") is not None and d["raw_insider"]*100 > F["promoter_min"]),
            "PE<SectorPE":  (d.get("pe")          is not None and d["pe"]>0 and d["pe"] < d.get("sector_pe",25)),
            "Margin>8%":    (d.get("raw_margin")  is not None and d["raw_margin"] > F["profit_margin"]),
            "RevGrowth>10%":(d.get("raw_rev_g")   is not None and d["raw_rev_g"]  > F["rev_growth"]),
        }
        d["checks"]       = checks
        d["pass_count"]   = sum(checks.values())
        d["total_checks"] = len(checks)
        if d["pass_count"] >= 4:
            passed.append(d)
    passed.sort(key=lambda x: x["pass_count"], reverse=True)
    return passed

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def fmt(v, dec=2):
    return f"{v:.{dec}f}" if v is not None else "N/A"

# ─── TELEGRAM SENDER ─────────────────────────────────────────────────────────
def send_telegram(results, scanned, crossover_count):
    """Send Telegram message with scan results."""
    if not TELEGRAM_ENABLED:
        return
    if False:
        print("  [!] Telegram skipped — paste BOT TOKEN in TELEGRAM_TOKEN")
        return
    if TELEGRAM_CHAT_ID == "DISABLED":
        print("  [!] Telegram skipped — paste CHAT ID in TELEGRAM_CHAT_ID")
        return

    timestamp = now()

    if results:
        lines = []
        for d in results:
            score = f"{d['pass_count']}/{d['total_checks']}"
            lines.append(
                f"📊 *{d.get('symbol')}* | Score: {score}\n"
                f"   🟢 Entry: ₹{fmt(d.get('entry'))}\n"
                f"   🔴 SL:    ₹{fmt(d.get('sl'))} (-{fmt(d.get('risk_pct'))}%)\n"
                f"   🎯 TP1:   ₹{fmt(d.get('tp1'))} (+{fmt(d.get('tp1_pct'))}%)\n"
                f"   🎯 TP2:   ₹{fmt(d.get('tp2'))} (+{fmt(d.get('tp2_pct'))}%)\n"
                f"   ROE:{fmt(d.get('roe_pct'),1)}% | D/E:{fmt(d.get('de_ratio'),2)} | PE:{fmt(d.get('pe'),1)}"
            )
        stocks_text = "\n\n".join(lines)
        msg = (
            f"⚡ *NSE EMA 9/21 SCREENER*\n"
            f"🕐 {timestamp}\n"
            f"Universe: {scanned} | Crossovers: {crossover_count} | ✅ Passed: {len(results)}\n\n"
            f"{stocks_text}\n\n"
            f"_SL=Swing/ATR | TP1=1.5R | TP2=3.0R_\n"
            f"_⚠️ Not financial advice_"
        )
    else:
        msg = (
            f"⚡ *NSE EMA 9/21 SCREENER*\n"
            f"🕐 {timestamp}\n"
            f"Universe: {scanned} | Crossovers: {crossover_count}\n\n"
            f"❌ No stocks passed filters this scan.\n"
            f"_Market may be flat or closed._"
        )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       msg,
            "parse_mode": "Markdown"
        }, timeout=30, proxies={"http":None,"https":None})
        if resp.status_code == 200:
            print(f"  📱 Telegram sent!")
        else:
            print(f"  [!] Telegram failed: {resp.text}")
    except Exception as e:
        print(f"  [!] Telegram error: {e}")

# ─── EMAIL SENDER ────────────────────────────────────────────────────────────
def send_email(results, scanned, crossover_count):
    """Send HTML email with scan results."""
    if not EMAIL_ENABLED:
        return
    if False:
        print("  [!] Email skipped — paste Gmail App Password in EMAIL_APP_PASSWORD")
        return

    timestamp = now()
    if results:
        rows_html = ""
        for d in results:
            score = f"{d['pass_count']}/{d['total_checks']}"
            rows_html += f"""
            <tr>
              <td><b>{d.get('symbol','')}</b></td>
              <td>{d.get('name','')[:20]}</td>
              <td>{d.get('sector','')[:15]}</td>
              <td style='color:#4499ff'>₹{fmt(d.get('entry'))}</td>
              <td style='color:#ff5566'>₹{fmt(d.get('sl'))}<br><small>-{fmt(d.get('risk_pct'))}%</small></td>
              <td style='color:#00cc66'>₹{fmt(d.get('tp1'))}<br><small>+{fmt(d.get('tp1_pct'))}%</small></td>
              <td style='color:#00cc66'>₹{fmt(d.get('tp2'))}<br><small>+{fmt(d.get('tp2_pct'))}%</small></td>
              <td>{fmt(d.get('roe_pct'),1)}%</td>
              <td>{fmt(d.get('de_ratio'),2)}</td>
              <td>{fmt(d.get('pe'),1)}</td>
              <td style='color:#ffaa00'>{score}</td>
            </tr>"""
        table_html = f"""
        <table border='1' cellpadding='8' cellspacing='0'
               style='border-collapse:collapse;font-family:monospace;font-size:12px;width:100%'>
          <thead style='background:#1a2040;color:#4488cc'>
            <tr><th>SYMBOL</th><th>NAME</th><th>SECTOR</th>
            <th>ENTRY</th><th>STOP LOSS</th><th>TARGET 1</th><th>TARGET 2</th>
            <th>ROE%</th><th>D/E</th><th>P/E</th><th>SCORE</th></tr>
          </thead>
          <tbody style='background:#0a0f1a;color:#c8d0e0'>{rows_html}</tbody>
        </table>"""
        note = f"<p style='color:#00ff88;font-size:14px'>✅ {len(results)} stock(s) passed all filters!</p>"
    else:
        table_html = ""
        note = "<p style='color:#ff5566'>❌ No stocks passed filters this scan.</p>"

    html_body = f"""
    <html><body style='background:#060810;color:#c8d0e0;font-family:monospace;padding:20px'>
      <h2 style='color:#00e5ff'>⚡ NSE EMA 9/21 Screener — {timestamp}</h2>
      <p>Universe: <b>{scanned}</b> | EMA Crossovers: <b>{crossover_count}</b> | Passed: <b>{len(results)}</b></p>
      {note}<br>{table_html}<br>
      <p style='color:#334;font-size:11px'>
        SL=Swing/ATR | TP1=1.5R | TP2=3.0R<br>
        ⚠️ Educational only. Not financial advice.
      </p>
    </body></html>"""

    subject = f"NSE Screener | {len(results)} stocks | {timestamp}"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                              context=ssl.create_default_context()) as s:
            s.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"  ✉  Email sent to {EMAIL_TO}")
    except smtplib.SMTPAuthenticationError:
        print("  [!] Email FAILED — wrong App Password")
    except Exception as e:
        print(f"  [!] Email error: {e}")

# ─── DISPLAY ─────────────────────────────────────────────────────────────────
def print_results(results, scanned, crossover_count):
    print(f"\n{'='*90}")
    print(f"  NSE SCREENER v5  |  {now()}")
    print(f"  Universe: {scanned} | EMA crossovers: {crossover_count} | Passed: {len(results)}")
    print(f"{'='*90}")
    if not results:
        print("\n  No stocks passed filters.")
        return
    print(f"\n{'SYMBOL':<12} {'ENTRY':>8} {'SL':>8} {'TP1':>8} {'TP2':>8} {'RISK%':>6} {'TP1%':>6} {'TP2%':>6} {'SCORE':>6}")
    print("-"*75)
    for d in results:
        print(f"{d['symbol']:<12} {fmt(d.get('entry')):>8} {fmt(d.get('sl')):>8}"
              f" {fmt(d.get('tp1')):>8} {fmt(d.get('tp2')):>8}"
              f" {fmt(d.get('risk_pct')):>6} {fmt(d.get('tp1_pct')):>6}"
              f" {fmt(d.get('tp2_pct')):>6} {d['pass_count']}/{d['total_checks']:>2}")

# ─── SAVE HTML+CSV ───────────────────────────────────────────────────────────
def save_outputs(results, scanned, crossover_count):
    timestamp = now()
    rows = []
    for d in results:
        rows.append({
            "Symbol": d.get("symbol"), "Name": d.get("name",""),
            "Sector": d.get("sector",""),
            "Entry": d.get("entry"), "SL": d.get("sl"),
            "TP1": d.get("tp1"), "TP2": d.get("tp2"),
            "ATR": d.get("atr"), "Risk%": d.get("risk_pct"),
            "TP1%": d.get("tp1_pct"), "TP2%": d.get("tp2_pct"),
            "ROE%": d.get("roe_pct"), "D/E": d.get("de_ratio"),
            "PE": d.get("pe"), "Promoter%": d.get("promoter_pct"),
            "Score": f"{d['pass_count']}/{d['total_checks']}",
            "Scanned": timestamp,
        })
    if rows:
        pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)

    check_keys = ["ROE>15%","D/E<0.5","Promoter>50%","PE<SectorPE","Margin>8%","RevGrowth>10%"]
    table_rows = ""
    for d in results:
        checks = d.get("checks",{})
        score  = d["pass_count"]
        bar    = "█"*score + "░"*(d["total_checks"]-score)
        cells  = (f"<td class='sym'>{d.get('symbol','')}</td>"
                  f"<td class='name'>{d.get('name','')[:22]}</td>"
                  f"<td>{d.get('sector','')[:16]}</td>"
                  f"<td class='entry'>₹{fmt(d.get('entry'))}</td>"
                  f"<td class='sl-cell'>₹{fmt(d.get('sl'))}<br><span class='pct'>-{fmt(d.get('risk_pct'))}%</span></td>"
                  f"<td class='tp-cell'>₹{fmt(d.get('tp1'))}<br><span class='pct'>+{fmt(d.get('tp1_pct'))}%</span></td>"
                  f"<td class='tp-cell'>₹{fmt(d.get('tp2'))}<br><span class='pct'>+{fmt(d.get('tp2_pct'))}%</span></td>"
                  f"<td class='num'>{fmt(d.get('roe_pct'),1)}%</td>"
                  f"<td class='num'>{fmt(d.get('de_ratio'),2)}</td>"
                  f"<td class='num'>{fmt(d.get('pe'),1)}</td>"
                  f"<td class='score'><span class='bar'>{bar}</span> {score}/{d['total_checks']}</td>")
        for k in check_keys:
            v   = checks.get(k)
            cls = "pass" if v else ("fail" if v is False else "na")
            sym = "✓" if v else ("✗" if v is False else "—")
            cells += f"<td class='{cls}'>{sym}</td>"
        table_rows += f"<tr>{cells}</tr>"

    check_headers = "".join(f"<th>{k}</th>" for k in check_keys)
    html = f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="{REFRESH_MINUTES*60}">
  <title>NSE Screener v5 | {timestamp}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Rajdhani:wght@600;700&display=swap');
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'JetBrains Mono',monospace;background:#060810;color:#c8d0e0;padding:20px}}
    h1{{font-family:'Rajdhani',sans-serif;font-size:24px;color:#00e5ff;letter-spacing:2px}}
    header{{display:flex;align-items:baseline;gap:16px;margin-bottom:16px;border-bottom:1px solid #1a2040;padding-bottom:14px}}
    .meta{{font-size:11px;color:#445}}
    .stats{{display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap}}
    .stat{{background:#0d1020;border:1px solid #1a2540;border-radius:6px;padding:8px 16px}}
    .stat-val{{font-size:20px;font-weight:bold}}
    .stat-lbl{{font-size:9px;color:#556;margin-top:2px}}
    .notify{{display:flex;gap:12px;margin-bottom:14px;font-size:11px}}
    .nb{{padding:4px 12px;border-radius:4px;border:1px solid}}
    .nb-email{{background:#0d2010;border-color:#226622;color:#44bb44}}
    .nb-tg{{background:#0d1535;border-color:#224488;color:#4488cc}}
    .legend{{display:flex;gap:20px;margin-bottom:12px;font-size:11px;color:#556;flex-wrap:wrap}}
    .legend span{{padding:4px 10px;border-radius:4px}}
    .l-entry{{background:#0d2040;color:#4499ff}}
    .l-sl{{background:#2a0a10;color:#ff6677}}
    .l-tp{{background:#0a2015;color:#00cc66}}
    .tbl-wrap{{overflow-x:auto}}
    table{{border-collapse:collapse;width:100%;font-size:11px}}
    th{{background:#0d1428;color:#4488cc;padding:7px 8px;text-align:center;white-space:nowrap;border-bottom:1px solid #1a2a4a;font-size:9px}}
    td{{padding:6px 8px;border-bottom:1px solid #0d1020;text-align:center;white-space:nowrap}}
    td.sym{{color:#fff;font-weight:bold;font-size:13px;text-align:left}}
    td.name{{color:#667;font-size:10px;text-align:left}}
    td.num{{color:#99aacc}}
    td.entry{{color:#4499ff;font-weight:bold;background:#080f1e}}
    td.sl-cell{{color:#ff5566;background:#120508;line-height:1.4}}
    td.tp-cell{{color:#00cc66;background:#060f0a;line-height:1.4}}
    td.score{{color:#00e5ff;font-size:10px}}
    .bar{{color:#1a3a5a;letter-spacing:-1px}}
    .pct{{font-size:9px;opacity:.8}}
    td.pass{{color:#00ff88;font-weight:bold}}
    td.fail{{color:#ff4455}}
    td.na{{color:#334}}
    tr:hover td{{background:#090f1a}}
    .footer{{margin-top:16px;font-size:10px;color:#334}}
    .empty{{text-align:center;padding:40px;color:#334}}
  </style>
</head><body>
<header>
  <h1>⚡ NSE EMA {EMA_FAST}/{EMA_SLOW} SCREENER v5</h1>
  <span class="meta">Auto-refresh 1hr | {timestamp}</span>
</header>
<div class="stats">
  <div class="stat"><div class="stat-val" style="color:#00e5ff">{scanned}</div><div class="stat-lbl">UNIVERSE</div></div>
  <div class="stat"><div class="stat-val" style="color:#ffaa00">{crossover_count}</div><div class="stat-lbl">EMA CROSSOVERS</div></div>
  <div class="stat"><div class="stat-val" style="color:#00ff88">{len(results)}</div><div class="stat-lbl">PASSED FILTERS</div></div>
</div>
<div class="notify">
  <span class="nb nb-email">✉ Email: {EMAIL_TO}</span>
  <span class="nb nb-tg">📱 Telegram: Active</span>
</div>
<div class="legend">
  <span class="l-entry">ENTRY = Crossover close</span>
  <span class="l-sl">SL = Swing/{SL_ATR_MULT}×ATR</span>
  <span class="l-tp">TP1={TP1_RR}R | TP2={TP2_RR}R</span>
</div>
<div class="tbl-wrap">
<table><thead><tr>
  <th>SYMBOL</th><th>NAME</th><th>SECTOR</th>
  <th>ENTRY</th><th>STOP LOSS</th><th>TARGET 1</th><th>TARGET 2</th>
  <th>ROE%</th><th>D/E</th><th>P/E</th><th>SCORE</th>{check_headers}
</tr></thead>
<tbody>
  {table_rows if table_rows else '<tr><td colspan="17" class="empty">No stocks passed filters this scan.</td></tr>'}
</tbody></table>
</div>
<div class="footer">
  Data: Yahoo Finance | Filters: ROE&gt;15% | D/E&lt;0.5 | Promoter&gt;50% | P/E&lt;Sector | Margin&gt;8% | RevGrowth&gt;10%<br>
  ⚠️ Educational only. Not financial advice.
</div>
</body></html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  ✓ Saved: {OUTPUT_CSV} | {OUTPUT_HTML}")

# ─── MAIN ────────────────────────────────────────────────────────────────────
NSE_SYMBOLS = []

def run_scan():
    global NSE_SYMBOLS
    print(f"\n{'#'*75}")
    print(f"  SCAN: {now()}")
    print(f"{'#'*75}")

    if not NSE_SYMBOLS:
        NSE_SYMBOLS = get_nse500_symbols()

    crossover_stocks = calc_ema_crossover(NSE_SYMBOLS)

    if not crossover_stocks:
        print("\n  No crossovers found. Market closed/flat/weekend.")
        save_outputs([], len(NSE_SYMBOLS), 0)
        send_telegram([], len(NSE_SYMBOLS), 0)
        send_email([], len(NSE_SYMBOLS), 0)
        print(f"\n  Next scan in {REFRESH_MINUTES} min. (Ctrl+C to stop)")
        return

    print(f"\n  Fetching fundamentals for {len(crossover_stocks)} stocks...")
    enriched = []
    for i, stock in enumerate(crossover_stocks, 1):
        print(f"    [{i}/{len(crossover_stocks)}] {stock['symbol']}...", end=" ", flush=True)
        data = get_fundamentals(stock)
        enriched.append(data)
        print(f"ROE={data.get('roe_pct','N/A')}%  Entry={data.get('entry','?')}  SL={data.get('sl','?')}")
        time.sleep(0.5)

    passed = apply_filters(enriched)
    print_results(passed, len(NSE_SYMBOLS), len(crossover_stocks))
    save_outputs(passed, len(NSE_SYMBOLS), len(crossover_stocks))
    send_telegram(passed, len(NSE_SYMBOLS), len(crossover_stocks))
    send_email(passed, len(NSE_SYMBOLS), len(crossover_stocks))
    print(f"\n  Next scan in {REFRESH_MINUTES} min. (Ctrl+C to stop)")

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║   NSE EMA 9/21 + FUNDAMENTAL SCREENER  v5                          ║
║   Entry | SL | TP1 | TP2 | Email | Telegram                        ║
║   Universe: NSE 500  |  Auto-refresh: 1 hr                         ║
╚══════════════════════════════════════════════════════════════════════╝
""")
    run_scan()
    schedule.every(REFRESH_MINUTES).minutes.do(run_scan)
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n\n  Stopped.")
        sys.exit(0)
