from factor_lab.universe import DEFAULT_UNIVERSE, DEFAULT_UNIVERSE_PATH, is_excluded_instrument_name, is_known_etf_symbol, is_supported_symbol, load_packaged_universe_frame, normalize_exchange, parse_nasdaq_symbol_directory, parse_sec_company_tickers_exchange, universe_frame_for_symbols
import pandas as pd


def test_default_universe_has_at_least_2000_stock_symbols_and_no_etfs():
    frame = load_packaged_universe_frame()
    assert len(DEFAULT_UNIVERSE) >= 2000
    assert len(frame) >= 2000
    assert frame["symbol"].is_unique
    assert not frame["is_etf"].any()
    assert set(frame["asset_type"]) == {"stock"}
    assert {"SPY", "QQQ", "IWM", "XLK", "XLF", "XLV"}.isdisjoint(set(frame["symbol"]))
    assert {"symbol", "name", "asset_type", "exchange", "source", "is_etf"}.issubset(frame.columns)


def test_raw_packaged_universe_resource_is_stock_only_not_runtime_only():
    raw = pd.read_csv(DEFAULT_UNIVERSE_PATH)
    assert len(raw) >= 2000
    assert raw["symbol"].is_unique
    assert not raw["is_etf"].astype(bool).any()
    assert set(raw["asset_type"]) == {"stock"}
    assert not raw["name"].map(is_excluded_instrument_name).any()
    assert {
        "SPY",
        "QQQ",
        "IWM",
        "XLK",
        "XLF",
        "XLV",
        "PHYS",
        "PDI",
        "QQQX",
        "BAR",
        "ECCU",
        "MGR",
        "PMTU",
        "PMTW",
        "BSTZ",
        "BTT",
        "PBT",
        "MTR",
        "SBR",
        "VVR",
        "GDV",
        "RVT",
        "GAB",
        "BCAT",
        "BDJ",
        "ECAT",
        "BTX",
        "BGR",
        "BLW",
        "GJR",
        "MCR",
        "BST",
        "BXDC",
        "ET",
        "EPD",
        "BIP",
        "BEP",
        "KRP",
        "DMLP",
    }.isdisjoint(set(raw["symbol"]))
    assert {"PLTR", "UBER", "SNOW", "BKU", "YOU", "ABR", "AUR", "EQR"}.issubset(set(raw["symbol"]))


def test_sec_company_tickers_exchange_parser():
    payload = (
        '{"fields":["cik","name","ticker","exchange"],"data":[[1,"Acme Corp","ACME","Nasdaq"]]}'
    )
    frame = parse_sec_company_tickers_exchange(payload)
    assert frame.loc[0, "symbol"] == "ACME"
    assert frame.loc[0, "asset_type"] == "stock"
    assert frame.loc[0, "exchange"] == "NASDAQ"


def test_exchange_labels_are_normalized_for_reporting():
    assert normalize_exchange("Nasdaq") == "NASDAQ"
    assert normalize_exchange("N") == "NYSE"
    assert normalize_exchange("A") == "NYSE American"
    assert normalize_exchange("P") == "NYSE Arca"
    assert normalize_exchange("") == "Unknown"


def test_sec_parser_filters_fund_like_instruments_by_name():
    payload = (
        '{"fields":["cik","name","ticker","exchange"],'
        '"data":[[1,"Sprott Physical Gold Trust","PHYS","NYSE Arca"],[2,"Acme Corp","ACME","Nasdaq"]]}'
    )
    frame = parse_sec_company_tickers_exchange(payload)
    assert list(frame["symbol"]) == ["ACME"]


def test_nasdaq_symbol_directory_parser_filters_tests_and_etfs():
    payload = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAA|AAA Corp|Q|N|N|100|N|N\nBBB|BBB ETF|Q|N|N|100|Y|N\nTEST|Test Issue|Q|Y|N|100|N|N\nFile Creation Time: today"
    frame = parse_nasdaq_symbol_directory(payload, source_name="fixture")
    assert list(frame["symbol"]) == ["AAA"]
    assert not frame["is_etf"].any()


def test_nasdaq_parser_can_retain_etf_evidence_for_refresh_merge():
    payload = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAA|AAA Corp|Q|N|N|100|N|N\nZZZ|ZZZ ETF|Q|N|N|100|Y|N\nFile Creation Time: today"
    frame = parse_nasdaq_symbol_directory(payload, source_name="fixture", include_etfs=True)
    assert set(frame["symbol"]) == {"AAA", "ZZZ"}
    assert frame.set_index("symbol").loc["ZZZ", "is_etf"]


def test_suffix_endings_do_not_drop_common_equities_and_metadata_excludes_derivatives():
    for symbol in [
        "UBER",
        "PLTR",
        "SNOW",
        "DOW",
        "BKU",
        "YOU",
        "ABR",
        "AUR",
        "WS",
        "WSC",
        "NWSA",
        "BRK-B",
    ]:
        assert is_supported_symbol(symbol)
    assert is_excluded_instrument_name("Acme Corp Warrants")
    assert is_excluded_instrument_name("Acme Corp Rights")
    assert is_excluded_instrument_name("Acme Corp Units")
    assert is_excluded_instrument_name("Acme 7.75% Notes due 2030")
    assert is_excluded_instrument_name("BlackRock Science & Technology Term Trust")
    assert is_excluded_instrument_name("BlackRock Science & Technology Trust")
    assert is_excluded_instrument_name("Permian Basin Royalty Trust")
    assert is_excluded_instrument_name("Invesco Senior Income Trust Common Stock (DE)")
    assert is_excluded_instrument_name("Enterprise Products Partners L.P.")
    assert is_excluded_instrument_name("Energy Transfer LP")
    assert not is_excluded_instrument_name("Preferred Bank")
    assert not is_excluded_instrument_name("BlackRock, Inc.")
    assert not is_excluded_instrument_name(
        "Equity Residential Common Shares of Beneficial Interest"
    )
    payload = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "UBER|Uber Technologies Inc. Common Stock|Q|N|N|100|N|N\n"
        "PLTR|Palantir Technologies Inc. Class A Common Stock|Q|N|N|100|N|N\n"
        "DOW|Dow Inc. Common Stock|Q|N|N|100|N|N\n"
        "EQR|Equity Residential Common Shares of Beneficial Interest|Q|N|N|100|N|N\n"
        "ECCU|Eagle Point Credit Company 7.75% Notes due 2030|Q|N|N|100|N|N\n"
        "BAR|GraniteShares Gold Trust Shares of Beneficial Interest|Q|N|N|100|N|N\n"
        "PBT|PERMIAN BASIN ROYALTY TRUST|Q|N|N|100|N|N\n"
        "BSTZ|BlackRock Science & Technology Term Trust|Q|N|N|100|N|N\n"
        "ACMEW|Acme Corp Warrants|Q|N|N|100|N|N\n"
        "ACMEU|Acme Corp Units|Q|N|N|100|N|N\n"
        "ACMER|Acme Corp Rights|Q|N|N|100|N|N\n"
        "File Creation Time: today"
    )
    frame = parse_nasdaq_symbol_directory(payload, source_name="fixture")
    assert set(frame["symbol"]) == {"UBER", "PLTR", "DOW", "EQR"}






class _FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload.encode("utf-8")






def test_known_etf_tickers_are_denied_as_custom_candidates():
    denied = ["SPY", "QQQ", "VUG", "VGT", "TQQQ", "SQQQ", "EFA", "EEM", "HYG", "LQD", "XBI", "XRT"]
    frame = universe_frame_for_symbols([*denied, "VDE", "UNKNOWN", "AAPL", "MSFT"])
    assert {"AAPL", "MSFT"}.issubset(set(frame["symbol"]))
    assert {*denied, "VDE", "UNKNOWN"}.isdisjoint(set(frame["symbol"]))
    assert all(is_known_etf_symbol(symbol) for symbol in denied)


def test_packaged_universe_excludes_leveraged_inverse_short_products():
    frame = load_packaged_universe_frame()
    assert not frame["name"].map(is_excluded_instrument_name).any()
    assert is_excluded_instrument_name("Direxion Daily Bear 3X Shares")
    assert is_excluded_instrument_name("GraniteShares 2x Long NVDA Daily ETF")
    assert is_excluded_instrument_name("GraniteShares 1.25x Long TSLA Daily ETF")
    assert "TSL" not in set(frame["symbol"])
    assert is_excluded_instrument_name("ProShares UltraShort QQQ")
