# ШАБЛОН «ПЕРЕМЕСТИТЬ НА ИСТОЧНИКЕ» (версия 1.0 от 14.11.2026)
#
# Что делает: после копирования перекладывает файлы ВНУТРИ того же диска-источника в папки
#   <диск>:\ПЕРЕНЕСЕНО → 45 и 77\<тот же путь>      (и «только 45», «только 77», «САФАРИ», … , «МУСОР»)
#   Внутри одного диска это переименование: данные не переписываются и не читаются, это быстро.
# Чего НЕ делает: ничего не удаляет и не перезаписывает, на другие диски не пишет вообще.
#   Если в назначении уже лежит файл - не трогает ни его, ни исходник (строка «КОНФЛИКТ» в журнале).
#   Пустые папки, оставшиеся на старом месте, не удаляются.
# Какие файлы перемещать, решает программа (py catalog\hashbase.py mvlist ...): в список попадает файл,
#   только если журнал копирования подтвердил его копии (SHA-256 прочитанного совпал) на всех целевых дисках.
#   Скрипт перед перемещением ещё раз сверяет размер и дату изменения файла со списком.
#
# Рядом со скриптом лежат два файла (UTF-8, поля через TAB):
#   тома.tsv        - <имя диска> TAB <серийный номер тома>  - одна строка: диск-источник
#   перемещение.tsv - <путь от корня диска> TAB <размер в байтах> TAB <дата изменения, секунды UTC или пусто>
#                     TAB <папка назначения, например «ПЕРЕНЕСЕНО → только 77»> TAB <SHA-256> TAB <основание>
#
# Запуск: двойной щелчок по «Запустить.cmd». Остановка: клавиша Q (после текущего файла).
# Повторный запуск продолжит: уже перемещённые файлы пропускаются («уже перемещён»).
# Журнал: «Журнал перемещения <дата время>.tsv» рядом со скриптом, строка после каждого файла.
#   Программа читает его сама: в базе у файла появится новый путь, решения по старому пути продолжат действовать.
# Пять ошибок подряд - признак сбоя диска: перемещение прекращается.
#
# Параметр только для проверки шаблона на тестовых папках: -TestRoots 'HDD55=C:\тест\источник'
param([string]$TestRoots = '')

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ListFile = Join-Path $Here 'перемещение.tsv'
$VolFile = Join-Path $Here 'тома.tsv'
$LongPrefix = '\\?\'
$U8 = [System.Text.Encoding]::UTF8
$Auto = [bool]$TestRoots
$Allowed = 'ПЕРЕНЕСЕНО → '
$Trash = 'МУСОР'

function Fmt-GB([double]$b) { '{0:N2} ГБ' -f ($b / 1GB) }
function Stop-Script([string]$text, [int]$code) {
    Write-Host $text -ForegroundColor Red
    if (-not $Auto) { [void](Read-Host 'Enter - закрыть') }
    exit $code
}
function Get-InnerMessage($err) {
    $e = $err.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    return $e.Message
}
function Test-Rel([string]$rel) {
    return ($rel -and -not $rel.StartsWith('\') -and -not $rel.Contains(':') -and -not $rel.Contains('/') -and
            -not ('\' + $rel + '\').Contains('\..\') -and -not ('\' + $rel + '\').Contains('\.\'))
}

# --- 1. Диск-источник: буква по серийному номеру тома ---
$lines = @([System.IO.File]::ReadAllLines($VolFile, $U8) | Where-Object { $_.Trim() })
if ($lines.Count -ne 1) { Stop-Script 'тома.tsv: нужна ровно одна строка - диск-источник. Ничего не сделано.' 1 }
$f = $lines[0].Split("`t")
if ($f.Count -lt 2) { Stop-Script 'тома.tsv: нет серийного номера. Ничего не сделано.' 1 }
$SrcName = $f[0].Trim(); $Serial = $f[1].Trim().ToUpper()
$Root = $null
if ($TestRoots) {
    foreach ($pair in $TestRoots.Split(';')) {
        $kv = $pair.Split('=', 2)
        if ($kv.Count -eq 2 -and $kv[0].Trim() -eq $SrcName) { $Root = $kv[1].Trim().TrimEnd('\') }
    }
} else {
    $found = @(Get-CimInstance Win32_LogicalDisk | Where-Object { $_.VolumeSerialNumber -and $_.VolumeSerialNumber.ToUpper() -eq $Serial })
    if ($found.Count -gt 1) { Stop-Script "Серийный номер $Serial сразу у нескольких дисков: $(($found | ForEach-Object DeviceID) -join ', '). Ничего не сделано." 1 }
    if ($found.Count -eq 1) { $Root = $found[0].DeviceID }
}
if (-not $Root) { Stop-Script "Диск $SrcName (серийный номер $Serial) не подключён. Ничего не сделано." 1 }

# --- 2. Список: всё проверяется ДО первого перемещения ---
$Items = New-Object System.Collections.Generic.List[object]
$lineNo = 0
foreach ($line in [System.IO.File]::ReadAllLines($ListFile, $U8)) {
    $lineNo++
    if (-not $line.Trim()) { continue }
    $f = $line.Split("`t")
    if ($f.Count -lt 4) { Stop-Script "перемещение.tsv, строка ${lineNo}: меньше четырёх полей. Ничего не сделано." 1 }
    $rel = $f[0]; $folder = $f[3].Trim().Trim('\')
    $size = [int64]0
    if (-not [int64]::TryParse($f[1], [ref]$size) -or $size -lt 0) { Stop-Script "перемещение.tsv, строка ${lineNo}: размер не число. Ничего не сделано." 1 }
    $mtime = [int64]-1
    if ($f[2].Trim() -and -not [int64]::TryParse($f[2], [ref]$mtime)) { Stop-Script "перемещение.tsv, строка ${lineNo}: дата не число. Ничего не сделано." 1 }
    if (-not (Test-Rel $rel)) { Stop-Script "перемещение.tsv, строка ${lineNo}: недопустимый путь «$rel». Ничего не сделано." 1 }
    if (-not (($folder.StartsWith($Allowed) -and -not $folder.Contains('\')) -or $folder -eq $Trash)) {
        Stop-Script "перемещение.tsv, строка ${lineNo}: папка назначения «$folder» - разрешены только «ПЕРЕНЕСЕНО → …» и «МУСОР». Ничего не сделано." 1
    }
    $first = $rel.Split('\')[0]
    if ($first.StartsWith($Allowed) -or $first -eq $Trash) { Stop-Script "перемещение.tsv, строка ${lineNo}: файл уже лежит в «$first». Ничего не сделано." 1 }
    $sha = if ($f.Count -ge 5) { $f[4].Trim() } else { '' }
    $why = if ($f.Count -ge 6) { $f[5].Trim() } else { '' }
    $Items.Add([pscustomobject]@{ Rel = $rel; Size = $size; Mtime = $mtime; Folder = $folder; Sha = $sha; Why = $why })
}
if ($Items.Count -eq 0) { Stop-Script 'Список пуст - перемещать нечего.' 0 }

Write-Host ''
Write-Host "Перемещение внутри диска $SrcName ($Root). Ничего не удаляется и не перезаписывается." -ForegroundColor Cyan
[double]$Total = 0
foreach ($g in ($Items | Group-Object Folder)) {
    [double]$b = 0; foreach ($x in $g.Group) { $b += $x.Size }
    $Total += $b
    Write-Host ("  -> {0}\{1}: {2} файлов, {3}" -f $Root, $g.Name, $g.Count, (Fmt-GB $b))
}
Write-Host 'Q - остановиться после текущего файла. Повторный запуск продолжит с места остановки.'
if (-not $Auto) {
    $ans = Read-Host ("Переместить {0} файлов ({1}) внутри диска {2}? Введите «да»" -f $Items.Count, (Fmt-GB $Total), $SrcName)
    if (@('да', 'д', 'y', 'yes') -notcontains "$ans".Trim().ToLower()) { Write-Host 'Отменено. Ничего не сделано.'; [void](Read-Host 'Enter - закрыть'); exit 0 }
}

# --- 3. Журнал ---
$Stamp = Get-Date -Format 'yyyy-MM-dd HH-mm-ss'
$LogPath = Join-Path $Here "Журнал перемещения $Stamp.tsv"
$Log = [System.IO.StreamWriter]::new($LogPath, $false, [System.Text.UTF8Encoding]::new($true))
$Log.AutoFlush = $true
$Log.WriteLine("время`tрезультат`tразмер`tSHA-256`tоткуда`tкуда`tоснование")

# --- 4. Перемещение ---
$CanKey = $true
try { [void][Console]::KeyAvailable } catch { $CanKey = $false }
$Moved = 0; $Already = 0; $Skipped = 0; $Errors = 0; $Stopped = $false; $ErrorsInRow = 0; $Failing = $false
[double]$MovedBytes = 0
$Start = Get-Date
$LastUi = $Start.AddSeconds(-10)
$i = 0
foreach ($it in $Items) {
    $i++
    $src = $Root + '\' + $it.Rel
    $dst = $Root + '\' + $it.Folder + '\' + $it.Rel
    $result = ''
    try {
        $s = [System.IO.FileInfo]::new($LongPrefix + $src)
        $d = [System.IO.FileInfo]::new($LongPrefix + $dst)
        if (-not $s.Exists) {
            if ($d.Exists -and $d.Length -eq $it.Size) { $result = 'уже перемещён' } else { $result = 'нет источника' }
        }
        elseif ($s.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $result = 'ссылка (reparse point), не трогал' }
        elseif ($s.Length -ne $it.Size) { $result = "размер изменился ($($s.Length)), не трогал" }
        elseif ($it.Mtime -ge 0 -and [math]::Abs(([DateTimeOffset]$s.LastWriteTimeUtc).ToUnixTimeSeconds() - $it.Mtime) -gt 2) { $result = 'дата изменения другая, не трогал' }
        elseif ($d.Exists) { $result = 'КОНФЛИКТ: в назначении уже есть файл, не трогал' }
        else {
            [void][System.IO.Directory]::CreateDirectory($LongPrefix + $dst.Substring(0, $dst.LastIndexOf('\')))
            [System.IO.File]::Move($LongPrefix + $src, $LongPrefix + $dst)
            $result = 'перемещён'
            $Moved++; $MovedBytes += $it.Size
        }
    } catch {
        $result = 'ОШИБКА: ' + (Get-InnerMessage $_)
        $Errors++
    }
    if ($result -eq 'уже перемещён') { $Already++ }
    elseif ($result -ne 'перемещён' -and $result -notlike 'ОШИБКА*') { $Skipped++ }
    if ($result -like 'ОШИБКА*') { $ErrorsInRow++ } else { $ErrorsInRow = 0 }
    if ($ErrorsInRow -ge 5) { $Stopped = $true; $Failing = $true; $result += ' | 5 ошибок подряд - перемещение прекращено, проверьте диск' }
    $Log.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f (Get-Date -Format 'HH:mm:ss'), $result, $it.Size, $it.Sha, $src, $dst, $it.Why))
    $now = Get-Date
    if ($result -ne 'перемещён' -and $result -ne 'уже перемещён') { Write-Host ("[{0}/{1}] {2} - {3}" -f $i, $Items.Count, $it.Rel, $result) -ForegroundColor Yellow }
    if (($now - $LastUi).TotalMilliseconds -ge 500 -or $i -eq $Items.Count) {
        $LastUi = $now
        $pct = [int][math]::Floor(100.0 * $i / $Items.Count)
        Write-Progress -Id 1 -Activity ("Перемещение внутри {0}: файл {1} из {2}" -f $SrcName, $i, $Items.Count) `
            -Status ("{0}% | перемещено {1}, уже было {2}, пропущено {3}, ошибок {4} | Q - стоп" -f $pct, $Moved, $Already, $Skipped, $Errors) -PercentComplete $pct
    }
    if ($CanKey -and [Console]::KeyAvailable) {
        $k = [Console]::ReadKey($true)
        if ($k.Key -eq 'Q') { $Stopped = $true }
    }
    if ($Stopped) { break }
}
$Log.Close()
Write-Progress -Id 1 -Activity ' ' -Completed
$tail = if ($Failing) { ', ПРЕКРАЩЕНО: 5 ошибок подряд' } elseif ($Stopped) { ', ОСТАНОВЛЕНО по Q' } else { '' }
$color = if ($Errors -gt 0) { 'Red' } else { 'Cyan' }
Write-Host ''
Write-Host ("Итог: перемещено {0} ({1}), уже было перемещено {2}, пропущено {3}, ошибок {4}{5}. Время {6:N1} мин." -f $Moved, (Fmt-GB $MovedBytes), $Already, $Skipped, $Errors, $tail, ((Get-Date) - $Start).TotalMinutes) -ForegroundColor $color
if ($Skipped -gt 0 -or $Errors -gt 0) { Write-Host 'Пропущенные и ошибки - строки журнала, кроме «перемещён» и «уже перемещён».' -ForegroundColor Yellow }
Write-Host "Журнал: $LogPath"
if (-not $Auto) { [void](Read-Host 'Enter - закрыть') }
if ($Errors -gt 0) { exit 1 }
exit 0
