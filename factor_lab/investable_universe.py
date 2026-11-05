"""Current exchange admission layered on a reviewed Factor result."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re

from .integrated_data import BENCHMARKS

DIRECTORY = "https://www.nasdaqtrader.com/dynamic/SymDir/"
VENUES = {
    "Q": "NASDAQ", "N": "NYSE", "A": "NYSE American", "P": "NYSE Arca",
    "Z": "Cboe BZX", "V": "IEX", "F": "TXSE",
}
ETF_GROUPS = {
    "us_equity": "VTI VOO RSP MDY IWM IJR VUG VTV SCHD AVUV MTUM QUAL USMV VLUE",
    "international_equity": "VXUS VEA VWO",
    "us_sector": "XLC XLY XLP XLE XLF XLV XLI XLB XLRE XLK XLU",
    "fixed_income": "BND SGOV TLT LQD HYG TIP",
}
ETF_GROUP = {s: group for group, symbols in ETF_GROUPS.items() for s in symbols.split()}
ECHO_SOURCE = (
    "https://ir.echostar.com/news-releases/news-release-details/"
    "echostar-changing-stocker-ticker-sats-echo-marking-companys-next"
)
DEPOSITARY = re.compile(r"\b(?:deposit[ao]ry (?:shares?|receipts?)|ADRs?|ADSs?)\b", re.I)
OTHER_SECURITY = re.compile(
    r"\b(?:preferred (?:stock|shares?)|preference shares?|warrants?|subscription rights"
    r"|senior notes?|exchange traded notes?)\b|\bunits?\s*$", re.I
)
# Issuer filings identify these legacy entries as non-ETF closed-end funds.
CLOSED_END = {"ASA", "HQH", "SOR"}
LISTING_EXCLUSIONS = {
    "otc_legacy", "listing_unconfirmed", "ticker_reused", "venue_unreviewed",
    "other_security", "product_unreviewed", "product_mismatch",
}


def _directory(path, filename, symbol_column):
    raw = Path(path).read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if len(lines) < 3:
        raise ValueError(f"Incomplete directory: {filename}")
    trailer = re.fullmatch(r"File Creation Time: (\d{8}\d{2}:\d{2})\|+", lines[-1])
    if not trailer:
        raise ValueError(f"Missing or invalid creation timestamp: {filename}")
    created = datetime.strptime(trailer[1], "%m%d%Y%H:%M")
    reader = csv.DictReader(lines[:-1], delimiter="|")
    required = {symbol_column, "Security Name", "Test Issue", "ETF"}
    required |= {"Financial Status"} if symbol_column == "Symbol" else {"Exchange"}
    if not required <= set(reader.fieldnames or []):
        raise ValueError(f"Unexpected directory columns: {filename}")
    listings = {}
    for row in reader:
        symbol = row[symbol_column]
        if (not symbol or not row["Security Name"] or None in row or None in row.values()
                or row["Test Issue"] not in {"Y", "N"} or row["ETF"] not in {"Y", "N"}):
            raise ValueError(f"Malformed directory record: {filename}")
        if row["Test Issue"] == "Y":
            continue
        # Yahoo encodes US class-share dots as hyphens, e.g. BRK.B -> BRK-B.
        key = symbol.replace(".", "-")
        if key in listings:
            raise ValueError(f"Duplicate directory symbol: {symbol}")
        listings[key] = {
            "listedSymbol": symbol,
            "listingName": row["Security Name"].strip(),
            "exchange": VENUES.get(row.get("Exchange", "Q")),
            "exchangeCode": row.get("Exchange", "Q"),
            "isExchangeTradedProduct": row["ETF"] == "Y",
            "listingFinancialStatus": row.get("Financial Status"),
        }
    return listings, {
        "url": DIRECTORY + filename, "sha256": sha256(raw).hexdigest(),
        "createdAtEastern": created.isoformat(timespec="minutes"),
    }


def build_universe_screen(result, nasdaq_path, other_path):
    """Screen current candidates. The result's price eligibility is read-only."""
    from exchange_calendars import get_calendar
    import pandas as pd

    nasdaq, nasdaq_source = _directory(nasdaq_path, "nasdaqlisted.txt", "Symbol")
    other, other_source = _directory(other_path, "otherlisted.txt", "NASDAQ Symbol")
    directory_date = nasdaq_source["createdAtEastern"][:10]
    if directory_date != other_source["createdAtEastern"][:10]:
        raise ValueError("Exchange directories have different creation dates")
    if nasdaq.keys() & other.keys():
        raise ValueError("Exchange directories disagree on primary listing")
    listings = nasdaq | other

    data = result["data"]
    market_date = data["asOf"]
    if market_date > directory_date:
        raise ValueError("Exchange directories predate the Factor market result")
    start, end = pd.Timestamp(market_date), pd.Timestamp(directory_date)
    calendar = get_calendar("XNYS", start=start - pd.Timedelta(days=7), end=end + pd.Timedelta(days=7))
    sessions = calendar.sessions_in_range(start, end)
    if not len(sessions) or str(sessions[0].date()) != market_date:
        raise ValueError("Factor market date must be a completed exchange session")
    lag = len(sessions) - 1
    original = {r["symbol"]: r for r in data["symbols"]}
    if len(original) != len(data["symbols"]) or set(original) != set(data["requestedSymbols"]):
        raise ValueError("Factor universe inventory is incomplete or contains duplicates")
    additions = {s: {"symbol": s}
                 for s in sorted((ETF_GROUP.keys() | {"ECHO"}) - original.keys() - set(BENCHMARKS))}
    rows = []
    for symbol, origin in sorted((original | additions).items()):
        provider = origin.get("providerTicker", symbol)
        listing = listings.get(provider)
        row = {
            "symbol": symbol, "providerTicker": provider,
            "legacyName": origin.get("name"), "legacyExchange": origin.get("exchange"),
            "priorStatus": origin.get("status"), "quoteAsOf": origin.get("observedAt"),
            "priorExclusionReason": origin.get("reason"),
            "category": None, "etfGroup": ETF_GROUP.get(symbol),
            "listedSymbol": None, "listingName": None, "exchange": None,
            "exchangeCode": None, "isExchangeTradedProduct": None,
            "listingFinancialStatus": None, "identitySource": None,
        }
        if symbol in additions:
            market_decision = "provider_data_required"
        elif origin["status"] != "eligible" or origin.get("observedAt") != market_date:
            market_decision = "market_filter"
        else:
            market_decision = "eligible" if lag <= 1 else "market_data_stale"
        if listing:
            row.update(listing)
        if symbol in BENCHMARKS:
            decision = "benchmark_only"
        elif symbol == "SATS" and listing and "Strive" in listing["listingName"]:
            decision = "ticker_reused"
            row["identitySource"] = ECHO_SOURCE
        elif not listing:
            decision = "otc_legacy" if origin.get("exchange") == "OTC" else "listing_unconfirmed"
        elif not listing["exchange"]:
            decision = "venue_unreviewed"
        elif symbol == "ECHO" and "EchoStar" not in listing["listingName"]:
            decision = "product_mismatch"
        elif listing["isExchangeTradedProduct"]:
            row["category"] = "etf" if symbol in ETF_GROUP else "unreviewed_etp"
            decision = market_decision if symbol in ETF_GROUP else "product_unreviewed"
        elif symbol in ETF_GROUP:
            decision = "product_mismatch"
        elif symbol in CLOSED_END or OTHER_SECURITY.search(listing["listingName"]) and (
            not DEPOSITARY.search(listing["listingName"])
        ):
            decision = "other_security"
        else:
            row["category"] = "adr" if DEPOSITARY.search(listing["listingName"]) else "equity"
            if symbol == "ECHO":
                row["identitySource"] = ECHO_SOURCE
            decision = market_decision
        row["decision"] = decision
        rows.append(row)

    by_symbol = {row["symbol"]: row for row in rows}
    holdings = result.get("selection", {}).get("holdings", [])
    return {
        "schemaVersion": "factor-exchange-screen/v1",
        "listingAsOfEastern": directory_date,
        "marketDataAsOf": market_date,
        "marketSessionLag": lag,
        "sourceResultId": result["resultIdentity"]["resultId"],
        "sources": [nasdaq_source, other_source],
        "benchmarkOnly": list(BENCHMARKS),
        "decisionCounts": dict(Counter(row["decision"] for row in rows)),
        "eligibleSymbols": [row["symbol"] for row in rows
                            if row["decision"] == "eligible" and row["category"] in {"equity", "adr"}],
        "eligibleEtfSymbols": [row["symbol"] for row in rows
                               if row["decision"] == "eligible" and row["category"] == "etf"],
        "listedEtfCandidates": [row["symbol"] for row in rows if row["category"] == "etf"],
        "existingHoldingsWithListingIssues": [
            {**holding, "decision": by_symbol[holding["symbol"]]["decision"]}
            for holding in holdings
            if holding["symbol"] in by_symbol and by_symbol[holding["symbol"]]["decision"]
            in LISTING_EXCLUSIONS
        ],
        "rows": rows,
    }


def write_universe_screen(result_path, nasdaq_path, other_path, output):
    result_bytes = Path(result_path).read_bytes()
    screen = build_universe_screen(json.loads(result_bytes), nasdaq_path, other_path)
    screen["sourceResultSha256"] = sha256(result_bytes).hexdigest()
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "screen.json").write_text(json.dumps(screen, indent=2, ensure_ascii=False) + "\n")
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(screen["rows"][0]))
    writer.writeheader()
    writer.writerows(screen["rows"])
    (directory / "universe.csv").write_text(stream.getvalue(), encoding="utf-8")
    return screen


def apply_exchange_screen(market, nasdaq_path, other_path):
    """Derive a local stock-selection snapshot for one evidenced signal date."""
    from dataclasses import replace

    from .integrated_service import data_inventory

    if "exchangeScreen" in market.metadata:
        raise ValueError("Choose the original frozen market snapshot")
    as_of = str(market.prices.index[-1].date())
    parent_id = market.metadata["snapshotId"]
    result = {
        "resultIdentity": {"resultId": parent_id},
        "data": {
            "asOf": as_of, "symbols": data_inventory(market),
            "requestedSymbols": market.metadata["requestedSymbols"],
        },
    }
    screen = build_universe_screen(result, nasdaq_path, other_path)
    if screen["listingAsOfEastern"] != as_of:
        raise ValueError("A selection snapshot requires exchange directories for its final session")
    allowed = set(screen["eligibleSymbols"])
    active = market.eligibility.iloc[-1]
    rejected = {
        row["symbol"]: "separate_etf_pool" if row["category"] == "etf" else row["decision"]
        for row in screen["rows"]
        if row["symbol"] in active.index and active[row["symbol"]] and row["symbol"] not in allowed
    }
    eligibility = market.eligibility.copy()
    eligibility.loc[eligibility.index[-1], list(rejected)] = False
    metadata = dict(market.metadata)
    metadata.pop("snapshotId")
    metadata.pop("files", None)
    metadata["exchangeScreen"] = {
        "schemaVersion": screen["schemaVersion"], "signalDate": as_of,
        "parentSnapshotId": parent_id, "sources": screen["sources"], "excluded": rejected,
        "implementationSha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return replace(market, eligibility=eligibility, metadata=metadata)
