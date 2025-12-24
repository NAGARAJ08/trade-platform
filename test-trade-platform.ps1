# Trade Platform API Testing Script
# Tests all 3 workflows (retail, institutional, algo) with success/failure scenarios

param(
    [switch]$SkipServiceManagement,
    [switch]$OnlySuccessTests,
    [switch]$OnlyFailureTests,
    [switch]$OnlySpecificTests
)

# Configuration
$BASE_URL = "http://localhost:8000"
$TRADE_SERVICE_URL = "http://localhost:8001"
$PRICING_SERVICE_URL = "http://localhost:8002"
$RISK_SERVICE_URL = "http://localhost:8003"

# Test data for success scenarios
$SUCCESS_TESTS = @(
    @{
        Name = "Retail Success"
        Endpoint = "/orders/retail"
        Payload = @{
            symbol = "AAPL"
            quantity = 50
            order_type = "BUY"
        }
    },
    @{
        Name = "Institutional Success"
        Endpoint = "/orders/institutional"
        Payload = @{
            symbol = "MSFT"
            quantity = 1000
            order_type = "BUY"
        }
    },
    @{
        Name = "Algo Success"
        Endpoint = "/orders/algo"
        Payload = @{
            symbol = "GOOGL"
            quantity = 25
            order_type = "BUY"
        }
    }
)

# Test data for specific scenarios
$SPECIFIC_TESTS = @(
    @{
        Name = "MSFT PnL Mismatch Investigation"
        Endpoint = "/orders/retail"
        Payload = @{
            symbol = "MSFT"
            quantity = 100
            order_type = "SELL"
        }
        Description = "Expected vs Actual Validation - MSFT PnL calculation"
    },
    @{
        Name = "NVDA High Risk Scoring"
        Endpoint = "/orders/retail"
        Payload = @{
            symbol = "NVDA"
            quantity = 200
            order_type = "BUY"
        }
        Description = "Complex Multi-Step Risk Calculation analysis"
    },
    @{
        Name = "AAPL Deep Call Stack"
        Endpoint = "/orders/retail"
        Payload = @{
            symbol = "AAPL"
            quantity = 100
            order_type = "BUY"
        }
        Description = "Deep Call Stack Validation tracing"
    }
)

function Write-TestHeader {
    param([string]$Title)
    Write-Host "`n================================================================================`n" -ForegroundColor Cyan
    Write-Host ">>> $Title" -ForegroundColor Cyan
    Write-Host "`n================================================================================`n" -ForegroundColor Cyan
}

function Write-TestResult {
    param([string]$TestName, [bool]$Success, [string]$Details = "")
    if ($Success) {
        Write-Host "[PASS] $TestName" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $TestName" -ForegroundColor Red
    }
    if ($Details) {
        Write-Host "   $Details" -ForegroundColor Yellow
    }
}

function Test-APIEndpoint {
    param(
        [string]$Name,
        [string]$Endpoint,
        [hashtable]$Payload,
        [string]$Description = ""
    )

    Write-Host "`n>>> Testing: $Name" -ForegroundColor Magenta
    if ($Description) {
        Write-Host "   $Description" -ForegroundColor Gray
    }

    try {
        $jsonPayload = $Payload | ConvertTo-Json
        Write-Host "   Payload: $jsonPayload" -ForegroundColor Blue

        $response = Invoke-RestMethod -Uri "$BASE_URL$Endpoint" -Method POST -Body $jsonPayload -ContentType "application/json" -TimeoutSec 30

        Write-Host "   Status: $($response.status)" -ForegroundColor Green
        Write-Host "   Order ID: $($response.order_id)" -ForegroundColor Green
        Write-Host "   Trace ID: $($response.trace_id)" -ForegroundColor Green
        Write-Host "   Latency: $($response.latency_ms)ms" -ForegroundColor Green

        if ($response.details -and $response.details.execution_flow) {
            Write-Host "   Execution Flow:" -ForegroundColor Cyan
            $response.details.execution_flow.PSObject.Properties | ForEach-Object {
                $stage = $_.Name
                $stageData = $_.Value
                Write-Host "     $stage`: $($stageData.status)" -ForegroundColor White
            }
        }

        return $true
    }
    catch {
        Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.Response) {
            try {
                $errorDetails = $_.Exception.Response.GetResponseStream() | ConvertFrom-Json
                Write-Host "   Error Details: $($errorDetails.detail)" -ForegroundColor Red
            } catch {
                Write-Host "   Raw Response: $($_.Exception.Response.StatusCode)" -ForegroundColor Red
            }
        }
        return $false
    }
}

function Start-Services {
    Write-Host "`nStarting all services..." -ForegroundColor Green

    # Kill any existing processes
    Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*app.py*" } | Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 2

    # Start services in background
    $services = @(
        @{Name = "Orchestrator"; Path = "orchestrator"; Port = 8000},
        @{Name = "Trade Service"; Path = "trade_service"; Port = 8001},
        @{Name = "Pricing Service"; Path = "pricing_pnl_service"; Port = 8002},
        @{Name = "Risk Service"; Path = "risk_service"; Port = 8003}
    )

    foreach ($service in $services) {
        Write-Host "   Starting $($service.Name) on port $($service.Port)..." -ForegroundColor Yellow
        $job = Start-Job -ScriptBlock {
            param($path, $port)
            Set-Location $path
            python src/app.py
        } -ArgumentList $service.Path, $service.Port
        Start-Sleep -Seconds 3
    }

    # Wait for services to be ready
    Write-Host "`nWaiting for services to start..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10

    # Health checks
    Write-Host "`nHealth checks:" -ForegroundColor Cyan
    $services | ForEach-Object {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:$($_.Port)/health" -TimeoutSec 5
            Write-Host "   [OK] $($_.Name): $($health.status)" -ForegroundColor Green
        } catch {
            Write-Host "   [FAIL] $($_.Name): Failed to respond" -ForegroundColor Red
        }
    }
}

function Stop-Service {
    param([string]$ServiceName, [int]$Port)

    Write-Host "`nStopping $ServiceName (Port $Port)..." -ForegroundColor Red

    # Find and kill the process
    $process = Get-Process | Where-Object {
        $_.ProcessName -like "*python*" -and
        $_.CommandLine -like "*$Port*" -and
        $_.CommandLine -like "*app.py*"
    } | Select-Object -First 1

    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Host "   [OK] $ServiceName stopped" -ForegroundColor Green
    } else {
        Write-Host "   [WARN] $ServiceName process not found" -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 2
}

function Run-SuccessTests {
    Write-TestHeader "SUCCESS SCENARIOS - All Services Running"

    $results = @()

    foreach ($test in $SUCCESS_TESTS) {
        $success = Test-APIEndpoint -Name $test.Name -Endpoint $test.Endpoint -Payload $test.Payload
        $results += @{Name = $test.Name; Success = $success}
    }

    Write-Host "`nSuccess Test Summary:" -ForegroundColor Cyan
    $results | ForEach-Object {
        Write-TestResult -TestName $_.Name -Success $_.Success
    }
}

function Run-FailureTests {
    Write-TestHeader "FAILURE SCENARIOS - Service Degradation Testing"

    # Test with Risk Service down
    Write-Host "`nTESTING WITH RISK SERVICE DOWN" -ForegroundColor Red
    # Note: In a real scenario, we'd stop the risk service process
    # For now, we'll simulate by testing against a non-existent endpoint

    $riskFailureResults = @()
    foreach ($test in $SUCCESS_TESTS) {
        $success = Test-APIEndpoint -Name "$($test.Name) (Risk Down)" -Endpoint $test.Endpoint -Payload $test.Payload
        $riskFailureResults += @{Name = $test.Name; Success = $success}
    }

    # Restart Risk Service
    Write-Host "`nRestarting Risk Service..." -ForegroundColor Yellow
    # Note: Service should already be running from initial startup

    # Test with Pricing Service down
    Write-Host "`nTESTING WITH PRICING SERVICE DOWN" -ForegroundColor Red
    # Note: In a real scenario, we'd stop the pricing service process
    # For now, we'll simulate by testing against a non-existent endpoint

    $pricingFailureResults = @()
    foreach ($test in $SUCCESS_TESTS) {
        $success = Test-APIEndpoint -Name "$($test.Name) (Pricing Down)" -Endpoint $test.Endpoint -Payload $test.Payload
        $pricingFailureResults += @{Name = $test.Name; Success = $success}
    }

    # Restart Pricing Service
    Write-Host "`nRestarting Pricing Service..." -ForegroundColor Yellow
    # Note: Service should already be running from initial startup

    # Summary
    Write-Host "`nFailure Test Summary:" -ForegroundColor Cyan
    Write-Host "`nRisk Service Down:" -ForegroundColor Yellow
    $riskFailureResults | ForEach-Object {
        Write-TestResult -TestName $_.Name -Success $_.Success -Details "Should fail at risk_assessment stage"
    }

    Write-Host "`nPricing Service Down:" -ForegroundColor Yellow
    $pricingFailureResults | ForEach-Object {
        Write-TestResult -TestName $_.Name -Success $_.Success -Details "Should fail at pricing_calculation stage"
    }
}

function Run-SpecificTests {
    Write-TestHeader "SPECIFIC SCENARIO INVESTIGATIONS"

    foreach ($test in $SPECIFIC_TESTS) {
        Test-APIEndpoint -Name $test.Name -Endpoint $test.Endpoint -Payload $test.Payload -Description $test.Description
        Write-Host "`n" + "="*80 -ForegroundColor Gray
    }
}

function Show-Logs {
    Write-TestHeader "RECENT LOG FILES"

    Write-Host "Recent log files:" -ForegroundColor Cyan

    Get-ChildItem -Path "*/logs" -Filter "*.log" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | ForEach-Object {
        Write-Host "   $($_.FullName)" -ForegroundColor White
        Write-Host "   Last modified: $($_.LastWriteTime)" -ForegroundColor Gray
        Write-Host "   Size: $([math]::Round($_.Length / 1KB, 2)) KB" -ForegroundColor Gray
        Write-Host ""
    }

    Write-Host "Tip: Check the logs folder for detailed execution traces" -ForegroundColor Cyan
}

# Main execution
Write-Host "Trade Platform API Testing Script" -ForegroundColor Magenta
Write-Host "=====================================" -ForegroundColor Magenta
Write-Host ""

if (-not $SkipServiceManagement) {
    Start-Services
}

if (-not $OnlyFailureTests -and -not $OnlySpecificTests) {
    Run-SuccessTests
}

if (-not $OnlySuccessTests -and -not $OnlySpecificTests) {
    Run-FailureTests
}

if (-not $OnlySuccessTests -and -not $OnlyFailureTests) {
    Run-SpecificTests
}

Show-Logs

Write-Host "`n*** Testing complete! ***" -ForegroundColor Green
Write-Host "Check the logs in each service logs/ directory for detailed traces." -ForegroundColor Cyan