# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ (версия 2.2 от 12.11.2026)
#
# Что делает: копирует файлы по списку с диска-источника на один или несколько дисков-целей.
#   Куда: <цель>:\ПЕРЕНОС с других дисков\<имя источника>\<тот же путь, что на источнике>
#   (папку на цели можно задать свою - третьей колонкой в тома.tsv)
# Чего НЕ делает: не удаляет, не перемещает и не перезаписывает ничего. На источник не пишет вообще.
#   Единственное, что скрипт стирает, - собственный недописанный временный файл «.part».
#
# Рядом со скриптом лежат два файла (UTF-8, поля через TAB):
#   тома.tsv   - <имя диска> TAB <серийный номер тома> [TAB <папка на этом диске>]. ПЕРВАЯ строка - источник,
#                остальные - цели. Третья колонка (только для целей) заменяет «ПЕРЕНОС с других дисков».
#                Если диска-цели нет под рукой, в его строке можно указать серийный номер другого диска и папку на нём.
#   список.tsv - <имя цели> TAB <путь от корня источника> TAB <размер в байтах> TAB <пометка> [TAB <SHA-256 из описи>]
#
# Запуск: двойной щелчок по «Запустить.cmd» (без вопроса о политике выполнения)
#         или правой кнопкой по этому файлу - «Выполнить с помощью PowerShell».
# Остановка: клавиша Q. Недописанный файл стирается, повторный запуск продолжит с места остановки.
# Журнал: «Журнал копирования <дата время>.tsv» рядом со скриптом, строка после каждого файла.
#   В журнал пишется SHA-256 того, что прочитано с источника, - сверка с описью без повторного чтения дисков.
# Если диск не отвечает дольше $TimeoutSec секунд, копирование прекращается с сообщением, какой диск завис.
#   Ограничение: предел ожидания действует на чтение и запись данных. Открытие файла, создание папки и
#   завершение записи (Flush) Windows может держать дольше. Если окно не меняется больше 5 минут -
#   закройте его и проверьте диск; недописанный «.part» уберёт следующий запуск.
# Файл, который уже лежит в цели с тем же размером, считается скопированным и повторно не читается
#   (правило проекта). Копии, сделанные старыми скриптами, сверяются по SHA-256 отдельно.
#
# Параметры ниже нужны только для проверки шаблона на тестовых папках, при обычном запуске не задаются:
#   -TestRoots 'HDD17=C:\тест\источник;HDD45=C:\тест\цель1'  (папки вместо дисков, без вопросов)
param(
    [string]$TestRoots = '',
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ListFile = Join-Path $Here 'список.tsv'
$VolFile = Join-Path $Here 'тома.tsv'
$DestFolder = 'ПЕРЕНОС с других дисков'
$LongPrefix = '\\?\'
$BufSize = 4MB
$TimeoutMs = $TimeoutSec * 1000
$U8 = [System.Text.Encoding]::UTF8
$Auto = [bool]$TestRoots

function Fmt-GB([double]$b) { '{0:N2} ГБ' -f ($b / 1GB) }
# Процент считается в дробных числах: никаких Int32, файлы и объёмы любого размера.
function Get-Pct([double]$part, [double]$whole) {
    if ($whole -le 0) { return 100 }
    $p = [int][math]::Floor(100.0 * $part / $whole)
    if ($p -lt 0) { return 0 }
    if ($p -gt 100) { return 100 }
    return $p
}
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

# --- 1. Диски: буквы определяются по серийному номеру тома ---
$BySerial = @{}
$LogicalDisks = if ($TestRoots) { @() } else { @(Get-CimInstance Win32_LogicalDisk) }
foreach ($d in $LogicalDisks) {
    if ($d.VolumeSerialNumber) {
        $key = $d.VolumeSerialNumber.ToUpper()
        if (-not $BySerial.ContainsKey($key)) { $BySerial[$key] = @() }
        $BySerial[$key] += $d.DeviceID
    }
}
# v2.2: third column of source row is a source subfolder, not a destination prefix.
$SourceSubfolder = ''
$Override = @{}
if ($TestRoots) {
    foreach ($pair in $TestRoots.Split(';')) {
        $kv = $pair.Split('=', 2)
        if ($kv.Count -eq 2) { $Override[$kv[0].Trim()] = $kv[1].Trim().TrimEnd('\') }
    }
}
$Names = New-Object System.Collections.Generic.List[string]
$Root = @{}
$Dest = @{}
foreach ($line in [System.IO.File]::ReadAllLines($VolFile, $U8)) {
    if (-not $line.Trim()) { continue }
    $f = $line.Split("`t")
    if ($f.Count -lt 2) { Stop-Script "тома.tsv: строка без серийного номера: $line" 1 }
    $name = $f[0].Trim(); $serial = $f[1].Trim().ToUpper()
    $Names.Add($name)
    $Dest[$name] = $DestFolder
    if ($f.Count -ge 3 -and $f[2].Trim()) {
        $Dest[$name] = $f[2].Trim().Trim('\')
        if ($Dest[$name].Contains(':') -or $Dest[$name].Contains('/') -or ('\' + $Dest[$name] + '\').Contains('\..\')) { Stop-Script "тома.tsv: недопустимая папка «$($Dest[$name])» у $name. Ничего не сделано." 1 }
    }
    if ($Names.Count -eq 1 -and $f.Count -ge 3 -and $f[2].Trim()) { $SourceSubfolder = $f[2].Trim('\') }
    if ($Override.ContainsKey($name)) { $Root[$name] = $Override[$name] }
    elseif ($TestRoots) { $Root[$name] = $null }
    elseif ($BySerial.ContainsKey($serial)) {
        if ($BySerial[$serial].Count -gt 1) { Stop-Script "Серийный номер $serial ($name) сразу у нескольких дисков: $($BySerial[$serial] -join ', '). Не могу выбрать. Ничего не сделано." 1 }
        $Root[$name] = $BySerial[$serial][0]
    }
    else { $Root[$name] = $null }
}
if ($Names.Count -lt 2) { Stop-Script 'В тома.tsv нужны минимум две строки: источник и хотя бы одна цель. Ничего не сделано.' 1 }
$SrcName = $Names[0]
if ($SourceSubfolder -and $Root[$SrcName]) {
    $Root[$SrcName] = $Root[$SrcName].TrimEnd('\') + '\' + $SourceSubfolder
}
$Targets = @($Names | Select-Object -Skip 1)

Write-Host ''
Write-Host 'Копирование по списку. Ничего не удаляется и не перезаписывается.' -ForegroundColor Cyan
Write-Host 'Диски:' -ForegroundColor Cyan
foreach ($n in $Names) {
    $role = if ($n -eq $SrcName) { 'источник' } else { 'цель' }
    if ($Root[$n]) { Write-Host ("  {0} ({1}) = {2}" -f $n, $role, $Root[$n]) }
    else { Write-Host ("  {0} ({1}) - НЕ ПОДКЛЮЧЁН" -f $n, $role) -ForegroundColor Yellow }
}
if (-not $Root[$SrcName]) { Stop-Script "Источник $SrcName не подключён. Ничего не сделано." 1 }
foreach ($t in $Targets) {
    if ($Root[$t] -and $Root[$t] -eq $Root[$SrcName]) { Stop-Script "Цель $t и источник $SrcName - один и тот же диск. Ничего не сделано." 1 }
}

# --- 2. Список ---
$Items = New-Object System.Collections.Generic.List[object]
$lineNo = 0
foreach ($line in [System.IO.File]::ReadAllLines($ListFile, $U8)) {
    $lineNo++
    if (-not $line.Trim()) { continue }
    $f = $line.Split("`t")
    if ($f.Count -lt 3) { Stop-Script "список.tsv, строка ${lineNo}: меньше трёх полей. Ничего не сделано." 1 }
    $rel = $f[1]
    $size = [int64]0
    if (-not [int64]::TryParse($f[2], [ref]$size) -or $size -lt 0) { Stop-Script "список.tsv, строка ${lineNo}: размер не число. Ничего не сделано." 1 }
    if ($Targets -notcontains $f[0]) { Stop-Script "список.tsv, строка ${lineNo}: цель «$($f[0])» не указана в тома.tsv. Ничего не сделано." 1 }
    if (-not $rel -or $rel.StartsWith('\') -or $rel.Contains(':') -or $rel.Contains('/') -or ('\' + $rel + '\').Contains('\..\')) {
        Stop-Script "список.tsv, строка ${lineNo}: недопустимый путь «$rel». Ничего не сделано." 1
    }
    $hash = ''
    if ($f.Count -ge 5 -and $f[4] -match '^[0-9A-Fa-f]{64}$') { $hash = $f[4].ToUpper() }
    $Items.Add([pscustomobject]@{ Target = $f[0]; Rel = $rel; Size = $size; Hash = $hash })
}
$Todo = @($Items | Where-Object { $Root[$_.Target] })
Write-Host ''
[double]$Total = 0
foreach ($t in $Targets) {
    $g = @($Items | Where-Object { $_.Target -eq $t })
    [double]$need = 0
    foreach ($x in $g) { $need += $x.Size }
    if (-not $Root[$t]) { Write-Host ("{0}: {1} файлов, {2} - диск не подключён, пропускается" -f $t, $g.Count, (Fmt-GB $need)) -ForegroundColor Yellow; continue }
    $Total += $need
    $free = [double]([System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($Root[$t] + '\')).AvailableFreeSpace)
    Write-Host ("{0}: {1} файлов, {2} -> {3}\{4}\{5}   (свободно {6})" -f $t, $g.Count, (Fmt-GB $need), $Root[$t], $Dest[$t], $SrcName, (Fmt-GB $free))
    if ($free -lt $need + 1GB) { Stop-Script "На $t не хватает места. Ничего не сделано." 1 }
}
if ($Todo.Count -eq 0) { Stop-Script 'Копировать нечего: нужные диски не подключены или список пуст.' 0 }
$withHash = @($Todo | Where-Object { $_.Hash }).Count
Write-Host ("Сверка с SHA-256 из описи: {0} из {1} файлов (для остальных SHA-256 только записывается в журнал)." -f $withHash, $Todo.Count)
Write-Host ''
if (-not $Auto) {
    $ans = Read-Host ("Копировать {0} файлов, {1}? Введите «да»" -f $Todo.Count, (Fmt-GB $Total))
    if (@('да', 'д', 'y', 'yes') -notcontains "$ans".Trim().ToLower()) { Write-Host 'Отменено. Ничего не сделано.'; [void](Read-Host 'Enter - закрыть'); exit 0 }
}

# --- 3. Журнал ---
$Stamp = Get-Date -Format 'yyyy-MM-dd HH-mm-ss'
$LogPath = Join-Path $Here "Журнал копирования $Stamp.tsv"
$Log = [System.IO.StreamWriter]::new($LogPath, $false, [System.Text.UTF8Encoding]::new($true))
$Log.AutoFlush = $true
$Log.WriteLine("время`tцель`tрезультат`tразмер`tSHA-256 прочитанного`tисточник`tкуда")

# --- 4. Копирование ---
$CanKey = $true
try { [void][Console]::KeyAvailable } catch { $CanKey = $false; Write-Host 'Нет консоли - остановка по Q недоступна (закройте окно, чтобы прервать).' -ForegroundColor Yellow }
[double]$Done = 0          # пройдено по списку, байт (для процента)
[double]$CopiedBytes = 0   # реально скопировано, байт (для скорости)
$Copied = 0; $Skipped = 0; $Errors = 0; $Stopped = $false; $Hung = ''
$Start = Get-Date
$LastUi = $Start.AddSeconds(-10)
$bytes = New-Object byte[] $BufSize
$i = 0
foreach ($it in $Todo) {
    $i++
    $srcPath = $Root[$SrcName] + '\' + $it.Rel
    $dstPath = $Root[$it.Target] + '\' + $Dest[$it.Target] + '\' + $SrcName + '\' + $it.Rel
    $result = ''; $readHash = ''; $part = $null; $in = $null; $out = $null; $sha = $null
    [double]$fileDone = 0
    try {
        $sInfo = [System.IO.FileInfo]::new($LongPrefix + $srcPath)
        $dInfo = [System.IO.FileInfo]::new($LongPrefix + $dstPath)
        if (-not $sInfo.Exists) { $result = 'нет источника' }
        elseif ($sInfo.Length -ne $it.Size) { $result = "размер источника изменился ($($sInfo.Length))" }
        elseif ($dInfo.Exists -and $dInfo.Length -eq $it.Size) { $result = 'уже есть' }
        elseif ($dInfo.Exists) { $result = "КОНФЛИКТ: в цели другой размер ($($dInfo.Length)), не трогал" }
        else {
            [void][System.IO.Directory]::CreateDirectory($LongPrefix + $dstPath.Substring(0, $dstPath.LastIndexOf('\')))
            $part = $LongPrefix + $dstPath + '.part'
            # .part - только наш временный файл от прерванного запуска: начинаем его заново
            if ([System.IO.File]::Exists($part)) { [System.IO.File]::Delete($part) }
            $in = [System.IO.FileStream]::new($LongPrefix + $srcPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read, $BufSize)
            $out = [System.IO.FileStream]::new($part, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None, $BufSize)
            $sha = [System.Security.Cryptography.SHA256CryptoServiceProvider]::new()
            while ($true) {
                $rt = $in.ReadAsync($bytes, 0, $BufSize)
                if (-not $rt.Wait($TimeoutMs)) { $Hung = "чтение с $SrcName ($($Root[$SrcName]))"; break }
                $n = $rt.Result
                if ($n -le 0) { break }
                $wt = $out.WriteAsync($bytes, 0, $n)
                if (-not $wt.Wait($TimeoutMs)) { $Hung = "запись на $($it.Target) ($($Root[$it.Target]))"; break }
                [void]$sha.TransformBlock($bytes, 0, $n, $null, 0)
                $fileDone += $n
                $now = Get-Date
                if (($now - $LastUi).TotalMilliseconds -ge 500) {
                    $LastUi = $now
                    $sec = ($now - $Start).TotalSeconds
                    $all = $Done + $fileDone
                    $speed = if ($sec -gt 0) { ($CopiedBytes + $fileDone) / 1MB / $sec } else { 0 }
                    $eta = if ($speed -gt 0.01) { [TimeSpan]::FromSeconds([math]::Floor(($Total - $all) / 1MB / $speed)).ToString() } else { '?' }
                    Write-Progress -Id 1 -Activity ("Идёт копирование на {0}: файл {1} из {2}" -f $it.Target, $i, $Todo.Count) `
                        -Status ("{0}% | {1} из {2} | {3:N0} МБ/с | осталось ~{4} | Q - стоп" -f (Get-Pct $all $Total), (Fmt-GB $all), (Fmt-GB $Total), $speed, $eta) `
                        -PercentComplete (Get-Pct $all $Total)
                    Write-Progress -Id 2 -ParentId 1 -Activity $it.Rel -PercentComplete (Get-Pct $fileDone $it.Size)
                }
                if ($CanKey -and [Console]::KeyAvailable) {
                    $k = [Console]::ReadKey($true)
                    if ($k.Key -eq 'Q') { $Stopped = $true; break }
                }
            }
            if ($Hung) {
                # Зависший диск: потоки не закрываем (закрытие тоже может зависнуть), .part уберёт следующий запуск.
                $Stopped = $true
                $result = "ОШИБКА: диск не отвечает дольше $TimeoutSec с - $Hung. Копирование прекращено"
                $Errors++
            } else {
                $out.Flush($true)   # дождаться, пока Windows действительно запишет файл на диск
                $out.Dispose(); $out = $null
                $in.Dispose(); $in = $null
                if ($Stopped) {
                    [System.IO.File]::Delete($part)
                    $result = 'ОСТАНОВЛЕНО (Q), недокопированный файл удалён'
                } else {
                    [void]$sha.TransformFinalBlock($bytes, 0, 0)
                    $readHash = [System.BitConverter]::ToString($sha.Hash).Replace('-', '')
                    $len = [System.IO.FileInfo]::new($part).Length
                    if ($fileDone -ne $it.Size -or $len -ne $it.Size) { throw "прочитано $fileDone, записано $len, а по списку $($it.Size)" }
                    if ($it.Hash -and $readHash -ne $it.Hash) { throw 'SHA-256 прочитанного с источника не совпал с описью, копия не оставлена' }
                    [System.IO.File]::Move($part, $LongPrefix + $dstPath)
                    $result = if ($it.Hash) { 'скопирован, размер и SHA-256 совпали' } else { 'скопирован, размер совпал' }
                    try {
                        [System.IO.File]::SetCreationTimeUtc($LongPrefix + $dstPath, $sInfo.CreationTimeUtc)
                        [System.IO.File]::SetLastWriteTimeUtc($LongPrefix + $dstPath, $sInfo.LastWriteTimeUtc)
                    } catch { $result += ' (дату файла поставить не удалось)' }
                    $Copied++
                    $CopiedBytes += $it.Size
                }
            }
        }
    } catch {
        $result = 'ОШИБКА: ' + (Get-InnerMessage $_)
        $Errors++
        if (-not $Hung) {
            try { if ($out) { $out.Dispose() } } catch { }
            try { if ($in) { $in.Dispose() } } catch { }
            try { if ($part -and [System.IO.File]::Exists($part)) { [System.IO.File]::Delete($part) } } catch { }
        }
    }
    if ($sha) { try { $sha.Dispose() } catch { } }
    if ($result -eq 'уже есть' -or $result -eq 'нет источника' -or $result -like 'КОНФЛИКТ*' -or $result -like 'размер источника*') { $Skipped++ }
    $Done += $it.Size
    $Log.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f (Get-Date -Format 'HH:mm:ss'), $it.Target, $result, $it.Size, $readHash, $srcPath, $dstPath))
    $color = if ($result -like 'скопирован*' -or $result -eq 'уже есть') { 'Gray' } else { 'Yellow' }
    Write-Host ("[{0}/{1}] {2} {3} - {4}" -f $i, $Todo.Count, $it.Target, $it.Rel, $result) -ForegroundColor $color
    if ($Stopped) { break }
}
$Log.Close()
Write-Progress -Id 2 -Activity ' ' -Completed
Write-Progress -Id 1 -Activity ' ' -Completed
$mins = ((Get-Date) - $Start).TotalMinutes
Write-Host ''
$tail = if ($Hung) { ', ПРЕКРАЩЕНО: диск не отвечает' } elseif ($Stopped) { ', ОСТАНОВЛЕНО по Q' } else { '' }
$sumColor = if ($Errors -gt 0 -or $Hung) { 'Red' } else { 'Cyan' }
Write-Host ("Итог: скопировано {0}, пропущено {1}, ошибок {2}{3}. Время {4:N1} мин." -f $Copied, $Skipped, $Errors, $tail, $mins) -ForegroundColor $sumColor
if ($Errors -gt 0) { Write-Host 'Есть ошибки: строки со словом ОШИБКА в журнале.' -ForegroundColor Red }
Write-Host "Журнал: $LogPath"
Write-Host 'Повторный запуск продолжит с места остановки: уже скопированные файлы пропускаются.'
if (-not $Auto) { [void](Read-Host 'Enter - закрыть') }
if ($Hung) { [Environment]::Exit(2) }
if ($Errors -gt 0) { exit 1 }
exit 0
