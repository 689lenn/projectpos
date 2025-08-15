@echo off
setlocal enabledelayedexpansion

REM === Jalankan dari folder tempat file ini berada ===
pushd %~dp0

echo.
echo ==== SETUP REPO GIT: POS APP ====
echo Folder: %CD%
echo.

REM === Buat folder uploads dan file .gitkeep ===
if not exist static\uploads (
  mkdir static\uploads
)
if not exist static\uploads\.gitkeep (
  type nul > static\uploads\.gitkeep
  echo Dibuat: static\uploads\.gitkeep
)

REM === Buat file .gitignore ===
if exist .gitignore (
  echo .gitignore sudah ada, dilewati.
) else (
  > .gitignore (
    echo # Python
    echo __pycache__/
    echo *.pyc
    echo *.pyo
    echo *.pyd
    echo .venv/
    echo venv/
    echo env/
    echo *.env
    echo.
    echo # Flask / instance / DB
    echo instance/
    echo database.db
    echo.
    echo # Uploads
    echo static/uploads/*
    echo !static/uploads/.gitkeep
  )
  echo Dibuat: .gitignore
)

REM === Inisialisasi Git jika belum ===
if not exist .git (
  echo Inisialisasi git...
  git init
) else (
  echo Repo git sudah ada.
)

REM === Paksa nama branch menjadi main ===
git branch -M main

REM === Tambahkan semua file dan commit ===
git add -A

REM === Cek kalau tidak ada perubahan ===
git diff --cached --quiet
if %errorlevel%==0 (
  echo Tidak ada file untuk di-commit (mungkin sudah commit sebelumnya).
) else (
  git commit -m "Initial commit POS app"
)

REM === SET REMOTE ORIGIN ===
set GIT_REMOTE=https://github.com/projectenl69/pos_app.git
echo Remote saat ini:
git remote -v

REM Jika origin belum ada, tambahkan
git remote get-url origin >nul 2>&1
if %errorlevel% neq 0 (
  echo Menambahkan remote origin: %GIT_REMOTE%
  git remote add origin %GIT_REMOTE%
) else (
  echo Remote origin sudah terpasang.
)

REM === PUSH PERTAMA KE MAIN ===
echo Push ke GitHub (branch main)...
git push -u origin main

echo.
echo ==== SELESAI SETUP ====
popd
pause