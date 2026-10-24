param([switch]$Register)
$ErrorActionPreference = 'Stop'
$integrationDir = $PSScriptRoot
$projectDir = Split-Path (Split-Path $integrationDir -Parent) -Parent
$pythonPath = Join-Path $integrationDir '.venv\Scripts\python.exe'
$temporaryDir = Join-Path $projectDir 'tmp\mcp-install'
New-Item -ItemType Directory -Force -Path $temporaryDir | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    $env:TEMP = $temporaryDir
    $env:TMP = $temporaryDir
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        python -m venv (Join-Path $integrationDir '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create MCP virtual environment' }
    }
    & $pythonPath -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install pip' }
    & $pythonPath -m pip install -r (Join-Path $integrationDir 'requirements.txt') --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install MCP dependencies' }
    if ($Register) {
        codex mcp add school_manager --env PYTHONUTF8=1 -- $pythonPath (Join-Path $integrationDir 'server.py')
        if ($LASTEXITCODE -ne 0) { throw 'Cannot register school_manager in Codex' }
        & $pythonPath (Join-Path $integrationDir 'configure.py')
        if ($LASTEXITCODE -ne 0) { throw 'Cannot configure MCP operation timeouts' }
        codex mcp get school_manager
    }
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
