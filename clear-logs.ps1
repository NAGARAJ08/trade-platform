# Clear Logs Script for Trade Platform Services
# This script deletes all log files from all service log directories

Write-Host "Clearing all log files from Trade Platform services..." -ForegroundColor Yellow

# Define log directories
$logDirectories = @(
    "trade_service/logs",
    "pricing_pnl_service/logs",
    "risk_service/logs",
    "orchestrator/logs"
)

$totalFilesDeleted = 0

foreach ($dir in $logDirectories) {
    if (Test-Path $dir) {
        $logFiles = Get-ChildItem -Path $dir -Filter "*.log" -File
        $fileCount = $logFiles.Count

        if ($fileCount -gt 0) {
            $logFiles | Remove-Item -Force
            Write-Host "Deleted $fileCount log files from $dir" -ForegroundColor Green
            $totalFilesDeleted += $fileCount
        } else {
            Write-Host "No log files found in $dir" -ForegroundColor Gray
        }
    } else {
        Write-Host "Directory $dir does not exist" -ForegroundColor Red
    }
}

Write-Host "`nTotal log files deleted: $totalFilesDeleted" -ForegroundColor Cyan
Write-Host "Log cleanup completed!" -ForegroundColor Green