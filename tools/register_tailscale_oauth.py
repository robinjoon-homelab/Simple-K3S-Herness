#!/usr/bin/env python3
"""Register Tailscale OAuth credentials without files, argv values or logs."""

import argparse
import base64
import getpass
import json
import subprocess
import sys


def apply_resource(context, resource):
    result = subprocess.run(
        [
            "kubectl", "--context", context, "--request-timeout=20s",
            "apply", "--server-side",
            "--field-manager=homelab-tailscale-bootstrap", "-f", "-",
        ],
        input=json.dumps(resource),
        text=True,
        capture_output=True,
    )
    if result.returncode:
        # API errors can echo submitted data; do not print stdout or stderr.
        raise RuntimeError(
            f"{resource['kind']} 등록 실패. 컨텍스트·연결·권한 및 기존 리소스의 "
            "필드 소유권을 확인하세요. 비밀 값 보호를 위해 서버 응답은 출력하지 않습니다."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="대상 kubectl context")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("숨김 입력을 위해 대화형 터미널에서 실행하세요.")

    print(f"대상: context={args.context}, namespace=tailscale, Secret=operator-oauth")
    client_id = getpass.getpass("Tailscale OAuth Client ID (숨김 입력): ").strip()
    client_secret = getpass.getpass("Tailscale OAuth Client Secret (숨김 입력): ").strip()
    if not client_id or not client_secret:
        parser.error("Client ID와 Client Secret은 비어 있을 수 없습니다.")

    apply_resource(args.context, {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "tailscale"},
    })
    apply_resource(args.context, {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "operator-oauth", "namespace": "tailscale"},
        "type": "Opaque",
        "data": {
            "client_id": base64.b64encode(client_id.encode()).decode(),
            "client_secret": base64.b64encode(client_secret.encode()).decode(),
        },
    })
    print("operator-oauth 등록 완료. 자격증명은 출력하거나 로컬 파일에 저장하지 않았습니다.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\n등록을 중단했습니다.", file=sys.stderr)
        sys.exit(1)
