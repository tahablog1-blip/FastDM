@echo off
chcp 65001 >nul
echo تحديث أداة يوتيوب (لو تحميل يوتيوب وقف فجأة)...
python -m pip install -U "yt-dlp[default]"
echo تم. لو بتستخدم نسخة exe، شغّل build_exe.bat تاني.
pause
