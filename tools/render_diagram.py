#!/usr/bin/env python3
"""draw.io 관계도를 헤드리스 Chrome으로 렌더링해 PNG로 저장한다."""

import argparse
import hashlib
import html
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGRAM = ROOT / "docs" / "diagrams" / "homelab-application-platform.drawio"
OUTPUT = DIAGRAM.with_suffix(".png")
# 원본 XML의 mxfile version과 같은 draw.io 태그의 뷰어를 고정해서 쓴다.
VIEWER_URL = "https://cdn.jsdelivr.net/gh/jgraph/drawio@v24.7.17/src/main/webapp/js/viewer-static.min.js"
WIDTH, HEIGHT = 3540, 2350
BUDGET_MS = 15000
# 뷰어는 요소들의 경계 상자를 화면 왼쪽 위에 붙인다. 렌더링용 사본에만 투명한 기준 셀을 넣어
# 기존 draw.io 내보내기와 같은 여백(가로 0, 세로 26)을 유지한다.
ORIGIN_CELL = (
    '<mxCell id="render-origin" value="" style="rounded=0;fillColor=none;strokeColor=none;" '
    'vertex="1" parent="1"><mxGeometry as="geometry" x="0" y="26" width="1" height="1" /></mxCell>'
)
ROOT_CELL = '<mxCell id="1" parent="0" />'
# 뷰어를 불러오지 못하면 흰 화면만 찍힌다. 현재 그림은 흰색이 아닌 픽셀이 약 14%이므로
# 5%보다 적으면 렌더링 실패로 본다.
MIN_INK = 0.05
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


def with_origin(xml):
    if xml.count(ROOT_CELL) != 1:
        raise ValueError("draw.io 원본에서 기본 부모 셀을 하나만 찾아야 한다")
    return xml.replace(ROOT_CELL, ROOT_CELL + ORIGIN_CELL, 1)


def viewer_page(xml, viewer_url=VIEWER_URL):
    config = {"xml": with_origin(xml), "toolbar": "", "nav": False, "lightbox": False,
              "resize": False, "zoom": 1, "border": 0}
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>html,body{margin:0;padding:0;background:#FFFFFF}</style></head><body>"
        f'<div class="mxgraph" data-mxgraph="{html.escape(json.dumps(config), quote=True)}"></div>'
        f'<script src="{html.escape(viewer_url, quote=True)}"></script></body></html>'
    )


def find_chrome(explicit=None):
    for candidate in ([explicit] if explicit else CHROME_CANDIDATES):
        path = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if path:
            return path
    raise FileNotFoundError("Chrome을 찾지 못했다. --chrome으로 실행 파일을 지정한다")


def png_size(path):
    data = Path(path).read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG가 아니다: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def ink_ratio(path):
    """8비트 RGB·RGBA, 비인터레이스 PNG에서 흰색이 아닌 픽셀의 비율을 구한다."""
    data = Path(path).read_bytes()
    position, header, compressed = 8, None, b""
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        chunk = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR" and len(chunk) == 13:
            header = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            compressed += chunk
        elif kind == b"IEND":
            break
    if header is None or header[2] != 8 or header[3] not in (2, 6) or header[6] != 0:
        raise ValueError(f"검사할 수 없는 PNG 형식이다: {path}")
    width, height, color = header[0], header[1], header[3]
    step = 3 if color == 2 else 4
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as error:
        raise ValueError(f"PNG 데이터를 풀 수 없다: {path}") from error
    if len(raw) < height * (width * step + 1):
        raise ValueError(f"PNG 데이터가 잘렸다: {path}")
    stride = width * step
    previous = bytearray(stride)
    ink = 0
    offset = 0
    for _ in range(height):
        kind = raw[offset]
        line = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += 1 + stride
        for x in range(stride):
            left = line[x - step] if x >= step else 0
            up = previous[x]
            corner = previous[x - step] if x >= step else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + ((left + up) >> 1)) & 255
            elif kind == 4:
                guess = left + up - corner
                pa, pb, pc = abs(guess - left), abs(guess - up), abs(guess - corner)
                line[x] = (line[x] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        for x in range(0, stride, step):
            if min(line[x], line[x + 1], line[x + 2]) < 250:
                ink += 1
        previous = line
    return ink / (width * height)


def same_file(first, second):
    first, second = Path(first), Path(second)
    if first.resolve() == second.resolve():
        return True
    return first.exists() and second.exists() and os.path.samefile(first, second)


def run_chrome(chrome, page, *args):
    """Chrome을 실행하고 표준 출력을 돌려준다. 테스트에서 대역으로 바꾼다."""
    result = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
         f"--window-size={WIDTH},{HEIGHT}", f"--virtual-time-budget={BUDGET_MS}", *args, page.as_uri()],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def render(diagram, output, chrome, viewer_url=VIEWER_URL):
    if same_file(diagram, output):
        raise ValueError("출력 파일이 draw.io 원본과 같다")
    source = Path(diagram).read_bytes()
    before = hashlib.sha256(source).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "diagram.html"
        page.write_text(viewer_page(source.decode("utf-8"), viewer_url), encoding="utf-8")
        shot = Path(tmp) / "diagram.png"
        run_chrome(chrome, page, f"--screenshot={shot}")
        if not shot.is_file() or png_size(shot) != (WIDTH, HEIGHT):
            raise RuntimeError(f"{WIDTH}x{HEIGHT} PNG를 만들지 못했다")
        # 실제로 저장할 캡처를 검사한다. 뷰어를 불러오지 못한 흰 화면은 여기서 걸러진다.
        if ink_ratio(shot) < MIN_INK:
            raise RuntimeError("뷰어가 그래프를 그리지 못했다. 뷰어 주소와 네트워크 연결을 확인한다")
        if hashlib.sha256(Path(diagram).read_bytes()).hexdigest() != before:
            raise RuntimeError("렌더링 중 draw.io 원본이 바뀌었다")
        shutil.copyfile(shot, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagram", type=Path, default=DIAGRAM, help="draw.io 원본")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="저장할 PNG")
    parser.add_argument("--chrome", help="Chrome 또는 Chromium 실행 파일")
    parser.add_argument("--viewer-url", default=VIEWER_URL, help="draw.io 뷰어 스크립트 주소")
    args = parser.parse_args()
    try:
        render(args.diagram, args.output, find_chrome(args.chrome), args.viewer_url)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"{args.output} ({WIDTH}x{HEIGHT})를 만들었다. 라벨·연결선이 겹치거나 잘리지 않았는지 눈으로 확인한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
