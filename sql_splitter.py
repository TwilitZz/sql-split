from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class SplitResult:
    input_path: Path
    output_dir: Path
    part_paths: list[Path]
    statement_count: int
    total_bytes: int


class ChunkedCharReader:
    def __init__(self, path: Path, encoding: str, chunk_size: int = 1024 * 1024):
        self._file = path.open("r", encoding=encoding, newline="")
        self._chunk_size = chunk_size
        self._chunk = ""
        self._pos = 0
        self._lookahead: Optional[str] = None

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "ChunkedCharReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _read_raw(self) -> Optional[str]:
        if self._pos >= len(self._chunk):
            self._chunk = self._file.read(self._chunk_size)
            self._pos = 0
            if not self._chunk:
                return None
        char = self._chunk[self._pos]
        self._pos += 1
        return char

    def next(self) -> Optional[str]:
        if self._lookahead is not None:
            char = self._lookahead
            self._lookahead = None
            return char
        return self._read_raw()

    def peek(self) -> Optional[str]:
        if self._lookahead is None:
            self._lookahead = self._read_raw()
        return self._lookahead


def iter_sql_statements(path: Path, encoding: str = "utf-8") -> Iterable[str]:
    """Yield SQL statements without splitting semicolons inside strings/comments."""
    buffer: list[str] = []
    state = "normal"

    with ChunkedCharReader(path, encoding) as reader:
        while True:
            char = reader.next()
            if char is None:
                break

            buffer.append(char)

            if state == "normal":
                next_char = reader.peek()
                if char == "'":
                    state = "single_quote"
                elif char == '"':
                    state = "double_quote"
                elif char == "`":
                    state = "backtick"
                elif char == "-" and next_char == "-":
                    buffer.append(reader.next() or "")
                    state = "line_comment"
                elif char == "#":
                    state = "line_comment"
                elif char == "/" and next_char == "*":
                    buffer.append(reader.next() or "")
                    state = "block_comment"
                elif char == ";":
                    statement = "".join(buffer)
                    if statement.strip():
                        yield statement
                    buffer.clear()

            elif state == "line_comment":
                if char in "\r\n":
                    state = "normal"

            elif state == "block_comment":
                if char == "*" and reader.peek() == "/":
                    buffer.append(reader.next() or "")
                    state = "normal"

            elif state in {"single_quote", "double_quote"}:
                quote = "'" if state == "single_quote" else '"'
                if char == "\\":
                    escaped = reader.next()
                    if escaped is not None:
                        buffer.append(escaped)
                elif char == quote:
                    if reader.peek() == quote:
                        buffer.append(reader.next() or "")
                    else:
                        state = "normal"

            elif state == "backtick":
                if char == "`":
                    if reader.peek() == "`":
                        buffer.append(reader.next() or "")
                    else:
                        state = "normal"

    tail = "".join(buffer)
    if tail.strip():
        yield tail


def _measure_statements(
    input_path: Path,
    encoding: str,
    progress_callback: Optional[ProgressCallback],
) -> list[int]:
    sizes: list[int] = []
    for statement in iter_sql_statements(input_path, encoding):
        sizes.append(len(statement.encode(encoding)))
        if progress_callback and len(sizes) % 1000 == 0:
            progress_callback("analyze", len(sizes), 0)
    return sizes


def _plan_part_boundaries(sizes: list[int], parts: int) -> list[int]:
    if parts < 1:
        raise ValueError("parts must be greater than 0")
    if not sizes:
        raise ValueError("no SQL statements found")
    if parts > len(sizes):
        raise ValueError(
            f"requested {parts} parts, but the file only contains {len(sizes)} SQL statements"
        )

    boundaries: list[int] = []
    start = 0
    total_remaining = sum(sizes)

    for part_index in range(parts):
        remaining_parts = parts - part_index
        if remaining_parts == 1:
            boundaries.append(len(sizes))
            break

        max_end = len(sizes) - (remaining_parts - 1)
        target = total_remaining / remaining_parts
        current = 0
        best_end = start + 1
        best_delta = abs(sizes[start] - target)

        for idx in range(start, max_end):
            current += sizes[idx]
            delta = abs(current - target)
            if delta <= best_delta:
                best_delta = delta
                best_end = idx + 1
            if current >= target:
                break

        boundaries.append(best_end)
        total_remaining -= sum(sizes[start:best_end])
        start = best_end

    return boundaries


def split_sql_file(
    input_path: str | Path,
    parts: int,
    output_dir: str | Path | None = None,
    encoding: str = "utf-8",
    progress_callback: Optional[ProgressCallback] = None,
) -> SplitResult:
    input_path = Path(input_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if parts < 1:
        raise ValueError("parts must be greater than 0")

    if output_dir is None:
        output_dir = input_path.with_name(f"{input_path.stem}_split_{parts:03d}")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    sizes = _measure_statements(input_path, encoding, progress_callback)
    boundaries = _plan_part_boundaries(sizes, parts)

    part_paths = [
        output_dir / f"{input_path.stem}_part_{idx:03d}_of_{parts:03d}{input_path.suffix}"
        for idx in range(1, parts + 1)
    ]

    writers = [path.open("w", encoding=encoding, newline="") for path in part_paths]
    try:
        part_index = 0
        next_boundary = boundaries[part_index]
        written_statements = 0

        for statement in iter_sql_statements(input_path, encoding):
            writers[part_index].write(statement)

            written_statements += 1
            if progress_callback and written_statements % 1000 == 0:
                progress_callback("write", written_statements, len(sizes))

            if written_statements >= next_boundary and part_index < parts - 1:
                part_index += 1
                next_boundary = boundaries[part_index]
    finally:
        for writer in writers:
            writer.close()

    if progress_callback:
        progress_callback("done", len(sizes), len(sizes))

    return SplitResult(
        input_path=input_path,
        output_dir=output_dir,
        part_paths=part_paths,
        statement_count=len(sizes),
        total_bytes=sum(sizes),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a SQL file into balanced parts.")
    parser.add_argument("input", help="SQL file to split")
    parser.add_argument("-p", "--parts", type=int, required=True, help="number of output parts")
    parser.add_argument("-o", "--output-dir", help="directory for output files")
    parser.add_argument("-e", "--encoding", default="utf-8", help="file encoding, default: utf-8")
    args = parser.parse_args()

    def report(stage: str, current: int, total: int) -> None:
        if total:
            print(f"{stage}: {current}/{total}")
        else:
            print(f"{stage}: {current}")

    result = split_sql_file(args.input, args.parts, args.output_dir, args.encoding, report)
    print(f"Created {len(result.part_paths)} files in: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
