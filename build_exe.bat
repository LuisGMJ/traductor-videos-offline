@echo off
setlocal

if exist .venv\Scripts\python.exe (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON=py -3"
  ) else (
    set "PYTHON=python"
  )
)

%PYTHON% -m PyInstaller --noconfirm traducir_videos.spec

echo.
echo Build local completado en dist\TraductorVideos\
echo Para una release versionada usa: build_release.bat
