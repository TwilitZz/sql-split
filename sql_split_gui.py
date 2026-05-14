from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from sql_splitter import split_sql_file


class SqlSplitApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SQL 拆分工具")
        self.geometry("760x520")
        self.minsize(680, 460)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.output_dir: Path | None = None

        default_sql = self._find_default_sql()
        self.file_var = tk.StringVar(value=str(default_sql) if default_sql else "")
        self.output_var = tk.StringVar(value=self._default_output_dir(default_sql) if default_sql else "")
        self.parts_var = tk.IntVar(value=5)
        self.encoding_var = tk.StringVar(value="utf-8")
        self.status_var = tk.StringVar(value="就绪")

        self._build_ui()
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

        ttk.Label(frame, text="SQL 文件").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.file_var).grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(frame, text="浏览...", command=self._choose_file).grid(
            row=0, column=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="输出目录").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(frame, text="浏览...", command=self._choose_output_dir).grid(
            row=1, column=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="分片数量").grid(row=2, column=0, sticky="w", pady=(0, 8))
        parts = ttk.Spinbox(frame, from_=1, to=999, textvariable=self.parts_var, width=10)
        parts.grid(row=2, column=1, sticky="w", padx=8, pady=(0, 8))

        ttk.Label(frame, text="Encoding").grid(row=3, column=0, sticky="w", pady=(0, 8))
        encoding = ttk.Combobox(
            frame,
            textvariable=self.encoding_var,
            values=("utf-8", "utf-8-sig", "gb18030", "gbk"),
            width=16,
        )
        encoding.grid(row=3, column=1, sticky="w", padx=8, pady=(0, 8))

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 12))
        self.split_button = ttk.Button(actions, text="开始拆分", command=self._start_split)
        self.split_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="打开输出目录", command=self._open_output_dir)
        self.open_button.pack(side="left", padx=(8, 0))
        self.open_button.state(["disabled"])

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 10))

        log_frame = ttk.Frame(frame)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=12, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        ttk.Label(frame, textvariable=self.status_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._log("请选择 SQL 文件，设置分片数量，然后开始拆分。")

    def _find_default_sql(self) -> Path | None:
        sql_files = sorted(Path.cwd().glob("*.sql"))
        return sql_files[0] if sql_files else None

    def _default_output_dir(self, sql_path: Path | None) -> str:
        if not sql_path:
            return ""
        return str(sql_path.with_name(f"{sql_path.stem}_split_005"))

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 SQL 文件",
            filetypes=(("SQL 文件", "*.sql"), ("所有文件", "*.*")),
        )
        if path:
            self.file_var.set(path)
            selected = Path(path)
            self.output_var.set(self._default_output_dir(selected))

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def _start_split(self) -> None:
        input_path = Path(self.file_var.get()).expanduser()
        output_path = Path(self.output_var.get()).expanduser()
        parts = self.parts_var.get()
        encoding = self.encoding_var.get().strip() or "utf-8"

        if not input_path.exists():
            messagebox.showerror("SQL 拆分工具", "SQL 文件不存在。")
            return
        if parts < 1:
            messagebox.showerror("SQL 拆分工具", "分片数量必须大于 0。")
            return
        if not str(output_path):
            messagebox.showerror("SQL 拆分工具", "必须选择输出目录。")
            return

        self.split_button.state(["disabled"])
        self.open_button.state(["disabled"])
        self.progress.configure(value=0, maximum=100)
        self.status_var.set("正在分析 SQL 语句...")
        self._log(f"正在拆分：{input_path}")
        self._log(f"输出目录：{output_path}")

        worker = threading.Thread(
            target=self._run_split,
            args=(input_path, output_path, parts, encoding),
            daemon=True,
        )
        worker.start()

    def _run_split(self, input_path: Path, output_path: Path, parts: int, encoding: str) -> None:
        def progress(stage: str, current: int, total: int) -> None:
            self.events.put(("progress", (stage, current, total)))

        try:
            result = split_sql_file(input_path, parts, output_path, encoding, progress)
            self.events.put(("done", result))
        except Exception as exc:
            self.events.put(("error", exc))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self._handle_progress(payload)  # type: ignore[arg-type]
                elif event == "done":
                    self._handle_done(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._handle_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle_progress(self, payload: tuple[str, int, int]) -> None:
        stage, current, total = payload
        if stage == "analyze":
            self.status_var.set(f"已分析 {current} 条 SQL 语句...")
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        elif stage == "write":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(total, 1), value=current)
            self.status_var.set(f"正在写入 SQL 语句 {current}/{total}...")
        elif stage == "done":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(total, 1), value=current)
            self.status_var.set("完成")

    def _handle_done(self, result: object) -> None:
        self.output_dir = result.output_dir  # type: ignore[attr-defined]
        self.split_button.state(["!disabled"])
        self.open_button.state(["!disabled"])
        self._log(
            f"已从 {result.statement_count} 条 SQL 语句生成 {len(result.part_paths)} 个文件。"  # type: ignore[attr-defined]
        )
        self._log(f"完成目录：{result.output_dir}")  # type: ignore[attr-defined]
        messagebox.showinfo("SQL 拆分工具", f"文件已生成到：\n{result.output_dir}")  # type: ignore[attr-defined]

    def _handle_error(self, exc: Exception) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.split_button.state(["!disabled"])
        self.status_var.set("失败")
        self._log(f"错误：{exc}")
        messagebox.showerror("SQL 拆分工具", str(exc))

    def _open_output_dir(self) -> None:
        if not self.output_dir:
            return
        path = str(self.output_dir)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")


if __name__ == "__main__":
    SqlSplitApp().mainloop()
