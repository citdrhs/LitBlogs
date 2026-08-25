[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$failures = [System.Collections.Generic.List[string]]::new()

function Add-TestResult {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail = ''
    )

    if ($Passed) {
        Write-Output "PASS $Name"
        return
    }

    $message = if ($Detail) { "$Name ($Detail)" } else { $Name }
    $failures.Add($message)
    Write-Output "FAIL $message"
}

function Get-CurrentPowerShellExecutable {
    try {
        $currentExecutable = (Get-Process -Id $PID -ErrorAction Stop).Path
        if ($currentExecutable -and (Test-Path -LiteralPath $currentExecutable -PathType Leaf)) {
            return $currentExecutable
        }
    }
    catch {
        # Fall through to command discovery when the host does not expose its path.
    }

    $fallbackNames = if ($PSVersionTable.PSEdition -eq 'Core') {
        @('pwsh', 'powershell')
    }
    else {
        @('powershell.exe', 'pwsh')
    }

    foreach ($name in $fallbackNames) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw 'Unable to locate the current PowerShell executable.'
}

function Invoke-SecretChecker {
    param([string]$Repository)

    $powerShellExecutable = Get-CurrentPowerShellExecutable
    $powerShellArguments = @('-NoLogo', '-NoProfile')
    if ($env:OS -eq 'Windows_NT') {
        $powerShellArguments += @('-ExecutionPolicy', 'Bypass')
    }
    $powerShellArguments += @('-File', (Join-Path $Repository 'scripts\check-no-tracked-secrets.ps1'))

    $output = @(
        & $powerShellExecutable @powerShellArguments 2>&1
    )
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output   = @($output | ForEach-Object { $_.ToString() })
    }
}

function Test-HasViolation {
    param(
        [object]$Result,
        [string]$Kind,
        [string]$Path,
        [string]$Key
    )

    $pattern = '^{0} {1}:\d+ {2}$' -f [regex]::Escape($Kind), [regex]::Escape($Path), [regex]::Escape($Key)
    return @($Result.Output | Where-Object { $_ -match $pattern }).Count -gt 0
}

$documentedCredentialNames = @(
    'DATABASE_URL',
    'SECRET_KEY',
    'ADMIN_ACCESS_CODE',
    'TEACHER_ACCESS_CODE',
    'ADMIN_CODE',
    'GOOGLE_CLIENT_ID',
    'MICROSOFT_CLIENT_ID',
    'MICROSOFT_CLIENT_SECRET',
    'VAPID_PUBLIC_KEY',
    'VAPID_PRIVATE_KEY',
    'EMAIL_USERNAME',
    'EMAIL_PASSWORD'
)

$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$testRepo = Join-Path $tempBase ("litblog-secret-check-tests-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRepo | Out-Null

try {
    New-Item -ItemType Directory -Path (Join-Path $testRepo 'scripts') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testRepo 'nested') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testRepo 'tests') | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'check-no-tracked-secrets.ps1') -Destination (Join-Path $testRepo 'scripts\check-no-tracked-secrets.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\.gitignore') -Destination (Join-Path $testRepo '.gitignore')

    & git -C $testRepo init -q
    & git -C $testRepo add -- '.gitignore' 'scripts/check-no-tracked-secrets.ps1'

    $originalPath = $env:PATH
    $gitDirectory = Split-Path -Parent (Get-Command git -ErrorAction Stop).Source
    $ranWithoutPowerShellOnPath = $false
    try {
        $env:PATH = $gitDirectory
        try {
            $restrictedPathResult = Invoke-SecretChecker $testRepo
            $ranWithoutPowerShellOnPath = $restrictedPathResult.ExitCode -eq 0
        }
        catch {
            $ranWithoutPowerShellOnPath = $false
        }
    }
    finally {
        $env:PATH = $originalPath
    }
    Add-TestResult 'uses the current PowerShell executable without PATH lookup' $ranWithoutPowerShellOnPath

    Set-Content -LiteralPath (Join-Path $testRepo 'nested\config.env') -Value 'TEST_MARKER=opaque-test-placeholder'
    & git -C $testRepo check-ignore -q -- 'nested/config.env'
    $ignoredBeforeForceAdd = $LASTEXITCODE -eq 0
    & git -C $testRepo add -f -- 'nested/config.env'
    $forcedEnvironmentResult = Invoke-SecretChecker $testRepo
    $forcedEnvironmentRejected = $forcedEnvironmentResult.ExitCode -eq 1 -and $forcedEnvironmentResult.Output -contains 'ENV_FILE nested/config.env'
    Add-TestResult 'rejects a force-added nested config.env' ($ignoredBeforeForceAdd -and $forcedEnvironmentRejected)
    & git -C $testRepo rm -q -f -- 'nested/config.env'

    New-Item -ItemType Directory -Path (Join-Path $testRepo 'nested') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $testRepo 'nested\.env.example') -Value 'SAMPLE_SETTING=example'
    Set-Content -LiteralPath (Join-Path $testRepo 'nested\config.env.example') -Value 'SAMPLE_SETTING=example'
    & git -C $testRepo add -- 'nested/.env.example' 'nested/config.env.example'
    $exampleResult = Invoke-SecretChecker $testRepo
    Add-TestResult 'allows nested .env.example variants' ($exampleResult.ExitCode -eq 0)

    Set-Content -LiteralPath (Join-Path $testRepo 'app.py') -Value 'ADMIN_CODE = "opaque-test-placeholder"'
    & git -C $testRepo add -- 'app.py'
    $adminLiteralResult = Invoke-SecretChecker $testRepo
    $adminLiteralRejected = $adminLiteralResult.ExitCode -eq 1 -and (Test-HasViolation $adminLiteralResult 'LITERAL_SECRET' 'app.py' 'ADMIN_CODE')
    Add-TestResult 'rejects an ADMIN_CODE literal assignment' $adminLiteralRejected

    Set-Content -LiteralPath (Join-Path $testRepo 'app.py') -Value 'ADMIN_CODE = os.getenv("ADMIN_CODE", "opaque-test-placeholder")'
    & git -C $testRepo add -- 'app.py'
    $adminFallbackResult = Invoke-SecretChecker $testRepo
    $adminFallbackRejected = $adminFallbackResult.ExitCode -eq 1 -and (Test-HasViolation $adminFallbackResult 'LITERAL_FALLBACK' 'app.py' 'ADMIN_CODE')
    Add-TestResult 'rejects an ADMIN_CODE literal environment fallback' $adminFallbackRejected

    $assignmentLines = [System.Collections.Generic.List[string]]::new()
    foreach ($key in $documentedCredentialNames) {
        $assignmentLines.Add(('{0} = "opaque-test-placeholder"' -f $key))
    }
    Set-Content -LiteralPath (Join-Path $testRepo 'app.py') -Value $assignmentLines
    & git -C $testRepo add -- 'app.py'
    $credentialAssignmentResult = Invoke-SecretChecker $testRepo
    $missingAssignments = @($documentedCredentialNames | Where-Object { -not (Test-HasViolation $credentialAssignmentResult 'LITERAL_SECRET' 'app.py' $_) })
    Add-TestResult 'covers every documented credential assignment name' ($credentialAssignmentResult.ExitCode -eq 1 -and $missingAssignments.Count -eq 0) (($missingAssignments -join ', '))

    $fallbackLines = [System.Collections.Generic.List[string]]::new()
    foreach ($key in $documentedCredentialNames) {
        $fallbackLines.Add(('{0} = os.getenv("{0}", "opaque-test-placeholder")' -f $key))
    }
    Set-Content -LiteralPath (Join-Path $testRepo 'app.py') -Value $fallbackLines
    & git -C $testRepo add -- 'app.py'
    $credentialFallbackResult = Invoke-SecretChecker $testRepo
    $missingFallbacks = @($documentedCredentialNames | Where-Object { -not (Test-HasViolation $credentialFallbackResult 'LITERAL_FALLBACK' 'app.py' $_) })
    Add-TestResult 'covers literal fallbacks for every documented credential name' ($credentialFallbackResult.ExitCode -eq 1 -and $missingFallbacks.Count -eq 0) (($missingFallbacks -join ', '))

    Set-Content -LiteralPath (Join-Path $testRepo 'app.js') -Value 'const ADMIN_CODE = process.env.ADMIN_CODE || "opaque-test-placeholder";'
    & git -C $testRepo rm -q -f -- 'app.py'
    & git -C $testRepo add -- 'app.js'
    $javaScriptFallbackResult = Invoke-SecretChecker $testRepo
    $javaScriptFallbackRejected = $javaScriptFallbackResult.ExitCode -eq 1 -and (Test-HasViolation $javaScriptFallbackResult 'LITERAL_FALLBACK' 'app.js' 'ADMIN_CODE')
    Add-TestResult 'rejects a JavaScript credential fallback' $javaScriptFallbackRejected

    Set-Content -LiteralPath (Join-Path $testRepo 'app.py') -Value 'ADMIN_CODE = os.getenv("ADMIN_CODE")'
    Set-Content -LiteralPath (Join-Path $testRepo 'tests\test_config.py') -Value 'ADMIN_CODE = os.getenv("ADMIN_CODE", "test-placeholder")'
    & git -C $testRepo rm -q -f -- 'app.js'
    & git -C $testRepo add -- 'app.py' 'tests/test_config.py'
    $safeLookupResult = Invoke-SecretChecker $testRepo
    Add-TestResult 'allows fail-closed lookups and test placeholder fallbacks' ($safeLookupResult.ExitCode -eq 0)
}
finally {
    if (Test-Path -LiteralPath $testRepo) {
        $resolvedTestRepo = (Resolve-Path -LiteralPath $testRepo).Path
        $validPrefix = $resolvedTestRepo.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)
        $validName = [System.IO.Path]::GetFileName($resolvedTestRepo) -like 'litblog-secret-check-tests-*'
        if (-not $validPrefix -or -not $validName) {
            throw "Refusing to remove unexpected test path: $resolvedTestRepo"
        }
        Remove-Item -LiteralPath $resolvedTestRepo -Recurse -Force
    }
}

if ($failures.Count -gt 0) {
    Write-Output ("FAILED_TESTS={0}" -f $failures.Count)
    exit 1
}

Write-Output 'ALL_TESTS_PASSED'
exit 0
