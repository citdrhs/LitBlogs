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
    $isEnvironmentFile = $fileName -like '*.env' -or $fileName -like '.env.*'
    $isEnvironmentExample = $fileName -like '*.env.example'
    if ($isEnvironmentFile -and -not $isEnvironmentExample) {
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

# Credential-bearing keys documented in litblogs/.env.example, followed by
# conventional aliases that should never receive source-code literals.
$knownServerSecretNames = @(
    'SECRET_KEY',
    'DATABASE_URL',
    'ADMIN_ACCESS_CODE',
    'TEACHER_ACCESS_CODE',
    'ADMIN_CODE',
    'GOOGLE_CLIENT_ID',
    'MICROSOFT_CLIENT_ID',
    'MICROSOFT_CLIENT_SECRET',
    'VAPID_PUBLIC_KEY',
    'VAPID_PRIVATE_KEY',
    'EMAIL_USERNAME',
    'EMAIL_PASSWORD',
    'MS_CLIENT_ID',
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
$literalFunctionFallbackPattern = '(?:os\.(?:getenv|environ\.get)|(?:settings|config)\.get)\s*\(\s*["''](?<key>(?:' + $secretNamePattern + '))["'']\s*,\s*(?:[rRuUbBfF]{0,2})?(?<quote>["''`])(?<value>.*?)\k<quote>'
$literalFunctionCoalescePattern = '(?:os\.(?:getenv|environ\.get)|(?:settings|config)\.get)\s*\(\s*["''](?<key>(?:' + $secretNamePattern + '))["'']\s*\)\s*(?:or|\?\?|\|\|)\s*(?:[rRuUbBfF]{0,2})?(?<quote>["''`])(?<value>.*?)\k<quote>'
$literalJavaScriptDotFallbackPattern = '(?:process\.env\.|import\.meta\.env\.)(?<key>(?:' + $secretNamePattern + '))\s*(?:\?\?|\|\|)\s*(?<quote>["''`])(?<value>.*?)\k<quote>'
$literalJavaScriptBracketFallbackPattern = '(?:process\.env|import\.meta\.env)\s*\[\s*["''](?<key>(?:' + $secretNamePattern + '))["'']\s*\]\s*(?:\?\?|\|\|)\s*(?<quote>["''`])(?<value>.*?)\k<quote>'
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
        $violationKind = 'LITERAL_SECRET'
        $match = [regex]::Match($line, $literalAssignmentPattern)
        if (-not $match.Success) {
            $match = [regex]::Match($line, $literalPropertyPattern)
        }
        if (-not $match.Success) {
            $violationKind = 'LITERAL_FALLBACK'
            foreach ($fallbackPattern in @(
                $literalFunctionFallbackPattern,
                $literalFunctionCoalescePattern,
                $literalJavaScriptDotFallbackPattern,
                $literalJavaScriptBracketFallbackPattern
            )) {
                $match = [regex]::Match($line, $fallbackPattern)
                if ($match.Success) {
                    break
                }
            }
        }
        if (-not $match.Success) {
            continue
        }

        $literalValue = $match.Groups['value'].Value.Trim()
        if ($violationKind -eq 'LITERAL_FALLBACK' -and $literalValue.Length -eq 0) {
            continue
        }
        if ($isTestFixture -and $literalValue -match $placeholderPattern) {
            continue
        }

        $violations.Add([pscustomobject]@{
            Kind = $violationKind
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
            Write-Output ("{0} {1}:{2} {3}" -f $violation.Kind, $violation.Path, $violation.Line, $violation.Key)
        }
    }
    exit 1
}

Write-Output 'No tracked secrets detected.'
exit 0
