# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ (версия 2.8 от 17.11.2026)
#
# Новое в 2.8 (правило владельца: файл кода не больше 600 строк): шаблон из частей, поведение 2.7 без изменений.
#   Рядом с этим файлом лежат части (.psm1 - «Запустить.cmd» их не запускает): «Копировать - общее.psm1»
#   (функции-помощники и история версий 2.4-2.7), «Копировать - проверки.psm1» (разбор.json, имена, место),
#   «Копировать - файл и итог.psm1» (копирование файла, строка журнала, список «Проблемные файлы»). Их SHA-256
#   записан ниже (таблица $PartSha): части нет или она изменена - задание не начинается (код 5). Задание хранит
#   свою копию шаблона со всеми частями; задания с однофайловым шаблоном 2.7 и старше работают как раньше.
#   Прежняя версия - «Копировать - версия 2.7.ps1.txt».
#
# Что делает: копирует файлы по списку с диска-источника на один или несколько дисков-целей.
#   Куда: <цель>:\ПЕРЕНОС с других дисков\<имя источника>\<тот же путь, что на источнике>
#   (папку на цели можно задать свою - третьей колонкой в тома.tsv)
# Чего НЕ делает: не удаляет, не перемещает и не перезаписывает ничего. На источник не пишет вообще.
#   Единственное, что скрипт стирает, - собственные недописанные временные файлы. Они лежат только в его
#   папке «_ВРЕМЕННО - копирование (можно удалить)» в корне диска-цели и названы именем запуска (run…​.part).
#   Чужие файлы, даже с окончанием «.part», скрипт не трогает (версия 2.3).
# Что означают слова в журнале - это разные степени проверки, они не равны друг другу:
#   «скопирован, размер и SHA-256 совпали» - байты, прочитанные с источника, совпали с описью, и записано столько же
#        байт. Записанный файл обратно НЕ читался.
#   «скопирован, размер совпал» - то же, но хеша в описи не было: сверять было не с чем, в журнале хеш прочитанного.
#   «уже есть, SHA-256 совпал» (2.5) - в цели лежит файл того же размера; он прочитан, и его SHA-256 совпал с описью
#        (или, если в описи хеша нет, с прочитанным источником). Это доказательство копии.
#   «уже есть» (без слов о SHA-256, версии до 2.5) - в цели был файл того же размера, содержимое НЕ читалось.
# Пять ошибок подряд считаются признаком сбоя диска: копирование прекращается (версия 2.3).
# Подпапка источника не меняет того, какой это диск: цель на том же диске, что источник, отвергается (версия 2.3).
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
# Журнал: «Журнал копирования <дата время>.tsv» рядом со скриптом, строка после каждого файла
#   (время, цель, результат, размер, SHA-256 прочитанного, источник, куда, дата изменения источника).
#   В журнал пишется SHA-256 того, что прочитано с источника, - сверка с описью без повторного чтения дисков.
# Если диск не отвечает дольше $TimeoutSec секунд, копирование прекращается с сообщением, какой диск завис.
#   Ограничение: предел ожидания действует на чтение и запись данных. Открытие файла, создание папки и
#   завершение записи (Flush) Windows может держать дольше. Если окно не меняется больше 5 минут -
#   закройте его и проверьте диск; недописанный временный файл уберёт следующий запуск.
# Файл, который уже лежит в цели с тем же размером, не копируется заново: он читается и сверяется по SHA-256
#   (2.5; до 2.5 сверялся только размер). Другое содержимое - КОНФЛИКТ, существующий файл не трогается.
#
# Параметры ниже нужны только для проверки шаблона на тестовых папках, при обычном запуске не задаются:
#   -TestRoots 'HDD17=C:\тест\источник;HDD45=C:\тест\цель1'  (папки вместо дисков, без вопросов)
# Параметры очереди окна (2.4): -Confirmed -Expect <отпечаток задания> (см. выше).
param(
    [string]$TestRoots = '',
    [double]$TestFreeBytes = -1,
    [string]$TestReadError = '',
    [int]$TimeoutSec = 120,
    [switch]$Confirmed,
    [string]$Expect = ''
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ListFile = Join-Path $Here 'список.tsv'
$VolFile = Join-Path $Here 'тома.tsv'
$RazborFile = Join-Path $Here 'разбор.json'
$DestFolder = 'ПЕРЕНОС с других дисков'
$BufSize = 4MB
$TimeoutMs = $TimeoutSec * 1000
$U8 = [System.Text.Encoding]::UTF8
$Auto = [bool]$TestRoots
$NoPause = $Auto -or $Confirmed.IsPresent           # ни одного вопроса и ни одной паузы (очередь окна, проверка шаблона)
$CodeOk = if ($Confirmed) { 10 } else { 0 }
$CodeIncomplete = if ($Confirmed) { 11 } else { 1 }
$Started = $false
$Log = $null
# Неожиданная ошибка (не перехваченная ниже): до начала копирования - код 5, во время - 4. Очередь в обоих случаях стоит.
trap {
    Write-Host ('НЕОЖИДАННАЯ ОШИБКА: ' + $_.Exception.Message) -ForegroundColor Red
    try { if ($Log) { $Log.Close() } } catch { }
    if (-not $NoPause) { try { [void](Read-Host 'Enter - закрыть') } catch { } }
    if ($Started) { exit 4 } else { exit 5 }
}

function Stop-Script([string]$text, [int]$code) {
    Write-Host $text -ForegroundColor Red
    if (-not $NoPause) { [void](Read-Host 'Enter - закрыть') }
    exit $code
}
# 2.8: части шаблона. SHA-256 текста части (UTF-8 без BOM, концы строк LF): нет файла или SHA-256 другой -
# ничего не делается, код 5. Выполняется ровно тот текст, который проверен.
$PartSha = [ordered]@{
    'Копировать - общее.psm1' = '6A4C72D8193B9193FDBFF49FF581E82B72A0BC7EE09B91C8E662E9AF19C547F1'
    'Копировать - проверки.psm1' = '68FB9864E19DAEE6DB96C469368D12BB382848E9540454FB811C61808C21DBEA'
    'Копировать - файл и итог.psm1' = '67152CA5EA048B5AFD9D5F5D29A5467F4EBBDFF4CAAF9C0F53B7480D6D6D5C2E'
}
foreach ($pn in $PartSha.Keys) {
    $pp = Join-Path $Here $pn
    if (-not [System.IO.File]::Exists($pp)) { Stop-Script "Нет части шаблона «$pn» рядом с Копировать.ps1. Подготовьте задание заново. Ничего не сделано." 5 }
    $pt = $U8.GetString([System.IO.File]::ReadAllBytes($pp)).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
    $ph = [System.Security.Cryptography.SHA256]::Create()
    $px = [System.BitConverter]::ToString($ph.ComputeHash($U8.GetBytes($pt))).Replace('-', ''); $ph.Dispose()
    if ($px -ne $PartSha[$pn]) { Stop-Script "Часть шаблона «$pn» изменена (SHA-256 не тот, что записан в Копировать.ps1). Подготовьте задание заново. Ничего не сделано." 5 }
    . ([scriptblock]::Create($pt))
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
# 2.7: -TestReadError 'путь=код;…' - имитация ошибки чтения источника (только на тестовых папках)
$FakeErr = @{}
if ($TestRoots -and $TestReadError) {
    foreach ($pair in $TestReadError.Split(';')) {
        $kv = $pair.Split('=', 2)
        if ($kv.Count -eq 2) { $FakeErr[$kv[0]] = [int](-2147024896 + [int]$kv[1]) }
    }
}
$Names = New-Object System.Collections.Generic.List[string]
$Root = @{}
$Dest = @{}
$VolSerial = @{}
foreach ($line in [System.IO.File]::ReadAllLines($VolFile, $U8)) {
    if (-not $line.Trim()) { continue }
    $f = $line.Split("`t")
    if ($f.Count -lt 2) { Stop-Script "тома.tsv: строка без серийного номера: $line" 5 }
    $name = $f[0].Trim(); $serial = $f[1].Trim().ToUpper()
    $Names.Add($name)
    $VolSerial[$name] = $serial
    $Dest[$name] = $DestFolder
    if ($f.Count -ge 3 -and $f[2].Trim()) {
        $Dest[$name] = $f[2].Trim('\')        # 2.6: пробелы по краям - часть имени папки, не обрезаются
        if (-not (Test-Rel $Dest[$name]) -or $Dest[$name].Contains(':')) { Stop-Script "тома.tsv: недопустимая папка «$($Dest[$name])» у $name. Ничего не сделано." 5 }
    }
    if ($Names.Count -eq 1 -and $f.Count -ge 3 -and $f[2].Trim()) { $SourceSubfolder = $f[2].Trim('\') }
    if ($Override.ContainsKey($name)) {
        # проверка шаблона: несуществующая папка - как неподключённый диск
        $Root[$name] = if ([System.IO.Directory]::Exists($Override[$name])) { $Override[$name] } else { $null }
    }
    elseif ($TestRoots) { $Root[$name] = $null }
    elseif ($BySerial.ContainsKey($serial)) {
        if ($BySerial[$serial].Count -gt 1) { Stop-Script "Серийный номер $serial ($name) сразу у нескольких дисков: $($BySerial[$serial] -join ', '). Не могу выбрать. Ничего не сделано." 5 }
        $Root[$name] = $BySerial[$serial][0]
    }
    else { $Root[$name] = $null }
}
if ($Names.Count -lt 2) { Stop-Script 'В тома.tsv нужны минимум две строки: источник и хотя бы одна цель. Ничего не сделано.' 5 }
$SrcName = $Names[0]
if ($SourceSubfolder -and (-not (Test-Rel $SourceSubfolder) -or $SourceSubfolder.Contains(':'))) { Stop-Script "тома.tsv: недопустимая подпапка источника «$SourceSubfolder». Ничего не сделано." 5 }
# Том (диск) каждого имени - ДО добавления подпапки источника: подпапка не меняет того, какой это диск.
$Vol = @{}
$Base = @{}
foreach ($n in $Names) {
    $Vol[$n] = if ($Root[$n]) { $Root[$n].TrimEnd('\').ToUpper() } else { $null }
    $Base[$n] = $Root[$n]
}
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
if (-not $Root[$SrcName]) { Stop-Script "Источник $SrcName не подключён. Ничего не сделано." 5 }
foreach ($t in $Targets) {
    if ($Vol[$t] -and $Vol[$t] -eq $Vol[$SrcName]) { Stop-Script "Цель $t и источник $SrcName - один и тот же диск. Ничего не сделано." 5 }
}

# --- 1а. Подтверждение в окне (2.4): отпечаток задания должен совпасть с тем, что владелец подтвердил ---
$Zero = New-Object byte[] 1
$fp = [System.Security.Cryptography.SHA256]::Create()
$parts = @($ListFile, $VolFile, $RazborFile)
for ($k = 0; $k -lt $parts.Count; $k++) {
    if ($k -gt 0) { [void]$fp.TransformBlock($Zero, 0, 1, $null, 0) }
    if ([System.IO.File]::Exists($parts[$k])) {
        $b = [System.IO.File]::ReadAllBytes($parts[$k])
        [void]$fp.TransformBlock($b, 0, $b.Length, $null, 0)
    }
}
[void]$fp.TransformFinalBlock($Zero, 0, 0)
$Fingerprint = [System.BitConverter]::ToString($fp.Hash).Replace('-', '')
$fp.Dispose()
if ($Confirmed) {
    if (-not $Expect) { Stop-Script 'Запуск с -Confirmed без -Expect (отпечатка задания). Ничего не сделано.' 5 }
    if ($Expect.Trim().ToUpper() -ne $Fingerprint) {
        Stop-Script 'Задание изменилось после подтверждения в окне (отпечаток не совпал). Подтвердите очередь заново. Ничего не сделано.' 5
    }
}

# --- 1б. разбор.json (задания «Разбора носителя»): набор дисков задания фиксирован; манифест - только предупреждение --- (Step-Razbor)
. Step-Razbor

# --- 2. Список ---
$Items = New-Object System.Collections.Generic.List[object]
$lineNo = 0
foreach ($line in [System.IO.File]::ReadAllLines($ListFile, $U8)) {
    $lineNo++
    if (-not $line.Trim()) { continue }
    $f = $line.Split("`t")
    if ($f.Count -lt 3) { Stop-Script "список.tsv, строка ${lineNo}: меньше трёх полей. Ничего не сделано." 5 }
    $rel = $f[1]
    $size = [int64]0
    if (-not [int64]::TryParse($f[2], [ref]$size) -or $size -lt 0) { Stop-Script "список.tsv, строка ${lineNo}: размер не число. Ничего не сделано." 5 }
    if ($Targets -notcontains $f[0]) { Stop-Script "список.tsv, строка ${lineNo}: цель «$($f[0])» не указана в тома.tsv. Ничего не сделано." 5 }
    if (-not (Test-Rel $rel)) {
        Stop-Script "список.tsv, строка ${lineNo}: недопустимый путь «$rel». Ничего не сделано." 5
    }
    $hash = ''
    if ($f.Count -ge 5 -and $f[4] -match '^[0-9A-Fa-f]{64}$') { $hash = $f[4].ToUpper() }
    $Items.Add((New-Row $f[0] $rel $size $hash ''))
}
# 2.7: заменённые имена и «свои копии» (Step-Names)
. Step-Names
$Todo = New-Object System.Collections.Generic.List[object]
foreach ($x in $Items) { if ($Root[$x.Target]) { $Todo.Add($x) } }
$Missing = @($Targets | Where-Object { -not $Root[$_] })
Write-Host ''
[double]$Total = 0
. Step-Space
if ($Items.Count -eq 0) { Stop-Script 'Копировать нечего: список пуст.' $CodeOk }
if ($Todo.Count -eq 0) { Stop-Script 'Копировать некуда: диски-цели не подключены. Ничего не сделано.' 5 }
$withHash = @($Todo | Where-Object { $_.Hash }).Count
Write-Host ("Сверка с SHA-256 из описи: {0} из {1} файлов (для остальных SHA-256 только записывается в журнал)." -f $withHash, $Todo.Count)
if ($Spare.Count) { Write-Host ("Есть запасные экземпляры дублей (если основной файл не удастся) для {0} файлов." -f $Spare.Count) }
foreach ($w in $Warn) { Write-Host ('ПРЕДУПРЕЖДЕНИЕ: ' + $w) -ForegroundColor Yellow }
if ($Confirmed) { Write-Host 'Подтверждено в окне программы (очередь заданий): вопроса «да» не будет.' -ForegroundColor Cyan }
Write-Host ''
if (-not $NoPause) {
    $ans = Read-Host ("Копировать {0} файлов, {1}? Введите «да»" -f $Todo.Count, (Fmt-GB $Total))
    if (@('да', 'д', 'y', 'yes') -notcontains "$ans".Trim().ToLower()) { Write-Host 'Отменено. Ничего не сделано.'; [void](Read-Host 'Enter - закрыть'); exit 0 }
}

# --- 3. Журнал ---
$Started = $true
$Stamp = Get-Date -Format 'yyyy-MM-dd HH-mm-ss'
$LogPath = Join-Path $Here "Журнал копирования $Stamp.tsv"
$Log = [System.IO.StreamWriter]::new($LogPath, $false, [System.Text.UTF8Encoding]::new($true))
$Log.AutoFlush = $true
$Log.WriteLine("время`tцель`tрезультат`tразмер`tSHA-256 прочитанного`tисточник`tкуда`tдата изменения источника")

# --- 4. Копирование ---
$CanKey = $true
try { [void][Console]::KeyAvailable } catch { $CanKey = $false; Write-Host 'Нет консоли - остановка по Q недоступна (закройте окно, чтобы прервать).' -ForegroundColor Yellow }
[double]$Done = 0          # пройдено по списку, байт (для процента)
[double]$CopiedBytes = 0   # реально скопировано, байт (для скорости)
$Copied = 0; $Skipped = 0; $Errors = 0; $Stopped = $false; $Hung = ''
$ErrorsInRow = 0; $MaxErrorsInRow = 5; $Failing = $false
$QStop = $false; $Problems = 0; $Why = ''     # $Why - причина аварийной остановки (код 4)
$ProblemList = New-Object System.Collections.Generic.List[object]     # 2.7: проблемные файлы для списка в конце
$Renamed = New-Object System.Collections.Generic.List[string]
$LastIdCheck = @{}
$DiskFull = @(-2147024784, -2147024857)       # 0x80070070 «на диске нет места», 0x80070027 «диск заполнен»
# Временные файлы пишутся только в собственную папку программы на диске-цели и носят имя этого запуска.
# Поэтому скрипт никогда не трогает чужие файлы, даже если они называются «….part».
$TmpName = '_ВРЕМЕННО - копирование (можно удалить)'
$RunId = 'run' + (Get-Date -Format 'yyyyMMddHHmmss') + '_' + $PID
$TmpDir = @{}
foreach ($t in $Targets) {
    if (-not $Root[$t]) { continue }
    $TmpDir[$t] = $Root[$t] + '\' + $TmpName
    try {
        if ([System.IO.Directory]::Exists((Get-Long $TmpDir[$t]))) {
            # остатки прошлых прерванных запусков: в этой папке лежат только наши файлы
            foreach ($old in [System.IO.Directory]::GetFiles((Get-Long $TmpDir[$t]), 'run*.part')) { [System.IO.File]::Delete($old) }
        }
    } catch { }
}
$Start = Get-Date
$LastUi = $Start.AddSeconds(-10)
$bytes = New-Object byte[] $BufSize
$Processed = 0
for ($idx = 0; $idx -lt $Todo.Count; $idx++) {
    $it = $Todo[$idx]
    $Processed++
    $i = $idx + 1
    $srcPath = $Root[$SrcName] + '\' + $it.Rel
    $dstPath = $Root[$it.Target] + '\' + $Dest[$it.Target] + '\' + $SrcName + '\' + $it.DstRel
    $result = ''; $readHash = ''; $part = $null; $in = $null; $out = $null; $sha = $null; $sInfo = $null
    $Kind = ''; $Side = 'источник'          # 2.7: вид проблемы и сторона, где случилась ошибка
    [double]$fileDone = 0
    try {
        if ($it.Bad) {
            $Kind = 'имя'
            $msg = if ($it.Bad -like 'имя после замены*') { "$($it.Bad) - не скопирован, чтобы два файла не слились в одну копию; переименуйте его вручную" }
                   else { "в имени запрещённый в Windows $($it.Bad) - Windows этот файл не открывает, он не скопирован; переименуйте его там, где он записан (Mac, Linux, фотоаппарат)" }
            throw [System.InvalidOperationException]::new($msg)
        }
        $sInfo = [System.IO.FileInfo]::new((Get-Long $srcPath))
        $Side = 'цель'
        $dInfo = [System.IO.FileInfo]::new((Get-Long $dstPath))
        $Side = 'источник'
        if (-not $sInfo.Exists) {
            $result = 'нет источника'
            # 2.7: FileInfo.Exists = false и при нет прав, и при сбое диска - спросим ещё раз; «нет источника» - только
            # если Windows ответила «нет файла» или «нет папки», иначе - настоящая причина (права, ввод-вывод)
            try { [void][System.IO.File]::GetAttributes((Get-Long $srcPath)) } catch { if (@(-2147024894, -2147024893) -notcontains (Get-InnerHResult $_)) { throw } }
        }
        elseif ($sInfo.Length -ne $it.Size) { $result = "размер источника изменился ($($sInfo.Length))" }
        elseif ([System.IO.Directory]::Exists((Get-Long $dstPath))) { $result = 'КОНФЛИКТ: в цели на месте файла лежит папка с таким именем, не трогал' }
        elseif ($dInfo.Exists -and $it.Changes -and -not $OwnCopy.ContainsKey((Get-CopyKey $it.Target $srcPath $dstPath))) {
            $result = 'КОНФЛИКТ: в цели уже есть файл с заменённым именем, но его записал не этот шаблон для этого файла (может быть копией другого файла), не трогал'
        }
        elseif ($dInfo.Exists -and $dInfo.Length -eq $it.Size) {
            # 2.5: тот же размер - содержимое сверяется по SHA-256. Эталон - опись; нет в описи - прочитанный источник.
            $want = $it.Hash; $r = @{}
            if (-not $want) {
                $r = Read-Sha $srcPath "$SrcName ($($Root[$SrcName]))" $it $i
                if ($r.Hash) { $want = $r.Hash }
            }
            $Side = 'цель'
            if ($want) { $r = Read-Sha $dstPath "$($it.Target) ($($Root[$it.Target]))" $it $i }
            if ($r.Hung) {
                $Hung = $r.Hung; $Stopped = $true; $Errors++
                $result = "ОШИБКА: диск не отвечает дольше $TimeoutSec с - $Hung (сверка SHA-256). Копирование прекращено"
            }
            elseif ($r.Q) { $Stopped = $true; $QStop = $true; $result = 'ОСТАНОВЛЕНО (Q) во время сверки SHA-256, ничего не изменено' }
            elseif ($want -and $r.Hash -eq $want) {
                $result = 'уже есть, SHA-256 совпал'
                $readHash = $r.Hash                 # SHA-256, прочитанный с места назначения (он и совпал)
                if ($it.Spare) { $result += " (запасной экземпляр вместо «$($it.Spare)»)" }
            }
            else { $result = 'КОНФЛИКТ: на месте назначения другой файл того же размера (SHA-256 отличается)' }
        }
        elseif ($dInfo.Exists) { $result = "КОНФЛИКТ: в цели другой размер ($($dInfo.Length)), не трогал" }
        else {
            . Step-CopyFile
        }
    } catch {
        # 2.7: понятная причина (занят / нет прав / сбойный сектор / запрещённое имя); строка по-прежнему «ОШИБКА: …»
        if ($Kind -eq 'имя') { $result = 'ОШИБКА: ' + (Get-InnerMessage $_) }
        else { $p = Get-Problem $_ $Side; $Kind = $p.Kind; $result = 'ОШИБКА: ' + $p.Text }
        $Errors++
        if ($DiskFull -contains (Get-InnerHResult $_)) {
            $Stopped = $true; $Failing = $true; $Why = "на $($it.Target) кончилось место"
            $result += ' | на диске нет места - копирование прекращено'
        }
        if (-not $Hung) {
            try { if ($out) { $out.Dispose() } } catch { }
            try { if ($in) { $in.Dispose() } } catch { }
            try { if ($part -and [System.IO.File]::Exists($part)) { [System.IO.File]::Delete($part) } } catch { }
        }
    }
    . Step-RowEnd
    if ($Stopped) { break }
}
$Log.Close()
Write-Progress -Id 2 -Activity ' ' -Completed
Write-Progress -Id 1 -Activity ' ' -Completed
$mins = ((Get-Date) - $Start).TotalMinutes
Write-Host ''
$tail = if ($Hung) { ', ПРЕКРАЩЕНО: диск не отвечает' } elseif ($QStop) { ', ОСТАНОВЛЕНО по Q' } elseif ($Failing) { ", ПРЕКРАЩЕНО: $Why" } else { '' }
# пустую папку временных файлов убираем за собой; непустую (остаток зависшего файла) оставляем следующему запуску
foreach ($t in $TmpDir.Keys) {
    try { if ([System.IO.Directory]::Exists((Get-Long $TmpDir[$t])) -and -not [System.IO.Directory]::EnumerateFileSystemEntries((Get-Long $TmpDir[$t])).GetEnumerator().MoveNext()) { [System.IO.Directory]::Delete((Get-Long $TmpDir[$t])) } } catch { }
}
$sumColor = if ($Errors -gt 0 -or $Hung) { 'Red' } else { 'Cyan' }
Write-Host ("Итог: скопировано {0}, пропущено {1}, ошибок {2}{3}. Время {4:N1} мин." -f $Copied, $Skipped, $Errors, $tail, $mins) -ForegroundColor $sumColor
if ($Errors -gt 0) { Write-Host 'Есть ошибки: строки со словом ОШИБКА в журнале.' -ForegroundColor Red }
if ($Missing.Count) { Write-Host ('Не подключены: ' + ($Missing -join ', ') + ' - для них запустите задание ещё раз, когда подключите.') -ForegroundColor Yellow }
Write-Host "Журнал: $LogPath"
. Step-Problems
Write-Host 'Повторный запуск продолжит с места остановки: уже скопированные файлы сверяются по SHA-256 и не копируются заново.'
# код выхода (очередь окна: 10 и 11 - дальше, остальное - стоп): 2 завис > 3 Q > 4 авария > 1/11 не всё > 0/10 всё
$code = if ($QStop) { 3 } elseif ($Failing) { 4 } elseif ($Errors -gt 0 -or $Problems -gt 0 -or $Missing.Count -gt 0) { $CodeIncomplete } else { $CodeOk }
if ($Confirmed) { Write-Host "Код завершения для очереди: $code" }
if (-not $NoPause) { [void](Read-Host 'Enter - закрыть') }
if ($Hung) { [Environment]::Exit(2) }
exit $code
