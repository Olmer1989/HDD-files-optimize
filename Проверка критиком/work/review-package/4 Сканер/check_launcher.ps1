# ASCII-only checker for Windows PowerShell 5.1; does not start the scan.
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot 'run_pilot.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { Write-Error $_.Message }
    exit 1
}
$assignment = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.VariablePath.UserPath -eq 'python'
}, $true)
$pythonPath = $assignment.Find({ param($node)
    $node -is [System.Management.Automation.Language.StringConstantExpressionAst]
}, $true).Value
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python executable path is invalid.' }
Write-Output ('Windows PowerShell {0}: syntax OK; Python path OK' -f $PSVersionTable.PSVersion)
