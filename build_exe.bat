@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === FastDM: بناء البرنامج ===
python --version || (echo لازم تسطب Python الأول من python.org & pause & exit /b)
python -m pip install -U pyinstaller "yt-dlp[default]" imageio-ffmpeg deno
for /f "delims=" %%i in ('python -c "import deno;print(deno.find_deno_bin())"') do set DENO=%%i
python -m PyInstaller --noconfirm --onedir --windowed --name FastDM --icon icon.ico ^
  --collect-submodules yt_dlp --collect-data yt_dlp_ejs --collect-data imageio_ffmpeg ^
  --add-binary "%DENO%;." FastDM.py
echo.
echo تم! البرنامج موجود في: dist\FastDM\FastDM.exe
echo (انقل فولدر dist\FastDM كله، مش الـ exe لوحده)
pause
