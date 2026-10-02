#!/usr/bin/env python3
"""Git이 추적하는 Markdown의 로컬 링크와 하네스 문서 구조를 검사한다."""

import argparse
import html
from html.parser import HTMLParser
import posixpath
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")
DEFINITION = re.compile(r"(?m)^ {0,3}\[((?:\\.|[^\]\\\n])+)\]:[ \t]*(?:\n[ \t]*)?")
AGENT_IMPORT = re.compile(r"(?m)^[ \t]*@([^\s]+\.md)[ \t]*$")
DOC_INDEX = "docs/README.md"
DIAGRAM = "docs/diagrams/homelab-application-platform.drawio"
# 색인은 자신을 연결할 필요가 없고, 그림 안내는 이미지와 함께 별도로 탐색한다.
INDEX_EXCEPTIONS = {DOC_INDEX, "docs/diagrams/README.md"}
REMOVED_COMMAND = re.compile(
    r"(?<![\w.-])platform\.py[\"']?(?:[ \t]|\\\r?\n)+"
    r"(doctor|schema|list|validate|render)(?=$|[\s`\"';|&<>])"
)


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.message}"


def blank(text):
    return re.sub(r"[^\n]", " ", text)


def fenced_blocks(text):
    """코드 펜스의 시작·끝 위치와 언어 표시를 읽는다."""
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        content = re.sub(r"^ {0,3}(?:> ?)+", "", line)
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                yield start, offset + len(line), language
                fence = None
        elif marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]
            start = offset
            language = marker[2].strip().split(maxsplit=1)[0] if marker[2].strip() else ""
        offset += len(line)
    if fence:
        yield start, len(text), language


def without_comments(text):
    return re.sub(r"<!--.*?(?:-->|\Z)", lambda m: blank(m[0]), text, flags=re.S)


def without_fences(text):
    """길이와 줄 번호를 유지한 채 코드 펜스와 주석을 가린다."""
    output = list(text)
    for start, end, _ in fenced_blocks(text):
        output[start:end] = blank(text[start:end])
    return without_comments("".join(output))


def code_spans(text):
    position = 0
    while position < len(text):
        if text[position] == "\\":
            position += 2
            continue
        if text[position] != "`":
            position += 1
            continue
        opening = re.match(r"`+", text[position:])[0]
        start = position
        position += len(opening)
        paragraph = re.split(r"\n[ \t]*\n", text[position:], maxsplit=1)[0]
        closing = re.search(r"(?<!`)" + opening + r"(?!`)", paragraph)
        if closing:
            end = position + closing.end()
            yield start, end, text[position:position + closing.start()]
            position = end


def without_inline_code(text):
    result = list(text)
    for start, end, _ in code_spans(text):
        result[start:end] = blank(text[start:end])
    return "".join(result)


def closing_bracket(text, start):
    depth = 0
    position = start
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return None


def destination(text, start):
    """괄호가 있는 경로, 꺾쇠 경로와 Markdown 이스케이프를 읽는다."""
    position = start
    if position < len(text) and text[position] == "<":
        position += 1
        while position < len(text):
            if text[position] == "\\":
                position += 2
                continue
            if text[position] == ">":
                return text[start + 1:position], position + 1
            if text[position] == "\n":
                return None
            position += 1
        return None
    depth = 0
    while position < len(text):
        char = text[position]
        if char == "\\" and position + 1 < len(text):
            position += 2
            continue
        if char.isspace() or (char == ")" and depth == 0):
            break
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        position += 1
    return (text[start:position], position) if depth == 0 else None


def inline_destination(text, start):
    position = start + 1
    while position < len(text) and text[position].isspace():
        position += 1
    parsed = destination(text, position)
    if parsed is None:
        return None
    target, position = parsed
    tail = re.match(r"\s*(?:(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))\s*)?\)", text[position:])
    return (target, position + tail.end()) if tail else None


def reference_id(label):
    return " ".join(ESCAPE.sub(r"\1", label).split()).casefold()


def markdown_links(text, references):
    position = 0
    while position < len(text):
        if text[position] == "\\":
            position += 2
            continue
        if text[position] != "[":
            position += 1
            continue
        close = closing_bracket(text, position)
        if close is None:
            break
        label = text[position + 1:close]
        end = close + 1
        target = None
        is_link = False
        if text[end:end + 1] == "(":
            parsed = inline_destination(text, end)
            if parsed:
                target, end = parsed
                is_link = True
        elif text[end:end + 1] == "[":
            ref_end = closing_bracket(text, end)
            if ref_end is not None:
                key = reference_id(text[end + 1:ref_end] or label)
                target = references.get(key)
                end = ref_end + 1
                is_link = True
        elif reference_id(label) in references:
            target = references[reference_id(label)]
            is_link = True
        if is_link:
            yield position, end, label, target
        # 링크 문구 안의 이미지도 검사한다.
        for start, inner_end, inner_label, inner_target in markdown_links(label, references):
            yield position + 1 + start, position + 1 + inner_end, inner_label, inner_target
        position = end


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchors = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value is not None and name in ("href", "src"):
                self.links.append((self.getpos()[0], value))
            if value is not None and (name == "id" or (tag == "a" and name == "name")):
                self.anchors.add(value)


def link_labels(text, references):
    output = []
    position = 0
    for start, end, label, target in markdown_links(text, references):
        if start < position or target is None:
            continue
        output.extend((text[position:start], link_labels(label, references)))
        position = end
    output.append(text[position:])
    return "".join(output)


def heading_slug(text, references):
    # 코드 안의 밑줄은 강조 표식으로 해석하지 않는다.
    literals = []
    for start, end, content in reversed(list(code_spans(text))):
        token = f"\x00{len(literals)}\x00"
        literals.append(content.replace("\n", " "))
        text = text[:start] + token + text[end:]
    text = link_labels(text, references)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(?<!\w)(_+)(.+?)\1(?!\w)", r"\2", text)
    text = text.replace("*", "").replace("~", "")
    text = html.unescape(ESCAPE.sub(r"\1", text))
    for index, content in enumerate(literals):
        text = text.replace(f"\x00{index}\x00", content)
    # GitHub 제목 규칙: 소문자, 공백→하이픈, 구두점·기호 제거.
    # https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#section-links
    return "".join(
        char for char in text.strip().lower()
        if char in " -_" or unicodedata.category(char)[0] in "LM" or unicodedata.category(char) in ("Nd", "Nl", "Pc")
    ).replace(" ", "-")


def parse_document(path, text):
    visible = without_fences(text)
    prose = without_inline_code(visible)
    references = {}
    definitions = []
    for match in DEFINITION.finditer(prose):
        parsed = destination(prose, match.end())
        if parsed and parsed[0]:
            references.setdefault(reference_id(match[1]), parsed[0])
            end = prose.find("\n", parsed[1])
            definitions.append((match.start(), len(prose) if end == -1 else end))
    for start, end in reversed(definitions):
        prose = prose[:start] + blank(prose[start:end]) + prose[end:]

    links = []
    problems = []
    for start, _, label, target in markdown_links(prose, references):
        line = prose.count("\n", 0, start) + 1
        if target is None:
            problems.append(Problem(path, line, f"참조 링크의 정의가 없다: [{label}]"))
        else:
            links.append((line, ESCAPE.sub(r"\1", target)))
    parser = HtmlLinks()
    parser.feed(prose)
    links.extend(parser.links)
    if PurePosixPath(path).name in ("CLAUDE.md", "GEMINI.md"):
        for match in AGENT_IMPORT.finditer(prose):
            links.append((prose.count("\n", 0, match.start()) + 1, match[1]))

    anchors = set()
    occurrences = {}
    previous = ""
    for line in visible.splitlines():
        content = re.sub(r"^ {0,3}(?:> ?)+", "", line)
        heading = re.match(r"^ {0,3}#{1,6}(?:[ \t]+(.*?)|$)$", content)
        if heading:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[1] or "")
        elif previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", content):
            title = previous.strip()
        else:
            previous = content
            continue
        slug = heading_slug(title, references)
        unique = slug
        while unique in occurrences:
            occurrences[slug] = occurrences.get(slug, 0) + 1
            unique = f"{slug}-{occurrences[slug]}"
        occurrences[unique] = 0
        anchors.add(unique)
        previous = ""
    anchors.update(parser.anchors)
    return anchors, links, problems


def local_target(name, target):
    """문서 기준 로컬 경로와 앵커를 반환한다. 외부 URL은 제외한다."""
    parts = urlsplit(html.unescape(target))
    if parts.scheme or parts.netloc:
        return None
    decoded = unquote(parts.path)
    if decoded.startswith("/"):
        resolved = posixpath.normpath(decoded.lstrip("/"))
    elif decoded:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), decoded))
    else:
        resolved = name
    return resolved, unquote(parts.fragment)


def linked_files(name, documents, directories):
    for _, target in documents.get(name, (set(), [], []))[1]:
        try:
            local = local_target(name, target)
        except ValueError:
            continue  # 잘못된 주소는 링크 검사에서 보고한다.
        if local:
            resolved = local[0]
            if resolved in directories:
                resolved = posixpath.join(resolved, "README.md").removeprefix("./")
            yield resolved


def check_final_structure(tracked, directories, documents, sources):
    problems = []
    if DOC_INDEX not in tracked:
        problems.append(Problem(DOC_INDEX, 1, "문서 색인을 Git으로 추적해야 한다"))
    indexed = set(linked_files(DOC_INDEX, documents, directories))
    for name in sorted(tracked):
        if name.startswith("docs/") and name.lower().endswith(".md") and name not in INDEX_EXCEPTIONS:
            if name not in indexed:
                problems.append(Problem(name, 1, f"{DOC_INDEX}에서 문서를 직접 연결해야 한다"))

    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
        if name not in tracked:
            problems.append(Problem(name, 1, "공통 에이전트 진입 파일을 Git으로 추적해야 한다"))
    for name in ("CLAUDE.md", "GEMINI.md"):
        if name in sources:
            imports = AGENT_IMPORT.findall(without_inline_code(without_fences(sources[name])))
            has_import = False
            for target in imports:
                try:
                    has_import |= local_target(name, target) == ("AGENTS.md", "")
                except ValueError:
                    pass  # 주소 오류는 링크 검사에서 보고한다.
            if not has_import:
                problems.append(Problem(name, 1, "@AGENTS.md로 공통 지침을 import해야 한다"))
    copilot = ".github/copilot-instructions.md"
    if copilot in sources and "AGENTS.md" not in set(linked_files(copilot, documents, directories)):
        problems.append(Problem(copilot, 1, "공통 AGENTS.md로 가는 링크가 필요하다"))

    diagrams = {name for name in tracked if name.lower().endswith(".drawio")}
    if diagrams != {DIAGRAM}:
        problems.append(Problem(DIAGRAM, 1, f"draw.io 원본은 이 파일 하나만 추적해야 한다: {sorted(diagrams)}"))

    for name, source in sources.items():
        visible = without_comments(source)
        if name.startswith("docs/") and not name.startswith("docs/design/archive/"):
            for start, _, language in fenced_blocks(visible):
                if language.casefold() == "mermaid":
                    problems.append(Problem(name, visible.count("\n", 0, start) + 1, "별도 Mermaid 그림 대신 목록이나 표를 쓴다"))
        if not name.startswith(("docs/design/archive/", "docs/records/")):
            for match in REMOVED_COMMAND.finditer(visible):
                problems.append(Problem(name, visible.count("\n", 0, match.start()) + 1, f"폐기된 CLI 명령이다: platform.py {match[1]}"))
    return problems


def check_repository(root, *, check_structure=True):
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root,
    ).decode("utf-8").split("\0")) - {""}
    directories = {str(parent) for name in tracked for parent in PurePosixPath(name).parents}
    documents = {}
    sources = {}
    problems = []
    for name in sorted(tracked):
        if not name.lower().endswith(".md"):
            continue
        path = root / name
        if path.is_symlink():
            problems.append(Problem(name, 1, "심볼릭 링크 문서는 검사할 수 없다"))
            continue
        try:
            sources[name] = path.read_text(encoding="utf-8")
            documents[name] = parse_document(name, sources[name])
        except (OSError, UnicodeError) as error:
            problems.append(Problem(name, 1, f"추적 문서를 읽을 수 없다: {error}"))

    for name, (_, links, parse_problems) in documents.items():
        problems.extend(parse_problems)
        for line, target in links:
            try:
                local = local_target(name, target)
            except ValueError:
                problems.append(Problem(name, line, f"잘못된 링크 주소: {target}"))
                continue
            if local is None:
                continue
            resolved, fragment = local
            if resolved not in tracked and resolved not in directories:
                problems.append(Problem(name, line, f"추적 파일 또는 디렉터리가 없다: {target}"))
                continue
            if not (root / resolved).exists():
                problems.append(Problem(name, line, f"작업 트리에 대상이 없다: {target}"))
                continue
            if fragment and resolved in directories:
                resolved = posixpath.join(resolved, "README.md").removeprefix("./")
                if resolved not in documents:
                    problems.append(Problem(name, line, f"앵커를 확인할 README.md가 없다: {target}"))
                    continue
            if fragment and resolved in documents and fragment not in documents[resolved][0]:
                problems.append(Problem(name, line, f"제목 또는 HTML 앵커가 없다: {target}"))
    if check_structure:
        problems.extend(check_final_structure(tracked, directories, documents, sources))
    return sorted(problems, key=lambda problem: (problem.path, problem.line, problem.message))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="검사할 Git 저장소")
    args = parser.parse_args()
    try:
        problems = check_repository(args.root)
    except subprocess.CalledProcessError:
        print("Git 추적 파일 목록을 읽을 수 없다.", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("문서 링크·구조 검사 통과")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
