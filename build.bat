@echo off
echo Building Granola Export Tool...
echo.

flet pack main.py ^
  --name "Granola Export" ^
  --product-name "Granola Export Tool" ^
  --product-version "1.4.0" ^
  --file-version "1.4.0.0" ^
  --file-description "Export Granola meeting transcripts with summaries and verification" ^
  --copyright "2026" ^
  --hidden-import keyring.backends ^
  --hidden-import keyring.backends.Windows ^
  -y

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo BUILD FAILED
    exit /b 1
)

echo.
echo Build complete! Output: dist\Granola Export.exe
