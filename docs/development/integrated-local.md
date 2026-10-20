# 로컬 통합 실행

현재 입력은 `outputs/integration/market-2026-10-20-repaired-v3`다. 가격·거래량과 유니버스가 고정되어 같은 입력으로 다시 계산할 수 있다.

```sh
# 프로젝트 루트에서 결과 조회와 실험 API를 함께 실행
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
.venv/bin/python -m momentum_factor_lab.cli serve-integrated \
  --snapshot outputs/integration/market-2026-10-20-repaired-v3 \
  --site outputs/integration/release-2026-10-20/site \
  --runs outputs/integration/api-runs --port 50073
```

- 통합 화면: http://127.0.0.1:50073/
- 통합 Hub: http://127.0.0.1:50073/hub/
- 실험 목록: `GET /api/integrated/runs`
- 실험 실행: `POST /api/integrated/runs`

현재 선택, 단일 팩터, 팩터 탐색, 비교, 실험, 데이터의 여섯 화면을 사용한다. 단일 팩터는 통합 32개 정의에서 선택하며, 26개 투자 정의의 전체 성과와 신호월별 체결 종가 보유 비중을 제공한다. 연구 전용 정의는 투자 내역을 만들지 않는다. 차트의 관찰일과 월별 보유 기준은 별도다. 커서·키보드로 고른 날짜는 수익률·낙폭 차트에 함께 반영된다. 보유 표는 비중 내림차순이며 PC에서는 두 열, 모바일에서는 10종목씩 표시한다. 조회 상태는 URL로 유지한다. 화면의 실험 실행은 이 서버가 켜진 동안만 동작하며 운영 예약을 만들지 않는다.

## 재계산

완료한 실행 디렉터리는 덮어쓰지 않는다. 새 출력 경로를 사용한다.

```sh
.venv/bin/python -m momentum_factor_lab.cli integrated-run \
  --snapshot outputs/integration/market-2026-10-20-repaired-v3 \
  --output outputs/integration/new-run

# 기존 기간 변형을 기본 월별 후보와 분리해 계산
.venv/bin/python -m momentum_factor_lab.cli integrated-run \
  --snapshot outputs/integration/market-2026-10-20-repaired-v3 \
  --experiment-project momentum --experiment-id mom_6_1 \
  --output outputs/integration/new-period-experiment
```

API의 기본 입력은 `{"settings":{}}`다. 고정 변형에는 `experimentDefinition: {"project":"momentum","id":"mom_6_1"}`을 추가한다. 공통 종목 재계산에는 `comparisonFactors`에 정의 ID 목록을 넣고 `commonUniverse`를 `true`로 지정한다. Best의 과거 입력 계약은 이 입력으로 자동 변환하지 않는다.

## 검증과 실행 상태

최종 입력의 품질 근거는 `outputs/integration/data-validation.json`, 기존 회계 회귀는 `original-parity.json`, API 직접 비교는 `api-validation.json`에 기록한다. 최종 통합 검증 보고서와 Best 정리 기록은 각각 `integration-validation.json`, `retirement-result.json`이다. 검증 완료 전에는 해당 보고서를 완료 증거로 취급하지 않는다.

대규모 계산은 한 작업씩 수치 라이브러리 스레드 1로 실행한다. 과거의 일회성 발열 제어기나 PID는 재사용하지 않는다.

Control API를 별도로 사용할 때는 `quant-dashboard/platform/services/control-api`에서 무료 로컬 브리지를 켠다. 원격 계산 제공자는 사용하지 않는다.

```sh
QUANT_CONTROL_ENV=development QUANT_CONTROL_PROVIDER=disabled \
QUANT_CONTROL_STORE=memory \
QUANT_CONTROL_INTEGRATED_ENGINE_URL=http://127.0.0.1:50073 \
.venv/bin/python -m uvicorn quant_control_api.app:app --host 127.0.0.1 --port 8767
```

명시적 계약은 `/v2/momentum-integrated/capabilities`와 `/v2/momentum-integrated/runs`다. 이 로컬 통합 모드에서 이전 Best 실행 주소는 410과 새 경로를 반환한다. 기본 운영 설정은 그대로 둔다.

현재 검증 결과는 `outputs/integration/repair-2026-10-20/final/reviewed-result.json`이며, 릴리스·API·화면 영수증은 `outputs/integration/release-2026-10-20/release-manifest.json`에 있다. 가격·기업행동 정정과 지연 분석은 `docs/development/performance-repair-2026-10-20.md`에 기록했다. 평가 기준일은 2026-10-16으로 고정한 감사 입력이다.
