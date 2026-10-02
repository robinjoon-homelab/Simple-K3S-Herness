import html
import json
import os
import re
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from tools import render_diagram

WIDTH, HEIGHT = 40, 20


def png(width, height, dark_rows=0, filter_type=0):
    """위쪽 dark_rows 줄만 검은색인 RGB PNG를 만든다."""
    rows = b""
    for y in range(height):
        pixel = b"\x00\x00\x00" if y < dark_rows else b"\xff\xff\xff"
        line = pixel * width
        if filter_type == 2 and y > 0:
            above = (b"\x00\x00\x00" if y - 1 < dark_rows else b"\xff\xff\xff") * width
            line = bytes((a - b) & 255 for a, b in zip(line, above))
        rows += bytes([filter_type if y > 0 else 0]) + line
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fake_chrome(image):
    """--screenshot 인자로 받은 경로에 image를 쓰는 Chrome 대역."""
    def run(chrome, page, *args):
        for arg in args:
            if arg.startswith("--screenshot="):
                Path(arg.split("=", 1)[1]).write_bytes(image)
        return ""
    return run


class RenderDiagramTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.diagram = self.tmp / "d.drawio"
        self.diagram.write_text("<mxfile>" + render_diagram.ROOT_CELL + "</mxfile>", encoding="utf-8")
        self.output = self.tmp / "d.png"
        size = patch.multiple(render_diagram, WIDTH=WIDTH, HEIGHT=HEIGHT)
        size.start()
        self.addCleanup(size.stop)

    def test_origin_cell_is_added_only_to_the_render_copy(self):
        source = render_diagram.DIAGRAM.read_text(encoding="utf-8")
        rendered = render_diagram.with_origin(source)
        self.assertNotIn('id="render-origin"', source)
        self.assertEqual(rendered.count('id="render-origin"'), 1)
        self.assertEqual(rendered.replace(render_diagram.ORIGIN_CELL, ""), source)

    def test_page_embeds_the_diagram_and_pinned_viewer(self):
        page = render_diagram.viewer_page(self.diagram.read_text())
        config = json.loads(html.unescape(re.search(r'data-mxgraph="([^"]+)"', page)[1]))
        self.assertIn(render_diagram.ORIGIN_CELL, config["xml"])
        self.assertIn("jgraph/drawio@v24.7.17", page)
        self.assertEqual((config["zoom"], config["border"]), (1, 0))

    def test_viewer_tag_matches_the_diagram_version(self):
        version = re.search(r'<mxfile [^>]*version="([^"]+)"', render_diagram.DIAGRAM.read_text())[1]
        self.assertIn(f"drawio@v{version}/", render_diagram.VIEWER_URL)

    def test_rejects_xml_without_a_single_root_cell(self):
        with self.assertRaises(ValueError):
            render_diagram.with_origin("<mxfile></mxfile>")

    def test_reads_png_size_and_rejects_other_files(self):
        self.assertEqual(render_diagram.png_size(render_diagram.OUTPUT), (3540, 2350))
        self.assertEqual(render_diagram.WIDTH, WIDTH)
        other = self.tmp / "x.png"
        other.write_bytes(b"not a png")
        with self.assertRaises(ValueError):
            render_diagram.png_size(other)

    def test_ink_ratio_counts_non_white_pixels_across_filters(self):
        for filter_type in (0, 2):
            with self.subTest(filter_type=filter_type):
                image = self.tmp / f"ink-{filter_type}.png"
                image.write_bytes(png(WIDTH, HEIGHT, dark_rows=5, filter_type=filter_type))
                self.assertAlmostEqual(render_diagram.ink_ratio(image), 5 / HEIGHT)

    def test_writes_the_capture_when_the_graph_was_drawn(self):
        with patch.object(render_diagram, "run_chrome", fake_chrome(png(WIDTH, HEIGHT, dark_rows=4))):
            render_diagram.render(self.diagram, self.output, "chrome")
        self.assertEqual(render_diagram.png_size(self.output), (WIDTH, HEIGHT))

    def test_keeps_the_existing_png_when_the_capture_is_blank(self):
        self.output.write_bytes(b"previous")
        with patch.object(render_diagram, "run_chrome", fake_chrome(png(WIDTH, HEIGHT))):
            with self.assertRaisesRegex(RuntimeError, "뷰어"):
                render_diagram.render(self.diagram, self.output, "chrome")
        self.assertEqual(self.output.read_bytes(), b"previous")

    def test_keeps_the_existing_png_when_the_capture_has_the_wrong_size(self):
        self.output.write_bytes(b"previous")
        with patch.object(render_diagram, "run_chrome", fake_chrome(png(WIDTH + 1, HEIGHT, dark_rows=4))):
            with self.assertRaisesRegex(RuntimeError, "PNG"):
                render_diagram.render(self.diagram, self.output, "chrome")
        self.assertEqual(self.output.read_bytes(), b"previous")

    def test_refuses_to_overwrite_the_diagram(self):
        source = self.diagram.read_bytes()
        link = self.tmp / "link.png"
        os.link(self.diagram, link)
        with patch.object(render_diagram, "run_chrome", fake_chrome(png(WIDTH, HEIGHT, dark_rows=4))):
            for target in (self.diagram, link):
                with self.subTest(target=target.name), self.assertRaisesRegex(ValueError, "원본과 같다"):
                    render_diagram.render(self.diagram, target, "chrome")
        self.assertEqual(self.diagram.read_bytes(), source)

    def test_rejects_corrupt_png_data(self):
        image = self.tmp / "broken.png"
        image.write_bytes(png(WIDTH, HEIGHT)[:60])
        with self.assertRaises(ValueError):
            render_diagram.ink_ratio(image)


if __name__ == "__main__":
    unittest.main()
