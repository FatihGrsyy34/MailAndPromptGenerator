@echo off
rem Arka planda (konsol penceresi olmadan) başlatır. Kısayol: config.toml -> [hotkey]
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m app.main
