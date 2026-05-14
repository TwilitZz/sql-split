use serde::Serialize;
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use tauri::{Emitter, Window};

#[derive(Clone, Serialize)]
struct ProgressPayload {
    stage: String,
    current: usize,
    total: usize,
}

#[derive(Serialize)]
struct SplitSummary {
    output_dir: String,
    part_paths: Vec<String>,
    statement_count: usize,
    total_bytes: u64,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum ParserState {
    Normal,
    LineComment,
    BlockComment,
    SingleQuote,
    DoubleQuote,
    Backtick,
}

struct ChunkedByteReader {
    reader: BufReader<File>,
    buffer: Vec<u8>,
    position: usize,
    length: usize,
    lookahead: Option<u8>,
}

impl ChunkedByteReader {
    fn new(path: &Path) -> Result<Self, String> {
        let file = File::open(path).map_err(|err| format!("打开输入文件失败：{err}"))?;
        Ok(Self {
            reader: BufReader::with_capacity(1024 * 1024, file),
            buffer: vec![0; 1024 * 1024],
            position: 0,
            length: 0,
            lookahead: None,
        })
    }

    fn read_raw(&mut self) -> Result<Option<u8>, String> {
        if self.position >= self.length {
            self.length = self
                .reader
                .read(&mut self.buffer)
                .map_err(|err| format!("读取输入文件失败：{err}"))?;
            self.position = 0;
            if self.length == 0 {
                return Ok(None);
            }
        }

        let byte = self.buffer[self.position];
        self.position += 1;
        Ok(Some(byte))
    }

    fn next(&mut self) -> Result<Option<u8>, String> {
        if let Some(byte) = self.lookahead.take() {
            return Ok(Some(byte));
        }
        self.read_raw()
    }

    fn peek(&mut self) -> Result<Option<u8>, String> {
        if self.lookahead.is_none() {
            self.lookahead = self.read_raw()?;
        }
        Ok(self.lookahead)
    }
}

fn emit_progress(window: &Window, stage: &str, current: usize, total: usize) {
    let _ = window.emit(
        "split-progress",
        ProgressPayload {
            stage: stage.to_string(),
            current,
            total,
        },
    );
}

fn for_each_statement<F>(path: &Path, mut callback: F) -> Result<(), String>
where
    F: FnMut(&[u8]) -> Result<(), String>,
{
    let mut reader = ChunkedByteReader::new(path)?;
    let mut statement = Vec::with_capacity(8192);
    let mut state = ParserState::Normal;

    while let Some(byte) = reader.next()? {
        statement.push(byte);

        match state {
            ParserState::Normal => {
                let next = reader.peek()?;
                if byte == b'\'' {
                    state = ParserState::SingleQuote;
                } else if byte == b'"' {
                    state = ParserState::DoubleQuote;
                } else if byte == b'`' {
                    state = ParserState::Backtick;
                } else if byte == b'-' && next == Some(b'-') {
                    if let Some(extra) = reader.next()? {
                        statement.push(extra);
                    }
                    state = ParserState::LineComment;
                } else if byte == b'#' {
                    state = ParserState::LineComment;
                } else if byte == b'/' && next == Some(b'*') {
                    if let Some(extra) = reader.next()? {
                        statement.push(extra);
                    }
                    state = ParserState::BlockComment;
                } else if byte == b';' {
                    if statement.iter().any(|item| !item.is_ascii_whitespace()) {
                        callback(&statement)?;
                    }
                    statement.clear();
                }
            }
            ParserState::LineComment => {
                if byte == b'\n' || byte == b'\r' {
                    state = ParserState::Normal;
                }
            }
            ParserState::BlockComment => {
                if byte == b'*' && reader.peek()? == Some(b'/') {
                    if let Some(extra) = reader.next()? {
                        statement.push(extra);
                    }
                    state = ParserState::Normal;
                }
            }
            ParserState::SingleQuote | ParserState::DoubleQuote => {
                let quote = if state == ParserState::SingleQuote {
                    b'\''
                } else {
                    b'"'
                };

                if byte == b'\\' {
                    if let Some(escaped) = reader.next()? {
                        statement.push(escaped);
                    }
                } else if byte == quote {
                    if reader.peek()? == Some(quote) {
                        if let Some(extra) = reader.next()? {
                            statement.push(extra);
                        }
                    } else {
                        state = ParserState::Normal;
                    }
                }
            }
            ParserState::Backtick => {
                if byte == b'`' {
                    if reader.peek()? == Some(b'`') {
                        if let Some(extra) = reader.next()? {
                            statement.push(extra);
                        }
                    } else {
                        state = ParserState::Normal;
                    }
                }
            }
        }
    }

    if statement.iter().any(|item| !item.is_ascii_whitespace()) {
        callback(&statement)?;
    }

    Ok(())
}

fn analyze_statements(input_path: &Path, window: &Window) -> Result<Vec<usize>, String> {
    let mut sizes = Vec::new();
    for_each_statement(input_path, |statement| {
        sizes.push(statement.len());
        if sizes.len() % 1000 == 0 {
            emit_progress(window, "analyze", sizes.len(), 0);
        }
        Ok(())
    })?;
    Ok(sizes)
}

fn plan_boundaries(sizes: &[usize], parts: usize) -> Result<Vec<usize>, String> {
    if parts == 0 {
        return Err("分片数量必须大于 0。".to_string());
    }
    if sizes.is_empty() {
        return Err("没有找到 SQL 语句。".to_string());
    }
    if parts > sizes.len() {
        return Err(format!(
            "请求拆成 {parts} 份，但文件中只有 {} 条 SQL 语句。",
            sizes.len()
        ));
    }

    let mut boundaries = Vec::with_capacity(parts);
    let mut start = 0usize;
    let mut total_remaining: u64 = sizes.iter().map(|size| *size as u64).sum();

    for part_index in 0..parts {
        let remaining_parts = parts - part_index;
        if remaining_parts == 1 {
            boundaries.push(sizes.len());
            break;
        }

        let max_end = sizes.len() - (remaining_parts - 1);
        let target = total_remaining as f64 / remaining_parts as f64;
        let mut current = 0u64;
        let mut best_end = start + 1;
        let mut best_delta = ((sizes[start] as f64) - target).abs();

        for (offset, size) in sizes[start..max_end].iter().enumerate() {
            current += *size as u64;
            let delta = (current as f64 - target).abs();
            if delta <= best_delta {
                best_delta = delta;
                best_end = start + offset + 1;
            }
            if current as f64 >= target {
                break;
            }
        }

        boundaries.push(best_end);
        total_remaining -= sizes[start..best_end]
            .iter()
            .map(|size| *size as u64)
            .sum::<u64>();
        start = best_end;
    }

    Ok(boundaries)
}

fn part_paths(input_path: &Path, output_dir: &Path, parts: usize) -> Result<Vec<PathBuf>, String> {
    let stem = input_path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "输入文件名无效。".to_string())?;
    let extension = input_path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{value}"))
        .unwrap_or_default();

    Ok((1..=parts)
        .map(|index| output_dir.join(format!("{stem}_part_{index:03}_of_{parts:03}{extension}")))
        .collect())
}

#[tauri::command]
fn default_output_dir(input_path: String, parts: usize) -> Result<String, String> {
    let path = PathBuf::from(input_path);
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "输入文件名无效。".to_string())?;
    Ok(parent
        .join(format!("{stem}_split_{parts:03}"))
        .to_string_lossy()
        .to_string())
}

#[tauri::command]
async fn split_sql(
    input_path: String,
    output_dir: String,
    parts: usize,
    window: Window,
) -> Result<SplitSummary, String> {
    tauri::async_runtime::spawn_blocking(move || {
        split_sql_impl(input_path, output_dir, parts, window)
    })
    .await
    .map_err(|err| format!("等待拆分任务完成失败：{err}"))?
}

fn split_sql_impl(
    input_path: String,
    output_dir: String,
    parts: usize,
    window: Window,
) -> Result<SplitSummary, String> {
    let input_path = PathBuf::from(input_path);
    let output_dir = PathBuf::from(output_dir);

    if !input_path.exists() {
        return Err("输入 SQL 文件不存在。".to_string());
    }
    if parts == 0 {
        return Err("分片数量必须大于 0。".to_string());
    }

    fs::create_dir_all(&output_dir).map_err(|err| format!("创建输出目录失败：{err}"))?;

    let sizes = analyze_statements(&input_path, &window)?;
    let boundaries = plan_boundaries(&sizes, parts)?;
    let paths = part_paths(&input_path, &output_dir, parts)?;
    let mut writers = Vec::with_capacity(paths.len());
    for path in &paths {
        let file = File::create(path)
            .map_err(|err| format!("创建输出文件失败 {}：{err}", path.display()))?;
        writers.push(BufWriter::with_capacity(1024 * 1024, file));
    }

    let mut part_index = 0usize;
    let mut next_boundary = boundaries[part_index];
    let mut written = 0usize;
    for_each_statement(&input_path, |statement| {
        writers[part_index]
            .write_all(statement)
            .map_err(|err| format!("写入输出文件失败：{err}"))?;
        written += 1;

        if written % 1000 == 0 {
            emit_progress(&window, "write", written, sizes.len());
        }

        if written >= next_boundary && part_index < parts - 1 {
            writers[part_index]
                .flush()
                .map_err(|err| format!("刷新输出文件失败：{err}"))?;
            part_index += 1;
            next_boundary = boundaries[part_index];
        }

        Ok(())
    })?;

    for writer in &mut writers {
        writer
            .flush()
            .map_err(|err| format!("刷新输出文件失败：{err}"))?;
    }

    emit_progress(&window, "done", sizes.len(), sizes.len());

    Ok(SplitSummary {
        output_dir: output_dir.to_string_lossy().to_string(),
        part_paths: paths
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect(),
        statement_count: sizes.len(),
        total_bytes: sizes.iter().map(|size| *size as u64).sum(),
    })
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![default_output_dir, split_sql])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_sql_path(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!("{name}_{nonce}.sql"))
    }

    #[test]
    fn parser_keeps_semicolons_inside_quotes_and_comments() {
        let path = temp_sql_path("sql_splitter_parser");
        fs::write(
            &path,
            "INSERT INTO t VALUES ('a;b');\n-- comment; still comment\nINSERT INTO t VALUES ('c');\n/* block; comment */ INSERT INTO t VALUES ('d');",
        )
        .expect("test file should be written");

        let mut statements = Vec::new();
        for_each_statement(&path, |statement| {
            statements.push(String::from_utf8_lossy(statement).to_string());
            Ok(())
        })
        .expect("parser should succeed");
        let _ = fs::remove_file(&path);

        assert_eq!(statements.len(), 3);
        assert!(statements[0].contains("'a;b'"));
        assert!(statements[1].trim_start().starts_with("-- comment"));
        assert!(statements[2].contains("block; comment"));
    }

    #[test]
    fn planner_returns_requested_part_count() {
        let boundaries = plan_boundaries(&[10, 10, 10, 10, 10, 10], 3)
            .expect("planner should produce boundaries");

        assert_eq!(boundaries.len(), 3);
        assert_eq!(boundaries[2], 6);
        assert!(boundaries.windows(2).all(|pair| pair[0] < pair[1]));
    }
}
