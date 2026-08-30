@echo off
rem Abre la interfaz del Generador de Sprites en el navegador
cd /d "%~dp0"
start "" http://127.0.0.1:8787
.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8787
