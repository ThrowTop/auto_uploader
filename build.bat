@echo off
REM Build YouTubeUploader with PyInstaller and ensure pywin32 is bundled correctly

pyinstaller ^
  --onefile ^
  --windowed ^
  --name "YouTubeUploader" ^
  --icon "lib/yt.ico" ^
  --add-data "lib/client_secret.json;lib" ^
  --add-data "lib/yt.ico;lib" ^
  --hidden-import win32crypt ^
  main_gui.py

del YouTubeUploader.spec
pause
