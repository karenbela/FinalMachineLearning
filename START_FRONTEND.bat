@echo off
cd /d "%~dp0frontend"
if not exist "node_modules" (
  echo Library React belum terinstal. Jalankan npm install dari folder frontend.
  pause
  exit /b 1
)
npm run dev
pause
