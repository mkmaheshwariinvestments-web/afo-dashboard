"""
Shah Family Office - Portfolio Dashboard
Password-protected Streamlit app with stock detail views, editable annotations, and transaction ledger.
"""

import streamlit as st
import pandas as pd
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pdf_parser import parse_holding_statement, parse_transaction_statement
from portfolio import (
    load_holdings, load_transactions, load_cash, load_nav_history,
    save_nav_history, get_bns_holdings, get_njs_holdings, get_all_holdings,
    compute_weightages, consolidate_holdings, compute_portfolio_summary,
    compute_nav, record_nav_point, initialize_nav_base,
    get_bns_cash, get_njs_cash, get_all_cash,
    load_pdb_context,
    TICKER_MAP, get_all_tickers, DATA_DIR,
)

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
ANNOTATIONS_PATH = DATA_DIR / "annotations.json"

st.set_page_config(page_title="Shah Family Office", page_icon="", layout="wide", initial_sidebar_state="collapsed")

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .main-header { font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; color: #0f172a; margin-bottom: 0; line-height: 1.2; }
    .sub-header { font-size: 0.78rem; color: #94a3b8; margin-bottom: 1rem; }
    [data-testid="stMetric"] { background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    [data-testid="stMetric"] label { font-size: 0.7rem !important; font-weight: 600 !important; color: #64748b !important; text-transform: uppercase; letter-spacing: 0.05em; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.25rem !important; font-weight: 700 !important; color: #0f172a !important; }
    [data-testid="stMetric"] [data-testid="stMetricDelta"] { font-size: 0.75rem !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f1f5f9; border-radius: 8px; padding: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 22px; font-weight: 600; font-size: 0.85rem; border-radius: 6px; color: #475569; }
    .stTabs [aria-selected="true"] { background: white !important; color: #0f172a !important; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .stDataFrame { font-size: 0.82rem; }
    .stDataFrame [data-testid="stDataFrameResizable"] { border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
    hr { border-color: #f1f5f9 !important; margin: 1rem 0 !important; }
    h3 { font-size: 1rem !important; font-weight: 700 !important; color: #334155 !important; }
    .stButton > button { border-radius: 8px; font-weight: 600; font-size: 0.82rem; padding: 0.4rem 1rem; border: 1px solid #cbd5e1; }
    .stButton > button:hover { border-color: #94a3b8; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
    [data-testid="stFileUploader"] { border: 2px dashed #cbd5e1; border-radius: 10px; padding: 1rem; }
    .stock-detail-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 1rem; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)


# ── Authentication ────────────────────────────────────────────────────
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True
    st.markdown('<p class="main-header">Shah Family Office</p>', unsafe_allow_html=True)
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        password = st.text_input("Enter password", type="password", key="password_input")
        if st.button("Login", use_container_width=True):
            try:
                correct = st.secrets["password"]
            except Exception:
                correct = "shah2026"
            if password == correct:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password")
    return False

if not check_password():
    st.stop()


# ── Annotations (comments, category, next steps) ─────────────────────
def load_annotations() -> dict:
    if ANNOTATIONS_PATH.exists():
        with open(ANNOTATIONS_PATH) as f:
            return json.load(f)
    return {}

def save_annotations(annotations: dict):
    with open(ANNOTATIONS_PATH, "w") as f:
        json.dump(annotations, f, indent=2)

def get_annotation(security: str) -> dict:
    return load_annotations().get(security, {"comment": "", "category": "", "next_steps": ""})

def set_annotation(security: str, comment: str, category: str, next_steps: str):
    annots = load_annotations()
    annots[security] = {
        "comment": comment,
        "category": category,
        "next_steps": next_steps,
        "updated_at": datetime.now().isoformat(),
    }
    save_annotations(annots)


# ── Data Loading ──────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_all_data():
    return load_holdings(), load_transactions(), load_cash(), load_nav_history()

def fetch_live_prices() -> dict:
    p = DATA_DIR / "live_prices.json"
    if p.exists():
        with open(p) as f:
            return json.load(f).get("prices", {})
    return {}

data, transactions, cash_data, nav_history = load_all_data()
live_prices = fetch_live_prices()
has_live = len(live_prices) > 0
pdb_context = load_pdb_context()
annotations = load_annotations()


# ── Helper Functions ──────────────────────────────────────────────────
def format_inr(value, show_sign=False):
    if value is None: return "-"
    abs_val = abs(value)
    sign = "-" if value < 0 else ("+" if show_sign and value > 0 else "")
    if abs_val >= 1e7: return f"{sign}{abs_val / 1e7:,.2f} Cr"
    elif abs_val >= 1e5: return f"{sign}{abs_val / 1e5:,.2f} L"
    else: return f"{sign}{abs_val:,.0f}"

def color_pnl(val):
    if isinstance(val, (int, float)):
        if val > 0: return "color: #15803d; background-color: #dcfce7; font-weight: 600"
        elif val < 0: return "color: #b91c1c; background-color: #fee2e2; font-weight: 600"
        else: return "color: #6b7280"
    return ""

def color_weight(val):
    if not isinstance(val, (int, float)): return ""
    if val >= 10: return "background-color: #1e3a5f; color: white; font-weight: 700"
    elif val >= 7: return "background-color: #2563eb; color: white; font-weight: 600"
    elif val >= 5: return "background-color: #60a5fa; color: white; font-weight: 600"
    elif val >= 3: return "background-color: #bfdbfe; color: #1e3a5f; font-weight: 500"
    elif val >= 1: return "background-color: #eff6ff; color: #1e3a5f"
    else: return "color: #9ca3af"

def color_upside(val):
    if not isinstance(val, (int, float)): return ""
    if val >= 100: return "background-color: #14532d; color: white; font-weight: 700"
    elif val >= 50: return "background-color: #15803d; color: white; font-weight: 600"
    elif val >= 20: return "background-color: #dcfce7; color: #15803d; font-weight: 600"
    elif val >= 0: return "color: #16a34a"
    elif val >= -10: return "color: #b91c1c"
    else: return "background-color: #fee2e2; color: #b91c1c; font-weight: 600"

def color_txn_type(val):
    if not isinstance(val, str): return ""
    v = val.lower()
    if "buy" in v: return "color: #15803d; font-weight: 600"
    elif "sell" in v: return "color: #b91c1c; font-weight: 600"
    elif "security in" in v: return "color: #2563eb; font-weight: 600"
    return ""


# ── Stock Detail Panel ────────────────────────────────────────────────
def render_stock_detail(security_name: str, all_h: list, txns: list, key_prefix: str = ""):
    """Render a full stock detail panel - PDB context, holdings breakdown, transactions, editable annotations."""
    ctx = pdb_context.get(security_name, {})
    annot = annotations.get(security_name, {"comment": "", "category": "", "next_steps": ""})

    # Holdings for this stock across all demats
    stock_holdings = [h for h in all_h if h["security"] == security_name]
    stock_txns = [t for t in txns if t.get("security") == security_name]

    # Header metrics
    total_qty = sum(h["quantity"] for h in stock_holdings)
    total_cost = sum(h["total_cost"] for h in stock_holdings)
    total_mval = sum(h.get("live_market_value", h.get("market_value", 0)) for h in stock_holdings)
    total_gl = total_mval - total_cost
    pct_gl = (total_gl / total_cost * 100) if total_cost > 0 else 0
    cmp = stock_holdings[0].get("live_price", stock_holdings[0].get("market_price", 0)) if stock_holdings else 0

    tp = ctx.get("target_price") or ctx.get("opp_target_price")
    upside = ((float(tp) / cmp) - 1) * 100 if tp and cmp > 0 else None
    irr = ctx.get("irr") or ctx.get("opp_irr")
    sector = ctx.get("sector", "-")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("CMP", f"{cmp:,.2f}")
    with c2: st.metric("Total Qty", f"{total_qty:,.0f}")
    with c3: st.metric("Market Value", format_inr(total_mval))
    with c4: st.metric("P&L", format_inr(total_gl, show_sign=True), delta=f"{pct_gl:+.2f}%")
    with c5: st.metric("Target", f"{float(tp):,.0f}" if tp else "-")
    with c6: st.metric("Upside", f"{upside:+.1f}%" if upside else "-")

    # Two-column layout: Research | Annotations
    col_research, col_annot = st.columns([3, 2])

    with col_research:
        st.markdown("**Research Context**")
        if ctx.get("thesis"):
            st.markdown(f"*Thesis:* {ctx['thesis']}")
        basis = ctx.get("basis") or ctx.get("target_basis")
        if basis:
            st.markdown(f"*Basis:* {basis}")
        if ctx.get("risks"):
            st.markdown(f"*Risks:* {ctx['risks']}")
        if ctx.get("exit_multiple"):
            st.markdown(f"*Exit Multiple:* {ctx['exit_multiple']}x")
        if irr:
            st.markdown(f"*IRR:* {float(irr)*100:.1f}%")
        outlook = ctx.get("outlook")
        if outlook:
            st.markdown(f"*Outlook:* {outlook}")
        if sector and sector != "-":
            st.markdown(f"*Sector:* {sector}")
        if not any([ctx.get("thesis"), basis, ctx.get("risks")]):
            st.caption("No research data available for this stock.")

    with col_annot:
        st.markdown("**Notes & Classification**")
        new_cat = st.selectbox(
            "Category",
            ["", "Compounder", "Alpha", "Trade", "Under Review", "Exit Candidate"],
            index=["", "Compounder", "Alpha", "Trade", "Under Review", "Exit Candidate"].index(annot.get("category", "")),
            key=f"{key_prefix}_cat_{security_name}",
        )
        new_comment = st.text_area("Comment", value=annot.get("comment", ""), height=68, key=f"{key_prefix}_cmt_{security_name}")
        new_next = st.text_area("Next Steps", value=annot.get("next_steps", ""), height=68, key=f"{key_prefix}_ns_{security_name}")
        if st.button("Save", key=f"{key_prefix}_save_{security_name}", use_container_width=True):
            set_annotation(security_name, new_comment, new_cat, new_next)
            st.success("Saved")
            st.rerun()

    # Holdings breakdown across demats
    if len(stock_holdings) > 1:
        st.markdown("**Holdings by Account**")
        h_rows = []
        for h in stock_holdings:
            mval = h.get("live_market_value", h.get("market_value", 0))
            gl = mval - h["total_cost"]
            h_rows.append({
                "Demat": h.get("demat", ""),
                "Qty": int(h["quantity"]),
                "Avg Cost": round(h.get("unit_cost", 0), 2),
                "Invested": round(h["total_cost"], 0),
                "Market Value": round(mval, 0),
                "P&L": round(gl, 0),
            })
        st.dataframe(pd.DataFrame(h_rows), use_container_width=True, hide_index=True)

    # Transactions for this stock
    if stock_txns:
        st.markdown("**Transaction History**")
        t_rows = [{"Date": t["tran_date"], "Type": t["type"], "Qty": int(t["quantity"]),
                    "Price": round(t["unit_price"], 2), "Amount": round(t["settlement_amount"], 0),
                    "Account": t.get("account", "")} for t in stock_txns]
        t_df = pd.DataFrame(t_rows).sort_values("Date", ascending=False).reset_index(drop=True)
        st.dataframe(t_df.style.map(color_txn_type, subset=["Type"]).format({
            "Qty": "{:,}", "Price": "{:,.2f}", "Amount": "{:,.0f}",
        }), use_container_width=True, hide_index=True)


# ── Table Builders ────────────────────────────────────────────────────
def make_holdings_df(holdings: list, use_live: bool = True) -> pd.DataFrame:
    rows = []
    for h in holdings:
        if use_live and "live_price" in h:
            price, mval, gl, pct = h["live_price"], h["live_market_value"], h["live_gl"], h["live_pct_gl"]
        else:
            price, mval = h.get("market_price", 0), h.get("market_value", 0)
            gl, pct = h.get("total_gl", 0), h.get("pct_gl", 0)
        annot = annotations.get(h["security"], {})
        rows.append({
            "Security": h["security"], "Ticker": h.get("ticker", ""),
            "Sector": h.get("pdb_sector", "-") or "-", "Demat": h.get("demat", ""),
            "Category": annot.get("category", "") or "-",
            "Qty": int(h["quantity"]), "Avg Cost": round(h.get("unit_cost", 0), 2),
            "Invested": round(h["total_cost"], 0), "CMP": round(price, 2),
            "Market Value": round(mval, 0), "P&L": round(gl, 0), "P&L %": round(pct, 2),
            "Weight %": round(h.get("weight_pct", 0), 2),
            "Target": round(h["target_price"], 0) if h.get("target_price") else None,
            "Upside %": round(h["upside_pct"], 1) if h.get("upside_pct") else None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Market Value", ascending=False).reset_index(drop=True)
    return df

def make_consolidated_df(holdings: list, use_live: bool = True) -> pd.DataFrame:
    consolidated = consolidate_holdings(holdings, use_live)
    total_value = sum(c["live_market_value"] if use_live else c["market_value"] for c in consolidated)
    rows = []
    for c in consolidated:
        val = c["live_market_value"] if use_live else c["market_value"]
        weight = (val / total_value * 100) if total_value > 0 else 0
        ctx = pdb_context.get(c["security"], {})
        annot = annotations.get(c["security"], {})
        tp = ctx.get("target_price") or ctx.get("opp_target_price")
        upside = ((float(tp) / c["live_price"]) - 1) * 100 if tp and c.get("live_price") and c["live_price"] > 0 else None
        rows.append({
            "Security": c["security"], "Ticker": c["ticker"],
            "Sector": ctx.get("sector", "-") or "-",
            "Category": annot.get("category", "") or "-",
            "Accounts": ", ".join(c["demats"]),
            "Total Qty": int(c["total_quantity"]), "Avg Cost": round(c["avg_cost"], 2),
            "Invested": round(c["total_cost"], 0), "CMP": round(c.get("live_price", 0), 2),
            "Market Value": round(val, 0), "P&L": round(c["total_gl"], 0),
            "P&L %": round(c["pct_gl"], 2), "Weight %": round(weight, 2),
            "Target": round(float(tp), 0) if tp else None,
            "Upside %": round(upside, 1) if upside is not None else None,
        })
    return pd.DataFrame(rows)


def render_holdings_table(df: pd.DataFrame):
    if df.empty:
        st.info("No holdings data available.")
        return
    subset_map = [(color_pnl, ["P&L", "P&L %"]), (color_weight, ["Weight %"])]
    if "Upside %" in df.columns:
        subset_map.append((color_upside, ["Upside %"]))
    styled = df.style
    for fn, cols in subset_map:
        valid = [c for c in cols if c in df.columns]
        if valid: styled = styled.map(fn, subset=valid)
    fmt = {"Invested": "{:,.0f}", "Market Value": "{:,.0f}", "P&L": "{:+,.0f}", "P&L %": "{:+.2f}%",
           "Weight %": "{:.2f}%", "CMP": "{:,.2f}", "Avg Cost": "{:,.2f}", "Qty": "{:,}"}
    if "Target" in df.columns:
        fmt["Target"] = lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
    if "Upside %" in df.columns:
        fmt["Upside %"] = lambda x: f"{x:+.1f}%" if pd.notna(x) else "-"
    styled = styled.format(fmt)
    st.dataframe(styled, use_container_width=True, height=min(500, 45 + len(df) * 36), hide_index=True)


def render_kpis(summary: dict, nav_value: float = None):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("Equity Value", format_inr(summary["total_equity_value"]))
    with c2: st.metric("Invested Cost", format_inr(summary["total_invested_cost"]))
    with c3: st.metric("Unrealized P&L", format_inr(summary["total_unrealized_gl"], show_sign=True), delta=f"{summary['pct_unrealized_gl']:.2f}%")
    with c4: st.metric("Cash", format_inr(summary["total_cash"]))
    with c5:
        if nav_value is not None:
            st.metric("NAV", f"{nav_value:,.2f}", delta=f"{((nav_value / 1000) - 1) * 100:.2f}% since inception")
        else:
            st.metric("NAV", "Pending", help="NAV base will be set on April 17, 2026")


# ── Stock Selector (click-to-expand) ──────────────────────────────────
def render_stock_selector(holdings: list, txns: list, key_prefix: str):
    """Render a selectbox for drilling into a specific stock."""
    stock_names = sorted(set(h["security"] for h in holdings))
    selected = st.selectbox(
        "Select stock for detail view",
        [""] + stock_names,
        key=f"{key_prefix}_stock_select",
        format_func=lambda x: "-- Select a stock --" if x == "" else x,
    )
    if selected:
        with st.container():
            render_stock_detail(selected, holdings, txns, key_prefix)


# ── Account View ──────────────────────────────────────────────────────
def render_account_view(holdings: list, cash_balances: dict, txns: list,
                        account_filter: str, view_label: str, use_live: bool = True):
    holdings = compute_weightages(holdings, use_live)
    summary = compute_portfolio_summary(holdings, cash_balances, use_live)
    nav_value = compute_nav(summary["total_portfolio_value"], nav_history) if nav_history.get("base_portfolio_value") else None
    render_kpis(summary, nav_value)
    st.markdown("---")

    st.subheader(f"Holdings ({summary['num_holdings']} stocks)")
    df = make_holdings_df(holdings, use_live)
    render_holdings_table(df)

    # Stock detail drill-down
    st.markdown("---")
    st.subheader("Stock Detail")
    account_txns = [t for t in txns if t.get("account") == account_filter]
    render_stock_selector(holdings, account_txns, f"{view_label}")

    # Transaction ledger
    st.markdown("---")
    st.subheader("Transaction Ledger")
    account_txns_all = [t for t in txns if t.get("account") == account_filter]
    render_transaction_ledger(account_txns_all, f"{view_label}_txn")


# ── Transaction Ledger ────────────────────────────────────────────────
def render_transaction_ledger(txns: list, key_prefix: str):
    """Full transaction ledger with filters, notes editing, and manual entry."""
    if not txns:
        st.info("No transactions available.")
        return

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        filter_type = st.multiselect("Filter by type", ["Buy and deposit funds", "Sell and withdraw cash", "Security in", "Square up Buy", "Square up Sell"],
                                     default=[], key=f"{key_prefix}_ftype")
    with fc2:
        securities = sorted(set(t["security"] for t in txns))
        filter_sec = st.multiselect("Filter by stock", securities, default=[], key=f"{key_prefix}_fsec")
    with fc3:
        sort_order = st.radio("Sort", ["Newest first", "Oldest first"], horizontal=True, key=f"{key_prefix}_sort")

    filtered = txns
    if filter_type:
        filtered = [t for t in filtered if t["type"] in filter_type]
    if filter_sec:
        filtered = [t for t in filtered if t["security"] in filter_sec]

    rows = []
    for t in filtered:
        rows.append({
            "Date": t["tran_date"],
            "Type": t["type"],
            "Security": t["security"],
            "Qty": int(t["quantity"]),
            "Price": round(t["unit_price"], 2),
            "Brokerage": round(t.get("brokerage", 0), 2),
            "STT": round(t.get("stt", 0), 2),
            "Amount": round(t["settlement_amount"], 0),
            "Note": t.get("note", ""),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No transactions match filters.")
        return

    ascending = sort_order == "Oldest first"
    df = df.sort_values("Date", ascending=ascending).reset_index(drop=True)

    # Summary row
    buys = sum(r["Amount"] for r in rows if "buy" in rows[rows.index(r)]["Type"].lower() or "security in" in rows[rows.index(r)]["Type"].lower()) if rows else 0
    sells = sum(r["Amount"] for r in rows if "sell" in rows[rows.index(r)]["Type"].lower()) if rows else 0

    sc1, sc2, sc3 = st.columns(3)
    with sc1: st.metric("Transactions", f"{len(df)}")
    with sc2: st.metric("Total Buys", format_inr(sum(r["Amount"] for r in rows if "Buy" in r["Type"] or "Security in" in r["Type"])))
    with sc3: st.metric("Total Sells", format_inr(sum(r["Amount"] for r in rows if "Sell" in r["Type"])))

    styled = df.style.map(color_txn_type, subset=["Type"]).format({
        "Qty": "{:,}", "Price": "{:,.2f}", "Amount": "{:,.0f}", "Brokerage": "{:.2f}", "STT": "{:.2f}",
    })
    st.dataframe(styled, use_container_width=True, height=min(500, 45 + len(df) * 36), hide_index=True)


# ── Main Layout ───────────────────────────────────────────────────────
col_title, col_refresh = st.columns([4, 1])
with col_title:
    st.markdown('<p class="main-header">Shah Family Office</p>', unsafe_allow_html=True)
    price_file = DATA_DIR / "live_prices.json"
    if price_file.exists():
        with open(price_file) as f:
            price_meta = json.load(f)
        updated = price_meta.get("updated_at", "Unknown")
        st.markdown(f'<p class="sub-header">Prices as of: {updated[:19].replace("T", " ")}</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="sub-header">Using statement prices (no live data yet)</p>', unsafe_allow_html=True)
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Refresh Prices", use_container_width=True):
        st.info("Price refresh requires market hours. Using latest available data.")

st.markdown("---")

tab_bns, tab_njs, tab_combined, tab_upload = st.tabs([
    "BNS (Bhowli Nikhil Shah)", "NJS (Nikhil Jitendra Shah)", "Combined Portfolio", "Upload & Settings",
])

bns_holdings = get_bns_holdings(data, live_prices, pdb_context)
njs_holdings = get_njs_holdings(data, live_prices, pdb_context)
all_holdings = bns_holdings + njs_holdings
bns_cash = get_bns_cash(cash_data)
njs_cash = get_njs_cash(cash_data)
all_cash = get_all_cash(cash_data)
use_live = has_live

# ── BNS Tab ───────────────────────────────────────────────────────────
with tab_bns:
    render_account_view(bns_holdings, bns_cash, transactions, "BNS", "BNS", use_live)

# ── NJS Tab ───────────────────────────────────────────────────────────
with tab_njs:
    render_account_view(njs_holdings, njs_cash, transactions, "NJS", "NJS", use_live)

# ── Combined Tab ──────────────────────────────────────────────────────
with tab_combined:
    all_with_weights = compute_weightages(list(all_holdings), use_live)
    combined_summary = compute_portfolio_summary(all_with_weights, all_cash, use_live)
    nav_value = compute_nav(combined_summary["total_portfolio_value"], nav_history) if nav_history.get("base_portfolio_value") else None
    render_kpis(combined_summary, nav_value)
    st.markdown("---")

    # Account breakdown
    st.subheader("Account Breakdown")
    bns_summary = compute_portfolio_summary(bns_holdings, bns_cash, use_live)
    njs_summary = compute_portfolio_summary(njs_holdings, njs_cash, use_live)
    acct_rows = []
    for label, s in [("BNS (Ambit + Dezerv)", bns_summary), ("NJS + NJS HUF (Ambit + Dezerv)", njs_summary)]:
        acct_rows.append({"Account": label, "Equity Value": round(s["total_equity_value"], 0),
            "Invested Cost": round(s["total_invested_cost"], 0), "Cash": round(s["total_cash"], 0),
            "Total Value": round(s["total_portfolio_value"], 0), "P&L": round(s["total_unrealized_gl"], 0),
            "P&L %": round(s["pct_unrealized_gl"], 2)})
    acct_df = pd.DataFrame(acct_rows)
    st.dataframe(acct_df.style.map(color_pnl, subset=["P&L", "P&L %"]).format({
        "Equity Value": "{:,.0f}", "Invested Cost": "{:,.0f}", "Cash": "{:+,.0f}",
        "Total Value": "{:,.0f}", "P&L": "{:+,.0f}", "P&L %": "{:+.2f}%",
    }), use_container_width=True, hide_index=True)

    st.markdown("---")

    # Consolidated holdings
    st.subheader(f"Consolidated Holdings ({combined_summary['num_holdings']} stocks)")
    consolidated_df = make_consolidated_df(all_with_weights, use_live)
    if not consolidated_df.empty:
        styled = consolidated_df.style.map(color_pnl, subset=["P&L", "P&L %"]).map(color_weight, subset=["Weight %"])
        if "Upside %" in consolidated_df.columns:
            styled = styled.map(color_upside, subset=["Upside %"])
        styled = styled.format({
            "Invested": "{:,.0f}", "Market Value": "{:,.0f}", "P&L": "{:+,.0f}", "P&L %": "{:+.2f}%",
            "Weight %": "{:.2f}%", "CMP": "{:,.2f}", "Avg Cost": "{:,.2f}", "Total Qty": "{:,}",
            "Target": lambda x: f"{x:,.0f}" if pd.notna(x) else "-",
            "Upside %": lambda x: f"{x:+.1f}%" if pd.notna(x) else "-",
        })
        st.dataframe(styled, use_container_width=True, height=min(650, 45 + len(consolidated_df) * 36), hide_index=True)

    # Stock detail drill-down
    st.markdown("---")
    st.subheader("Stock Detail")
    render_stock_selector(all_with_weights, transactions, "combined")

    # Annotations quick-edit table
    st.markdown("---")
    st.subheader("Quick Edit: Comments & Categories")
    st.caption("Edit inline and click Save below the table.")

    stock_names = sorted(set(h["security"] for h in all_with_weights))
    edit_rows = []
    for s in stock_names:
        a = annotations.get(s, {})
        edit_rows.append({
            "Security": s,
            "Category": a.get("category", ""),
            "Comment": a.get("comment", ""),
            "Next Steps": a.get("next_steps", ""),
        })
    edit_df = pd.DataFrame(edit_rows)

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Security": st.column_config.TextColumn("Security", disabled=True),
            "Category": st.column_config.SelectboxColumn("Category", options=["", "Compounder", "Alpha", "Trade", "Under Review", "Exit Candidate"]),
            "Comment": st.column_config.TextColumn("Comment"),
            "Next Steps": st.column_config.TextColumn("Next Steps"),
        },
        key="combined_edit_table",
    )

    if st.button("Save All Annotations", key="save_all_annots"):
        all_annots = load_annotations()
        for _, row in edited.iterrows():
            sec = row["Security"]
            all_annots[sec] = {
                "comment": row.get("Comment", ""),
                "category": row.get("Category", ""),
                "next_steps": row.get("Next Steps", ""),
                "updated_at": datetime.now().isoformat(),
            }
        save_annotations(all_annots)
        st.success(f"Saved annotations for {len(edited)} stocks.")
        st.rerun()

    # Transaction Ledger (all accounts)
    st.markdown("---")
    st.subheader("Transaction Ledger (All Accounts)")
    render_transaction_ledger(transactions, "combined_txn")

    # NAV Chart
    if nav_history.get("history"):
        st.markdown("---")
        st.subheader("Portfolio NAV")
        nav_df = pd.DataFrame(nav_history["history"])
        nav_df["date"] = pd.to_datetime(nav_df["date"])
        st.line_chart(nav_df.set_index("date")["nav"], use_container_width=True)


# ── Upload & Settings Tab ─────────────────────────────────────────────
with tab_upload:
    st.subheader("Upload Ambit Statements")
    st.markdown("Upload new Ambit holding or transaction statement PDFs. Auto-detects account and updates data.")

    uploaded_files = st.file_uploader("Drop Ambit PDF statements here", type=["pdf"], accept_multiple_files=True, key="pdf_uploader")
    if uploaded_files:
        for uploaded_file in uploaded_files:
            save_path = UPLOADS_DIR / uploaded_file.name
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.info(f"Processing: {uploaded_file.name}")
            try:
                if "holding" in uploaded_file.name.lower():
                    result = parse_holding_statement(str(save_path))
                    _update_holdings(result)
                    st.success(f"Holding: {result['short_name']} ({len(result['holdings'])} positions, {result['report_date']})")
                elif "transaction" in uploaded_file.name.lower():
                    result = parse_transaction_statement(str(save_path))
                    _update_transactions(result)
                    st.success(f"Transactions: {result['short_name']} ({len(result['transactions'])} txns, {result['from_date']} to {result['to_date']})")
                else:
                    try:
                        result = parse_holding_statement(str(save_path))
                        _update_holdings(result)
                        st.success(f"Detected holding: {result['short_name']}")
                    except Exception:
                        result = parse_transaction_statement(str(save_path))
                        _update_transactions(result)
                        st.success(f"Detected transactions: {result['short_name']}")
            except Exception as e:
                st.error(f"Failed: {uploaded_file.name}: {e}")
        if st.button("Apply Changes & Refresh"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")
    st.subheader("Cash Balances")
    cc1, cc2 = st.columns(2)
    with cc1:
        bns_cv = st.number_input("BNS Ambit Cash", value=float(cash_data.get("balances", {}).get("BNS_Ambit", 0)), step=10000.0, format="%.2f")
    with cc2:
        njs_cv = st.number_input("NJS Ambit Cash", value=float(cash_data.get("balances", {}).get("NJS_Ambit", 0)), step=10000.0, format="%.2f")
    if st.button("Update Cash"):
        cash_data["balances"]["BNS_Ambit"] = bns_cv
        cash_data["balances"]["NJS_Ambit"] = njs_cv
        cash_data["as_of"] = datetime.now().strftime("%d/%m/%Y")
        with open(DATA_DIR / "cash.json", "w") as f:
            json.dump(cash_data, f, indent=2)
        st.success("Cash updated.")
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.subheader("NAV Settings")
    if nav_history.get("base_portfolio_value"):
        st.info(f"NAV Base: {nav_history['base_value']} on {nav_history['base_date']} (Portfolio: {format_inr(nav_history['base_portfolio_value'])})")
    else:
        st.warning("NAV base not set. Will initialize on first refresh after April 17, 2026.")
        if st.button("Initialize NAV Base Now"):
            all_h = get_all_holdings(data, live_prices, pdb_context)
            all_c = get_all_cash(cash_data)
            s = compute_portfolio_summary(all_h, all_c, has_live)
            initialize_nav_base(s["total_portfolio_value"])
            st.success(f"NAV base set to 1000 at {format_inr(s['total_portfolio_value'])}")
            st.cache_data.clear()
            st.rerun()


# ── Upload Helpers ────────────────────────────────────────────────────
def _update_holdings(parsed: dict):
    hp = DATA_DIR / "holdings.json"
    existing = json.load(open(hp)) if hp.exists() else {"accounts": [], "last_updated": None}
    acct_id = parsed["account_id"]
    found = False
    for i, acct in enumerate(existing["accounts"]):
        if acct["account_id"] == acct_id:
            existing["accounts"][i] = {k: parsed[k] for k in ["account_id", "owner_name", "short_name", "broker", "report_date", "holdings", "equity_total_cost", "equity_total_market_value"]}
            found = True
            break
    if not found:
        existing["accounts"].append({k: parsed[k] for k in ["account_id", "owner_name", "short_name", "broker", "report_date", "holdings", "equity_total_cost", "equity_total_market_value"]})
    existing["last_updated"] = datetime.now().isoformat()
    with open(hp, "w") as f:
        json.dump(existing, f, indent=2)

def _update_transactions(parsed: dict):
    tp = DATA_DIR / "transactions.json"
    existing = json.load(open(tp)) if tp.exists() else []
    for t in parsed["transactions"]:
        t["account"] = parsed["short_name"]
    acct = parsed["short_name"]
    new_dates = set(t["tran_date"] for t in parsed["transactions"])
    existing = [t for t in existing if not (t.get("account") == acct and t["tran_date"] in new_dates)]
    existing.extend(parsed["transactions"])
    existing.sort(key=lambda x: x["tran_date"], reverse=True)
    with open(tp, "w") as f:
        json.dump(existing, f, indent=2)
