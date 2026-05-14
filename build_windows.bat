@echo off
setlocal
call npm install
call npm run tauri:build:windows
endlocal
