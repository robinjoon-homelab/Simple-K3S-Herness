# 홈 네트워크 VPN — Tailscale

상태: 배포 선언·인증 정보 등록 도구 준비 및 `operator-oauth` 등록 확인 완료. GitOps 배포와 실제 외부 VPN 접속 검증은 별도로 확인한다.

2026-09-18 사전 검증: 기존 테스트와 인증 등록 도구 테스트 총 41개, 기존 앱 `validate --all`, 공식 Chart lint·렌더링, 공식 CRD 기반 Connector 스키마 검증, 실제 홈랩 API에서 Application·CRD server-side dry-run이 통과했다. 이 결과는 실제 VPN 접속 성공을 의미하지 않는다.

## 범위와 구조

외부의 개인 노트북·휴대폰에서 홈 LAN `192.168.0.0/24` 전체에 접근한다. 홈랩 노드의 내부 IP는 `192.168.0.195`이며, 같은 LAN에 연결된 운영자 PC의 DHCP 서브넷 마스크 `255.255.255.0`으로 대역을 확인했고, 운영자가 이 대역만 연결 대상으로 확정했다. 추가 VLAN·다른 공유기 아래의 네트워크는 확인 후 별도 경로를 추가해야 한다.

```text
외부 기기(Tailscale 로그인)
  → Tailscale 터널
  → k3s 안의 homelab-lan 서브넷 라우터
  → 홈 LAN 192.168.0.0/24 (홈 서버·NAS·기타 장치)
```

Tailscale 계정·관리 서비스(tailnet)를 이용한다. 하네스는 공식 Operator Helm Chart와 Connector를 `default` Argo CD Project의 별도 인프라 Application으로 배포한다. Operator와 프록시의 인증·상태는 Kubernetes Secrets에 보관하며, 공유 PostgreSQL이나 PVC는 필요하지 않다. 일반 앱용 CLI·공통 Chart·앱 소스 CI는 변경하지 않는다.

홈 LAN 경로만 광고한다. 인터넷 전체를 집으로 보내는 exit node, Pod/Service CIDR 광고, Kubernetes API 프록시, Tailscale Ingress는 구성하지 않는다. 홈 서버 IP를 통해 이미 열려 있는 포트는 접근 정책과 서버 방화벽에 따라 접근할 수 있다. VPN 접속 자체가 SSH·웹서비스 인증을 대신하지 않는다. LAN의 브로드캐스트나 mDNS 기반 장치 자동 검색까지 확장하는 구성은 아니므로 우선 IP로 접속한다.

클러스터 장애 복구용 VPN이 아니다. k3s나 홈 서버가 중단되면 VPN도 중단된다. 기본 SNAT를 유지하므로 일반적으로 LAN 장치에 VPN 반환 경로를 추가할 필요가 없다. 별도 VLAN의 방화벽이나 목적지 장치의 접근 제한은 여전히 적용된다.

## 1. Tailscale 계정과 정책 준비

1. [Tailscale 관리 화면](https://login.tailscale.com/admin)에 로그인하고 사용할 개인 tailnet을 선택한다.
2. [Access controls](https://login.tailscale.com/admin/acls)에서 아래 태그, 경로 자동 승인, 접근 허용 규칙을 설정한다. 새 개인 tailnet의 최소 정책 예시다. 기존 tailnet에서는 기존 정책을 보존하면서 병합한다. 허용 규칙은 합산되므로 기존 전체 허용 규칙이 있다면 이 규칙을 추가하는 것만으로 접근 범위가 줄어들지는 않는다.

```json
{
  "tagOwners": {
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  },
  "autoApprovers": {
    "routes": {
      "192.168.0.0/24": ["tag:k8s"]
    }
  },
  "grants": [
    {
      "src": ["autogroup:admin"],
      "dst": ["192.168.0.0/24"],
      "ip": ["*"]
    }
  ]
}
```

이 예시는 tailnet 관리자 계정의 기기에서 홈 LAN 전체로 접근하도록 허용한다. 일반 멤버 계정도 사용할 경우 `src`에 해당 로그인 이메일을 명시한다. 경로 승인과 접근 허용은 별개이며 둘 다 필요하다. 자동 승인 대신 관리 화면의 Machines에서 `homelab-lan`의 경로를 수동 승인해도 된다.

3. 관리 화면의 **Settings → Trust credentials → OAuth clients**에서 OAuth client를 만든다. 이름은 `homelab-k3s-operator`로 구분하고 `tag:k8s-operator`를 지정한다. 현재 공식 설치 가이드가 요구하는 다음 항목의 **Write** 권한을 선택한다.

   - `General / Services`
   - `Devices / Core`
   - `Keys / Auth Keys`

4. 표시되는 **Client ID**와 **Client Secret**을 비밀번호 관리자에 보관한다. 개인 로그인 비밀번호나 일반 Auth key를 대신 넣지 않는다. 값은 채팅·Git·스크린샷에 남기지 않는다.

## 2. OAuth 자격증명 등록

홈랩에 접근할 수 있는 운영자 PC의 일반 터미널에서 실행한다. Python 3와 kubectl만 필요하다.

```bash
cd /Users/imsubin/IdeaProjects/Simple-K3S-Herness
python3 tools/register_tailscale_oauth.py --context homelab
```

두 프롬프트에 Client ID와 Client Secret을 붙여 넣는다. 입력은 화면에 표시되지 않는다. 도구는 `tailscale` namespace와 `operator-oauth` Secret을 server-side apply로 등록한다. 비밀은 stdin으로만 전달하며 셸 인자·임시 파일·로그·last-applied annotation에 저장하지 않는다. Secret 오류 응답도 값을 포함할 수 있어 출력하지 않는다. Kubernetes 자체의 Secret 저장·백업·감사 로그 정책은 클러스터 설정을 따른다.

등록 여부는 값 대신 리소스 이름으로 확인한다.

```bash
kubectl --context homelab -n tailscale get secret operator-oauth -o name
```

이는 실행용 Secret 초기 등록이다. SMS의 CI 자격증명 조회나 GitOps 워크로드 배포와는 별개다. 자격증명 교체도 같은 도구로 등록한 다음 Operator를 재시작하고 재연결을 확인한다.

## 3. GitOps 배포

배포 파일:

- [Operator Application](../argocd/managed/apps/tailscale-operator.yaml): 공식 Chart `1.102.4`, 기존 `operator-oauth` 참조, CRD·RBAC·Operator 설치.
- [Router Application](../argocd/managed/apps/tailscale-router.yaml): Connector 배포.
- [Connector](../infrastructure/tailscale/connector.yaml): 단일 `homelab-lan` 라우터와 홈 LAN 경로.

자격증명 등록 후 검증된 구성을 원격 `main`에 반영하면 기존 Root Application이 두 Application을 발견한다. Root는 원격 Git을 읽으며 로컬 파일·커밋만으로 배포되지 않는다. 직접 `helm install`이나 `kubectl apply -f connector.yaml`로 우회하지 않는다.

Router Application에는 sync wave와 재시도를 설정했다. 기본 App-of-Apps에서 wave만으로 자식 Application의 CRD 준비까지 보장되지는 않으므로, 초기 CRD 미등록 오류는 재시도로 회복한다. Operator가 계속 실패하면 아래 상태를 확인해 원인을 해결한다. Chart의 프록시는 IP forwarding 설정과 네트워크 처리를 위해 높은 컨테이너 권한을 사용하므로, Pod Security 제한을 추가할 때 공식 요구사항을 함께 검토한다.

```bash
kubectl --context homelab -n argocd get applications tailscale-operator tailscale-router
kubectl --context homelab -n tailscale get pods
kubectl --context homelab get connector homelab-lan
kubectl --context homelab -n tailscale rollout status deployment/operator --timeout=60s
```

관리 화면의 Machines에서 `homelab-operator`와 `homelab-lan`이 연결되고, `192.168.0.0/24` 경로가 승인됐는지 확인한다. Argo CD의 Synced나 Connector 생성만으로 실제 VPN 접속 성공을 판정하지 않는다.

## 4. 외부 기기 연결과 검증

1. 노트북·휴대폰에 Tailscale을 설치하고 허용한 계정으로 로그인한다.
2. Linux 클라이언트는 `sudo tailscale set --accept-routes=true`로 서브넷 경로 수신을 활성화한다.
3. 집 Wi-Fi를 끄고 휴대폰 셀룰러 또는 다른 외부망에서 홈 서버 `192.168.0.195`의 실제 SSH·웹서비스와 다른 LAN 장치에 접속한다. ping만으로 판정하지 않는다.
4. VPN을 끊으면 같은 사설 IP에 VPN 경로로 접근할 수 없는지 확인한다.
5. 라우터 Pod 재시작 후 기존 장치 신원과 경로가 유지되고 외부 접속이 복구되는지 확인한다.

외부 Wi-Fi도 `192.168.0.0/24`이면 주소 충돌이 생길 수 있다. 우선 셀룰러에서 시험하고, 반복되는 충돌은 홈 LAN 대역 변경이나 Tailscale 4via6 같은 별도 설계로 해결한다. 수동 공유기 포트 포워딩 없이 연결을 시도하며, 직접 연결이 어려우면 Tailscale 릴레이를 사용한다. 외부 연결을 제한하는 방화벽에서는 공식 문서의 outbound 요구사항을 확인한다.

기존 `*.homelab.robinjoon.xyz` 이름을 내부 IP로 사용하려면 split DNS와 해당 DNS 서버의 VPN 접근을 별도로 구성한다. 이번 기본 구성은 IP 기반 홈 LAN 접근이며, 기존 DNS·공개 Ingress·앱 인증 설정은 유지한다.

## 공식 참고 문서

- [Operator 설치·OAuth 권한](https://tailscale.com/docs/kubernetes-operator/install-operator)
- [Kubernetes 서브넷 라우터](https://tailscale.com/docs/kubernetes-operator/connector/deploy-subnet-router)
- [서브넷 라우터](https://tailscale.com/kb/1019/subnets)
- [접근 허용 규칙](https://tailscale.com/kb/1324/grants)
- [방화벽 연결 요구사항](https://tailscale.com/docs/reference/faq/firewall-ports)
