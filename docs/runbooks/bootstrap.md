# 초기 연동 절차

빈 k3s 클러스터에 하네스를 처음 연결하는 순서다. 끝나면 Argo CD가 원격 Git의 선언을 동기화하고, 워크로드 네임스페이스가 레지스트리와 공유 DB 접속 Secret을 받는다.

## 선행 조건

클러스터에 Argo CD, Traefik, cert-manager와 `letsencrypt-prod` ClusterIssuer가 먼저 있어야 한다. Root Application은 CNPG, Reflector, 공유 DB, zot, 레지스트리 NetworkPolicy, Tailscale, 공용 Traefik 정책을 설치한다.

공통 워크로드의 HTTPS 정책에는 Traefik의 `web`·`websecure` entrypoint, Kubernetes Ingress·CRD provider, `traefik.io`의 `Middleware` CRD가 필요하다. 자세한 조건은 [워크로드 HTTPS 계약](../contracts/workload.md#워크로드-https-계약)에 있다. 정책 적용 확인은 [공용 Traefik HTTPS 정책 적용과 확인](traefik-https.md)을 따른다.

## 1. DNS와 외부 접근

`registry.homelab.robinjoon.xyz`는 k3s의 모든 노드와 레지스트리를 쓰는 외부 클라이언트에서 Traefik 진입점을 가리켜야 한다. 다른 주소를 쓰려면 `argocd/managed/apps/zot.yaml`의 Ingress host와 TLS host를 함께 바꾸고 원격 Git에 push한 뒤 연동을 시작한다.

외부 접근은 공유기의 공개 포트 포워딩 대신 Tailscale이나 WireGuard와 split DNS를 쓰는 구성을 권한다. `letsencrypt-prod`는 공개 443 포트를 열지 않아도 인증서를 받을 수 있도록 DNS-01 방식으로 구성한다. zot의 Service는 `ClusterIP`으로 두고 NodePort나 LoadBalancer로 직접 노출하지 않는다. VPN 설치와 인증 정보 등록은 [VPN 운영 절차](vpn.md)를 따른다. VPN은 zot의 TLS·인증·ACL을 대신하지 않는다.

## 2. 레지스트리 Secret

[레지스트리 운영 절차의 계정과 Secret 만들기](registry.md#계정과-secret-만들기)를 실행해 `registry-system`에 `zot-auth`와 `registry-credentials`를 만든다.

## 3. 원격 Git 반영과 Root Application 등록

Argo CD는 작업 폴더나 로컬 커밋이 아니라 원격 Git을 읽는다. 매니페스트 변경을 커밋한 뒤 원격 브랜치에 push한다. `local.env`와 Kubernetes Secret은 Git에 올리지 않는다. Root Application이 이미 등록돼 있으면 `kubectl apply`를 건너뛴다. push한 변경은 Argo CD가 자동으로 동기화한다.

```bash
kubectl apply -f argocd/root.yaml
kubectl -n kube-system rollout status deployment/reflector --timeout=5m
kubectl -n registry-system rollout status statefulset/zot --timeout=5m
kubectl -n registry-system get statefulset,pod,service,pvc,ingress,networkpolicy
```

## Reflector 복제 범위 제한

Reflector가 `registry-credentials`를 하네스의 워크로드 네임스페이스에만 자동 복제하도록 표시한다.

```bash
kubectl -n registry-system annotate secret registry-credentials --overwrite \
  reflector.v1.k8s.emberstack.com/reflection-allowed="true" \
  reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces-selector="simple-k3s-harness.dev/workload=true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-enabled="true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-namespaces-selector="simple-k3s-harness.dev/workload=true"
```

CLI가 만드는 Argo CD Application은 `managedNamespaceMetadata`로 앱 네임스페이스에 `simple-k3s-harness.dev/workload=true` 라벨을 붙인다. 이 라벨이 없는 기존 앱 네임스페이스에는 한 번 직접 붙인다.

```bash
kubectl label namespace my-api \
  simple-k3s-harness.dev/workload="true" --overwrite
```

이 라벨은 레지스트리 자격증명과 공유 DB 접속 Secret을 받을 권한을 뜻한다. 하네스가 관리하지 않는 네임스페이스나 시스템 네임스페이스에는 붙이지 않는다. 대상 네임스페이스에 같은 이름의 Secret을 따로 만들면 Reflector가 충돌을 감지하고 복제를 건너뛴다. 그래서 `registry-credentials`는 `registry-system`의 원본에서만 관리한다. 허용·자동 복제 네임스페이스 목록과 셀렉터를 모두 생략하거나 비워 두면 복제 범위가 전체 네임스페이스로 넓어질 수 있으므로 금지한다.

CNPG가 `database-system`에 만든 `shared-db-app` Secret에도 같은 제한을 건다.

```bash
kubectl -n database-system annotate secret shared-db-app --overwrite \
  reflector.v1.k8s.emberstack.com/reflection-allowed="true" \
  reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces-selector="simple-k3s-harness.dev/workload=true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-enabled="true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-namespaces-selector="simple-k3s-harness.dev/workload=true"
```

위 명령은 복제 범위를 정하는 metadata만 추가하고 CNPG가 관리하는 `data`는 고치지 않는다. 워크로드가 이 Secret에서 쓸 수 있는 키와 `DB_HOST` 주입 규칙은 [워크로드 계약의 데이터베이스 모델](../contracts/workload.md#3-데이터베이스-모델)이 정한다.
