[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$trackedFiles = @(& git -C $repoRoot ls-files)
if ($LASTEXITCODE -ne 0) {
    Write-Output 'ERROR git ls-files failed.'
    exit 2
}

$violations = [System.Collections.Generic.List[object]]::new()

foreach ($path in $trackedFiles) {
    $fileName = [System.IO.Path]::GetFileName($path)
    $isEnvironmentFile = $fileName -eq '.env' -or $fileName -like '.env.*'
    if ($isEnvironmentFile -and $fileName -ne '.env.example') {
        $violations.Add([pscustomobject]@{
            Kind = 'ENV_FILE'
            Path = $path
            Line = $null
            Key  = $null
        })
    }
}

$sourceExtensions = @(
    '.py', '.pyi',
    '.js', '.jsx', '.mjs', '.cjs',
    '.ts', '.tsx', '.mts', '.cts'
)

$knownServerSecretNames = @(
    'SECRET_KEY',
    'DATABASE_URL',
    'ADMIN_ACCESS_CODE',
    'TEACHER_ACCESS_CODE',
    'VAPID_PRIVATE_KEY',
    'EMAIL_PASSWORD',
    'MICROSOFT_CLIENT_SECRET',
    'MS_CLIENT_SECRET',
    'GOOGLE_CLIENT_SECRET',
    'CLIENT_SECRET',
    'JWT_SECRET',
    'SESSION_SECRET',
    'API_SECRET',
    'API_KEY',
    'PRIVATE_KEY'
)

$secretNamePattern = ($knownServerSecretNames | ForEach-Object { [regex]::Escape($_) }) -join '|'
$literalAssignmentPattern = '^[\s]*(?:(?:(?:export|declare)[\s]+)*(?:const|let|var)[\s]+)?(?<key>(?:' + $secretNamePattern + '))(?:[\s]*:[\s]*[^=]+)?[\s]*=[\s]*(?:[rRuUbBfF]{0,2})?(?<quote>["''`])(?<value>.*?)\k<quote>'
$literalPropertyPattern = '^[\s]*(?:["''`]?)(?<key>(?:' + $secretNamePattern + '))(?:["''`]?)\s*:\s*(?<quote>["''`])(?<value>.*?)\k<quote>'
$testFixturePathPattern = '(?i)(?:^|/)(?:tests?|testdata|fixtures?|mocks?|__tests__)(?:/|$)|(?:^|/)(?:test_.*|.*_(?:test|spec)|.*\.(?:test|spec))\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|mts|cts)$'
$placeholderPattern = '(?i)^(?:|test(?:[-_].*)?|testing(?:[-_].*)?|fixture(?:[-_].*)?|placeholder(?:[-_].*)?|example(?:[-_].*)?|dummy(?:[-_].*)?|fake(?:[-_].*)?|sample(?:[-_].*)?|mock(?:[-_].*)?|change[-_]?me|replace[-_]?me|not[-_]?a[-_]?secret|x+)$'

foreach ($path in $trackedFiles) {
    $extension = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($sourceExtensions -notcontains $extension) {
        continue
    }

    $fullPath = Join-Path $repoRoot ($path -replace '/', [System.IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        continue
    }

    $normalizedPath = $path -replace '\\', '/'
    $isTestFixture = $normalizedPath -match $testFixturePathPattern
    $lineNumber = 0

    foreach ($line in Get-Content -LiteralPath $fullPath) {
        $lineNumber++
        $match = [regex]::Match($line, $literalAssignmentPattern)
        if (-not $match.Success) {
            $match = [regex]::Match($line, $literalPropertyPattern)
        }
        if (-not $match.Success) {
            continue
        }

        $literalValue = $match.Groups['value'].Value.Trim()
        if ($isTestFixture -and $literalValue -match $placeholderPattern) {
            continue
        }

        $violations.Add([pscustomobject]@{
            Kind = 'LITERAL_SECRET'
            Path = $path
            Line = $lineNumber
            Key  = $match.Groups['key'].Value
        })
    }
}

if ($violations.Count -gt 0) {
    Write-Output 'Tracked secret policy violations:'
    foreach ($violation in $violations | Sort-Object Path, Line, Kind, Key -Unique) {
        if ($violation.Kind -eq 'ENV_FILE') {
            Write-Output ("ENV_FILE {0}" -f $violation.Path)
        }
        else {
            Write-Output ("LITERAL_SECRET {0}:{1} {2}" -f $violation.Path, $violation.Line, $violation.Key)
        }
    }
    exit 1
}

Write-Output 'No tracked secrets detected.'
exit 0
