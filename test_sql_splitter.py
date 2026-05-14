from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sql_splitter import iter_sql_statements, split_sql_file


class SqlSplitterTests(unittest.TestCase):
    def test_iter_sql_statements_respects_quotes_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.sql"
            path.write_text(
                "\n".join(
                    [
                        "INSERT INTO t VALUES ('a;b');",
                        "-- comment; still comment",
                        "INSERT INTO t VALUES ('c');",
                        "/* block; comment */ INSERT INTO t VALUES ('d');",
                    ]
                ),
                encoding="utf-8",
            )

            statements = list(iter_sql_statements(path))

        self.assertEqual(len(statements), 3)
        self.assertIn("'a;b'", statements[0])
        self.assertTrue(statements[1].lstrip().startswith("-- comment"))
        self.assertIn("block; comment", statements[2])

    def test_split_sql_file_creates_requested_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "input.sql"
            path.write_text(
                "".join(f"INSERT INTO t VALUES ({idx});\n" for idx in range(10)),
                encoding="utf-8",
            )

            result = split_sql_file(path, 3, root / "parts")

            self.assertEqual(len(result.part_paths), 3)
            self.assertTrue(all(part.exists() for part in result.part_paths))
            self.assertEqual(result.statement_count, 10)
            combined = "".join(part.read_text(encoding="utf-8") for part in result.part_paths)
            self.assertEqual(combined.rstrip("\n"), path.read_text(encoding="utf-8").rstrip("\n"))


if __name__ == "__main__":
    unittest.main()
