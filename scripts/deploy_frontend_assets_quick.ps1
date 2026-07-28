param(
    [string]$TargetHost = "jetson-dashboard",
    [string]$RemoteTempDir = "/tmp/jetson-frontend-dist",
    [string]$FrontendContainer = "jetson-nano-frontend",
    [string]$ContainerWebRoot = "/usr/share/nginx/html",
    [string]$FrontendDir = "",
    [switch]$SkipBuild,
    [switch]$NoCacheBustUrl,
    [string]$DashboardBaseUrl = "http://192.168.1.5/"
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailability([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not available in PATH."
    }
}

function Invoke-Step([string]$Message, [scriptblock]$Action) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
    & $Action
}

function Invoke-ExternalChecked([scriptblock]$Command, [string]$FailureMessage) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($FrontendDir)) {
    $FrontendDir = Join-Path $repoRoot "frontend"
}
$FrontendDir = (Resolve-Path $FrontendDir).Path
$distDir = Join-Path $FrontendDir "dist"

Test-CommandAvailability "ssh"
Test-CommandAvailability "scp"
if (-not $SkipBuild) {
    Test-CommandAvailability "npm"
}

Invoke-Step "Validating SSH access to '$TargetHost'" {
    Invoke-ExternalChecked { ssh -o BatchMode=yes $TargetHost "echo ssh_ok" } "SSH key-based connectivity check failed"
}

if (-not $SkipBuild) {
    Invoke-Step "Building frontend in '$FrontendDir'" {
        Push-Location $FrontendDir
        try {
            Invoke-ExternalChecked { & npm.cmd run build } "Frontend build failed"
        }
        finally {
            Pop-Location
        }
    }
}

if (-not (Test-Path (Join-Path $distDir "index.html"))) {
    throw "Build output not found at '$distDir/index.html'. Run without -SkipBuild first."
}

Invoke-Step "Preparing remote staging folder '$RemoteTempDir'" {
    Invoke-ExternalChecked { ssh $TargetHost "rm -rf $RemoteTempDir ; mkdir -p $RemoteTempDir" } "Failed to prepare remote staging folder"
}

Invoke-Step "Copying dist assets to target via SCP" {
    Invoke-ExternalChecked { scp -r "$distDir\*" "$TargetHost`:$RemoteTempDir/" } "SCP asset copy failed"
}

Invoke-Step "Ensuring container '$FrontendContainer' is running" {
    Invoke-ExternalChecked { ssh $TargetHost "docker ps --format '{{.Names}}' | grep -q '^$FrontendContainer$'" } "Frontend container not found on target"
}

Invoke-Step "Replacing static files inside container" {
    Invoke-ExternalChecked { ssh $TargetHost "docker exec $FrontendContainer sh -lc 'rm -rf $ContainerWebRoot/*'" } "Failed clearing container web root"
    Invoke-ExternalChecked { ssh $TargetHost "docker cp $RemoteTempDir/. ${FrontendContainer}:${ContainerWebRoot}/" } "Failed copying assets into frontend container"
}

Invoke-Step "Verifying deployed asset references" {
    Invoke-ExternalChecked { ssh $TargetHost "docker exec $FrontendContainer sh -lc 'ls -1 $ContainerWebRoot/assets'" } "Failed to list deployed assets"
    Invoke-ExternalChecked { ssh $TargetHost "docker exec $FrontendContainer sh -lc 'cat $ContainerWebRoot/index.html'" } "Failed reading deployed index.html"
}

Write-Host "`n✅ Frontend asset quick deploy completed." -ForegroundColor Green

if (-not $NoCacheBustUrl) {
    $ts = Get-Date -Format "yyyyMMdd-HHmmss"
    $base = $DashboardBaseUrl.TrimEnd('/')
    Write-Host "Open this cache-busting URL:" -ForegroundColor Yellow
    Write-Host "  $base/?v=quick-deploy-$ts" -ForegroundColor Yellow
}
