@echo off
setlocal
call npm install
call npm run tauri:build:windows
if exist src-tauri\target\release\sql_splitter_tauri.exe (
  copy /Y src-tauri\target\release\sql_splitter_tauri.exe SQL拆分工具.exe
)
endlocal
