# Run as the normal Windows user, not from the Codex sandbox. ASCII for PS 5.1.
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$repository = 'https://github.com/wadimka78/hdd-opimization-foto-video.git'
$git = Join-Path $env:ProgramFiles 'Git\cmd\git.exe'
if (-not (Test-Path -LiteralPath $git)) { $git = (Get-Command git -ErrorAction Stop).Source }

function Invoke-Git {
    & $script:git -C $script:project @args
    if ($LASTEXITCODE -ne 0) { throw "Git stopped (exit $LASTEXITCODE). No force push was attempted." }
}

$remotes = @(& $git -C $project remote)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Git remotes.' }
if ($remotes -notcontains 'origin') {
    Invoke-Git remote add origin $repository
} else {
    $remote = & $git -C $project remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $remote.Trim().TrimEnd('/') -ne $repository) {
        throw 'Existing origin differs from the requested repository. Inspect it before continuing.'
    }
}

# Fail before staging if GitHub is unavailable or authentication is missing.
Invoke-Git ls-remote origin
Invoke-Git add -- .
$staged = @(& $git -C $project diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect staged paths.' }
foreach ($name in $staged) {
    if ($name -match '(^|/)(\.env($|\.)|[^/]*\.env$)|(^|/)disks\.json$|\.(sqlite|db|xlsx)($|-)|^dist/|^git-acl-') {
        throw "Unexpected private/generated path staged: $name. Inspect the index before continuing."
    }
}
Invoke-Git diff --cached --stat
if ($staged.Count -gt 0) {
    Invoke-Git commit -m 'Preserve HDD inventory tools and add offline Windows scanning kit'
}
$branch = & $git -C $project branch --show-current
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) { throw 'Cannot determine current branch.' }
Invoke-Git push -u origin $branch.Trim()
Invoke-Git log -1 --format='%h %s'
Write-Host 'Published successfully.'
