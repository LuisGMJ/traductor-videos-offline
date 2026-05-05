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

%PYTHON% app.py
