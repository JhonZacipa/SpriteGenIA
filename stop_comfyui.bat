@echo off
rem Apaga el motor de IA (ComfyUI) y libera la RAM/VRAM.
rem Se vuelve a encender solo la próxima vez que generes un sprite.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%%'\" | Where-Object { $_.ExecutablePath -like '*ComfyUI*' -or $_.CommandLine -like '*ComfyUI*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Motor de IA apagado.
pause
