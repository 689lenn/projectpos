@echo off
setlocal enabledelayedexpansion

REM ==== Jalankan dari folder script ====
pushd %~dp0

echo.
echo ==== PUSH ALL: POS APP ====
echo Folder: %CD%
echo.

REM ==== Tambahkan semua perubahan ====
git add -A

REM ==== Minta pesan commit ====
set MSG=
set /p MSG=Masukkan pesan commit (kosong = auto timestamp): 

if "%MSG%"=="" (
  for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DATE=%%a-%%b-%%c
  set MSG=Update %DATE% %time%
)

REM ==== Cek apakah ada perubahan staged ====
git diff --cached --quiet
if %errorlevel%==0 (
  echo Tidak ada perubahan untuk di-commit.
) else (
  git commit -m "%MSG%"
)

REM ==== Tentukan branch aktif ====
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set BR=%%b
if "%BR%"=="" set BR=main

REM ==== Push ====
echo Push ke remote origin branch %BR% ...
git push -u origin %BR%

echo.
echo ==== SELESAI ====
popd
pause