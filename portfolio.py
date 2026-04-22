"""
Portfolio engine: NAV calculation, performance metrics, weightage computation.
"""

import json
import os
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Security name -> NSE TrueData symbol mapping
TICKER_MAP = {
    "Aarti Industries Ltd": "AARTIIND",
    "Aegis Vopak Terminals Ltd": "AEGISVOPAK",
    "Artemis Medicare Services Ltd": "ARTEMISMED",
    "Bajaj Finance Ltd": "BAJFINANCE",
    "Bharti Airtel Ltd": "BHARTIARTL",
    "Brookfield I Real Estate Trust REIT": "BIRET",
    "Central Depository Services India Ltd": "CDSL",
    "Dixon Technologies India Ltd": "DIXON",
    "E I H Ltd": "EIHOTEL",
    "Embassy Office Parks REIT": "EMBASSY",
    "Five-Star Business Finance Ltd": "FIVESTAR",
    "Godavari Biorefineries Ltd": "GODAVARIB",
    "HDFC Gold Exchange Traded Fund": "HDFCGOLD",
    "Healthcare Global Enterprises Ltd": "HCG",
    "Heritage Foods Ltd": "HERITGFOOD",
    "ICICI Bank Ltd": "ICICIBANK",
    "Indegene Ltd": "INDGN",
    "Jubilant Pharmova Ltd": "JUBLPHARMA",
    "Max Estates Ltd": "MAXESTATES",
    "Meesho Ltd": "MEESHO",
    "Muthoot Finance Ltd": "MUTHOOTFIN",
    "Nippon India ETF Gold Bees": "GOLDBEES",
    "NTPC Ltd": "NTPC",
    "Piramal Pharma": "PPLPHARMA",
    "Prestige Estates Projects Ltd": "PRESTIGE",
    "Rainbow Childrens Medicare Ltd": "RAINBOW",
    "SBI ETF Gold": "SETFGOLD",
    "Samhi Hotels Ltd": "SAMHI",
    "Scoda Tubes Ltd": "SCODATUBES",
    "Swiggy Ltd": "SWIGGY",
}

# Reverse map: ticker -> security name
REVERSE_TICKER_MAP = {v: k for k, v in TICKER_MAP.items()}

# NAV base date: April 17, 2026 market open
NAV_BASE_DATE = "2026-04-17"
NAV_BASE_VALUE = 1000.0


def load_pdb_context() -> dict:
    """Load qualitative context from Portfolio Dashboard (read-only)."""
    path = DATA_DIR / "pdb_context.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_all_tickers() -> list:
    """Return list of all TrueData ticker symbols."""
    return list(TICKER_MAP.values())


def fetch_yfinance_prices(tickers: list) -> dict:
    """
    Batch-fetch latest NSE closes via yfinance. Returns {bare_ticker: price}.
    Silently skips symbols yfinance can't resolve (e.g. a wrong HDFCMFGETF suffix)
    so a few bad mappings don't kill the whole refresh.
    """
    import yfinance as yf

    if not tickers:
        return {}
    ns_tickers = [f"{t}.NS" for t in tickers]
    prices: dict = {}
    try:
        data = yf.download(
            " ".join(ns_tickers),
            period="5d",
            progress=False,
            auto_adjust=True,
            threads=True,
            group_by="column",
        )
    except Exception as e:
        print(f"yfinance batch fetch failed: {e}")
        return {}

    if data.empty or "Close" not in data:
        return {}
    close = data["Close"]

    if len(ns_tickers) == 1:
        # Single-symbol call returns a Series, not a DataFrame column.
        s = close.dropna()
        if not s.empty:
            prices[tickers[0]] = float(s.iloc[-1])
    else:
        for t, ns in zip(tickers, ns_tickers):
            if ns in close.columns:
                col = close[ns].dropna()
                if not col.empty:
                    prices[t] = float(col.iloc[-1])
    return prices


def get_ticker(security_name: str) -> str:
    """Get NSE ticker for a security name."""
    return TICKER_MAP.get(security_name, security_name)


def load_holdings() -> dict:
    """Load all holdings from JSON files. Returns dict with Ambit + Dezerv holdings."""
    holdings_path = DATA_DIR / "holdings.json"
    dezerv_path = DATA_DIR / "dezerv.json"

    ambit_holdings = {}
    if holdings_path.exists():
        with open(holdings_path) as f:
            ambit_holdings = json.load(f)

    dezerv_holdings = {}
    if dezerv_path.exists():
        with open(dezerv_path) as f:
            dezerv_holdings = json.load(f)

    return {"ambit": ambit_holdings, "dezerv": dezerv_holdings}


def load_transactions() -> list:
    """Load all transactions."""
    txn_path = DATA_DIR / "transactions.json"
    if txn_path.exists():
        with open(txn_path) as f:
            return json.load(f)
    return []


def load_cash() -> dict:
    """Load cash balances."""
    cash_path = DATA_DIR / "cash.json"
    if cash_path.exists():
        with open(cash_path) as f:
            return json.load(f)
    return {"balances": {}}


def load_nav_history() -> dict:
    """Load NAV history."""
    nav_path = DATA_DIR / "nav_history.json"
    if nav_path.exists():
        with open(nav_path) as f:
            return json.load(f)
    return {"base_date": NAV_BASE_DATE, "base_value": NAV_BASE_VALUE, "base_portfolio_value": None, "history": []}


def save_nav_history(nav_data: dict):
    """Save NAV history."""
    with open(DATA_DIR / "nav_history.json", "w") as f:
        json.dump(nav_data, f, indent=2)


def get_bns_holdings(data: dict, live_prices: dict = None, pdb: dict = None) -> list:
    """
    Get all BNS holdings (Ambit BNS + Dezerv BNS).
    Applies live prices if provided.
    """
    holdings = []

    # Ambit BNS
    if "ambit" in data and "accounts" in data["ambit"]:
        for acct in data["ambit"]["accounts"]:
            if acct["short_name"] == "BNS":
                for h in acct["holdings"]:
                    holding = _enrich_holding(h, "Ambit", live_prices, pdb)
                    holdings.append(holding)

    # Dezerv BNS
    if "dezerv" in data:
        for acct in data["dezerv"].get("accounts", []):
            if acct["short_name"] == "BNS":
                for h in acct["holdings"]:
                    holding = _enrich_holding(h, "Dezerv", live_prices, pdb)
                    holdings.append(holding)

    return holdings


def get_njs_holdings(data: dict, live_prices: dict = None, pdb: dict = None) -> list:
    """
    Get all NJS + NJS HUF holdings (Ambit NJS + Dezerv NJS + Dezerv NJS HUF).
    """
    holdings = []

    # Ambit NJS
    if "ambit" in data and "accounts" in data["ambit"]:
        for acct in data["ambit"]["accounts"]:
            if acct["short_name"] == "NJS":
                for h in acct["holdings"]:
                    holding = _enrich_holding(h, "Ambit", live_prices, pdb)
                    holdings.append(holding)

    # Dezerv NJS and NJS HUF
    if "dezerv" in data:
        for acct in data["dezerv"].get("accounts", []):
            if acct["short_name"] in ("NJS", "NJS HUF"):
                label = f"Dezerv ({acct['short_name']})"
                for h in acct["holdings"]:
                    holding = _enrich_holding(h, label, live_prices, pdb)
                    holdings.append(holding)

    return holdings


def get_all_holdings(data: dict, live_prices: dict = None, pdb: dict = None) -> list:
    """Get all holdings across all accounts."""
    return get_bns_holdings(data, live_prices, pdb) + get_njs_holdings(data, live_prices, pdb)


def _enrich_holding(h: dict, demat_label: str, live_prices: dict = None, pdb: dict = None) -> dict:
    """Add computed fields to a holding: live price, weight (computed later), ticker, PDB context."""
    holding = dict(h)
    holding["demat"] = demat_label
    holding["ticker"] = get_ticker(h["security"])

    # Apply live price if available
    if live_prices:
        ticker = holding["ticker"]
        if ticker in live_prices and live_prices[ticker] > 0:
            holding["live_price"] = live_prices[ticker]
            holding["live_market_value"] = holding["quantity"] * live_prices[ticker]
            holding["live_gl"] = holding["live_market_value"] - holding["total_cost"]
            holding["live_pct_gl"] = (
                (holding["live_gl"] / holding["total_cost"] * 100)
                if holding["total_cost"] > 0
                else 0.0
            )

    # Attach PDB research context (read-only from Portfolio Dashboard)
    if pdb:
        ctx = pdb.get(h["security"], {})
        if ctx:
            holding["pdb_sector"] = ctx.get("sector")
            tp = ctx.get("target_price") or ctx.get("opp_target_price")
            if tp:
                holding["target_price"] = float(tp)
                cmp = holding.get("live_price", h.get("market_price", 0))
                if cmp and cmp > 0:
                    holding["upside_pct"] = ((float(tp) / cmp) - 1) * 100
            holding["pdb_risks"] = ctx.get("risks")
            holding["pdb_thesis"] = ctx.get("thesis")
            holding["pdb_outlook"] = ctx.get("outlook")
            holding["pdb_basis"] = ctx.get("basis") or ctx.get("target_basis")
            holding["pdb_exit_multiple"] = ctx.get("exit_multiple")
            irr = ctx.get("irr") or ctx.get("opp_irr")
            if irr:
                holding["pdb_irr"] = float(irr) * 100  # Convert to %

    return holding


def compute_weightages(holdings: list, use_live: bool = True) -> list:
    """
    Compute portfolio weight % for each holding.
    Modifies holdings in place and returns them.
    """
    total_value = 0
    for h in holdings:
        if use_live and "live_market_value" in h:
            total_value += h["live_market_value"]
        else:
            total_value += h.get("market_value", 0)

    for h in holdings:
        if use_live and "live_market_value" in h:
            val = h["live_market_value"]
        else:
            val = h.get("market_value", 0)
        h["weight_pct"] = (val / total_value * 100) if total_value > 0 else 0.0

    return holdings


def consolidate_holdings(holdings: list, use_live: bool = True) -> list:
    """
    Merge holdings of the same security across demats.
    Returns consolidated list sorted by market value descending.
    """
    merged = {}
    for h in holdings:
        sec = h["security"]
        if sec not in merged:
            merged[sec] = {
                "security": sec,
                "ticker": h["ticker"],
                "demats": [],
                "total_quantity": 0,
                "total_cost": 0,
                "market_value": 0,
                "live_market_value": 0,
                "live_price": h.get("live_price", h.get("market_price", 0)),
            }
        m = merged[sec]
        m["demats"].append(h["demat"])
        m["total_quantity"] += h["quantity"]
        m["total_cost"] += h["total_cost"]
        m["market_value"] += h.get("market_value", 0)
        if "live_market_value" in h:
            m["live_market_value"] += h["live_market_value"]
        else:
            m["live_market_value"] += h.get("market_value", 0)

    result = []
    for sec, m in merged.items():
        m["demats"] = list(set(m["demats"]))
        m["avg_cost"] = m["total_cost"] / m["total_quantity"] if m["total_quantity"] > 0 else 0
        val = m["live_market_value"] if use_live else m["market_value"]
        m["total_gl"] = val - m["total_cost"]
        m["pct_gl"] = (m["total_gl"] / m["total_cost"] * 100) if m["total_cost"] > 0 else 0
        result.append(m)

    result.sort(key=lambda x: x["live_market_value"] if use_live else x["market_value"], reverse=True)
    return result


def compute_portfolio_summary(holdings: list, cash_balances: dict, use_live: bool = True) -> dict:
    """
    Compute aggregate portfolio metrics.
    cash_balances: dict of account_key -> cash amount
    """
    total_cost = sum(h["total_cost"] for h in holdings)
    if use_live:
        total_value = sum(h.get("live_market_value", h.get("market_value", 0)) for h in holdings)
    else:
        total_value = sum(h.get("market_value", 0) for h in holdings)

    total_cash = sum(cash_balances.values())
    total_gl = total_value - total_cost
    pct_gl = (total_gl / total_cost * 100) if total_cost > 0 else 0

    return {
        "total_equity_value": total_value,
        "total_invested_cost": total_cost,
        "total_cash": total_cash,
        "total_portfolio_value": total_value + total_cash,
        "total_unrealized_gl": total_gl,
        "pct_unrealized_gl": pct_gl,
        "num_holdings": len(set(h["security"] for h in holdings)),
    }


def compute_nav(current_portfolio_value: float, nav_history: dict) -> float:
    """
    Compute current NAV.
    If base portfolio value is not set yet (pre April 17), returns None.
    """
    base_val = nav_history.get("base_portfolio_value")
    if base_val is None or base_val == 0:
        return None
    return NAV_BASE_VALUE * (current_portfolio_value / base_val)


def record_nav_point(current_portfolio_value: float, nav_history: dict) -> dict:
    """Record today's NAV in history. Returns updated nav_history."""
    today = date.today().isoformat()
    nav = compute_nav(current_portfolio_value, nav_history)
    if nav is not None:
        # Remove existing entry for today if any
        nav_history["history"] = [
            p for p in nav_history["history"] if p["date"] != today
        ]
        nav_history["history"].append({"date": today, "nav": round(nav, 2), "portfolio_value": round(current_portfolio_value, 2)})
        nav_history["history"].sort(key=lambda x: x["date"])
    return nav_history


def initialize_nav_base(portfolio_value: float):
    """
    Set the base NAV portfolio value. Called on April 17 (or first run).
    """
    nav_history = load_nav_history()
    if nav_history.get("base_portfolio_value") is None:
        nav_history["base_portfolio_value"] = round(portfolio_value, 2)
        nav_history["base_date"] = date.today().isoformat()
        nav_history["history"] = [{
            "date": date.today().isoformat(),
            "nav": NAV_BASE_VALUE,
            "portfolio_value": round(portfolio_value, 2),
        }]
        save_nav_history(nav_history)
    return nav_history


def get_bns_cash(cash_data: dict) -> dict:
    """Get BNS cash balances."""
    b = cash_data.get("balances", {})
    return {
        "BNS_Ambit": b.get("BNS_Ambit", 0),
        "BNS_Dezerv": b.get("BNS_Dezerv", 0),
    }


def get_njs_cash(cash_data: dict) -> dict:
    """Get NJS + NJS HUF cash balances."""
    b = cash_data.get("balances", {})
    return {
        "NJS_Ambit": b.get("NJS_Ambit", 0),
        "NJS_Dezerv": b.get("NJS_Dezerv", 0),
        "NJS_HUF_Dezerv": b.get("NJS_HUF_Dezerv", 0),
    }


def get_all_cash(cash_data: dict) -> dict:
    """Get all cash balances."""
    return cash_data.get("balances", {})
