$env:PGHOST = "81.71.158.239"
$env:HTTPS_PROXY = "http://127.0.0.1:10809"
$env:HTTP_PROXY = "http://127.0.0.1:10809"
$env:NO_PROXY = "81.71.158.239,127.0.0.1,localhost"
Set-Location "C:\Users\Xingyu Liu\Desktop\Balanced Portfolio"
& ".venv\Scripts\python.exe" -c "import logging,sys; logging.basicConfig(level=logging.INFO); from bp_ingest.crypto_futures import run_once; print(run_once())" 2>&1 | Select-Object -Last 12