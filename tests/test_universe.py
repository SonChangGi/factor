from factor_lab.universe import (
    DEFAULT_UNIVERSE,
    DEFAULT_UNIVERSE_PATH,
    NASDAQ_LISTED_URL,
    NASDAQ_OTHER_LISTED_URL,
    SEC_COMPANY_TICKERS_EXCHANGE_URL,
    _fetch_text_with_cache,
    build_public_universe_frame,
    is_excluded_instrument_name,
    is_known_etf_symbol,
    is_supported_symbol,
    load_packaged_universe_frame,
    normalize_exchange,
    parse_nasdaq_symbol_directory,
    parse_sec_company_tickers_exchange,
    universe_frame_for_symbols,
)
import pandas as pd
from datetime import UTC, datetime, timedelta


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


def test_public_universe_refresh_combined_output_is_stock_only(monkeypatch, tmp_path):
    sec_payload = (
        '{"fields":["cik","name","ticker","exchange"],'
        '"data":[[1,"AAA Corp","AAA","Nasdaq"],[2,"SPDR S&P 500 ETF Trust","SPY","NYSE Arca"],'
        '[3,"Invesco QQQ Trust","QQQ","Nasdaq"],[4,"Sprott Physical Gold Trust","PHYS","NYSE Arca"],'
        '[5,"ZZZ Holding Co","ZZZ","Nasdaq"]]}'
    )
    nasdaq_payload = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAA|AAA Corp|Q|N|N|100|N|N\nQQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\nZZZ|ZZZ ETF|Q|N|N|100|Y|N\nTEST|Test Issue|Q|Y|N|100|N|N\nFile Creation Time: today"
    other_payload = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nBBB|BBB Corp|N|BBB|N|100|N|BBB\nIWM|iShares Russell 2000 ETF|P|IWM|Y|100|N|IWM\nFile Creation Time: today"

    def fake_fetch(url, cache_dir, cache_name, retry_count, retry_backoff_seconds):
        payloads = {
            "sec_company_tickers_exchange.json": sec_payload,
            "nasdaqlisted.txt": nasdaq_payload,
            "otherlisted.txt": other_payload,
        }
        return payloads[cache_name], {
            "source": url,
            "status": "fixture",
            "cache_path": str(tmp_path / cache_name),
            "retries": 0,
        }

    monkeypatch.setattr("factor_lab.universe._fetch_text_with_cache", fake_fetch)

    result = build_public_universe_frame(cache_dir=tmp_path)

    assert list(result.frame["symbol"]) == ["AAA", "BBB"]
    assert not result.frame["is_etf"].any()
    assert set(result.frame["asset_type"]) == {"stock"}


def test_public_universe_refresh_urls_are_https(monkeypatch, tmp_path):
    assert SEC_COMPANY_TICKERS_EXCHANGE_URL.startswith("https://")
    assert NASDAQ_LISTED_URL.startswith("https://")
    assert NASDAQ_OTHER_LISTED_URL.startswith("https://")
    captured_urls = []

    def fake_fetch(url, cache_dir, cache_name, retry_count, retry_backoff_seconds, user_agent=None):
        captured_urls.append(url)
        payloads = {
            "sec_company_tickers_exchange.json": (
                '{"fields":["cik","name","ticker","exchange"],"data":[[1,"AAA Corp","AAA","Nasdaq"]]}'
            ),
            "nasdaqlisted.txt": (
                "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
                "BBB|BBB Corp|Q|N|N|100|N|N\n"
                "File Creation Time: today"
            ),
            "otherlisted.txt": (
                "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
                "CCC|CCC Corp|N|CCC|N|100|N|CCC\n"
                "File Creation Time: today"
            ),
        }
        return payloads[cache_name], {
            "source": url,
            "status": "fixture",
            "cache_path": str(tmp_path / cache_name),
            "retries": 0,
        }

    monkeypatch.setattr("factor_lab.universe._fetch_text_with_cache", fake_fetch)

    build_public_universe_frame(cache_dir=tmp_path)

    assert captured_urls
    assert all(url.startswith("https://") for url in captured_urls)


class _FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload.encode("utf-8")


def test_fetch_text_with_cache_refetches_stale_universe_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "stale.txt"
    cache_path.write_text("stale payload", encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(days=3)).timestamp()
    cache_path.touch()
    import os

    os.utime(cache_path, (old, old))
    fresh_payload = "fresh payload"

    monkeypatch.setattr(
        "factor_lab.universe.urlopen",
        lambda request, timeout=30: _FakeResponse(fresh_payload),
    )

    text, source = _fetch_text_with_cache(
        "https://example.test/stale.txt",
        tmp_path,
        "stale.txt",
        retry_count=0,
        retry_backoff_seconds=0.0,
        cache_ttl_days=1,
    )

    assert text == fresh_payload
    assert source["status"] == "fetched"
    assert source["cache_stale"] is True


def test_fetch_text_with_cache_uses_fresh_cache_without_network(monkeypatch, tmp_path):
    cache_path = tmp_path / "fresh.txt"
    cached_payload = "cached payload"
    cache_path.write_text(cached_payload, encoding="utf-8")

    def fail_network(*args, **kwargs):
        raise AssertionError("network should not be called for fresh cache")

    monkeypatch.setattr("factor_lab.universe.urlopen", fail_network)

    text, source = _fetch_text_with_cache(
        "https://example.test/fresh.txt",
        tmp_path,
        "fresh.txt",
        retry_count=0,
        retry_backoff_seconds=0.0,
        cache_ttl_days=1,
    )

    assert text == cached_payload
    assert source["status"] == "cache_hit"
    assert source["cache_fresh"] is True


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


def test_public_universe_refresh_records_partial_source_without_pit(monkeypatch, tmp_path):
    nasdaq_payload = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAA|AAA Corp|Q|N|N|100|N|N\nETFZ|ETFZ ETF|Q|N|N|100|Y|N\nFile Creation Time: today"
    other_payload = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nBBB|BBB Corp|N|BBB|N|100|N|BBB\nFile Creation Time: today"

    def fake_fetch(url, cache_dir, cache_name, retry_count, retry_backoff_seconds, user_agent=None):
        if cache_name == "sec_company_tickers_exchange.json":
            return None, {
                "source": url,
                "status": "failed",
                "error": "HTTP Error 403: Forbidden",
                "retries": 0,
            }
        payloads = {"nasdaqlisted.txt": nasdaq_payload, "otherlisted.txt": other_payload}
        return payloads[cache_name], {
            "source": url,
            "status": "fixture",
            "cache_path": str(tmp_path / cache_name),
            "retries": 0,
        }

    monkeypatch.setattr("factor_lab.universe._fetch_text_with_cache", fake_fetch)

    result = build_public_universe_frame(cache_dir=tmp_path, user_agent="test contact@example.com")

    assert list(result.frame["symbol"]) == ["AAA", "BBB"]
    assert not result.frame["is_etf"].any()
    summary = result.data_sources[result.data_sources["source"].eq("public-universe-refresh")].iloc[
        0
    ]
    assert summary["status"] == "partial_source_current_universe"
    assert not bool(summary["point_in_time_universe"])
    sec_row = result.data_sources[result.data_sources["status"].eq("failed")].iloc[0]
    assert sec_row["records"] == 0
    assert bool(sec_row["sec_user_agent_configured"])


def test_public_universe_refresh_surfaces_stale_cache_status(monkeypatch, tmp_path):
    sec_payload = (
        '{"fields":["cik","name","ticker","exchange"],'
        '"data":[[1,"AAA Corp","AAA","Nasdaq"],[2,"BBB Corp","BBB","NYSE"]]}'
    )
    nasdaq_payload = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAA|AAA Corp|Q|N|N|100|N|N\n"
        "File Creation Time: today"
    )
    other_payload = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "BBB|BBB Corp|N|BBB|N|100|N|BBB\n"
        "File Creation Time: today"
    )

    def fake_fetch(url, cache_dir, cache_name, retry_count, retry_backoff_seconds, user_agent=None):
        payloads = {
            "sec_company_tickers_exchange.json": sec_payload,
            "nasdaqlisted.txt": nasdaq_payload,
            "otherlisted.txt": other_payload,
        }
        status = (
            "stale_cache_fallback"
            if cache_name == "sec_company_tickers_exchange.json"
            else "fixture"
        )
        return payloads[cache_name], {
            "source": url,
            "status": status,
            "cache_path": str(tmp_path / cache_name),
            "retries": 0,
        }

    monkeypatch.setattr("factor_lab.universe._fetch_text_with_cache", fake_fetch)

    result = build_public_universe_frame(cache_dir=tmp_path)

    summary = result.data_sources[result.data_sources["source"].eq("public-universe-refresh")].iloc[
        0
    ]
    assert summary["status"] == "partial_or_stale_source_current_universe"
    assert "stale_cache_fallback" in set(result.data_sources["status"])
