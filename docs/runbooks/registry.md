# 레지스트리 운영 절차

자체 컨테이너 레지스트리(zot)의 계정 준비, 이미지 발행, 비밀번호 교체, 백업·복구, 점검 절차다. 레지스트리 구조와 접근 모델은 [워크로드 계약의 컨테이너 레지스트리 모델](../WORKLOAD_PLATFORM.md#4-컨테이너-레지스트리-모델)이 설명한다. 최초 연동 순서는 [초기 연동 절차](bootstrap.md)에 있다.

레지스트리 주소는 `registry.homelab.robinjoon.xyz`이고 계정은 `admin` 하나다.

## 계정과 Secret 만들기

저장소 루트의 `local.env`에 레지스트리 주소와 `admin` 계정 정보를 넣는다. 이 파일은 `.gitignore`에 들어 있으므로 강제로 추가하지 않는다. `REGISTRY_PASSWORD`에는 `openssl rand -hex 32`로 만든 값처럼 셸 인용이 필요 없는 강한 임의 비밀번호를 넣고, 같은 값을 비밀번호 관리자에도 보관한다.

```dotenv
REGISTRY_HOST='registry.homelab.robinjoon.xyz'
REGISTRY_USERNAME='admin'
REGISTRY_PASSWORD=''
```

파일 권한을 제한하고 환경변수를 불러온 뒤 `registry-system` 네임스페이스에 Secret 두 개를 만든다.

```bash
chmod 600 local.env
source ./local.env
test -n "$REGISTRY_PASSWORD"

kubectl create namespace registry-system --dry-run=client -o yaml |
kubectl apply -f -

kubectl -n registry-system create secret generic zot-auth \
  --from-literal=htpasswd="$(htpasswd -nbB "$REGISTRY_USERNAME" "$REGISTRY_PASSWORD")" \
  --dry-run=client -o yaml |
kubectl apply -f -

kubectl -n registry-system create secret docker-registry registry-credentials \
  --docker-server="$REGISTRY_HOST" \
  --docker-username="$REGISTRY_USERNAME" \
  --docker-password="$REGISTRY_PASSWORD" \
  --dry-run=client -o yaml |
kubectl apply -f -
```

`zot-auth`는 zot 서버가 로그인을 검증할 때 쓰는 htpasswd 형식 Secret이다. `registry-credentials`는 kubelet이 비공개 이미지를 pull할 때 쓰는 `kubernetes.io/dockerconfigjson` 형식 Secret이다. 형식과 사용 주체가 달라 Secret이 두 개지만 둘 다 같은 `admin` 계정을 담는다. `admin`은 예약 이름이 아니며, `argocd/managed/apps/zot.yaml`의 ACL이 이 사용자에게 모든 저장소의 읽기·생성·갱신·삭제를 허용한다. 사용자 이름을 바꾸려면 `local.env`와 ACL을 함께 바꾼다.

워크로드 네임스페이스에 복제되는 `registry-credentials`에는 레지스트리 전체 권한이 담긴다. 이 Secret을 쓸 수 있는 주체는 pull뿐 아니라 push, 덮어쓰기, 삭제도 할 수 있다. `local.env`는 평문이므로 공유하거나 커밋하지 않는다. 위 명령은 실행 중 비밀번호를 로컬 프로세스 인자에 잠깐 담으므로 여러 사용자가 함께 쓰는 관리 호스트에서는 실행하지 않는다.

복제 범위 설정은 [초기 연동 절차의 Reflector 절](bootstrap.md#reflector-복제-범위-제한)을 따른다.

## 워크로드에서 이미지 받기

워크로드는 Reflector가 앱 네임스페이스에 복제한 `registry-credentials`를 이름으로만 참조한다.

```json
{
  "workload": {
    "imagePullSecrets": [
      {"name": "registry-credentials"}
    ]
  }
}
```

CLI와 Chart는 레지스트리 Secret을 만들거나 인증 정보를 values에 저장하지 않는다. Reflector가 원본 Secret의 `type`과 `data`를 허용된 워크로드 네임스페이스에 복제한다.

## 로컬에서 이미지 발행

CI에서 발행하는 방법은 [CI 자격증명 연동 절차](load-ci-secrets.md)에 있다. 로컬에서는 먼저 `source ./local.env`를 실행한다. 추적과 롤백을 위해 `latest` 대신 커밋 SHA 같은 새 태그를 쓴다.

```bash
IMAGE_TAG="git-$(git rev-parse --short=12 HEAD)"
IMAGE="$REGISTRY_HOST/apps/my-api:$IMAGE_TAG"

printf '%s' "$REGISTRY_PASSWORD" |
docker login "$REGISTRY_HOST" --username "$REGISTRY_USERNAME" --password-stdin
docker build -t "$IMAGE" .
docker push "$IMAGE"
docker logout "$REGISTRY_HOST"
```

## 비밀번호 교체

1. `local.env`의 `REGISTRY_PASSWORD`를 바꾸고 [계정과 Secret 만들기](#계정과-secret-만들기)의 Secret 생성 명령을 다시 실행한다.
2. zot을 명시적으로 재시작한다. 실행 중인 zot이 projected Secret의 파일 교체를 바로 감지한다고 가정하지 않는다.

   ```bash
   kubectl -n registry-system rollout restart statefulset/zot
   kubectl -n registry-system rollout status statefulset/zot --timeout=5m
   ```

3. 같은 유지보수 창에서 워크로드 네임스페이스의 `registry-credentials` 복제본이 갱신됐는지 확인한다.
4. SMS의 `zot` 객체, SMS 자체 CI의 GitHub Secrets, 비밀번호 관리자를 함께 갱신한다.

복제된 자격증명을 회수할 때는 원본 Secret을 바로 지우지 않는다. 먼저 `reflection-allowed="false"`로 바꾸고 대상 복제본이 사라졌는지 확인한다.

## 백업과 복구

이미지 데이터는 `local-path` StorageClass의 `zot-pvc-zot-0` PVC에 저장되고 컨테이너의 `/var/lib/registry/data`에 마운트된다. 노드 로컬 RWO 볼륨이라 고가용성이나 노드 밖 백업을 제공하지 않는다.

1. CI push를 멈추고 진행 중인 업로드가 없는 유지보수 창을 잡는다.
2. Argo CD에서 `root-apps`와 `zot` Application의 자동 동기화를 차례로 멈춘 뒤 `statefulset/zot`의 replica를 0으로 내리고 Pod 종료를 확인한다. 실행 중인 PVC를 파일 단위로 복사해도 일관성이 보장된다고 가정하지 않는다.
3. 스토리지 드라이버의 스냅샷이나 PVC 전체를 보존하는 백업 도구로 다른 물리 장치에 복사한다. 설정은 Git에 있지만 계정 비밀번호는 비밀번호 관리자에서 따로 복구할 수 있어야 한다.
4. replica를 1로 되돌리고 zot이 Ready인지 확인한 뒤 Argo CD 자동 동기화를 다시 켠다.

복구 연습에서는 같은 zot 버전에서 `zot verify /etc/zot/config.json`으로 설정을 확인한다. 서버를 멈춘 상태에서 `zot scrub /etc/zot/config.json`으로 OCI 데이터 무결성을 검사하고, 대표 이미지를 digest로 지정해 pull한다. `scrub`은 손상을 감지만 하고 고치지 않는다. `component=scrub status=affected` WARN이 있으면 해당 콘텐츠가 손상됐다고 판단한다.

감사 로그는 같은 PVC의 `/var/lib/registry/zot-audit.log`에 계속 쌓이고 zot이 회전하지 않는다. 크기를 감시하고 주기적으로 노드 밖에 보관한 뒤, inode를 바꾸지 않는 `copytruncate` 방식으로 회전한다. 감사 로그는 성공한 변경 작업과 GC 중심이므로 이미지 pull과 인증 실패는 zot의 stdout 로그도 함께 본다.

## 점검

```bash
source ./local.env

kubectl -n registry-system rollout status statefulset/zot --timeout=5m
kubectl -n registry-system exec statefulset/zot -- \
  zot verify /etc/zot/config.json

HTTP_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' \
  "https://$REGISTRY_HOST/v2/")"
test "$HTTP_STATUS" = "401"

# curl이 admin 비밀번호를 대화식으로 묻는다.
curl --fail --user "$REGISTRY_USERNAME" \
  "https://$REGISTRY_HOST/v2/_catalog"

kubectl -n my-api get secret registry-credentials \
  -o jsonpath='{.type}{"\n"}'
```

마지막 명령의 결과는 `kubernetes.io/dockerconfigjson`이어야 한다. Secret의 `.dockerconfigjson` 데이터를 터미널이나 로그에 출력해 확인하지 않는다. 처음 운영하기 전에는 `admin` 계정으로 테스트 태그를 push하고, 복제된 Secret을 쓰는 앱 네임스페이스에서 그 이미지를 pull해 본다.
