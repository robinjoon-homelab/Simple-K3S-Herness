# 홈 LAN VPN 검증 기록

[VPN 운영 절차](../runbooks/vpn.md)로 확인한 결과를 날짜순으로 쌓는다. 각 기록은 그날의 관찰이며 현재 상태를 보장하지 않는다.

## 2026-09-18 — 배포 전 사전 검증

기존 테스트와 인증 등록 도구 테스트 41개, 당시 CLI의 `validate --all`, 공식 Chart lint와 렌더링, 공식 CRD 기반 Connector 스키마 검증, 실제 홈랩 API에서 Application·CRD server-side dry-run이 통과했다. 이 결과는 실제 VPN 접속 성공을 뜻하지 않는다. `validate` 명령은 이후 CLI에서 삭제됐다.

## 2026-09-18 — 배포와 외부 접속

- `tailscale-operator`와 `tailscale-router`: Argo CD `Synced/Healthy`, 동기화 성공.
- Operator와 서브넷 라우터 Pod: `1/1 Running`.
- Tailscale: `Running`, 온라인, `192.168.0.0/24`가 승인된 기본 경로로 표시됐다.
- 라우터 Pod 재시작: rollout 성공, 기존 Tailscale 주소와 승인 경로 유지.
- VPN Pod에서 홈 서버 `192.168.0.195:6443`, 공유기 `192.168.0.1:80`으로 TCP 연결 성공.
- 기존 Application은 모두 `Synced/Healthy`를 유지했다.
- 외부 휴대폰: 운영자가 집 Wi-Fi를 끄고 셀룰러와 Tailscale로 접속해 `http://192.168.0.1` 공유기 화면이 열리는 것을 확인했다.
- 확인하지 않은 범위: 모든 LAN 장치의 개별 서비스는 시험하지 않았다.
