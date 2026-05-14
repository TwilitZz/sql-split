#!/usr/bin/env bash
set -euo pipefail

npm install
npm run tauri:build:mac
