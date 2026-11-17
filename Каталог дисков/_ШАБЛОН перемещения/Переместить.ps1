# ШАБЛОН «ПЕРЕМЕСТИТЬ НА НОСИТЕЛЕ» (версия 1.3 от 17.11.2026; 1.2 - от 16.11.2026; 1.1 - от 15.11.2026; 1.0 - от 14.11.2026)
#
# Новое в 1.3 (проблемные файлы; решение владельца 17.11.2026, ЖУРНАЛ_ДОДЕЛОК.md):
#   - длинные пути (больше 260 знаков): все обращения к файлам и папкам - через \\?\ (сетевой путь - \\?\UNC\…);
#     в журнале и на экране пути обычные;
#   - понятная причина в журнале (строка по-прежнему «ОШИБКА: …»): файл занят другой программой; нет прав (права
#     программа НЕ меняет - инструкция в итоге); ошибка ввода-вывода диска (код Windows). «Занят» и «нет прав» не
#     считаются в «5 ошибок подряд» (это не сбой диска). Такие файлы остаются на месте;
#   - в конце - отдельный список «Проблемные файлы» (на экране и в файле «Проблемные файлы <дата время>.txt» рядом
#     с журналом): всё, что не перемещено, с причиной и что делать.
#   Прежняя версия - «Переместить - версия 1.2.ps1.txt».
#
# Что делает: после копирования перекладывает файлы ВНУТРИ того же диска-источника в служебные папки
#   <диск>:\Скопировано на Семейный архив (45 и 77)\<тот же путь>   (логика v3, версия 1.1)
#   <диск>:\ПЕРЕНЕСЕНО → 45 и 77\<тот же путь>                      (прежние задания; и «только 77», «78», «МУСОР»)
#   Версия 1.2 (второй проход): <диск>:\Скопировано на A\<путь> -> <диск>:\Скопировано на A и B\<тот же путь> -
#   служебная папка, указанная в колонке «снять», снимается с начала пути (без вложенности); вся папка «Скопировано
#   на A» целиком - одним переименованием в «Скопировано на A и B».
#   Внутри одного диска это переименование: данные не переписываются и не читаются, это быстро.
# Чего НЕ делает: ничего не удаляет и не перезаписывает, на другие диски не пишет вообще.
#   Если в назначении уже лежит файл - не трогает ни его, ни исходник (строка «КОНФЛИКТ» в журнале).
#   Пустые папки, оставшиеся на старом месте после переноса по файлам, не удаляются.
# Какие файлы перемещать, решает программа (mvlist): в список попадает файл, только если его копии подтверждены
#   (SHA-256) на всех дисках-целях. Скрипт перед перемещением ещё раз сверяет размер и дату изменения со списком.
#   Содержимое файлов скрипт не читает.
#
# Рядом со скриптом лежат файлы (UTF-8, поля через TAB):
#   тома.tsv            - <имя диска> TAB <серийный номер тома>  - одна строка: диск-источник
#   перемещение.tsv     - <путь от корня> TAB <размер> TAB <дата изменения, секунды UTC или пусто>
#                         TAB <папка назначения> TAB <SHA-256> TAB <основание> [TAB <снять>]
#                         <снять> (1.2) - служебная папка «Скопировано на …» в начале пути: она есть в корни.tsv как
#                         «известен» и не равна папке назначения; назначение = <папка назначения>\<путь без неё>
#   папки целиком.tsv   - (версия 1.1, может не быть) <путь папки от корня> TAB <папка назначения> TAB <файлов> TAB <байт>
#                         [TAB <снять> (1.2)]:
#                         папка переносится ОДНИМ переименованием, если на диске в ней лежат ровно эти файлы
#                         (имена, размеры, даты); иначе - по файлам
#   корни.tsv           - (версия 1.1) <папка «Скопировано на …»> TAB «известен» (её создал журнал перемещения)
#                         или «новый» (её создаст этот скрипт). Существующую папку, которую программа не создавала,
#                         скрипт не использует: «нужна ручная проверка».
#
# Сбой посередине (версия 1.1): перед переименованием папки скрипт записывает намерение в «Намерение перемещения.tsv»
#   (с принудительной записью на диск), перед переносом каждого файла - строку «начато» в журнал. Повторный запуск
#   сначала разбирает незаконченные намерения: источника нет, а назначение есть и совпадает со списком - «уже
#   перемещён»; источник на месте и назначения нет - переноса не было; иначе - «нужна ручная проверка», эти файлы
#   не трогаются. Файл без строки «начато» не признаётся перемещённым только потому, что в назначении что-то лежит.
#
# Запуск: двойной щелчок по «Запустить.cmd». Остановка: клавиша Q (после текущей операции).
# Повторный запуск продолжит: уже перемещённые файлы пропускаются («уже перемещён»).
# Два перемещения на одном носителе одновременно не идут: замок «_замок перемещения <серийный номер>.lock»
#   рядом с папками заданий.
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
$WholeFile = Join-Path $Here 'папки целиком.tsv'
$RootsFile = Join-Path $Here 'корни.tsv'
$IntentPath = Join-Path $Here 'Намерение перемещения.tsv'
$U8 = [System.Text.Encoding]::UTF8
$U8NoBom = New-Object System.Text.UTF8Encoding($false)
$Auto = [bool]$TestRoots
$OldPrefix = 'ПЕРЕНЕСЕНО → '
$NewPrefix = 'Скопировано на '
$Trash = 'МУСОР'
$RP = [System.IO.FileAttributes]::ReparsePoint

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
# 1.3: через \\?\ Windows не убирает пустые части, «.» и «..» - они запрещены целиком
function Test-Rel([string]$rel) {
    if (-not $rel -or $rel.StartsWith('\') -or $rel.Contains(':') -or $rel.Contains('/')) { return $false }
    foreach ($c in $rel.Split('\')) { if ($c -eq '' -or $c -eq '.' -or $c -eq '..') { return $false } }
    return $true
}
# 1.3: путь для .NET без предела 260 знаков; в журнал и на экран - обычный путь
function Get-Long([string]$p) {
    if ($p.StartsWith('\\?\')) { return $p }
    if ($p.StartsWith('\\')) { return '\\?\UNC\' + $p.Substring(2) }
    return '\\?\' + $p
}
# 1.3: причина ошибки по коду Windows -> @{ Kind = занят | права | сбой | ошибка; Text }
$RightsHelp = 'программа права не меняет: правой кнопкой по файлу или папке - Свойства - Безопасность - Дополнительно - Владелец «Изменить» (нужны права администратора), или запустите задание от имени администратора'
$IoText = @{ 23 = 'данные не читаются (ошибка CRC)'; 27 = 'сектор не найден'; 30 = 'ошибка чтения'; 31 = 'устройство не работает';
    38 = 'неожиданный конец файла'; 483 = 'аппаратная ошибка устройства'; 1006 = 'том изменён извне'; 1117 = 'ошибка ввода-вывода устройства';
    1392 = 'файл или папка повреждены' }
function Get-Problem($err) {
    $e = $err.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    $hr = $e.HResult
    $code = if (((($hr -shr 16) -band 0xFFFF) -eq 0x8007)) { $hr -band 0xFFFF } else { 0 }
    if ($code -eq 32 -or $code -eq 33) { return @{ Kind = 'занят'; Text = 'файл занят другой программой - закройте её и запустите перемещение ещё раз' } }
    if ($code -eq 5) { return @{ Kind = 'права'; Text = 'нет прав на перемещение (файл или его папка) - ' + $RightsHelp } }
    if ($IoText.ContainsKey($code)) { return @{ Kind = 'сбой'; Text = "ошибка ввода-вывода диска (код Windows ${code}: $($IoText[$code])) - файл не перемещён, диск стоит проверить" } }
    return @{ Kind = 'ошибка'; Text = $e.Message }
}
function Test-DestName([string]$name) {
    if ($name -eq $Trash) { return $true }
    if ($name.Contains('\')) { return $false }
    return ($name.StartsWith($OldPrefix) -or $name.StartsWith($NewPrefix))
}
function Get-Unix($dt) { return ([DateTimeOffset]$dt).ToUnixTimeSeconds() }
# путь назначения в журнале -> «<служебная папка>\<путь>» (буква диска между запусками может быть другой)
function Get-DestKey([string]$full) {
    $parts = $full.Split('\')
    for ($k = 0; $k -lt $parts.Count; $k++) {
        if ($parts[$k] -and (Test-DestName $parts[$k])) { return (($parts[$k..($parts.Count - 1)]) -join '\').ToLowerInvariant() }
    }
    return $null
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

# --- 2. Служебные папки (корни.tsv) ---
$RootState = @{}          # имя папки «Скопировано на …» -> известен / новый
if (Test-Path -LiteralPath $RootsFile) {
    foreach ($line in [System.IO.File]::ReadAllLines($RootsFile, $U8)) {
        if (-not $line.Trim()) { continue }
        $p = $line.Split("`t")
        $RootState[$p[0].Trim()] = if ($p.Count -ge 2) { $p[1].Trim() } else { 'известен' }
    }
}
# намерения прежних запусков
$Ops = [ordered]@{}       # номер операции -> @{ Kind; From; To; Count; State }
$CreatedRoots = @{}
if (Test-Path -LiteralPath $IntentPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($IntentPath, $U8)) {
        $p = $line.Split("`t")
        if ($p.Count -lt 6 -or $p[0] -eq 'время') { continue }
        $op = $p[1]
        if ($p[2] -eq 'корень' -and $p[3] -eq 'создан') { $CreatedRoots[$p[5]] = $true; continue }
        if (-not $Ops.Contains($op)) { $Ops[$op] = @{ Kind = $p[2]; From = $p[4]; To = $p[5]; Count = $(if ($p.Count -ge 7) { $p[6] } else { '' }); State = $p[3] } }
        else { $Ops[$op].State = $p[3] }
    }
}

# --- 3. Список: всё проверяется ДО первого перемещения ---
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
    if (-not (Test-DestName $folder)) {
        Stop-Script "перемещение.tsv, строка ${lineNo}: папка назначения «$folder» - разрешены только «ПЕРЕНЕСЕНО → …», «Скопировано на …» и «МУСОР». Ничего не сделано." 1
    }
    if ($folder.StartsWith($NewPrefix) -and -not $RootState.ContainsKey($folder)) {
        Stop-Script "перемещение.tsv, строка ${lineNo}: папки «$folder» нет в корни.tsv - задание собрано не программой. Ничего не сделано." 1
    }
    $first = $rel.Split('\')[0]
    $strip = if ($f.Count -ge 7) { $f[6].Trim().Trim('\') } else { '' }
    $dstRel = $folder + '\' + $rel
    if ($strip) {
        # версия 1.2, второй проход: служебная папка программы снимается с начала пути
        if (-not $strip.StartsWith($NewPrefix) -or $RootState[$strip] -ne 'известен' -or $strip -eq $folder -or
            -not $rel.StartsWith($strip + '\') -or $first -ne $strip) {
            Stop-Script "перемещение.tsv, строка ${lineNo}: колонка «снять» («$strip») не годится - снимать можно только служебную папку программы в начале пути. Ничего не сделано." 1
        }
        $dstRel = $folder + '\' + $rel.Substring($strip.Length + 1)
    } elseif ($first.StartsWith($OldPrefix) -or $first -eq $Trash -or $RootState.ContainsKey($first)) { Stop-Script "перемещение.tsv, строка ${lineNo}: файл уже лежит в служебной папке «$first». Ничего не сделано." 1 }
    $sha = if ($f.Count -ge 5) { $f[4].Trim() } else { '' }
    $why = if ($f.Count -ge 6) { $f[5].Trim() } else { '' }
    $Items.Add([pscustomobject]@{ Rel = $rel; Size = $size; Mtime = $mtime; Folder = $folder; Dst = $dstRel; Sha = $sha; Why = $why; Done = $false; Blocked = '' })
}
if ($Items.Count -eq 0) { Stop-Script 'Список пуст - перемещать нечего.' 0 }
$Whole = New-Object System.Collections.Generic.List[object]
if (Test-Path -LiteralPath $WholeFile) {
    foreach ($line in [System.IO.File]::ReadAllLines($WholeFile, $U8)) {
        if (-not $line.Trim()) { continue }
        $p = $line.Split("`t")
        if ($p.Count -lt 3 -or -not (Test-Rel $p[0]) -or -not (Test-DestName $p[1].Trim())) { Stop-Script "папки целиком.tsv: строка «$line» не разобрана. Ничего не сделано." 1 }
        $pre = $p[0].ToLowerInvariant() + '\'
        $mine = @($Items | Where-Object { $_.Rel.ToLowerInvariant().StartsWith($pre) -and $_.Folder -eq $p[1].Trim() })
        $wstrip = if ($p.Count -ge 5) { $p[4].Trim().Trim('\') } else { '' }
        $wdst = $p[1].Trim() + '\' + $p[0]
        if ($wstrip) {
            if ($RootState[$wstrip] -ne 'известен' -or -not $wstrip.StartsWith($NewPrefix) -or $wstrip -eq $p[1].Trim() -or
                -not ($p[0] -eq $wstrip -or $p[0].StartsWith($wstrip + '\'))) { Stop-Script "папки целиком.tsv: строка «$line» - колонка «снять» не годится. Ничего не сделано." 1 }
            $wdst = if ($p[0] -eq $wstrip) { $p[1].Trim() } else { $p[1].Trim() + '\' + $p[0].Substring($wstrip.Length + 1) }
        }
        $Whole.Add([pscustomobject]@{ Rel = $p[0]; Folder = $p[1].Trim(); Dst = $wdst; Count = [int]$p[2]; Items = $mine })
    }
}
# существующая папка «Скопировано на …», которую программа не создавала, не используется (1.2: кроме назначения
# незаконченного переименования всей служебной папки - его разберёт шаг 6 сверкой оглавления)
$PendingTo = @{}
foreach ($op in @($Ops.Keys)) { if ($Ops[$op].Kind -eq 'папка' -and $Ops[$op].State -eq 'намерение') { $PendingTo[$Ops[$op].To] = $true } }
foreach ($name in @($Items | ForEach-Object Folder | Sort-Object -Unique)) {
    if (-not $name.StartsWith($NewPrefix)) { continue }
    $exists = [System.IO.Directory]::Exists((Get-Long ($Root + '\' + $name)))
    if ($exists -and $RootState[$name] -ne 'известен' -and -not $CreatedRoots.ContainsKey($name) -and -not $PendingTo.ContainsKey($name)) {
        Stop-Script "Нужна ручная проверка: на диске уже есть папка «$name», но программа её не создавала (нет в базе и в записи намерений). Ничего не сделано." 1
    }
}

Write-Host ''
Write-Host "Перемещение внутри диска $SrcName ($Root). Ничего не удаляется и не перезаписывается." -ForegroundColor Cyan
[double]$Total = 0
foreach ($g in ($Items | Group-Object Folder)) {
    [double]$b = 0; foreach ($x in $g.Group) { $b += $x.Size }
    $Total += $b
    Write-Host ("  -> {0}\{1}: {2} файлов, {3}" -f $Root, $g.Name, $g.Count, (Fmt-GB $b))
}
if ($Whole.Count) { Write-Host ("  папкой целиком (одно переименование, если на диске ровно эти файлы): {0}" -f (($Whole | ForEach-Object Rel) -join '; ')) }
$pending = @($Ops.Keys | Where-Object { $Ops[$_].State -eq 'намерение' })
if ($pending.Count) { Write-Host ("  незаконченных переносов папок прошлого запуска: {0} - сначала они будут разобраны" -f $pending.Count) -ForegroundColor Yellow }
Write-Host 'Содержимое файлов не перечитывается: сверяются размер и дата изменения с описью.'
Write-Host 'Q - остановиться после текущей операции. Повторный запуск продолжит с места остановки.'

# --- 4. Замок: два перемещения на одном носителе одновременно не идут ---
$LockPath = Join-Path (Split-Path $Here -Parent) ("_замок перемещения " + $Serial + ".lock")
try { $Lock = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None) }
catch { Stop-Script "На носителе $SrcName уже идёт другое перемещение (занят «$LockPath»). Ничего не сделано." 1 }

if (-not $Auto) {
    $ans = Read-Host ("Переместить {0} файлов ({1}) внутри диска {2}? Введите «да»" -f $Items.Count, (Fmt-GB $Total), $SrcName)
    if (@('да', 'д', 'y', 'yes') -notcontains "$ans".Trim().ToLower()) { $Lock.Close(); Write-Host 'Отменено. Ничего не сделано.'; [void](Read-Host 'Enter - закрыть'); exit 0 }
}

# --- 5. Журнал и намерения ---
$Stamp = Get-Date -Format 'yyyy-MM-dd HH-mm-ss'
# строки «начато» и «перемещён» прежних журналов: только по ним «нет источника, есть назначение» = «уже перемещён»
$Started = @{}
foreach ($old in (Get-ChildItem -LiteralPath $Here -Filter 'Журнал перемещения *.tsv' -ErrorAction SilentlyContinue)) {
    foreach ($line in [System.IO.File]::ReadAllLines($old.FullName, $U8)) {
        $p = $line.Split("`t")
        if ($p.Count -ge 6 -and @('начато', 'перемещён', 'уже перемещён') -contains $p[1]) {
            $k = Get-DestKey $p[5]
            if ($k) { $Started[$k] = $true }
        }
    }
}
$LogPath = Join-Path $Here "Журнал перемещения $Stamp.tsv"
$Log = [System.IO.StreamWriter]::new($LogPath, $false, [System.Text.UTF8Encoding]::new($true))
$Log.AutoFlush = $true
$Log.WriteLine("время`tрезультат`tразмер`tSHA-256`tоткуда`tкуда`tоснование")
function Write-LogLine($it, [string]$result, [string]$src, [string]$dst) {
    $Log.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f (Get-Date -Format 'HH:mm:ss'), $result, $it.Size, $it.Sha, $src, $dst, $it.Why))
}
function Write-Intent([string]$op, [string]$kind, [string]$state, [string]$from, [string]$to, [string]$count) {
    $new = -not [System.IO.File]::Exists($IntentPath)
    $fs = [System.IO.FileStream]::new($IntentPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $text = ''
        if ($new) { $text = "время`tоперация`tвид`tсостояние`tоткуда`tкуда`tфайлов`n" }
        $text += ("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`n" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $op, $kind, $state, $from, $to, $count)
        $b = $U8NoBom.GetBytes($text)
        $fs.Write($b, 0, $b.Length)
        $fs.Flush($true)                    # на диск, а не только в память Windows: запись должна пережить сбой
    } finally { $fs.Close() }
}
function Confirm-Root([string]$name) {
    if (-not $name.StartsWith($NewPrefix)) { return }
    $full = $Root + '\' + $name
    if ([System.IO.Directory]::Exists((Get-Long $full))) { return }
    Write-Intent ("$Stamp-корень") 'корень' 'создан' '' $name ''
    $script:CreatedRoots[$name] = $true
    [void][System.IO.Directory]::CreateDirectory((Get-Long $full))
}
function Note-Root([string]$name) {
    # 1.2: служебная папка появилась переименованием всей «Скопировано на …» - записать, что её создала программа
    if ($script:CreatedRoots.ContainsKey($name)) { return }
    Write-Intent ("$Stamp-корень") 'корень' 'создан' '' $name ''
    $script:CreatedRoots[$name] = $true
}
$RpCache = @{}
function Test-ReparseChain([string]$dir) {
    # папка или любая её папка-предок (ниже корня диска) - ссылка (reparse point)?
    if ($dir.Length -le $Root.Length) { return $false }
    if ($RpCache.ContainsKey($dir)) { return $RpCache[$dir] }
    $r = Test-ReparseChain ($dir.Substring(0, $dir.LastIndexOf('\')))
    if (-not $r) {
        $di = [System.IO.DirectoryInfo]::new((Get-Long $dir))
        if ($di.Exists -and ($di.Attributes -band $RP)) { $r = $true }
    }
    $RpCache[$dir] = $r
    return $r
}
# оглавление папки на диске сверяется со списком: имена (без учёта регистра), размеры, даты; ссылки внутри - отказ
function Test-Listing([string]$dir, $items, [string]$listPrefix) {
    $want = @{}
    foreach ($it in $items) { $want[$it.Rel.Substring($listPrefix.Length).ToLowerInvariant()] = $it }
    $seen = 0
    $di = [System.IO.DirectoryInfo]::new((Get-Long $dir))
    $base = $di.FullName.Length + 1
    foreach ($e in $di.EnumerateFileSystemInfos('*', [System.IO.SearchOption]::AllDirectories)) {
        if ($e.Attributes -band $RP) { return 'внутри есть ссылка (reparse point)' }
        if ($e -is [System.IO.DirectoryInfo]) { continue }
        $k = $e.FullName.Substring($base).ToLowerInvariant()
        if (-not $want.ContainsKey($k)) { return "на диске есть файл, которого нет в списке: $($e.FullName.Substring($base))" }
        $it = $want[$k]
        if ($e.Length -ne $it.Size) { return "другой размер: $($e.FullName.Substring($base))" }
        if ($it.Mtime -ge 0 -and [math]::Abs((Get-Unix $e.LastWriteTimeUtc) - $it.Mtime) -gt 2) { return "другая дата изменения: $($e.FullName.Substring($base))" }
        $seen++
    }
    if ($seen -ne $want.Count) { return ("на диске нет {0} файлов из списка" -f ($want.Count - $seen)) }
    return ''
}

$CanKey = $true
try { [void][Console]::KeyAvailable } catch { $CanKey = $false }
$Moved = 0; $Already = 0; $Skipped = 0; $Errors = 0; $Stopped = $false; $ErrorsInRow = 0; $Failing = $false; $Manual = 0
$WholeDone = 0
$ProblemList = New-Object System.Collections.Generic.List[object]     # 1.3: не перемещённые файлы для списка в конце
[double]$MovedBytes = 0
$Start = Get-Date

# --- 6. Сначала - незаконченные переносы папок прошлых запусков ---
foreach ($op in @($Ops.Keys)) {
    $o = $Ops[$op]
    if ($o.Kind -ne 'папка' -or $o.State -ne 'намерение') { continue }
    $w = $Whole | Where-Object { $_.Rel -eq $o.From -and $_.Dst -eq $o.To } | Select-Object -First 1
    $src = $Root + '\' + $o.From; $dst = $Root + '\' + $o.To
    $se = [System.IO.Directory]::Exists((Get-Long $src)); $de = [System.IO.Directory]::Exists((Get-Long $dst))
    $sameList = $false                              # 1.3: оглавление не читается (права, сбой) - ручная проверка
    if ($w -and -not $se -and $de) { try { $sameList = -not (Test-Listing $dst $w.Items ($w.Rel + '\')) } catch { $sameList = $false } }
    if ($sameList) {
        if ($w.Dst -eq $w.Folder) { Note-Root $w.Folder }
        foreach ($it in $w.Items) {
            Write-LogLine $it 'уже перемещён' ($Root + '\' + $it.Rel) ($Root + '\' + $it.Dst)
            $it.Done = $true; $Already++
        }
        Write-Intent $op 'папка' 'выполнено' $o.From $o.To $o.Count
        Write-Host "Прошлый перенос папки «$($o.From)» состоялся: учтён как «уже перемещён»." -ForegroundColor Cyan
    } elseif ($w -and $se -and -not $de) {
        Write-Intent $op 'папка' 'не выполнено' $o.From $o.To $o.Count
        Write-Host "Прошлый перенос папки «$($o.From)» не состоялся: папка на месте, перенос начнётся заново." -ForegroundColor Cyan
    } else {
        Write-Intent $op 'папка' 'ручная проверка' $o.From $o.To $o.Count
        $pre = $o.From.ToLowerInvariant() + '\'
        foreach ($it in $Items) { if ($it.Rel.ToLowerInvariant().StartsWith($pre)) { $it.Blocked = 'нужна ручная проверка: прерванный перенос папки' } }
        $Manual++
        Write-Host "НУЖНА РУЧНАЯ ПРОВЕРКА: перенос папки «$($o.From)» прервался, а на диске не та картина (папка на месте: $se, в назначении: $de). Файлы этой папки не трогаю." -ForegroundColor Red
    }
}

# --- 7. Папки целиком: одно переименование ---
$n = 0
foreach ($w in $Whole) {
    if ($Stopped) { break }
    $n++
    if (@($w.Items | Where-Object { $_.Done -or $_.Blocked }).Count) { continue }
    $src = $Root + '\' + $w.Rel; $dst = $Root + '\' + $w.Dst
    $reason = ''
    $wholeRoot = $w.Dst -eq $w.Folder               # 1.2: вся «Скопировано на A» -> «Скопировано на A и B»
    # 1.3: ошибка проверки или подготовки (права, занято, сбой) - папка идёт по файлам, у каждого файла своя причина
    try {
        if ($w.Items.Count -ne $w.Count -or $w.Count -eq 0) { $reason = 'список папки не сходится с перемещение.tsv' }
        elseif (-not [System.IO.Directory]::Exists((Get-Long $src))) { $reason = 'папки нет на месте' }
        elseif ([System.IO.Directory]::Exists((Get-Long $dst)) -or [System.IO.File]::Exists((Get-Long $dst))) { $reason = 'в назначении уже есть такая папка' }
        elseif ((Test-ReparseChain $src) -or (Test-ReparseChain ($dst.Substring(0, $dst.LastIndexOf('\'))))) { $reason = 'в пути есть ссылка (reparse point)' }
        else { $reason = Test-Listing $src $w.Items ($w.Rel + '\') }
        if (-not $reason -and -not $wholeRoot) {
            Confirm-Root $w.Folder
            [void][System.IO.Directory]::CreateDirectory((Get-Long $dst.Substring(0, $dst.LastIndexOf('\'))))
        }
    } catch { $reason = 'не удалось проверить или подготовить: ' + (Get-Problem $_).Text }
    if ($reason) { Write-Host "Папка «$($w.Rel)» пойдёт по файлам: $reason." -ForegroundColor Yellow; continue }
    $op = "$Stamp-$n"
    Write-Intent $op 'папка' 'намерение' $w.Rel $w.Dst $w.Count
    $moveErr = ''
    try { [System.IO.Directory]::Move((Get-Long $src), (Get-Long $dst)) } catch { $moveErr = Get-InnerMessage $_ }
    if (-not $moveErr) {
        if ($wholeRoot) { Note-Root $w.Folder }
        foreach ($it in $w.Items) {
            Write-LogLine $it 'перемещён' ($Root + '\' + $it.Rel) ($Root + '\' + $it.Dst)
            $it.Done = $true; $Moved++; $MovedBytes += $it.Size
        }
        Write-Intent $op 'папка' 'выполнено' $w.Rel $w.Dst $w.Count
        $WholeDone++
        Write-Host ("Папка «{0}» перенесена целиком: {1} файлов." -f $w.Rel, $w.Count) -ForegroundColor Cyan
    } else {
        $se = [System.IO.Directory]::Exists((Get-Long $src)); $de = [System.IO.Directory]::Exists((Get-Long $dst))
        if ($se -and -not $de) {
            Write-Intent $op 'папка' 'не выполнено' $w.Rel $w.Dst $w.Count
            Write-Host "Папку «$($w.Rel)» переименовать не удалось ($moveErr) - пойдёт по файлам." -ForegroundColor Yellow
        } else {
            Write-Intent $op 'папка' 'ручная проверка' $w.Rel $w.Dst $w.Count
            foreach ($it in $w.Items) { $it.Blocked = 'нужна ручная проверка: перенос папки' }
            $Manual++
            Write-Host "НУЖНА РУЧНАЯ ПРОВЕРКА: перенос папки «$($w.Rel)» дал ошибку ($moveErr), на диске не та картина." -ForegroundColor Red
        }
    }
    if ($CanKey -and [Console]::KeyAvailable) { if (([Console]::ReadKey($true)).Key -eq 'Q') { $Stopped = $true } }
}

# --- 8. По файлам ---
$LastUi = $Start.AddSeconds(-10)
$i = 0
$handled = 0
foreach ($it in $Items) {
    $i++
    if ($Stopped) { break }
    $handled = $i
    if ($it.Done) { continue }
    $src = $Root + '\' + $it.Rel
    $dst = $Root + '\' + $it.Dst
    $result = ''; $Kind = ''
    try {
        if ($it.Blocked) { $result = $it.Blocked }
        else {
            $s = [System.IO.FileInfo]::new((Get-Long $src))
            $d = [System.IO.FileInfo]::new((Get-Long $dst))
            if (-not $s.Exists) {
                # 1.3: Exists = false и при нет прав, и при сбое диска - спросим ещё раз; «нет источника» - только при
                # ответе Windows «нет файла» / «нет папки», иначе - настоящая причина (права, ввод-вывод)
                try { [void][System.IO.File]::GetAttributes((Get-Long $src)) } catch { $h = $_.Exception; while ($h.InnerException) { $h = $h.InnerException }; if (@(-2147024894, -2147024893) -notcontains $h.HResult) { throw } }
                $same = $d.Exists -and $d.Length -eq $it.Size -and ($it.Mtime -lt 0 -or [math]::Abs((Get-Unix $d.LastWriteTimeUtc) - $it.Mtime) -le 2)
                if ($same -and $Started.ContainsKey((Get-DestKey $dst))) { $result = 'уже перемещён' }
                elseif ($same) { $result = 'нужна ручная проверка: источника нет, в назначении такой же файл, но записи «начато» нет' }
                else { $result = 'нет источника' }
            }
            elseif ($s.Attributes -band $RP) { $result = 'ссылка (reparse point), не трогал' }
            elseif ($s.Length -ne $it.Size) { $result = "размер изменился ($($s.Length)), не трогал" }
            elseif ($it.Mtime -ge 0 -and [math]::Abs((Get-Unix $s.LastWriteTimeUtc) - $it.Mtime) -gt 2) { $result = 'дата изменения другая, не трогал' }
            elseif ($d.Exists -or [System.IO.Directory]::Exists((Get-Long $dst))) { $result = 'КОНФЛИКТ: в назначении уже есть файл, не трогал' }
            elseif ((Test-ReparseChain ($src.Substring(0, $src.LastIndexOf('\')))) -or (Test-ReparseChain ($dst.Substring(0, $dst.LastIndexOf('\'))))) { $result = 'в пути есть ссылка (reparse point), не трогал' }
            else {
                Confirm-Root $it.Folder
                [void][System.IO.Directory]::CreateDirectory((Get-Long $dst.Substring(0, $dst.LastIndexOf('\'))))
                Write-LogLine $it 'начато' $src $dst
                [System.IO.File]::Move((Get-Long $src), (Get-Long $dst))
                $result = 'перемещён'
                $Moved++; $MovedBytes += $it.Size
            }
        }
    } catch {
        $p = Get-Problem $_; $Kind = $p.Kind
        $result = 'ОШИБКА: ' + $p.Text
        $Errors++
    }
    if ($result -eq 'уже перемещён') { $Already++ }
    elseif ($result -like 'нужна ручная проверка*') { $Skipped++; $Manual++ }
    elseif ($result -ne 'перемещён' -and $result -notlike 'ОШИБКА*') { $Skipped++ }
    # 1.3: «занят» и «нет прав» - не сбой диска: в «5 ошибок подряд» не идут (и счёт не сбрасывают)
    if ($result -like 'ОШИБКА*') { if (@('занят', 'права') -notcontains $Kind) { $ErrorsInRow++ } } else { $ErrorsInRow = 0 }
    if ($ErrorsInRow -ge 5) { $Stopped = $true; $Failing = $true; $result += ' | 5 ошибок подряд - перемещение прекращено, проверьте диск' }
    Write-LogLine $it $result $src $dst
    if ($result -ne 'перемещён' -and $result -ne 'уже перемещён') {
        $g = if (@('занят', 'права', 'сбой') -contains $Kind) { $Kind } else { 'прочее' }
        $ProblemList.Add([pscustomobject]@{ Group = $g; Text = "$src - $result" })
    }
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
}
$Log.Close()
$Lock.Close()
Write-Progress -Id 1 -Activity ' ' -Completed
$tail = if ($Failing) { ', ПРЕКРАЩЕНО: 5 ошибок подряд' } elseif ($Stopped) { ', ОСТАНОВЛЕНО по Q' } else { '' }
$color = if ($Errors -gt 0 -or $Manual -gt 0) { 'Red' } else { 'Cyan' }
Write-Host ''
Write-Host ("Итог: перемещено {0} ({1}; папок целиком {2}), уже было перемещено {3}, пропущено {4}, ошибок {5}{6}. Время {7:N1} мин." -f $Moved, (Fmt-GB $MovedBytes), $WholeDone, $Already, $Skipped, $Errors, $tail, ((Get-Date) - $Start).TotalMinutes) -ForegroundColor $color
if ($Manual -gt 0) { Write-Host "Нужна ручная проверка: $Manual (строки журнала и «Намерение перемещения.tsv»)." -ForegroundColor Red }
if ($Skipped -gt 0 -or $Errors -gt 0) { Write-Host 'Пропущенные и ошибки - строки журнала, кроме «перемещён» и «уже перемещён».' -ForegroundColor Yellow }
Write-Host "Журнал: $LogPath"
# 1.3: отдельный список того, что не перемещено, с причиной - на экране и в файле рядом с журналом
$NotDone = @($Items | Select-Object -Skip $handled | Where-Object { -not $_.Done }).Count
if ($NotDone -gt 0) {
    $stopWhy = if ($Failing) { '5 ошибок подряд, проверьте диск' } else { 'остановлено клавишей Q' }
    $ProblemList.Add([pscustomobject]@{ Group = 'прочее'; Text = "не обработано файлов: $NotDone - причина: $stopWhy. Запустите перемещение ещё раз" })
}
if ($ProblemList.Count) {
    $Help = [ordered]@{
        'занят' = 'Файл занят другой программой. Закройте её (фоторедактор, плеер, облачный клиент) и запустите перемещение ещё раз.'
        'права' = 'Нет прав. Программа права НЕ меняет. Правой кнопкой по файлу или папке - Свойства - Безопасность - Дополнительно - Владелец «Изменить» (нужны права администратора); или запустите задание от имени администратора (правой кнопкой по «Запустить.cmd»).'
        'сбой'  = 'Ошибка ввода-вывода диска. Файл остался на месте. Проверьте диск.'
        'прочее' = 'Прочие (нет источника, изменился, конфликт, ручная проверка, другие ошибки) - причина в строке.'
    }
    $txt = New-Object System.Collections.Generic.List[string]
    $txt.Add("Проблемные файлы - перемещение $Stamp. Журнал: $LogPath")
    foreach ($g in $Help.Keys) {
        $rows = @($ProblemList | Where-Object { $_.Group -eq $g })
        if (-not $rows.Count) { continue }
        $txt.Add(''); $txt.Add(("{0} ({1})" -f $Help[$g], $rows.Count))
        foreach ($r in $rows) { $txt.Add('  ' + $r.Text) }
    }
    $ProbPath = Join-Path $Here "Проблемные файлы $Stamp.txt"
    try { [System.IO.File]::WriteAllLines($ProbPath, $txt, [System.Text.UTF8Encoding]::new($true)) } catch { $ProbPath = "(файл записать не удалось: $(Get-InnerMessage $_))" }
    Write-Host ("ПРОБЛЕМНЫЕ ФАЙЛЫ: не перемещено {0}. Список: {1}" -f $ProblemList.Count, $ProbPath) -ForegroundColor Yellow
    $shown = 0
    foreach ($line in $txt | Select-Object -Skip 1) {
        if ($shown -ge 40) { Write-Host '  … остальное - в файле списка' -ForegroundColor Yellow; break }
        Write-Host $line -ForegroundColor Yellow; $shown++
    }
}
if (-not $Auto) { [void](Read-Host 'Enter - закрыть') }
if ($Errors -gt 0 -or $Manual -gt 0) { exit 1 }
exit 0
