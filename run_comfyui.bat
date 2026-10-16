@echo off
rem Arranca el servidor de ComfyUI (interfaz en http://127.0.0.1:8188)
rem --reserve-vram 0.1    : reserva minima para el escritorio; casi toda la VRAM va a los modelos (a 0 el PC se congela)
rem (sin --cache-none)    : la cache por defecto retiene los modelos entre generaciones,
rem                         asi el 2o video Wan no recarga los expertos desde disco; en
rem                         reposo retiene ~9 GB de RAM: apagar el motor al terminar
rem --preview-method auto : emite previews del latente por WebSocket (latent2rgb,
rem                         coste infimo) para la miniatura en vivo de la GUI
cd /d "%~dp0ComfyUI"
.venv\Scripts\python.exe main.py --reserve-vram 0.1 --preview-method auto
pause
