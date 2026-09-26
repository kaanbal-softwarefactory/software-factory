# Nexus Console Development - Quick Start
# Ejecutar este script para iniciar el frontend en desarrollo

Write-Host "🚀 Iniciando Nexus Console (Frontend)..." -ForegroundColor Cyan

# Configurar API URL
$env:VITE_API_URL = "http://localhost:8000"

Write-Host ""
Write-Host "📋 Configuración:" -ForegroundColor Cyan
Write-Host "   API Backend: $env:VITE_API_URL"
Write-Host ""

# Verificar si el backend está corriendo
$apiCheck = $null
try {
    $apiCheck = Invoke-RestMethod -Uri "http://localhost:8000" -TimeoutSec 2 -ErrorAction SilentlyContinue
} catch { }

if (-not $apiCheck) {
    Write-Host "⚠️  El backend no está corriendo en localhost:8000" -ForegroundColor Yellow
    Write-Host "   Ejecuta primero: cd nexus-api; .\dev-local.ps1" -ForegroundColor Yellow
    Write-Host ""
}

# Instalar dependencias si es necesario
if (-not (Test-Path ".\node_modules")) {
    Write-Host "📦 Instalando dependencias npm..." -ForegroundColor Yellow
    npm install
}

Write-Host ""
Write-Host "🌐 Iniciando Kaanbal Console en http://localhost:5173" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para detener: Ctrl+C" -ForegroundColor Gray
Write-Host ""

# Iniciar Vite
npm run dev
