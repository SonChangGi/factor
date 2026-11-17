from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd

RESOURCE_DIR = Path(__file__).with_name("resources")
DEFAULT_UNIVERSE_PATH = RESOURCE_DIR / "default_universe.csv"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"




CORE_STOCK_SAMPLE_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "JPM",
    "UNH",
    "COST",
    "HD",
    "PG",
    "NFLX",
    "AMD",
    "ORCL",
    "AVGO",
    "TSLA",
    "LLY",
    "WMT",
    "XOM",
    "V",
]

# The packaged default no longer carries ETF rows. Keep an explicit deny-list so
# common benchmark, sector, international, bond, commodity, and leveraged ETF
# tickers cannot re-enter as user-supplied custom candidates after the resource
# rows are deleted. Benchmark prices may still be downloaded separately by the
# data layer for benchmark-relative metrics.
KNOWN_ETF_SYMBOLS = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "MDY",
        "RSP",
        "VTI",
        "VOO",
        "IVV",
        "SCHB",
        "ITOT",
        "XLK",
        "XLF",
        "XLV",
        "XLY",
        "XLP",
        "XLE",
        "XLI",
        "XLB",
        "XLU",
        "XLRE",
        "XLC",
        "SMH",
        "SOXX",
        "XBI",
        "XRT",
        "VUG",
        "VGT",
        "IWF",
        "IWD",
        "IWB",
        "EFA",
        "EEM",
        "VEA",
        "VWO",
        "IEFA",
        "IEMG",
        "ARKK",
        "TLT",
        "IEF",
        "SHY",
        "AGG",
        "BND",
        "HYG",
        "LQD",
        "TIP",
        "MUB",
        "GLD",
        "SLV",
        "USO",
        "UNG",
        "PHYS",
        "PSLV",
        "TQQQ",
        "SQQQ",
        "UPRO",
        "SPXU",
        "SSO",
        "SDS",
        "TNA",
        "TZA",
        "SOXL",
        "SOXS",
    }
)

# Backward-compatible alias for older callers; contents are now stock-only.
CORE_SAMPLE_SYMBOLS = CORE_STOCK_SAMPLE_SYMBOLS




def normalize_symbol(symbol: object) -> str:
    return str(symbol).strip().upper().replace(".", "-")


FORBIDDEN_INSTRUMENT_TERMS = (
    "2X",
    "3X",
    "-2X",
    "-3X",
    "LEVERAGED",
    "ULTRA",
    "ULTRAPRO",
    "DIREXION DAILY",
    "BEAR",
    "INVERSE",
    "SHORT ",
    "SHORT-",
    "BULL 2",
    "BULL 3",
    " DAILY BULL",
    " DAILY BEAR",
)

NON_STOCK_INSTRUMENT_PATTERNS = (
    r"\bETF\b",
    r"\bETN\b",
    r"EXCHANGE[- ]TRADED",
    r"\bINDEX FUND\b",
    r"\bMUTUAL FUND\b",
    r"\bCLOSED[- ]END FUND\b",
    r"\bFUND\b",
    r"\bFUNDS\b",
    r"\bPHYSICAL (GOLD|SILVER|PLATINUM|PALLADIUM)\b",
    r"\bSPROTT PHYSICAL\b",
    r"\bTREASURY\b",
    r"\bBOND\b",
    r"\bNOTES?\b",
    r"\bDEBENTURES?\b",
    r"\bDUE\s+20\d{2}\b",
    r"\bCOMMODIT(Y|IES)\b",
    r"\bCURRENCY\b",
    r"\b(GOLD|SILVER|PLATINUM|PALLADIUM)\s+TRUST\b",
    r"\bTRUST\s+SHARES?\b",
    r"\bROYALTY\s+TRUST\b",
    r"\bTERM\s+TRUST\b",
    r"\bTARGET\s+TERM\s+TRUST\b",
    r"\bMUNICIPAL\s+\d{4}\s+TARGET\s+TERM\s+TRUST\b",
    r"\bDIVIDEND\s+AND\s+INCOME\s+TRUST\b",
    r"\bEQUITY\s+TRUST\b",
    r"\bENHANCED\s+EQUITY\s+DIVIDEND\s+TRUST\b",
    r"\bSENIOR\s+INCOME\s+TRUST\b",
    r"\bCHARTER\s+INCOME\s+TRUST\b",
    r"\bLIMITED\s+DURATION\s+INCOME\s+TRUST\b",
    r"\bENERGY\s+AND\s+RESOURCES\s+TRUST\b",
    r"\bSMALL[- ]CAP\s+TRUST\b",
    r"\bBLACKROCK\b.*\bTRUST\b",
    r"\bBLACKSTONE\s+DIGITAL\s+INFRASTRUCTURE\s+TRUST\b",
    r"\bSTRATS\s+TRUST\b",
    r"\bSYNTHETIC\s+FIXED[- ]INCOME\b",
    r"\bL\.P\.",
    r"\bLP\b",
    r"\bLIMITED\s+PARTNERSHIP\b",
    r"\bWARRANTS?\b",
    r"\bRIGHTS?\b",
    r"\bUNITS?\b",
    r"\bPREFERRED\s+(STOCK|SHARES?|SECURIT(Y|IES)|SERIES|UNITS?|RIGHTS?|WARRANTS?|DEPOSITARY)\b",
    r"\bPREFERENCE\s+(STOCK|SHARES?|SECURIT(Y|IES))\b",
    r"\bDEPOSITARY SHARES\b",
)

EXCHANGE_ALIASES = {
    "NASDAQ": "NASDAQ",
    "NASDAQ GLOBAL SELECT MARKET": "NASDAQ",
    "NASDAQ GLOBAL MARKET": "NASDAQ",
    "NASDAQ CAPITAL MARKET": "NASDAQ",
    "NYSE": "NYSE",
    "NEW YORK STOCK EXCHANGE": "NYSE",
    "N": "NYSE",
    "NYSE AMERICAN": "NYSE American",
    "NYSE MKT": "NYSE American",
    "A": "NYSE American",
    "NYSE ARCA": "NYSE Arca",
    "P": "NYSE Arca",
    "CBOE": "Cboe",
    "CBOE BZX": "Cboe BZX",
    "Z": "Cboe BZX",
    "IEX": "IEX",
    "V": "IEX",
    "OTC": "OTC",
    "OTCQX": "OTC",
    "OTCQB": "OTC",
}


def is_supported_symbol(symbol: str) -> bool:
    # Some ordinary common stocks end in letters commonly used by derivatives
    # (for example PLTR/UBER/SNOW/BKU/YOU/ABR/AUR). Reject only structurally
    # invalid symbols here; derivative/unit/preferred filtering belongs in
    # provider metadata and instrument-name rules.
    return bool(re.match(r"^[A-Z][A-Z0-9-]{0,9}$", symbol))


def is_excluded_instrument_name(name: object) -> bool:
    upper = str(name).upper().replace("&", " AND ")
    if any(term in upper for term in FORBIDDEN_INSTRUMENT_TERMS):
        return True
    if any(re.search(pattern, upper) for pattern in NON_STOCK_INSTRUMENT_PATTERNS):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*X\b", upper):
        return True
    if re.search(r"\b\d+(?:\.\d+)?X\s+(LONG|SHORT)", upper):
        return True
    if " DAILY " in upper and (" LONG " in upper or " SHORT " in upper):
        return True
    return False


def normalize_exchange(exchange: object) -> str:
    if pd.isna(exchange):
        return "Unknown"
    cleaned = re.sub(r"\s+", " ", str(exchange or "").strip())
    if not cleaned:
        return "Unknown"
    return EXCHANGE_ALIASES.get(cleaned.upper(), cleaned)


def normalize_symbols(symbols: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if symbols is None:
        return list(DEFAULT_UNIVERSE)
    raw = symbols.replace("\n", ",").split(",") if isinstance(symbols, str) else list(symbols)
    out: list[str] = []
    for item in raw:
        symbol = normalize_symbol(item)
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def _base_columns() -> list[str]:
    return ["symbol", "name", "asset_type", "exchange", "source", "is_etf"]


def _normalize_frame(
    frame: pd.DataFrame,
    *,
    drop_duplicates: bool = True,
    exclude_by_name: bool = True,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_base_columns())
    out = frame.copy()
    for col in _base_columns():
        if col not in out:
            out[col] = ""
    out["symbol"] = out["symbol"].map(normalize_symbol)
    out["exchange"] = out["exchange"].map(normalize_exchange)
    out = out[out["symbol"].map(is_supported_symbol)]
    if exclude_by_name:
        out = out[~out["name"].map(is_excluded_instrument_name)]
    out["is_etf"] = out["is_etf"].map(lambda v: str(v).lower() in {"true", "1", "yes", "y"})
    out["asset_type"] = out.apply(
        lambda row: "etf" if bool(row["is_etf"]) else (str(row["asset_type"]).lower() or "stock"),
        axis=1,
    )
    if drop_duplicates:
        out = out.drop_duplicates("symbol", keep="first")
    return out[_base_columns()].reset_index(drop=True)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return _normalize_frame(frame, drop_duplicates=True, exclude_by_name=True)


def is_known_etf_symbol(symbol: object) -> bool:
    return normalize_symbol(symbol) in KNOWN_ETF_SYMBOLS


def stock_only_universe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = _clean_frame(frame)
    if cleaned.empty:
        return cleaned
    stock_mask = (
        ~cleaned["is_etf"]
        & cleaned["asset_type"].ne("etf")
        & ~cleaned["symbol"].map(is_known_etf_symbol)
    )
    return cleaned.loc[stock_mask].reset_index(drop=True)


def load_packaged_universe_frame(path: Path = DEFAULT_UNIVERSE_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"default universe resource missing: {path}")
    frame = pd.read_csv(path)
    return stock_only_universe_frame(frame)


def _load_default_symbols() -> list[str]:
    try:
        return load_packaged_universe_frame()["symbol"].tolist()
    except Exception:
        return list(CORE_STOCK_SAMPLE_SYMBOLS)


DEFAULT_UNIVERSE = _load_default_symbols()


def universe_frame_for_symbols(symbols: list[str] | tuple[str, ...] | str | None) -> pd.DataFrame:
    normalized = normalize_symbols(symbols)
    packaged = load_packaged_universe_frame().set_index("symbol")
    rows = []
    for symbol in normalized:
        if symbol in packaged.index:
            row = packaged.loc[symbol].to_dict()
            row["symbol"] = symbol
        else:
            # Fail closed for symbol-only custom inputs. Without provider
            # metadata we cannot prove an unknown ticker is an individual stock
            # rather than an ETF/ETN/fund, so user-supplied universes are
            # intersected with packaged/public stock metadata.
            continue
        rows.append(row)
    return stock_only_universe_frame(pd.DataFrame(rows))


def parse_sec_company_tickers_exchange(payload: str) -> pd.DataFrame:
    data = json.loads(payload)
    fields = data.get("fields", [])
    rows = []
    for raw in data.get("data", []):
        item = dict(zip(fields, raw, strict=False))
        symbol = normalize_symbol(item.get("ticker", ""))
        rows.append(
            {
                "symbol": symbol,
                "name": item.get("name", ""),
                "asset_type": "stock",
                "exchange": item.get("exchange", ""),
                "source": "sec-company-tickers-exchange",
                "is_etf": False,
            }
        )
    return stock_only_universe_frame(pd.DataFrame(rows))


def parse_nasdaq_symbol_directory(
    payload: str, *, source_name: str, include_etfs: bool = False
) -> pd.DataFrame:
    lines = [
        line
        for line in payload.splitlines()
        if "|" in line and not line.startswith("File Creation Time")
    ]
    if not lines:
        return pd.DataFrame(columns=_base_columns())
    reader = csv.DictReader(lines, delimiter="|")
    rows = []
    for row in reader:
        symbol = normalize_symbol(
            row.get("Symbol") or row.get("ACT Symbol") or row.get("NASDAQ Symbol") or ""
        )
        if row.get("Test Issue", "N").strip().upper() == "Y":
            continue
        is_etf = row.get("ETF", "N").strip().upper() == "Y"
        if is_etf and not include_etfs:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": (row.get("Security Name") or "").strip(),
                "asset_type": "etf" if is_etf else "stock",
                "exchange": (row.get("Exchange") or "NASDAQ").strip(),
                "source": source_name,
                "is_etf": is_etf,
            }
        )
    frame = pd.DataFrame(rows)
    if include_etfs:
        return _normalize_frame(frame, drop_duplicates=False, exclude_by_name=False)
    return stock_only_universe_frame(frame)
