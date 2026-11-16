# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ (версия 2.4 от 15.11.2026)
#
# Новое в 2.4 (логика v3, этап 4; «Логика_v3_разбор_носителя.md», раздел «Этап 4»):
#   - запуск из очереди окна: -Confirmed -Expect <отпечаток> - без вопроса «да» и без «Enter - закрыть». Отпечаток -
#     SHA-256 байтов список.tsv + 0 + тома.tsv + 0 + разбор.json; не совпал (задание изменилось после подтверждения) -
#     ничего не делается, код 5;
#   - коды выхода (очередь: 10 и 11 - дальше, всё остальное - стоп):
#       0 / 10 (с -Confirmed) - закончено, всё прошло (или копировать нечего);
#       1 / 11 (с -Confirmed) - закончено не всё: ошибки, конфликты, «нет источника», часть целей не подключена;
#       2 - диск завис;  3 - остановлено клавишей Q;
#       4 - аварийная остановка: 5 ошибок подряд, «диск переполнен», том источника или цели пропал, неожиданная ошибка;
#       5 - не начато: ошибка в файлах задания, диск не подключён, нет места, задание не совпадает с разбор.json;
#   - разбор.json рядом (задания «Разбора носителя»): цели в тома.tsv обязаны совпасть с целями разбора (набор дисков
#     задания фиксирован), источник - с носителем; манифест разбора не «готово» - только ПРЕДУПРЕЖДЕНИЕ (решение
#     владельца: задания независимы и ничего не перезаписывают);
#   - запасной экземпляр дубля: одинаковое содержимое внутри задания копируется один раз; если этот файл не удался
#     (нет источника, изменился, ошибка чтения, SHA-256 не совпал, конфликт в цели), копируется следующий дубль с тем же
#     SHA-256 на СВОЙ путь (список дублей - «зависимые» в разбор.json);
#   - в журнале 8-я колонка «дата изменения источника» (секунды UTC, как в описи): хеш прочитанного привязан к версии
#     файла. Сборщик читает колонки по заголовку, старые журналы (7 колонок) читаются как раньше.
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
#   «уже есть» - в цели лежит файл с тем же размером. Его содержимое НЕ читалось: это не доказательство копии.
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
# Файл, который уже лежит в цели с тем же размером, считается скопированным и повторно не читается
#   (правило проекта). Копии, сделанные старыми скриптами, сверяются по SHA-256 отдельно.
#
# Параметры ниже нужны только для проверки шаблона на тестовых папках, при обычном запуске не задаются:
#   -TestRoots 'HDD17=C:\тест\источник;HDD45=C:\тест\цель1'  (папки вместо дисков, без вопросов)
# Параметры очереди окна (2.4): -Confirmed -Expect <отпечаток задания> (см. выше).
param(
    [string]$TestRoots = '',
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
$LongPrefix = '\\?\'
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
    if (-not $NoPause) { [void](Read-Host 'Enter - закрыть') }
    exit $code
}
# Путь от корня: без буквы, без «/», без «..», не с «\» (одинаково для список.tsv и «зависимых» разбор.json).
function Test-Rel([string]$rel) {
    return [bool]($rel -and -not $rel.StartsWith('\') -and -not $rel.Contains(':') -and -not $rel.Contains('/') -and -not ('\' + $rel + '\').Contains('\..\'))
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
        $Dest[$name] = $f[2].Trim().Trim('\')
        if ($Dest[$name].Contains(':') -or $Dest[$name].Contains('/') -or ('\' + $Dest[$name] + '\').Contains('\..\')) { Stop-Script "тома.tsv: недопустимая папка «$($Dest[$name])» у $name. Ничего не сделано." 5 }
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

# --- 1б. разбор.json (задания «Разбора носителя»): набор дисков задания фиксирован; манифест - только предупреждение ---
$Warn = New-Object System.Collections.Generic.List[string]
$Razbor = $null
$Spare = @{}            # «цель|SHA-256» -> очередь путей дублей (запасные экземпляры)
if ([System.IO.File]::Exists($RazborFile)) {
    try {
        Add-Type -AssemblyName System.Web.Extensions
        $js = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $js.MaxJsonLength = [int]::MaxValue
        $Razbor = $js.DeserializeObject([System.IO.File]::ReadAllText($RazborFile, $U8))
    } catch { Stop-Script ("разбор.json не читается: " + (Get-InnerMessage $_) + '. Ничего не сделано.') 5 }
    $rzSrc = "$($Razbor['носитель'])"
    $rzTargets = @(); if ($Razbor['цели']) { $rzTargets = @($Razbor['цели'] | ForEach-Object { "$_" }) }
    $rzMust = @(); if ($Razbor['обязательные диски']) { $rzMust = @($Razbor['обязательные диски'] | ForEach-Object { "$_" }) }
    $bad = @()
    if ($rzSrc -ne $SrcName) { $bad += "источник $SrcName, а в разборе - $rzSrc" }
    foreach ($t in $Targets) {
        if ($rzTargets -notcontains $t) { $bad += "цель $t не входит в цели разбора" }
        if ($rzMust -notcontains $t) { $bad += "цель $t не среди обязательных дисков направления" }
    }
    foreach ($t in $rzTargets) { if ($Targets -notcontains $t) { $bad += "цели разбора $t нет в тома.tsv" } }
    if ($bad.Count) { Stop-Script ("Состав дисков задания не совпадает с разбор.json: " + ($bad -join '; ') + '. Подготовьте задание заново. Ничего не сделано.') 5 }
    $deps = $Razbor['зависимые']
    if ($deps) {
        foreach ($t in @($deps.Keys)) {
            if ($Targets -notcontains $t) { Stop-Script "разбор.json: зависимые дубли для диска $t, которого нет среди целей. Ничего не сделано." 5 }
            foreach ($d in @($deps[$t])) {
                $dp = "$($d[0])"; $dsha = "$($d[1])".ToUpper()
                if (-not (Test-Rel $dp) -or $dsha -notmatch '^[0-9A-F]{64}$') { Stop-Script "разбор.json: недопустимый зависимый дубль «$dp». Ничего не сделано." 5 }
                $key = "$t|$dsha"
                if (-not $Spare.ContainsKey($key)) { $Spare[$key] = New-Object System.Collections.Generic.Queue[string] }
                $Spare[$key].Enqueue($dp)
            }
        }
    }
    # манифест: ищется вверх от папки задания («…\Каталог дисков\_БАЗА\разборы\<имя>») и прямо в родителе (временная сборка)
    $manName = "$($Razbor['манифест'])"
    $taskDir = [System.IO.DirectoryInfo]::new($Here)
    if ($taskDir.Parent -and $taskDir.Parent.Name.EndsWith('.tmp')) {
        $Warn.Add('Папка задания лежит во временной папке сборки разбора (…\.tmp): подготовка комплекта не закончилась.')
    }
    $manPath = $null
    if ($manName) {
        $dir = $taskDir.Parent
        for ($up = 0; $up -lt 5 -and $dir -and -not $manPath; $up++) {
            foreach ($cand in @((Join-Path $dir.FullName "Каталог дисков\_БАЗА\разборы\$manName"), (Join-Path $dir.FullName $manName))) {
                if ([System.IO.File]::Exists($cand)) { $manPath = $cand; break }
            }
            $dir = $dir.Parent
        }
    }
    $manOk = $false
    if (-not $manPath) { $Warn.Add("Манифест разбора «$manName» не найден: комплект заданий не подтверждён как готовый.") }
    else {
        try {
            $man = $js.DeserializeObject([System.IO.File]::ReadAllText($manPath, $U8))
            $manTasks = @(); if ($man['задания']) { $manTasks = @($man['задания'] | ForEach-Object { "$($_['имя'])" }) }
            if ("$($man['носитель'])" -ne $SrcName) { $Warn.Add("Манифест «$manName» - другого носителя ($($man['носитель'])).") }
            elseif ($manTasks -notcontains $taskDir.Name) { $Warn.Add("Задания «$($taskDir.Name)» нет в манифесте «$manName».") }
            elseif ("$($man['статус'])" -ne 'готово') { $Warn.Add("Манифест разбора «$manName»: статус «$($man['статус'])» - комплект заданий не подтверждён как готовый.") }
            else { $manOk = $true }
        } catch { $Warn.Add("Манифест разбора «$manName» не читается: " + (Get-InnerMessage $_)) }
    }
    if (-not $manOk) { $Warn.Add('Запуск разрешён решением владельца: это задание само ничего не перезаписывает; другие задания этого разбора могут отсутствовать.') }
}

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
    $Items.Add([pscustomobject]@{ Target = $f[0]; Rel = $rel; Size = $size; Hash = $hash; Spare = '' })
}
$Todo = New-Object System.Collections.Generic.List[object]
foreach ($x in $Items) { if ($Root[$x.Target]) { $Todo.Add($x) } }
$Missing = @($Targets | Where-Object { -not $Root[$_] })
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
    if ($free -lt $need + 1GB) { Stop-Script "На $t не хватает места. Ничего не сделано." 5 }
}
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
# Том на месте? После «нет источника» и после ОШИБКИ: папка корня есть и (на настоящих дисках) серийный номер тома на
# этой букве тот же - после отключения буква могла достаться другому диску (Дискуссия этапа 4, р2-9).
$LastIdCheck = @{}
function Test-Volume([string]$n) {
    $b = "$($Base[$n])"
    if (-not $b -or -not [System.IO.Directory]::Exists($b.TrimEnd('\') + '\')) { return $false }
    if ($TestRoots) { return $true }
    $now = Get-Date
    if ($LastIdCheck.ContainsKey($n) -and ($now - $LastIdCheck[$n]).TotalSeconds -lt 30) { return $true }
    $LastIdCheck[$n] = $now
    try {
        $d = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $b.Substring(0, 2))
        return [bool]($d -and $d.VolumeSerialNumber -and $d.VolumeSerialNumber.ToUpper() -eq $VolSerial[$n])
    } catch { return $true }    # спросить Windows не удалось - решают 5 ошибок подряд
}
function Get-InnerHResult($err) {
    $e = $err.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    return $e.HResult
}
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
        if ([System.IO.Directory]::Exists($LongPrefix + $TmpDir[$t])) {
            # остатки прошлых прерванных запусков: в этой папке лежат только наши файлы
            foreach ($old in [System.IO.Directory]::GetFiles($LongPrefix + $TmpDir[$t], 'run*.part')) { [System.IO.File]::Delete($old) }
        }
    } catch { }
}
$Start = Get-Date
$LastUi = $Start.AddSeconds(-10)
$bytes = New-Object byte[] $BufSize
for ($idx = 0; $idx -lt $Todo.Count; $idx++) {
    $it = $Todo[$idx]
    $i = $idx + 1
    $srcPath = $Root[$SrcName] + '\' + $it.Rel
    $dstPath = $Root[$it.Target] + '\' + $Dest[$it.Target] + '\' + $SrcName + '\' + $it.Rel
    $result = ''; $readHash = ''; $part = $null; $in = $null; $out = $null; $sha = $null; $sInfo = $null
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
            [void][System.IO.Directory]::CreateDirectory($LongPrefix + $TmpDir[$it.Target])
            $part = $LongPrefix + $TmpDir[$it.Target] + '\' + $RunId + '_' + $i + '.part'
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
                    if ($k.Key -eq 'Q') { $Stopped = $true; $QStop = $true; break }
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
                    if ($it.Spare) { $result += " (запасной экземпляр вместо «$($it.Spare)»)" }
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
    if ($sha) { try { $sha.Dispose() } catch { } }
    # Несколько ошибок подряд - признак сбоя диска: дальше не идём, чтобы не усугублять.
    if ($result -like 'ОШИБКА*') { $ErrorsInRow++ } elseif ($result -like 'скопирован*' -or $result -eq 'уже есть') { $ErrorsInRow = 0 }
    if (-not $Stopped -and ($result -eq 'нет источника' -or $result -like 'ОШИБКА*')) {
        $check = if ($result -eq 'нет источника') { @($SrcName) } else { @($SrcName, $it.Target) }
        foreach ($n in $check) {
            if (-not (Test-Volume $n)) {
                $Stopped = $true; $Failing = $true; $Why = "диск $n пропал или на его букве уже другой диск"
                $result += " | $Why - копирование прекращено"
                break
            }
        }
    }
    if ($ErrorsInRow -ge $MaxErrorsInRow -and -not $Stopped) {
        $Stopped = $true; $Failing = $true; $Why = "$MaxErrorsInRow ошибок подряд, проверьте диски"
        $result += " | $MaxErrorsInRow ошибок подряд - копирование прекращено, проверьте диски"
    }
    if ($result -eq 'уже есть' -or $result -eq 'нет источника' -or $result -like 'КОНФЛИКТ*' -or $result -like 'размер источника*') { $Skipped++ }
    if ($result -eq 'нет источника' -or $result -like 'КОНФЛИКТ*' -or $result -like 'размер источника*') { $Problems++ }
    # Запасной экземпляр дубля (2.4): этот файл не удался - следующей строкой следующий дубль с тем же SHA-256 на свой путь.
    # «уже есть» у основного файла запасной не запускает; у запасного - запускает следующий (содержимое не сверялось).
    if ($it.Hash -and -not $Stopped -and ($result -eq 'нет источника' -or $result -like 'размер источника*' -or $result -like 'КОНФЛИКТ*' -or
            $result -like 'ОШИБКА*' -or ($it.Spare -and $result -eq 'уже есть'))) {
        $key = "$($it.Target)|$($it.Hash)"
        if ($Spare.ContainsKey($key) -and $Spare[$key].Count -gt 0) {
            $next = $Spare[$key].Dequeue()
            $of = if ($it.Spare) { $it.Spare } else { $it.Rel }
            $Todo.Insert($idx + 1, [pscustomobject]@{ Target = $it.Target; Rel = $next; Size = $it.Size; Hash = $it.Hash; Spare = $of })
            $Total += $it.Size
            $result += " | следующим берётся запасной экземпляр «$next»"
        }
    }
    $Done += $it.Size
    # 2.4: дата изменения источника (секунды UTC, как в описи) - хеш прочитанного привязан к версии файла
    $srcMtime = ''
    try { if ($sInfo -and $sInfo.Exists) { $srcMtime = [string][int64][math]::Floor(($sInfo.LastWriteTimeUtc - [datetime]'1970-01-01').TotalSeconds) } } catch { }
    $Log.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`t{7}" -f (Get-Date -Format 'HH:mm:ss'), $it.Target, $result, $it.Size, $readHash, $srcPath, $dstPath, $srcMtime))
    $color = if ($result -like 'скопирован*' -or $result -eq 'уже есть') { 'Gray' } else { 'Yellow' }
    Write-Host ("[{0}/{1}] {2} {3} - {4}" -f $i, $Todo.Count, $it.Target, $it.Rel, $result) -ForegroundColor $color
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
    try { if ([System.IO.Directory]::Exists($LongPrefix + $TmpDir[$t]) -and -not [System.IO.Directory]::EnumerateFileSystemEntries($LongPrefix + $TmpDir[$t]).GetEnumerator().MoveNext()) { [System.IO.Directory]::Delete($LongPrefix + $TmpDir[$t]) } } catch { }
}
$sumColor = if ($Errors -gt 0 -or $Hung) { 'Red' } else { 'Cyan' }
Write-Host ("Итог: скопировано {0}, пропущено {1}, ошибок {2}{3}. Время {4:N1} мин." -f $Copied, $Skipped, $Errors, $tail, $mins) -ForegroundColor $sumColor
if ($Errors -gt 0) { Write-Host 'Есть ошибки: строки со словом ОШИБКА в журнале.' -ForegroundColor Red }
if ($Missing.Count) { Write-Host ('Не подключены: ' + ($Missing -join ', ') + ' - для них запустите задание ещё раз, когда подключите.') -ForegroundColor Yellow }
Write-Host "Журнал: $LogPath"
Write-Host 'Повторный запуск продолжит с места остановки: уже скопированные файлы пропускаются.'
# код выхода (очередь окна: 10 и 11 - дальше, остальное - стоп): 2 завис > 3 Q > 4 авария > 1/11 не всё > 0/10 всё
$code = if ($QStop) { 3 } elseif ($Failing) { 4 } elseif ($Errors -gt 0 -or $Problems -gt 0 -or $Missing.Count -gt 0) { $CodeIncomplete } else { $CodeOk }
if ($Confirmed) { Write-Host "Код завершения для очереди: $code" }
if (-not $NoPause) { [void](Read-Host 'Enter - закрыть') }
if ($Hung) { [Environment]::Exit(2) }
exit $code
