import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import "./styles.css";

const inputPath = document.querySelector("#inputPath");
const outputDir = document.querySelector("#outputDir");
const parts = document.querySelector("#parts");
const chooseFile = document.querySelector("#chooseFile");
const chooseOutput = document.querySelector("#chooseOutput");
const startSplit = document.querySelector("#startSplit");
const progressBar = document.querySelector("#progressBar");
const progressText = document.querySelector("#progressText");
const statusBadge = document.querySelector("#statusBadge");
const log = document.querySelector("#log");

let running = false;

function appendLog(message) {
  const time = new Date().toLocaleTimeString();
  log.textContent += `[${time}] ${message}\n`;
  log.scrollTop = log.scrollHeight;
}

function setRunning(value) {
  running = value;
  startSplit.disabled = value;
  chooseFile.disabled = value;
  chooseOutput.disabled = value;
  parts.disabled = value;
}

function setProgress(percent, text) {
  progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  progressText.textContent = text;
}

function setStatus(text, mode = "idle") {
  statusBadge.textContent = text;
  statusBadge.dataset.mode = mode;
}

async function updateDefaultOutput() {
  if (!inputPath.value) return;
  outputDir.value = await invoke("default_output_dir", {
    inputPath: inputPath.value,
    parts: Number(parts.value || 1),
  });
}

chooseFile.addEventListener("click", async () => {
  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "SQL 文件", extensions: ["sql"] }],
  });
  if (typeof selected === "string") {
    inputPath.value = selected;
    await updateDefaultOutput();
  }
});

chooseOutput.addEventListener("click", async () => {
  const selected = await open({
    multiple: false,
    directory: true,
  });
  if (typeof selected === "string") {
    outputDir.value = selected;
  }
});

parts.addEventListener("change", updateDefaultOutput);

listen("split-progress", (event) => {
  const { stage, current, total } = event.payload;
  if (stage === "analyze") {
    setProgress(12, `已分析 ${current} 条 SQL 语句`);
    setStatus("分析中", "busy");
  } else if (stage === "write") {
    const percent = total > 0 ? 20 + (current / total) * 80 : 20;
    setProgress(percent, `正在写入 ${current} / ${total} 条 SQL 语句`);
    setStatus("写入中", "busy");
  } else if (stage === "done") {
    setProgress(100, `完成：${current} 条 SQL 语句`);
    setStatus("完成", "done");
  }
});

startSplit.addEventListener("click", async () => {
  if (running) return;

  const requestedParts = Number(parts.value);
  if (!inputPath.value.trim()) {
    appendLog("请先选择 SQL 文件。");
    return;
  }
  if (!outputDir.value.trim()) {
    appendLog("请先选择输出目录。");
    return;
  }
  if (!Number.isInteger(requestedParts) || requestedParts < 1) {
    appendLog("分片数量必须是大于 0 的整数。");
    return;
  }

  setRunning(true);
  setStatus("启动中", "busy");
  setProgress(0, "正在启动");
  appendLog(`输入文件：${inputPath.value}`);
  appendLog(`输出目录：${outputDir.value}`);

  try {
    const result = await invoke("split_sql", {
      inputPath: inputPath.value,
      outputDir: outputDir.value,
      parts: requestedParts,
    });
    appendLog(`已生成 ${result.part_paths.length} 个文件。`);
    appendLog(`SQL 语句数量：${result.statement_count}`);
    appendLog(`完成目录：${result.output_dir}`);
    setStatus("就绪", "done");
  } catch (error) {
    appendLog(`错误：${error}`);
    setStatus("失败", "error");
    setProgress(0, "拆分失败");
  } finally {
    setRunning(false);
  }
});
