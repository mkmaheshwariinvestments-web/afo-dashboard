"""
Shah Family Office - Portfolio Dashboard
Simple, password-protected Streamlit app for tracking equity holdings.
"""

import streamlit as st
import pandas as pd
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

# Add parent to path for imports
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

st.set_page_config(
    page_title="Shah Family Office",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Page-level ────────────────────────── */
    .block-container { padding-top: 1.5rem; }
    section[data-testid="stSidebar"] { display: none; }

    /* ── Header ────────────────────────────── */
    .main-header {
        font-size: 1.6rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #0f172a;
        margin-bottom: 0;
        line-height: 1.2;
    }
    .sub-header {
        font-size: 0.78rem;
        color: #94a3b8;
        margin-bottom: 1rem;
    }

    /* ── Metric cards ──────────────────────── */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    [data-testid="stMetric"] label {
        font-size: 0.7rem !important;
        font-weight: 600 !important;
        color: #64748b !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        color: #0f172a !important;
    }
    [data-testid="stMetric"] [data-testid="stMetricDelta"] {
        font-size: 0.75rem !important;
    }

    /* ── Tabs ──────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: #f1f5f9;
        border-radius: 8px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 22px;
        font-weight: 600;
        font-size: 0.85rem;
        border-radius: 6px;
        color: #475569;
    }
    .stTabs [aria-selected="true"] {
        background: white !important;
        color: #0f172a !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }

    /* ── Dataframes ────────────────────────── */
    .stDataFrame { font-size: 0.82rem; }
    .stDataFrame [data-testid="stDataFrameResizable"] {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        overflow: hidden;
    }

    /* ── Dividers ──────────────────────────── */
    hr { border-color: #f1f5f9 !important; margin: 1rem 0 !important; }

    /* ── Subheaders ────────────────────────── */
    h3 {
        font-size: 1rem !important;
        font-weight: 700 !important;
        color: #334155 !important;
        letter-spacing: -0.01em;
    }

    /* ── Expanders ─────────────────────────── */
    .streamlit-expanderHeader {
        font-size: 0.85rem;
        font-weight: 600;
        color: #475569;
    }

    /* ── Buttons ───────────────────────────── */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.82rem;
        padding: 0.4rem 1rem;
        border: 1px solid #cbd5e1;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        border-color: #94a3b8;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }

    /* ── File uploader ─────────────────────── */
    [data-testid="stFileUploader"] {
        border: 2px dashed #cbd5e1;
        border-radius: 10px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Authentication ────────────────────────────────────────────────────
def check_password():
    """Simple password gate."""
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


# ── Data Loading ──────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_all_data():
    """Load all portfolio data from JSON files."""
    data = load_holdings()
    transactions = load_transactions()
    cash = load_cash()
    nav = load_nav_history()
    return data, transactions, cash, nav


def fetch_live_prices() -> dict:
    """
    Fetch live prices. Uses cached prices from data/live_prices.json.
    The file is updated by the refresh mechanism.
    """
    prices_path = DATA_DIR / "live_prices.json"
    if prices_path.exists():
        with open(prices_path) as f:
            price_data = json.load(f)
        return price_data.get("prices", {})
    return {}


def save_live_prices(prices: dict):
    """Save live prices to disk."""
    with open(DATA_DIR / "live_prices.json", "w") as f:
        json.dump({
            "prices": prices,
            "updated_at": datetime.now().isoformat(),
        }, f, indent=2)


data, transactions, cash_data, nav_history = load_all_data()
live_prices = fetch_live_prices()
has_live = len(live_prices) > 0
pdb_context = load_pdb_context()


# ── Helper Functions ──────────────────────────────────────────────────
def format_inr(value, show_sign=False):
    """Format number as INR with lakhs/crores notation."""
    if value is None:
        return "-"
    abs_val = abs(value)
    sign = "-" if value < 0 else ("+" if show_sign and value > 0 else "")
    if abs_val >= 1e7:
        return f"{sign}{abs_val / 1e7:,.2f} Cr"
    elif abs_val >= 1e5:
        return f"{sign}{abs_val / 1e5:,.2f} L"
    else:
        return f"{sign}{abs_val:,.0f}"


def format_inr_full(value):
    """Format as full INR number with commas."""
    if value is None:
        return "-"
    return f"{value:,.0f}"


def color_pnl(val):
    """Return color + background based on P&L value."""
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: #15803d; background-color: #dcfce7; font-weight: 600"
        elif val < 0:
            return "color: #b91c1c; background-color: #fee2e2; font-weight: 600"
        else:
            return "color: #6b7280"
    return ""


def color_weight(val):
    """Gradient background for weight % - darker = higher concentration."""
    if not isinstance(val, (int, float)):
        return ""
    if val >= 10:
        return "background-color: #1e3a5f; color: white; font-weight: 700"
    elif val >= 7:
        return "background-color: #2563eb; color: white; font-weight: 600"
    elif val >= 5:
        return "background-color: #60a5fa; color: white; font-weight: 600"
    elif val >= 3:
        return "background-color: #bfdbfe; color: #1e3a5f; font-weight: 500"
    elif val >= 1:
        return "background-color: #eff6ff; color: #1e3a5f"
    else:
        return "color: #9ca3af"


def make_holdings_df(holdings: list, use_live: bool = True) -> pd.DataFrame:
    """Convert holdings list to a display DataFrame."""
    rows = []
    for h in holdings:
        if use_live and "live_price" in h:
            price = h["live_price"]
            mval = h["live_market_value"]
            gl = h["live_gl"]
            pct = h["live_pct_gl"]
        else:
            price = h.get("market_price", 0)
            mval = h.get("market_value", 0)
            gl = h.get("total_gl", 0)
            pct = h.get("pct_gl", 0)

        rows.append({
            "Security": h["security"],
            "Ticker": h.get("ticker", ""),
            "Sector": h.get("pdb_sector", "-") or "-",
            "Demat": h.get("demat", ""),
            "Qty": int(h["quantity"]),
            "Avg Cost": round(h.get("unit_cost", 0), 2),
            "Invested": round(h["total_cost"], 0),
            "CMP": round(price, 2),
            "Market Value": round(mval, 0),
            "P&L": round(gl, 0),
            "P&L %": round(pct, 2),
            "Weight %": round(h.get("weight_pct", 0), 2),
            "Target": round(h["target_price"], 0) if h.get("target_price") else None,
            "Upside %": round(h["upside_pct"], 1) if h.get("upside_pct") else None,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Market Value", ascending=False).reset_index(drop=True)
    return df


def make_consolidated_df(holdings: list, use_live: bool = True) -> pd.DataFrame:
    """Make consolidated holdings DataFrame (merged across demats)."""
    consolidated = consolidate_holdings(holdings, use_live)

    # Compute weightages on consolidated
    total_value = sum(
        c["live_market_value"] if use_live else c["market_value"]
        for c in consolidated
    )

    rows = []
    for c in consolidated:
        val = c["live_market_value"] if use_live else c["market_value"]
        weight = (val / total_value * 100) if total_value > 0 else 0
        # Look up target from PDB context
        ctx = pdb_context.get(c["security"], {})
        tp = ctx.get("target_price") or ctx.get("opp_target_price")
        upside = None
        if tp and c.get("live_price") and c["live_price"] > 0:
            upside = ((float(tp) / c["live_price"]) - 1) * 100

        rows.append({
            "Security": c["security"],
            "Ticker": c["ticker"],
            "Sector": ctx.get("sector", "-") or "-",
            "Accounts": ", ".join(c["demats"]),
            "Total Qty": int(c["total_quantity"]),
            "Avg Cost": round(c["avg_cost"], 2),
            "Invested": round(c["total_cost"], 0),
            "CMP": round(c.get("live_price", 0), 2),
            "Market Value": round(val, 0),
            "P&L": round(c["total_gl"], 0),
            "P&L %": round(c["pct_gl"], 2),
            "Weight %": round(weight, 2),
            "Target": round(float(tp), 0) if tp else None,
            "Upside %": round(upside, 1) if upside is not None else None,
        })

    return pd.DataFrame(rows)


def color_upside(val):
    """Color upside % with intensity gradient."""
    if not isinstance(val, (int, float)):
        return ""
    if val >= 100:
        return "background-color: #14532d; color: white; font-weight: 700"
    elif val >= 50:
        return "background-color: #15803d; color: white; font-weight: 600"
    elif val >= 20:
        return "background-color: #dcfce7; color: #15803d; font-weight: 600"
    elif val >= 0:
        return "color: #16a34a"
    elif val >= -10:
        return "color: #b91c1c"
    else:
        return "background-color: #fee2e2; color: #b91c1c; font-weight: 600"


def color_txn_type(val):
    """Color transaction type: buy = green, sell = red, transfer = blue."""
    if not isinstance(val, str):
        return ""
    v = val.lower()
    if "buy" in v:
        return "color: #15803d; font-weight: 600"
    elif "sell" in v:
        return "color: #b91c1c; font-weight: 600"
    elif "security in" in v:
        return "color: #2563eb; font-weight: 600"
    return ""


def make_transactions_df(transactions: list, account_filter: str = None) -> pd.DataFrame:
    """Convert transactions to DataFrame."""
    if not transactions:
        return pd.DataFrame()

    rows = []
    for t in transactions:
        if account_filter and t.get("account") != account_filter:
            continue
        rows.append({
            "Date": t["tran_date"],
            "Type": t["type"],
            "Security": t["security"],
            "Qty": int(t["quantity"]),
            "Price": round(t["unit_price"], 2),
            "Amount": round(t["settlement_amount"], 0),
            "Account": t.get("account", ""),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
    return df


def render_kpis(summary: dict, nav_value: float = None):
    """Render KPI metric cards."""
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric(
            "Equity Value",
            format_inr(summary["total_equity_value"]),
        )
    with c2:
        st.metric(
            "Invested Cost",
            format_inr(summary["total_invested_cost"]),
        )
    with c3:
        gl = summary["total_unrealized_gl"]
        st.metric(
            "Unrealized P&L",
            format_inr(gl, show_sign=True),
            delta=f"{summary['pct_unrealized_gl']:.2f}%",
        )
    with c4:
        st.metric(
            "Cash",
            format_inr(summary["total_cash"]),
        )
    with c5:
        if nav_value is not None:
            st.metric(
                "NAV",
                f"{nav_value:,.2f}",
                delta=f"{((nav_value / 1000) - 1) * 100:.2f}% since inception",
            )
        else:
            st.metric("NAV", "Pending", help="NAV base will be set on April 17, 2026")


def render_holdings_table(df: pd.DataFrame):
    """Render a styled holdings table."""
    if df.empty:
        st.info("No holdings data available.")
        return

    subset_map = [
        (color_pnl, ["P&L", "P&L %"]),
        (color_weight, ["Weight %"]),
    ]
    if "Upside %" in df.columns:
        subset_map.append((color_upside, ["Upside %"]))

    styled = df.style
    for fn, cols in subset_map:
        valid_cols = [c for c in cols if c in df.columns]
        if valid_cols:
            styled = styled.map(fn, subset=valid_cols)

    fmt = {
        "Invested": "{:,.0f}",
        "Market Value": "{:,.0f}",
        "P&L": "{:+,.0f}",
        "P&L %": "{:+.2f}%",
        "Weight %": "{:.2f}%",
        "CMP": "{:,.2f}",
        "Avg Cost": "{:,.2f}",
        "Qty": "{:,}",
    }
    if "Target" in df.columns:
        fmt["Target"] = lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
    if "Upside %" in df.columns:
        fmt["Upside %"] = lambda x: f"{x:+.1f}%" if pd.notna(x) else "-"

    styled = styled.format(fmt)

    st.dataframe(
        styled,
        use_container_width=True,
        height=min(500, 45 + len(df) * 36),
        hide_index=True,
    )


def render_account_view(holdings: list, cash_balances: dict, transactions: list,
                        account_filter: str, view_label: str, use_live: bool = True):
    """Render a single account view (BNS or NJS)."""
    # Compute weightages
    holdings = compute_weightages(holdings, use_live)

    # Summary
    summary = compute_portfolio_summary(holdings, cash_balances, use_live)
    nav_value = compute_nav(summary["total_portfolio_value"], nav_history) if nav_history.get("base_portfolio_value") else None
    render_kpis(summary, nav_value)

    st.markdown("---")

    # Holdings table
    st.subheader(f"Holdings ({summary['num_holdings']} stocks)")
    df = make_holdings_df(holdings, use_live)
    render_holdings_table(df)

    # Transactions
    if transactions:
        with st.expander("Recent Transactions"):
            txn_df = make_transactions_df(transactions, account_filter)
            if not txn_df.empty:
                txn_styled = txn_df.style.map(
                    color_txn_type, subset=["Type"]
                ).format({
                    "Qty": "{:,}",
                    "Price": "{:,.2f}",
                    "Amount": "{:,.0f}",
                })
                st.dataframe(txn_styled, use_container_width=True, hide_index=True)
            else:
                st.info("No transactions for this account.")


# ── Main Layout ───────────────────────────────────────────────────────
# Header
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
        st.markdown(f'<p class="sub-header">Using statement prices (no live data yet)</p>', unsafe_allow_html=True)

with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Refresh Prices", use_container_width=True, help="Fetch latest market prices"):
        # This will be triggered - we'll try to fetch from available sources
        st.info("Price refresh requires market hours. Using latest available data.")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────
tab_bns, tab_njs, tab_combined, tab_upload = st.tabs([
    "BNS (Bhowli Nikhil Shah)",
    "NJS (Nikhil Jitendra Shah)",
    "Combined Portfolio",
    "Upload & Settings",
])

# Prepare data
bns_holdings = get_bns_holdings(data, live_prices, pdb_context)
njs_holdings = get_njs_holdings(data, live_prices, pdb_context)
all_holdings = bns_holdings + njs_holdings

bns_cash = get_bns_cash(cash_data)
njs_cash = get_njs_cash(cash_data)
all_cash = get_all_cash(cash_data)

use_live = has_live

# ── BNS Tab ──────────────────────────────────────────────────────────
with tab_bns:
    render_account_view(bns_holdings, bns_cash, transactions, "BNS", "BNS", use_live)

# ── NJS Tab ──────────────────────────────────────────────────────────
with tab_njs:
    render_account_view(njs_holdings, njs_cash, transactions, "NJS", "NJS", use_live)

# ── Combined Tab ─────────────────────────────────────────────────────
with tab_combined:
    # KPIs
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
        acct_rows.append({
            "Account": label,
            "Equity Value": round(s["total_equity_value"], 0),
            "Invested Cost": round(s["total_invested_cost"], 0),
            "Cash": round(s["total_cash"], 0),
            "Total Value": round(s["total_portfolio_value"], 0),
            "P&L": round(s["total_unrealized_gl"], 0),
            "P&L %": round(s["pct_unrealized_gl"], 2),
        })
    acct_df = pd.DataFrame(acct_rows)
    st.dataframe(
        acct_df.style.map(color_pnl, subset=["P&L", "P&L %"]).format({
            "Equity Value": "{:,.0f}",
            "Invested Cost": "{:,.0f}",
            "Cash": "{:+,.0f}",
            "Total Value": "{:,.0f}",
            "P&L": "{:+,.0f}",
            "P&L %": "{:+.2f}%",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # Consolidated holdings
    st.subheader(f"Consolidated Holdings ({combined_summary['num_holdings']} stocks)")
    consolidated_df = make_consolidated_df(all_with_weights, use_live)
    if not consolidated_df.empty:
        styled = consolidated_df.style.map(
            color_pnl, subset=["P&L", "P&L %"]
        ).map(
            color_weight, subset=["Weight %"]
        )
        if "Upside %" in consolidated_df.columns:
            styled = styled.map(color_upside, subset=["Upside %"])
        styled = styled.format({
            "Invested": "{:,.0f}",
            "Market Value": "{:,.0f}",
            "P&L": "{:+,.0f}",
            "P&L %": "{:+.2f}%",
            "Weight %": "{:.2f}%",
            "CMP": "{:,.2f}",
            "Avg Cost": "{:,.2f}",
            "Total Qty": "{:,}",
            "Target": lambda x: f"{x:,.0f}" if pd.notna(x) else "-",
            "Upside %": lambda x: f"{x:+.1f}%" if pd.notna(x) else "-",
        })
        st.dataframe(styled, use_container_width=True, height=min(650, 45 + len(consolidated_df) * 36), hide_index=True)

    # Research Context (from Portfolio Dashboard - read-only)
    if pdb_context:
        st.markdown("---")
        st.subheader("Research Context")
        st.caption("Source: Portfolio Dashboard (read-only)")

        # Build research cards for stocks that have data
        research_stocks = sorted(
            [(sec, ctx) for sec, ctx in pdb_context.items()
             if ctx.get("risks") or ctx.get("thesis") or ctx.get("target_basis") or ctx.get("basis")],
            key=lambda x: x[0]
        )

        if research_stocks:
            for sec, ctx in research_stocks:
                tp = ctx.get("target_price") or ctx.get("opp_target_price")
                irr = ctx.get("irr") or ctx.get("opp_irr")
                irr_str = f"{float(irr)*100:.0f}%" if irr else "-"
                tp_str = f"{float(tp):,.0f}" if tp else "-"
                outlook = ctx.get("outlook", "-")
                basis = ctx.get("basis") or ctx.get("target_basis") or "-"

                with st.expander(f"{sec}  |  Target: {tp_str}  |  IRR: {irr_str}  |  Outlook: {outlook}"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if ctx.get("thesis"):
                            st.markdown(f"**Thesis:** {ctx['thesis']}")
                        if basis and basis != "-":
                            st.markdown(f"**Basis:** {basis}")
                        if ctx.get("exit_multiple"):
                            st.markdown(f"**Exit Multiple:** {ctx['exit_multiple']}x")
                    with col_b:
                        if ctx.get("risks"):
                            st.markdown(f"**Risks:** {ctx['risks']}")
        else:
            st.info("No research context available yet.")

    # NAV Chart
    if nav_history.get("history"):
        st.markdown("---")
        st.subheader("Portfolio NAV")
        nav_df = pd.DataFrame(nav_history["history"])
        nav_df["date"] = pd.to_datetime(nav_df["date"])
        st.line_chart(nav_df.set_index("date")["nav"], use_container_width=True)

    # All transactions
    if transactions:
        with st.expander("All Recent Transactions"):
            txn_df = make_transactions_df(transactions)
            if not txn_df.empty:
                txn_styled = txn_df.style.map(
                    color_txn_type, subset=["Type"]
                ).format({
                    "Qty": "{:,}",
                    "Price": "{:,.2f}",
                    "Amount": "{:,.0f}",
                })
                st.dataframe(txn_styled, use_container_width=True, hide_index=True)


# ── Upload Tab ───────────────────────────────────────────────────────
with tab_upload:
    st.subheader("Upload Ambit Statements")
    st.markdown("Upload new Ambit holding or transaction statement PDFs. The dashboard will auto-detect the account and update data.")

    uploaded_files = st.file_uploader(
        "Drop Ambit PDF statements here",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader",
    )

    if uploaded_files:
        for uploaded_file in uploaded_files:
            # Save to uploads folder
            save_path = UPLOADS_DIR / uploaded_file.name
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            st.info(f"Processing: {uploaded_file.name}")

            try:
                # Try as holding statement first
                if "holding" in uploaded_file.name.lower():
                    result = parse_holding_statement(str(save_path))
                    _update_holdings(result)
                    st.success(
                        f"Holding statement parsed: {result['short_name']} "
                        f"({len(result['holdings'])} equity positions, "
                        f"report date: {result['report_date']})"
                    )
                elif "transaction" in uploaded_file.name.lower():
                    result = parse_transaction_statement(str(save_path))
                    _update_transactions(result)
                    st.success(
                        f"Transaction statement parsed: {result['short_name']} "
                        f"({len(result['transactions'])} equity transactions, "
                        f"period: {result['from_date']} to {result['to_date']})"
                    )
                else:
                    # Try holding first, then transaction
                    try:
                        result = parse_holding_statement(str(save_path))
                        _update_holdings(result)
                        st.success(f"Detected as holding statement: {result['short_name']}")
                    except Exception:
                        result = parse_transaction_statement(str(save_path))
                        _update_transactions(result)
                        st.success(f"Detected as transaction statement: {result['short_name']}")
            except Exception as e:
                st.error(f"Failed to parse {uploaded_file.name}: {str(e)}")

        if st.button("Apply Changes & Refresh"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    # Cash balance editor
    st.subheader("Cash Balances")
    st.markdown("Update cash positions manually.")

    cash_col1, cash_col2 = st.columns(2)
    with cash_col1:
        bns_cash_val = st.number_input(
            "BNS Ambit Cash",
            value=float(cash_data.get("balances", {}).get("BNS_Ambit", 0)),
            step=10000.0,
            format="%.2f",
        )
    with cash_col2:
        njs_cash_val = st.number_input(
            "NJS Ambit Cash",
            value=float(cash_data.get("balances", {}).get("NJS_Ambit", 0)),
            step=10000.0,
            format="%.2f",
        )

    if st.button("Update Cash Balances"):
        cash_data["balances"]["BNS_Ambit"] = bns_cash_val
        cash_data["balances"]["NJS_Ambit"] = njs_cash_val
        cash_data["as_of"] = datetime.now().strftime("%d/%m/%Y")
        with open(DATA_DIR / "cash.json", "w") as f:
            json.dump(cash_data, f, indent=2)
        st.success("Cash balances updated.")
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    # NAV initialization
    st.subheader("NAV Settings")
    if nav_history.get("base_portfolio_value"):
        st.info(
            f"NAV Base: {nav_history['base_value']} on {nav_history['base_date']} "
            f"(Portfolio value: {format_inr(nav_history['base_portfolio_value'])})"
        )
    else:
        st.warning("NAV base not yet set. It will be initialized on the next refresh after April 17, 2026.")
        if st.button("Initialize NAV Base Now (using current portfolio value)"):
            all_h = get_all_holdings(data, live_prices, pdb_context)
            all_c = get_all_cash(cash_data)
            summary = compute_portfolio_summary(all_h, all_c, has_live)
            nav_h = initialize_nav_base(summary["total_portfolio_value"])
            st.success(f"NAV base set to 1000 at portfolio value {format_inr(summary['total_portfolio_value'])}")
            st.cache_data.clear()
            st.rerun()


# ── Helper functions for upload processing ────────────────────────────
def _update_holdings(parsed: dict):
    """Update holdings.json with newly parsed holding statement."""
    holdings_path = DATA_DIR / "holdings.json"

    if holdings_path.exists():
        with open(holdings_path) as f:
            existing = json.load(f)
    else:
        existing = {"accounts": [], "last_updated": None}

    # Find or create account entry
    acct_id = parsed["account_id"]
    found = False
    for i, acct in enumerate(existing["accounts"]):
        if acct["account_id"] == acct_id:
            existing["accounts"][i] = {
                "account_id": acct_id,
                "owner_name": parsed["owner_name"],
                "short_name": parsed["short_name"],
                "broker": parsed["broker"],
                "report_date": parsed["report_date"],
                "holdings": parsed["holdings"],
                "equity_total_cost": parsed["equity_total_cost"],
                "equity_total_market_value": parsed["equity_total_market_value"],
            }
            found = True
            break

    if not found:
        existing["accounts"].append({
            "account_id": acct_id,
            "owner_name": parsed["owner_name"],
            "short_name": parsed["short_name"],
            "broker": parsed["broker"],
            "report_date": parsed["report_date"],
            "holdings": parsed["holdings"],
            "equity_total_cost": parsed["equity_total_cost"],
            "equity_total_market_value": parsed["equity_total_market_value"],
        })

    existing["last_updated"] = datetime.now().isoformat()

    with open(holdings_path, "w") as f:
        json.dump(existing, f, indent=2)


def _update_transactions(parsed: dict):
    """Update transactions.json with newly parsed transaction statement."""
    txn_path = DATA_DIR / "transactions.json"

    if txn_path.exists():
        with open(txn_path) as f:
            existing = json.load(f)
    else:
        existing = []

    # Add account tag to each transaction
    for t in parsed["transactions"]:
        t["account"] = parsed["short_name"]

    # Remove old transactions for this account in the same date range
    acct = parsed["short_name"]
    new_dates = set(t["tran_date"] for t in parsed["transactions"])
    existing = [t for t in existing if not (t.get("account") == acct and t["tran_date"] in new_dates)]

    # Add new
    existing.extend(parsed["transactions"])

    # Sort by date descending
    existing.sort(key=lambda x: x["tran_date"], reverse=True)

    with open(txn_path, "w") as f:
        json.dump(existing, f, indent=2)
