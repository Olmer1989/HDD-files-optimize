$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$python = 'C:\Users\Вадим\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Bundled Python not found.' }
$selection = Join-Path $PSScriptRoot '..\Каталог дисков\Выборка_20261107_205134_030997\selection.sqlite'
foreach ($diskId in @('HDD02', 'HDD01')) {
    & $python (Join-Path $PSScriptRoot 'hash_files.py') --selection $selection --disk $diskId --max-gb 1
    if ($LASTEXITCODE -ne 0) { throw "Hash pilot stopped: $diskId" }
}
