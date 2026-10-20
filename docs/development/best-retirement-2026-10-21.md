# Best 최종 종료 — 2026-10-21

통합 안내와 job skip만으로는 GitHub 예약이 종료되지 않았다. 실제 Best workflow가 활성 상태이고 cron 3개가 남아 있음을 확인해 수동 비활성화한 뒤 저장소 Actions 전체를 차단했다. Factor와 공통 소비자의 독립성을 확인한 후 `SonChangGi/best-factor` 저장소 자체를 삭제했다. API 재조회는 404다.

## 삭제 및 전환

- Best 저장소의 workflow·예약·149개 artifact·1개 cache·2개 전용 secret·Pages 경로를 저장소와 함께 제거했다. 공유 callback 자격증명 자체는 폐기하지 않았다.
- Best 전용 로컬 주 checkout, 연결 worktree, 독립 소스 복제본 및 확인된 전용 patch·workflow 사본·과거 원격 메타데이터를 삭제했다. 별도 보관소는 만들지 않았다.
- Hub의 Best loader·parser·renderer·fallback·스타일·별칭·독립 fixture를 삭제했다. 현재 Factor 차트와 다른 활성 화면 스타일은 유지했다.
- 공통 Control API에서 Best adapter·정규화·provider target·artifact binding을 삭제했다. Best capabilities와 새 실행은 설정·본문·인증과 무관하게 410이다. 과거 pending dispatch도 worker 호출 전에 차단한다.
- Render의 Best 전용 GitHub owner/repository/workflow/ref 설정 4개만 제거했다. 다른 환경값은 값 단위로 일치한다.
- Supabase의 Best 프로젝트 1개, 설정 2개, 실행 3개, outbox 3개, 스냅샷 1개, artifact 1개를 삭제했다. 동일 transaction에서 나머지 프로젝트의 전체 행 digest가 불변임을 검사했다. `projects_best_factor_retired` 제약으로 재등록을 차단한다.
- 과거의 로컬 전용 정리 도구 4개와 종료 안내 화면 선택 검사를 제거했다.

## 검증과 보존

Factor·SOX·ETF·Fear & Greed·Regime·DRAM·News·이전 Momentum 안내 저장소의 원격 main 자동화 27개 파일에는 Best 저장소 의존성이 없었다. 로컬 launchd·crontab·Codex 예약과 실행 프로세스에도 Best 전용 항목이 없다.

Factor의 2,960종목 합집합, 추가 95종목 데이터, 이관된 수식·382행 대응표·기업행사 근거·통합 스냅샷·입력 cache는 삭제 대상이 아니다. 이들은 Best 원격이나 로컬 폴더를 읽지 않는다. `integrated_legacy_best.py`와 출처 URL/원본 ID는 이관한 정의의 구현과 출처 추적을 위해 유지한다. 다른 프로젝트의 Git 이력·기존 사용자 작업도 보존한다.

Control API 137개 검사, Hub 전체 검사와 플랫폼 33개 검사·타입 검사·빌드, Factor 공통 release 검사를 통과했다. Best 로컬 삭제 후 2,960종목과 이관 수식이 독립적으로 로드되고 daily 사전검사가 통과했다. 새 시세 수집이나 백테스트는 실행하지 않았으며 금융 결과와 Factor 정기 실행 시각은 바꾸지 않았다. GitHub CI·Pages 성공, Render live 배포, Factor/Fear capabilities와 `/readyz`의 200, Best의 410을 각각 확인했다.

세부 실행 영수증은 로컬 `outputs/best-final-retirement-20261021/`에 있다. 경로·건수·검증 해시만 기록하며 삭제한 Best 금융 결과를 보관하지 않는다.
