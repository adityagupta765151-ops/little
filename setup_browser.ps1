# Installs the browser Little drives. Run once, inside the venv:
#   .\.venv\Scripts\Activate.ps1
#   powershell -ExecutionPolicy Bypass -File setup_browser.ps1

Write-Host "Installing Playwright and Chromium (about 150 MB, one time)..." -ForegroundColor Cyan
python -m pip install playwright
python -m playwright install chromium
Write-Host "Done. Try: summarize this page https://news.ycombinator.com" -ForegroundColor Cyan
