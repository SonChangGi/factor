# 미국 거래소 유니버스

가격 데이터 기준일은 2026-11-03, Nasdaq Trader 상장 명부 생성 시각은 2026-11-04 21:31 미국 동부시간이다. 2026-11-05 한국시간에 내려받은 두 명부를 직전 검증 결과와 대조했다. 명부는 주 상장 거래소를 확인한다. 가격과 거래량은 기존 Factor 결과에서 가져왔으며, 두 시점은 CSV와 JSON에 각각 기록한다. [Nasdaq Trader 명부 정의](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs), [TXSE 거래소 코드](https://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2026-10).

| 기존 2,960종목 | 수 | 처리 |
| --- | ---: | --- |
| 상장 및 기존 시장 데이터 기준 통과 | 2,285 | 주식·ADR 후보. ADR은 108개 |
| 상장 확인, 기존 시장 데이터 기준 미충족 | 484 | 가격, 거래대금 또는 관측 부족 사유를 원자료에서 유지 |
| 기존 OTC 분류, 거래소 명부에 없음 | 119 | 제외. 이 중 15개는 기존 가격·거래대금 기준을 통과 |
| 현재 상장 확인 불가 | 68 | 보류. 상장폐지, 이전, 변경 등은 개별 증거 확인 후 분류 |
| 비ETF 폐쇄형 펀드 | 3 | ASA, HQH, SOR 제외 |
| 재사용 티커 | 1 | 기존 EchoStar의 SATS 제외. 현재 SATS는 Strive 우선주이며 EchoStar는 ECHO로 후보 등록 |

기존 11월 3일 보유 기록에서 BMWKY와 GWLIF의 합계는 7.75%였다. 거래소 상장 여부는 실제 매수 후보와 보유 구성에도 영향을 준다. ECHO의 과거 가격을 SATS에서 연결하려면 별도 증권 동일성 검증과 가격 재수집이 필요하다. [BMWKY OTC Markets](https://www.otcmarkets.com/stock/BMWKY/overview), [GWLIF OTC Markets](https://www.otcmarkets.com/stock/GWLIF/profile), [EchoStar 티커 변경 공지](https://ir.echostar.com/news-releases/news-release-details/echostar-changing-stocker-ticker-sats-echo-marking-companys-next).

주식 후보에는 NYSE, NYSE American, NYSE Arca, Nasdaq, Cboe BZX, TXSE, IEX 상장을 허용한다. 상장 ADR과 외국 발행사 보통주도 포함한다. Nasdaq 재무·상장 준수 상태 플래그는 별도 열에 표시한다. 비ETF 폐쇄형 펀드로 확인된 세 종목은 제외하고, 상장 BDC 보통주와 REIT 보통주는 주식 후보에 포함했다. 이름과 거래소 티커를 함께 쓰는 실용적인 선별이며, 전 종목의 CUSIP나 모든 역사적 티커 변경을 확인하는 방법은 아니다.

ETF는 기존 분석 후보에 없었다. 미국 주식 14개, 해외 주식 3개, 미국 섹터 11개, 채권 6개를 별도 후보군으로 등록했다. 이 34개는 거래소 명부에서 ETF 플래그를 확인했고, 기존 결과에 가격 이력이 없으므로 가격 검증 대기로 분류했다. ETF는 유사 노출이 겹치므로 자산군 안에서 분석한다. ETF 편입 평가에 시장가격 총수익, 거래대금, 운용사가 공개하는 30일 중간 호가 스프레드를 사용한다. SPY와 QQQ는 기존 벤치마크 역할을 유지한다. 현재 후보는 일반 ETF 위주로 선정했으며 일간 레버리지·인버스 상품과 ETN은 후보에 포함하지 않았다. [Vanguard ETF 목록](https://investor.vanguard.com/investment-products/list/etfs), [iShares ETF 목록](https://www.ishares.com/us/products/etf-investments), [State Street 섹터 ETF](https://www.ssga.com/us/en/individual/capabilities/equities/sector-investing/select-sector-etfs), [SEC ETF 공시 가이드](https://www.sec.gov/investment/exchange-traded-funds-small-entity-compliance-guide).

## 로컬 실행

검증된 Factor 결과와 같은 날 또는 이후 날짜의 거래소 명부를 사용한다. 가격 기준일이 명부보다 두 세션 이상 오래된 경우 주식 적격 목록을 비운다. 이 허용 간격은 현재 목록을 읽는 용도에만 적용한다.

```bash
curl -fSLo nasdaqlisted.txt https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
curl -fSLo otherlisted.txt https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt
python -m factor_lab.cli integrated-universe \
  --result site/data/integrated-result.json \
  --nasdaq nasdaqlisted.txt --other otherlisted.txt \
  --output outputs/new-exchange-screen
```

`universe.csv`에는 종목별 기존 분류, 상장 시장, 가격 기준, 편입·제외 사유를 기록한다. `screen.json`의 `eligibleSymbols`는 적격 주식·ADR, `listedEtfCandidates`는 ETF 상장 확인 목록, `eligibleEtfSymbols`는 가격 기준까지 확인된 ETF다. 기존 보유 기록의 상장 문제는 `existingHoldingsWithListingIssues`에 별도로 남긴다.

가격 스냅샷과 **같은 거래일**의 명부가 있으면 로컬 계산에도 적용할 수 있다. 원본 동결 스냅샷에서 마지막 세션의 주식 편입 자격만 바꾼 사본을 만들고, 그 사본으로 기존 엔진을 실행한다. ETF 순위는 별도 분석군으로 다룬다. 월말 신호에서 새 편입 목록을 적용하며, 과거 신호와 기존 보유 평가에 필요한 가격은 보존한다.

```bash
python -m factor_lab.cli integrated-apply-universe \
  --snapshot path/to/original-frozen-market \
  --nasdaq nasdaqlisted.txt --other otherlisted.txt \
  --output outputs/new-screened-market
python -m factor_lab.cli integrated-run \
  --snapshot outputs/new-screened-market --output outputs/new-screened-run
```

운영 반영에는 동일 날짜 입력으로 계산한 검토된 새 기준선이 필요하다. 일별 거래소 명부를 보존해 적용일 이후의 거래 자격을 재현하고, ETF의 가격·분배금·액면분할과 스프레드를 검증해 별도 분석군을 구축한다. 명부 확보 전 과거 구간의 기존 생존 편향은 남는다.

## 추가 팩터 우선순위

기존 32개 정의는 가격·거래량에 집중되어 있다. 모멘텀, 베타, 잔차 모멘텀, 변동성, 하방 위험, 비유동성의 변형을 늘리는 것보다 재무 공시에서 수익성과 투자율을 추가하는 편이 새로운 정보를 얻는 데 유리하다.

| 우선 | 대상 | 후보와 검증 |
| --- | --- | --- |
| 1 | 주식 | **자산 대비 매출총이익**. 연간 매출총이익 ÷ 같은 기말 총자산. 공시 후에만 반영하고 은행·보험은 별도 취급한다. [Novy-Marx](https://www.nber.org/papers/w15940) |
| 2 | 주식 | **보수적 투자**. 직전 두 연간 총자산의 성장률이 낮을수록 높은 점수. 인수합병·회계 범위 변경으로 자산이 급증하는 사례와 산업별 분포를 별도로 확인한다. [Hou·Xue·Zhang](https://global-q.org/uploads/1/2/2/6/122679606/houxuezhang2015rfs.pdf), [Fama·French 정의](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html) |
| 3 | ETF | **시계열 추세**. 12개월 ETF 시장가격 총수익이 양수인 펀드만 자산군별 편입 대상으로 하고, 음수인 경우 현금 유지와 비교한다. 고정 보유 대비 비용·현금 체류·낙폭을 평가한다. 원 연구는 선물 롱숏 전략을 다뤘으므로 ETF 성과는 별도로 검증한다. [Moskowitz·Ooi·Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) |
| 4 | 주식 | **현금 기반 영업수익성**. 영업이익에서 영업 관련 발생액을 차감해 장부자본 대비 측정한다. 재무 태그와 영업·비영업 분류를 점검하고, 1번과 같은 모집단에서 추가 설명력을 비교한다. [Ball 외](https://faculty.tuck.dartmouth.edu/images/uploads/faculty/joseph-gerakos/Ball%2C_Gerakos%2C_Linnainmaa%2C_et_al._2016.pdf) |
| 5 | 주식 | **순주주환원수익률**. (현금배당 + 자사주 매입 − 주식 발행) ÷ 신호일 시가총액. 정확한 역사적 발행주식수·복수 클래스·ADR 비율이 준비되면 진행한다. [Boudoukh 외](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2007.01226.x) |

주식 1·2번은 SEC EDGAR의 무료 XBRL과 공시 접수시각으로 시작한다. 신호시점까지 접수된 원본만 사용하고 수정 공시는 접수 이후부터 적용한다. 빠진 값은 결측으로 유지한다. 새 팩터의 순위 IC, 비용 후 수익, 회전율을 기존 팩터와 동일한 월·종목에서 비교한다. 시계열 외부 표본과 거래비용 민감도에서 추가 효과가 유지되는 정의만 월별 선택 후보로 검토한다. [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Hou·Xue·Zhang 재현 연구](https://www.nber.org/papers/w23394), [Novy-Marx·Velikov 거래비용 연구](https://www.nber.org/papers/w20721).

## 일일 갱신

기존 Factor 일일 작업은 데이터 기준일이 이미 게시된 경우 건너뛴다. 새 미국 거래일을 처리할 때는 일일 사전 검사 후 Nasdaq Trader 두 명부를 받아 기준일과 장 마감 이후 생성 시각, 데이터 형식, 검토 기준 대비 상장 주식 포괄률을 확인한다. 검증된 원본은 거래일별 캐시에 저장해 가격 공급자가 지연된 재시도에서도 같은 바이트를 사용한다. 기준을 충족하지 못하면 가격 수집 전에 실패하고 마지막 정상 결과를 보존한다.

검토 정책은 기존 요청 종목 파일의 해시와 2026-11-04 명부 감사를 참조한다. 첫 적용은 2026-11-05 이후 기존 기준선보다 새로운 세션부터다. 현재 데이터 기준일의 적격 목록에 거래소 제외 기준을 적용하고, 월말에 사용한 판정과 명부 해시는 다음 계산에서도 그대로 재생한다. 계산이 월말을 건너뛰면 그 날짜에 저장한 원본을 복구해야 한다. OTC 또는 상장 미확인으로 빠진 티커가 다시 보이면 동일 증권 근거가 필요하다. 보유 평가와 기업행동에는 기존 가격·회계 검증을 사용한다.

주식 자동 갱신 범위는 검토된 기존 수집 종목이다. ETF 34개와 ECHO는 매일 상장 후보 목록을 갱신한다. 신규 주식·ETF의 가격 수집과 분석 편입은 요청 종목이 바뀌므로 별도 기준선 검토가 필요하다. 이번 변경에서 추가하는 팩터 정의는 없다.

## 운영 기준선 전환

2026-11-04 상장 명부에서 확정한 주식·ADR 2,769개를 전체 기간에 적용하는 검토 정책은 `integrated_historical_universe.json`에 고정한다. 수동 `Apply Reviewed Factor Universe` 작업은 지정된 기존 결과 ID와 원본 해시를 확인하고, 그 결과의 GitHub Actions 캐시에서 가격 입력을 복원한다. 기존 팩터와 비용 설정으로 전체 분석을 계산한 뒤 포트폴리오·시점·보유 합계·민감도 검증을 통과하면 `reviewed_universe_migration` 기준선으로 게시한다.

이후 일일 작업은 이 역사 구간의 제외 목록과 새로운 거래일의 명부를 함께 적용한다. 정책 변경에는 새 검토 기준선이 필요하다. 캐시 복구, 소스 경합, 계산 또는 게시 검증에 실패하면 마지막 정상 게시본을 보존한다.
