@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FastDM

rem 1) هل Python متسطّب؟
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [X] Python مش متسطّب على الجهاز.
  echo      هفتحلك صفحة التحميل. وانت بتسطّب علّم على "Add python.exe to PATH"
  echo      وبعد التسطيب شغّل run.bat تاني.
  start https://www.python.org/downloads/
  pause
  exit /b
)

rem 2) أدوات الفيديو (أول مرة بس)
python -c "import yt_dlp, imageio_ffmpeg, deno" >nul 2>&1
if errorlevel 1 (
  echo  أول تشغيل: بتسطيب أدوات تحميل الفيديو... ممكن ياخد دقيقة
  python -m pip install -U "yt-dlp[default]" imageio-ffmpeg deno
)

rem 3) لو البرنامج شغال أصلاً
curl -s -m 2 http://127.0.0.1:6801/ping >nul 2>&1
if not errorlevel 1 (
  echo  [OK] FastDM شغال بالفعل.
  timeout /t 2 >nul
  exit /b
)

rem 4) تشغيل البرنامج والتأكد إنه فتح
start "" pythonw FastDM.py
echo  بيفتح FastDM...
timeout /t 4 >nul
curl -s -m 2 http://127.0.0.1:6801/ping >nul 2>&1
if not errorlevel 1 (
  echo  [OK] FastDM اشتغل. تقدر تقفل النافذة دي.
  timeout /t 2 >nul
  exit /b
)

rem 5) ما فتحش: نشغّله بطريقة بتعرض الخطأ
echo.
echo  [X] البرنامج ما فتحش. ده سبب المشكلة:
echo  ------------------------------------------
python FastDM.py
echo  ------------------------------------------
echo  صوّر الشاشة دي وابعتها.
pause
