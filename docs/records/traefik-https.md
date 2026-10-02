# 공용 Traefik HTTPS 정책 검증 기록

[적용 확인 절차](../runbooks/traefik-https.md)로 확인한 결과를 날짜순으로 쌓는다. 각 기록은 그날의 관찰이며 현재 상태를 보장하지 않는다.

## 2026-09-19 — 공용 정책 첫 배포

- 대상: 커밋 `3d45736`
- 결과: Argo CD의 Application 11개가 모두 `Synced/Healthy`였다. Traefik Helm 작업과 rollout이 끝났다.
- 외부 접속: 일반 앱, Argo CD, 레지스트리의 네 호스트 모두 HTTP 301 전환, 경로·쿼리 보존, HTTPS 인증서 검증, HSTS 헤더를 확인했다. HTTPS 응답은 블로그와 Argo CD 200, SMS는 로그인 경로로 302, 인증 없는 레지스트리 `/v2/`는 401이었다.
- 확인하지 않은 범위: 검사는 작업 머신에서 프록시 없이 공개 DNS 주소로 했다. 별도 외부망, 로그인 후 기능, 이미지 push·pull은 확인하지 않았다.
