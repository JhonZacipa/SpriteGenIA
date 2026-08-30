@echo off
rem Arranca el servidor de ComfyUI (interfaz en http://127.0.0.1:8188)
rem --reserve-vram 0.4 : deja VRAM libre para el escritorio, asi el PC sigue usable
rem --cache-none       : no retiene modelos entre generaciones (libera ~8 GB de RAM)
cd /d "%~dp0ComfyUI"
.venv\Scripts\python.exe main.py --reserve-vram 0.4 --cache-none
pause
