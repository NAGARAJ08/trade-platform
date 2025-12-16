# Start All Trade Platform Services
# Run this script to start all 4 microservices

Write-Host "Starting Trade Platform Services..." -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
try {
    python --version | Out-Null
} catch {
    Write-Host "Error: Python not found. Please install Python 3.11+" -ForegroundColor Red
    exit 1
}

Write-Host "Starting services in new windows..." -ForegroundColor Yellow
Write-Host ""

# Start Trade Service
Write-Host "1. Starting Trade Service (Port 8001)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\trade_service\src'; python app.py"
Start-Sleep -Seconds 2

# Start Pricing & PnL Service
Write-Host "2. Starting Pricing & PnL Service (Port 8002)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\pricing_pnl_service\src'; python app.py"
Start-Sleep -Seconds 2

# Start Risk Service
Write-Host "3. Starting Risk Service (Port 8003)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\risk_service\src'; python app.py"
Start-Sleep -Seconds 2

# Start Orchestrator
Write-Host "4. Starting Orchestrator (Port 8000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\orchestrator\src'; python app.py"

Write-Host ""
Write-Host "All services started in separate windows!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Wait 10 seconds for services to initialize, then:" -ForegroundColor Yellow
Write-Host "  - Open Swagger UI: http://localhost:8000/docs" -ForegroundColor White
Write-Host "  - Test endpoint: http://localhost:8000/orders?success=true" -ForegroundColor White
Write-Host ""
Write-Host "To stop all services: Close all PowerShell windows" -ForegroundColor Yellow
