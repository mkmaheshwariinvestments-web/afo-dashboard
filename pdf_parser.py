"""
PDF Parser for Ambit Global Private Client statements.
Parses holding statements and transaction statements from raw text extraction.
"""

import re
import json
import pdfplumber
from datetime import datetime


# Account ID to name mapping
ACCOUNT_MAP = {
    "107997": {"name": "Bhowli Nikhil Shah", "short": "BNS", "broker": "Ambit"},
    "105737": {"name": "Nikhil Jitendra Shah", "short": "NJS", "broker": "Ambit"},
}


def parse_holding_statement(pdf_path: str) -> dict:
    """
    Parse an Ambit holding statement PDF.
    Returns dict with account info, report date, and equity holdings.
    """
    text = _extract_text(pdf_path)

    # Extract metadata
    owner_match = re.search(r"Owner\s*:\s*(\d+)\s+(.+)", text)
    date_match = re.search(r"Report Date\s*:\s*(\d{2}/\d{2}/\d{4})", text)

    if not owner_match or not date_match:
        raise ValueError(f"Could not extract metadata from {pdf_path}")

    account_id = owner_match.group(1).strip()
    owner_name = owner_match.group(2).strip()
    report_date = date_match.group(1).strip()
    account_info = ACCOUNT_MAP.get(account_id, {"name": owner_name, "short": "UNK", "broker": "Ambit"})

    # Extract only equity holdings (between "Direct Equity" and "Equity - Total" or "Commodity")
    equity_section = _extract_equity_section(text)
    holdings = _parse_holding_lines(equity_section)

    # Extract equity total for verification
    total_match = re.search(
        r"Direct Equity - Total\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+",
        text
    )
    total_cost = _parse_number(total_match.group(1)) if total_match else None
    total_market_value = _parse_number(total_match.group(2)) if total_match else None

    return {
        "account_id": account_id,
        "owner_name": owner_name,
        "short_name": account_info["short"],
        "broker": account_info["broker"],
        "report_date": report_date,
        "holdings": holdings,
        "equity_total_cost": total_cost,
        "equity_total_market_value": total_market_value,
    }


def parse_transaction_statement(pdf_path: str) -> dict:
    """
    Parse an Ambit transaction statement PDF.
    Returns dict with account info, date range, and equity transactions only.
    """
    text = _extract_text(pdf_path)

    # Extract metadata
    owner_match = re.search(r"Owner\s*:\s*(\d+)\s+(.+)", text)
    date_range_match = re.search(r"From\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", text)

    if not owner_match:
        raise ValueError(f"Could not extract owner from {pdf_path}")

    account_id = owner_match.group(1).strip()
    owner_name = owner_match.group(2).strip()
    account_info = ACCOUNT_MAP.get(account_id, {"name": owner_name, "short": "UNK", "broker": "Ambit"})

    from_date = date_range_match.group(1).strip() if date_range_match else None
    to_date = date_range_match.group(2).strip() if date_range_match else None

    # Extract equity transactions (Shares - Listed section, before Mutual Funds section)
    equity_txn_text = _extract_equity_transactions(text)
    transactions = _parse_transaction_lines(equity_txn_text)

    return {
        "account_id": account_id,
        "owner_name": owner_name,
        "short_name": account_info["short"],
        "broker": account_info["broker"],
        "from_date": from_date,
        "to_date": to_date,
        "transactions": transactions,
    }


def _extract_text(pdf_path: str) -> str:
    """Extract all text from a PDF."""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
    return full_text


def _extract_equity_section(text: str) -> str:
    """Extract only the Direct Equity section from holding statement text."""
    # Find "Direct Equity" start and "Direct Equity - Total" or "Equity - Total" end
    start = re.search(r"Direct Equity\n", text)
    end = re.search(r"Direct Equity - Total", text)

    if not start:
        # Try alternative pattern
        start = re.search(r"Equity\nDirect Equity", text)
        if start:
            start = re.search(r"Direct Equity", text[start.start():])
            if start:
                start = type('Match', (), {'end': lambda self: start.end() + text.index("Direct Equity")})()

    if start and end:
        return text[start.end():end.start()]
    elif start:
        # If no end marker, take until Commodity or end
        commodity_start = text.find("Commodity", start.end())
        reit_start = text.find("REIT", start.end())
        fixed_income_end = text.find("Fixed Income - Total", start.end())

        end_pos = len(text)
        for marker_pos in [commodity_start, reit_start, fixed_income_end]:
            if marker_pos > 0:
                end_pos = min(end_pos, marker_pos)

        return text[start.end():end_pos]
    return ""


def _parse_holding_lines(section_text: str) -> list:
    """
    Parse individual holding lines from the equity section.
    Format: SecurityName WA_Days Qty UnitCost TotalCost MarketPrice MarketValue Income TotalGL %GL IRR_L1Y IRR_Incep %Assets
    """
    holdings = []
    lines = section_text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("Direct Equity") or line.startswith("Equity"):
            continue

        # Pattern: Security name followed by numbers
        # The security name can have multiple words, then numeric fields follow
        match = re.match(
            r"^(.+?)\s+"           # Security name (greedy but lazy)
            r"(\d+)\s+"            # WA Days
            r"([\d,]+)\s+"         # Quantity
            r"([\d,.]+)\s+"        # Unit Cost
            r"([\d,]+(?:\.\d+)?)\s+"  # Total Cost (may or may not have decimals)
            r"([\d,.]+)\s+"        # Market Price
            r"([\d,]+(?:\.\d+)?)\s+"  # Market Value
            r"(\d+)\s+"            # Income
            r"(-?[\d,]+(?:\.\d+)?)\s+"  # Total G/L (can be negative)
            r"(-?[\d,.]+)\s+"      # % G/L
            r"(-|-?[\d,.]+)\s+"    # IRR L1Y (can be - or negative number)
            r"(-?[\d,.]+)\s+"      # IRR Incep
            r"([\d,.]+)$",         # % Assets
            line
        )

        if match:
            security_name = match.group(1).strip()
            holdings.append({
                "security": security_name,
                "wa_days": int(match.group(2)),
                "quantity": _parse_number(match.group(3)),
                "unit_cost": _parse_number(match.group(4)),
                "total_cost": _parse_number(match.group(5)),
                "market_price": _parse_number(match.group(6)),
                "market_value": _parse_number(match.group(7)),
                "income": _parse_number(match.group(8)),
                "total_gl": _parse_number(match.group(9)),
                "pct_gl": _parse_number(match.group(10)),
                "irr_incep": match.group(12) if match.group(12) != "-" else None,
                "pct_assets": _parse_number(match.group(13)),
            })

    return holdings


def _extract_equity_transactions(text: str) -> str:
    """Extract equity transaction section (Shares - Listed, before Mutual Funds)."""
    # Find start of transactions
    start = re.search(r"Shares - Listed\n", text)
    if not start:
        start = re.search(r"Current Period Settled Transactions\n", text)

    # Find end (Mutual Funds section or Transaction Summary)
    end_markers = ["Mutual Funds", "TRANSACTION STATEMENT SUMMARY"]
    end_pos = len(text)
    for marker in end_markers:
        pos = text.find(marker, start.end() if start else 0)
        if pos > 0:
            end_pos = min(end_pos, pos)

    if start:
        return text[start.end():end_pos]
    return text[:end_pos]


def _parse_transaction_lines(section_text: str) -> list:
    """
    Parse transaction lines.
    Format: TransactionType Date SettDate Security Exchange Qty UnitPrice Brkg STT SettlementAmount
    """
    transactions = []
    lines = section_text.strip().split("\n")

    # Transaction types we care about
    txn_types = [
        "Security in",
        "Buy and deposit funds",
        "Sell and withdraw cash",
        "Square up Buy",
        "Square up Sell",
    ]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip header lines and non-transaction lines
        skip_patterns = [
            "Transaction Description", "Current Period", "Shares - Listed",
            "Date", "Exchg", "Settlement"
        ]
        if any(line.startswith(p) for p in skip_patterns):
            continue

        # Try to match transaction line
        for txn_type in txn_types:
            if line.startswith(txn_type):
                remainder = line[len(txn_type):].strip()
                match = re.match(
                    r"(\d{2}/\d{2}/\d{4})\s+"       # Tran Date
                    r"(\d{2}/\d{2}/\d{4})\s+"       # Settlement Date
                    r"(.+?)\s+"                      # Security
                    r"(NSE|BSE)\s+"                  # Exchange
                    r"([\d,.]+)\s+"                  # Quantity
                    r"([\d,.]+)\s+"                  # Unit Price
                    r"([\d,.]+)\s+"                  # Brokerage
                    r"([\d,.]+)\s+"                  # STT
                    r"([\d,.]+)$",                   # Settlement Amount
                    remainder
                )
                if match:
                    transactions.append({
                        "type": txn_type,
                        "tran_date": match.group(1),
                        "settlement_date": match.group(2),
                        "security": match.group(3).strip(),
                        "exchange": match.group(4),
                        "quantity": _parse_number(match.group(5)),
                        "unit_price": _parse_number(match.group(6)),
                        "brokerage": _parse_number(match.group(7)),
                        "stt": _parse_number(match.group(8)),
                        "settlement_amount": _parse_number(match.group(9)),
                    })
                break

    return transactions


def _parse_number(s: str) -> float:
    """Parse a number string with commas and optional negative sign."""
    if s is None or s == "-" or s == "":
        return 0.0
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    import sys

    base = "/Users/yvs/Desktop/MIPL AI Workflows/clients/abhishek-family-office/Holding Data - Source of Truth"

    # Test holding statement parsing
    for fname in ["Holding Statement BNS - AMBIT.pdf", "Holding Statement NJS - AMBIT.pdf"]:
        path = f"{base}/{fname}"
        print(f"\n=== Parsing {fname} ===")
        result = parse_holding_statement(path)
        print(f"Account: {result['short_name']} ({result['account_id']})")
        print(f"Date: {result['report_date']}")
        print(f"Holdings: {len(result['holdings'])}")
        for h in result['holdings']:
            print(f"  {h['security']}: Qty={h['quantity']:.0f}, Cost={h['total_cost']:.0f}, MktVal={h['market_value']:.0f}, P&L={h['total_gl']:.0f} ({h['pct_gl']:.2f}%)")
        print(f"Total Cost: {result['equity_total_cost']}")
        print(f"Total MktVal: {result['equity_total_market_value']}")

    # Test transaction statement parsing
    for fname in ["BNS Transaction Statement - AMBIT.pdf", "Transaction Statement NJS - AMBIT.pdf"]:
        path = f"{base}/{fname}"
        print(f"\n=== Parsing {fname} ===")
        result = parse_transaction_statement(path)
        print(f"Account: {result['short_name']} ({result['account_id']})")
        print(f"Period: {result['from_date']} to {result['to_date']}")
        print(f"Equity Transactions: {len(result['transactions'])}")
        for t in result['transactions'][:5]:
            print(f"  {t['tran_date']} {t['type']}: {t['security']} Qty={t['quantity']:.0f} @ {t['unit_price']:.2f} = {t['settlement_amount']:.2f}")
        if len(result['transactions']) > 5:
            print(f"  ... and {len(result['transactions']) - 5} more")
