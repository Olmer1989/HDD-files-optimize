# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ (версия 2.7 от 17.11.2026)
#
# Новое в 2.7 (проблемные файлы; решение владельца 17.11.2026, ЖУРНАЛ_ДОДЕЛОК.md):
#   - длинные пути (больше 260 знаков) на источнике и цели: все обращения к файлам - через \\?\ (сетевой путь -
#     \\?\UNC\…); в журнале и на экране пути обычные, без префикса;
#   - понятная причина в журнале (строка по-прежнему начинается с «ОШИБКА: »): файл занят другой программой; нет прав
#     на чтение (права программа НЕ меняет - инструкция в итоге); сбойный сектор / ошибка ввода-вывода (код Windows);
#     в имени символ, который Windows не открывает (< > : " | ? * и управляющие) - файл не трогается, только список.
#     «Занят» и «нет прав» на источнике не считаются в «5 ошибок подряд» (это не сбой диска);
#   - имя с точкой или пробелом на конце и зарезервированное имя Windows (CON, PRN, AUX, NUL, COM1-9, LPT1-9, с любым
#     расширением) - в любой части пути: читается через \\?\ и копируется под заменённым именем (концевые точки и
#     пробелы -> «_», к зарезервированному имени добавляется «_»: «CON.jpg» -> «CON_.jpg»). Колонка «куда» - новый
#     путь, «источник» - исходный, к результату дописано « (имя изменено: «…» -> «…»)». Замена всегда одна и та же:
#     повторный запуск находит копию и сверяет SHA-256. В цели такое имя уже занято - КОНФЛИКТ, ничего не пишется;
#   - в конце - отдельный список «Проблемные файлы» (на экране и в файле «Проблемные файлы <дата время>.txt» рядом
#     с журналом) с причиной и что делать; отдельно - файлы, скопированные под другим именем;
#   - -TestReadError '<путь>=<код Windows>[;…]' - только вместе с -TestRoots: имитация ошибки чтения источника
#     (проверка ветки «сбойный сектор» без сбойного диска).
#
# Новое в 2.6 (логика v3, этап 16; «Логика_v3_разбор_носителя.md», раздел «Этап 16»; решение владельца 16.11.2026):
#   - проверка свободного места считает только файлы, которых на месте назначения ещё НЕТ. Строка, у которой файл
#     в цели уже лежит, места не займёт: тот же размер - «уже есть» (сверка SHA-256, ничего не пишется), другой
#     размер - КОНФЛИКТ (ничего не пишется). Папки назначения перечисляются по одному разу (без чтения файлов);
#     папку прочитать не удалось - её строки считаются новыми (места нужно больше, а не меньше). На экране - сколько
#     файлов уже лежит на цели и сколько места нужно на новые;
#   - папка цели третьей колонкой тома.tsv больше не обрезается по пробелам (пробел по краям - часть имени папки);
#   - -TestFreeBytes <байт> - только вместе с -TestRoots: свободное место для проверки шаблона на тестовых папках.
#
# Новое в 2.5 (логика v3, этап 15; «Логика_v3_разбор_носителя.md», раздел «Этап 15»):
#   - если на месте назначения уже лежит файл ТОГО ЖЕ размера, он читается и его SHA-256 сравнивается с эталоном:
#     SHA-256 из список.tsv, а если его там нет - SHA-256 источника (источник тогда читается целиком). Совпал -
#     «уже есть, SHA-256 совпал» (в журнале - этот хеш; сборка базы засчитывает как подтверждённую копию, степень C).
#     Не совпал - «КОНФЛИКТ: на месте назначения другой файл того же размера (SHA-256 отличается)»: ничего не
#     перезаписывается, файл не скопирован, пробуется запасной экземпляр дубля (если есть). Другой размер - как раньше.
#   - чтение при сверке - с тем же контролем, что копирование: диск не отвечает - код 2, Q - код 3, ошибка чтения -
#     ОШИБКА (5 подряд, пропавший том - код 4). Простое «уже есть» (без сверки) 2.5 больше не пишет; в старых журналах
#     оно читается как раньше (степень Z).
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
# Путь от корня: без «/», не с «\», без пустых частей, «.» и «..» (одинаково для список.tsv, «зависимых» разбор.json и
# папок тома.tsv). 2.7: через \\?\ Windows такие части не убирает, поэтому они запрещены целиком. Двоеточие (в том
# числе «C:…») в строке списка - не отказ всего задания, а проблема одной строки: запрещённый символ (Get-SafeRel),
# такой файл не открывается вообще. В папках тома.tsv двоеточие - отказ.
function Test-Rel([string]$rel) {
    if (-not $rel -or $rel.StartsWith('\') -or $rel.Contains('/')) { return $false }
    foreach ($c in $rel.Split('\')) { if ($c -eq '' -or $c -eq '.' -or $c -eq '..') { return $false } }
    return $true
}
function Get-InnerMessage($err) {
    $e = $err.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    return $e.Message
}
# 2.7: путь для .NET без предела 260 знаков; в журнал и на экран - всегда обычный путь (без префикса).
function Get-Long([string]$p) {
    if ($p.StartsWith('\\?\')) { return $p }
    if ($p.StartsWith('\\')) { return '\\?\UNC\' + $p.Substring(2) }
    return '\\?\' + $p
}
# 2.7: имя, которое Windows не разрешает. Символ < > : " | ? * или управляющий - файл не открывается вообще
# (-> @{ Bad = 'символ «?»' }). Точка или пробел на конце части пути, зарезервированное имя (CON, PRN, AUX, NUL,
# COM1-9, LPT1-9, в том числе COM¹-³/LPT¹-³, с любым расширением) - файл читается через \\?\, на цель идёт под
# заменённым именем (-> @{ Rel = <путь на цели>; Changes = '«a.» -> «a_», …' }). Замена всегда одна и та же.
$ReservedName = '^(CON|PRN|AUX|NUL|COM[1-9\u00B9\u00B2\u00B3]|LPT[1-9\u00B9\u00B2\u00B3])$'
function Get-SafeRel([string]$rel) {
    $parts = $rel.Split('\'); $chg = @()
    for ($k = 0; $k -lt $parts.Count; $k++) {
        $c = $parts[$k]
        $m = [regex]::Match($c, '[<>:"|?*\x00-\x1F]')
        if ($m.Success) {
            $ch = if ([int][char]$m.Value -lt 32) { "с кодом $([int][char]$m.Value)" } else { "«$($m.Value)»" }
            return @{ Bad = "символ $ch в «$c»" }
        }
        $n = $c
        $stem = $n.Split('.')[0].TrimEnd(' ')
        if ($stem -match $ReservedName) { $n = $stem + '_' + $n.Substring($stem.Length) }
        $t = $n.TrimEnd('.', ' ')
        if ($t.Length -lt $n.Length) { $n = $t + ('_' * ($n.Length - $t.Length)) }
        if ($n -cne $c) { $chg += "«$c» -> «$n»"; $parts[$k] = $n }
    }
    return @{ Rel = ($parts -join '\'); Changes = ($chg -join ', ') }
}
# строка задания: Rel - путь на источнике, DstRel - путь на цели (2.7: может быть с заменённым именем), Bad - не открывается
function New-Row($target, [string]$rel, [int64]$size, [string]$hash, [string]$spare) {
    $s = Get-SafeRel $rel
    $bad = if ($s.Bad) { $s.Bad } else { '' }
    $dr = if ($s.Bad) { $rel } else { $s.Rel }
    $chg = if ($s.Bad) { '' } else { $s.Changes }
    return [pscustomobject]@{ Target = $target; Rel = $rel; Size = $size; Hash = $hash; Spare = $spare; DstRel = $dr; Changes = $chg; Bad = $bad }
}
# 2.7: причина ошибки по коду Windows и стороне (источник / цель). -> @{ Kind; Text }. Kind: занят, права (только
# источник - не считаются в «5 ошибок подряд»), сбой, ошибка. Строка журнала - «ОШИБКА: » + Text.
$RightsHelp = 'программа права не меняет: правой кнопкой по файлу или папке - Свойства - Безопасность - Дополнительно - Владелец «Изменить» (нужны права администратора), или запустите задание от имени администратора'
$IoText = @{ 23 = 'данные не читаются (ошибка CRC)'; 27 = 'сектор не найден'; 30 = 'ошибка чтения'; 31 = 'устройство не работает';
    38 = 'неожиданный конец файла'; 483 = 'аппаратная ошибка устройства'; 1006 = 'том изменён извне'; 1117 = 'ошибка ввода-вывода устройства';
    1392 = 'файл или папка повреждены' }
function Get-Problem($err, [string]$side) {
    $hr = Get-InnerHResult $err
    $code = if (((($hr -shr 16) -band 0xFFFF) -eq 0x8007)) { $hr -band 0xFFFF } else { 0 }
    $src = $side -eq 'источник'
    if ($code -eq 32 -or $code -eq 33) {
        if ($src) { return @{ Kind = 'занят'; Text = 'файл занят другой программой - закройте её и нажмите «Повторить копирование»' } }
        return @{ Kind = 'ошибка'; Text = 'файл на диске-цели занят другой программой (антивирус, Проводник) - закройте её и повторите' }
    }
    if ($code -eq 5) {
        if ($src) { return @{ Kind = 'права'; Text = 'нет прав на чтение (файл или его папка на источнике) - ' + $RightsHelp } }
        return @{ Kind = 'ошибка'; Text = 'нет прав на запись на диске-цели - ' + $RightsHelp }
    }
    if ($IoText.ContainsKey($code)) {
        if ($src) { return @{ Kind = 'сбой'; Text = "сбойный сектор или ошибка ввода-вывода при чтении источника (код Windows ${code}: $($IoText[$code])) - файл не скопирован, диск стоит проверить" } }
        return @{ Kind = 'сбой'; Text = "ошибка ввода-вывода на диске-цели (запись или сверка; код Windows ${code}: $($IoText[$code])) - копия не оставлена, диск-цель стоит проверить" }
    }
    return @{ Kind = 'ошибка'; Text = (Get-InnerMessage $err) }
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
    $Items.Add((New-Row $f[0] $rel $size $hash ''))
}
# 2.7: заменённое имя не должно совпасть с другим путём того же задания (a. и a_, CON.jpg и CON_.jpg - без учёта
# регистра, как в Windows): два разных исходника не сливаются в одну копию. Совпало - строка с заменой не копируется.
$Natural = @{}
foreach ($x in $Items) { if (-not $x.Bad -and -not $x.Changes) { $Natural["$($x.Target)|$($x.DstRel.ToLowerInvariant())"] = $x.Rel } }
$SeenNew = @{}
foreach ($x in $Items) {
    if ($x.Bad -or -not $x.Changes) { continue }
    $k = "$($x.Target)|$($x.DstRel.ToLowerInvariant())"
    if ($Natural.ContainsKey($k)) { $x.Bad = "имя после замены совпадает с другим файлом «$($Natural[$k])»" }
    elseif ($SeenNew.ContainsKey($k) -and $SeenNew[$k] -ne $x.Rel) { $x.Bad = "имя после замены совпадает с другим файлом «$($SeenNew[$k])»" }
    else { $SeenNew[$k] = $x.Rel }
}
# 2.7: копия под заменённым именем уже в цели - признаётся, только если её записал этот же шаблон для этого же
# исходника (строка «скопирован…»/«уже есть…» прежних журналов задания). Иначе это может быть копия другого файла
# с таким именем - КОНФЛИКТ, даже при совпавшем SHA-256.
$OwnCopy = @{}
function Get-CopyKey([string]$t, [string]$src, [string]$dst) {     # без буквы диска: она между запусками может смениться
    return ($t + '|' + $src.Substring([math]::Max(0, $src.IndexOf(''))) + '|' + $dst.Substring([math]::Max(0, $dst.IndexOf('')))).ToLowerInvariant()
}
if (@($Items | Where-Object { $_.Changes -and -not $_.Bad }).Count) {
    foreach ($old in [System.IO.Directory]::GetFiles($Here, 'Журнал копирования *.tsv')) {
        foreach ($line in [System.IO.File]::ReadAllLines($old, $U8)) {
            $p = $line.Split("`t")
            if ($p.Count -ge 7 -and ($p[2] -like 'скопирован*' -or $p[2] -like 'уже есть*')) { $OwnCopy[(Get-CopyKey $p[1] $p[5] $p[6])] = $true }
        }
    }
}
$Todo = New-Object System.Collections.Generic.List[object]
foreach ($x in $Items) { if ($Root[$x.Target]) { $Todo.Add($x) } }
$Missing = @($Targets | Where-Object { -not $Root[$_] })
Write-Host ''
[double]$Total = 0
# 2.6: файлы папки назначения - словарь «имя -> размер» без учёта регистра (как в Windows); папки нет - $null.
# Содержимое файлов не читается. Ошибка перечисления - исключение (строки этой папки считаются новыми).
function Get-DestFiles([string]$dir) {
    $full = Get-Long $dir
    if (-not [System.IO.Directory]::Exists($full)) { return $null }
    $d = New-Object 'System.Collections.Generic.Dictionary[string,long]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($fi in [System.IO.DirectoryInfo]::new($full).EnumerateFiles()) {
        if (-not $d.ContainsKey($fi.Name)) { $d[$fi.Name] = $fi.Length }
    }
    return ,$d
}
foreach ($t in $Targets) {
    $g = @($Items | Where-Object { $_.Target -eq $t })
    [double]$all = 0
    foreach ($x in $g) { $all += $x.Size }
    if (-not $Root[$t]) { Write-Host ("{0}: {1} файлов, {2} - диск не подключён, пропускается" -f $t, $g.Count, (Fmt-GB $all)) -ForegroundColor Yellow; continue }
    $Total += $all
    # 2.6: место нужно только под файлы, которых на месте назначения ещё нет
    [double]$need = 0; [double]$sameBytes = 0; $same = 0; $other = 0; $unread = 0
    $destBase = $Root[$t] + '\' + $Dest[$t] + '\' + $SrcName
    $haveBase = [System.IO.Directory]::Exists((Get-Long $destBase))
    $dirs = @{}
    foreach ($x in $g) {
        $len = $null
        if ($haveBase) {
            $p = $destBase + '\' + $x.DstRel
            $k = $p.LastIndexOf('\')
            $dir = $p.Substring(0, $k); $leaf = $p.Substring($k + 1)
            if (-not $dirs.ContainsKey($dir)) {
                try { $dirs[$dir] = Get-DestFiles $dir }
                catch { $dirs[$dir] = 'не прочитана'; $unread++ }
            }
            $files = $dirs[$dir]
            if ($null -ne $files -and $files -isnot [string] -and $files.ContainsKey($leaf)) { $len = $files[$leaf] }
        }
        if ($null -eq $len) { $need += $x.Size }
        elseif ($len -eq $x.Size) { $same++; $sameBytes += $x.Size }
        else { $other++ }
    }
    $free = [double]([System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($Root[$t] + '\')).AvailableFreeSpace)
    if ($TestRoots -and $TestFreeBytes -ge 0) { $free = $TestFreeBytes }
    Write-Host ("{0}: {1} файлов, {2} -> {3}\{4}\{5}   (свободно {6})" -f $t, $g.Count, (Fmt-GB $all), $Root[$t], $Dest[$t], $SrcName, (Fmt-GB $free))
    if ($same) { Write-Host ("  уже лежат на цели с тем же размером: {0} файлов, {1} - будут сверены по SHA-256, места не займут" -f $same, (Fmt-GB $sameBytes)) }
    if ($other) { Write-Host ("  лежат на цели с другим размером: {0} файлов - КОНФЛИКТ, не копируются, места не займут" -f $other) -ForegroundColor Yellow }
    if ($unread) { Write-Host ("  папок назначения не прочитано: {0} - их файлы посчитаны как новые" -f $unread) -ForegroundColor Yellow }
    Write-Host ("  нужно места под новые файлы: {0} (+ запас 1 ГБ)" -f (Fmt-GB $need))
    if ($free -lt $need + 1GB) { Stop-Script ("На $t не хватает места: нужно {0} с запасом 1 ГБ, свободно {1}. Ничего не сделано." -f (Fmt-GB ($need + 1GB)), (Fmt-GB $free)) 5 }
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
$ProblemList = New-Object System.Collections.Generic.List[object]     # 2.7: проблемные файлы для списка в конце
$Renamed = New-Object System.Collections.Generic.List[string]
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
        if ([System.IO.Directory]::Exists((Get-Long $TmpDir[$t]))) {
            # остатки прошлых прерванных запусков: в этой папке лежат только наши файлы
            foreach ($old in [System.IO.Directory]::GetFiles((Get-Long $TmpDir[$t]), 'run*.part')) { [System.IO.File]::Delete($old) }
        }
    } catch { }
}
$Start = Get-Date
$LastUi = $Start.AddSeconds(-10)
$bytes = New-Object byte[] $BufSize
# 2.5: SHA-256 файла (только чтение) с тем же контролем, что копирование: ожидание не дольше $TimeoutSec на блок,
# клавиша Q между блоками. -> @{Hash} | @{Hung = 'чтение с …'} | @{Q}. Ошибка чтения - исключение (общий catch строки).
# Зависший поток не закрывается (закрытие тоже может зависнуть) - как при копировании.
function Read-Sha([string]$path, [string]$who, $it, [int]$i) {
    $s = $null; $h = $null
    try {
        $s = [System.IO.FileStream]::new((Get-Long $path), [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read, $BufSize)
        $h = [System.Security.Cryptography.SHA256CryptoServiceProvider]::new()
        [double]$got = 0
        while ($true) {
            $rt = $s.ReadAsync($bytes, 0, $BufSize)
            if (-not $rt.Wait($TimeoutMs)) { $s = $null; return @{ Hung = "чтение с $who" } }
            $n = $rt.Result
            if ($n -le 0) { break }
            [void]$h.TransformBlock($bytes, 0, $n, $null, 0)
            $got += $n
            $now = Get-Date
            if (($now - $script:LastUi).TotalMilliseconds -ge 500) {
                $script:LastUi = $now
                Write-Progress -Id 1 -Activity ("Сверка SHA-256 (уже лежит файл того же размера): файл {0} из {1}" -f $i, $Todo.Count) `
                    -Status ("{0}% | {1} | Q - стоп" -f (Get-Pct ($Done + $got) $Total), $who) -PercentComplete (Get-Pct ($Done + $got) $Total)
                Write-Progress -Id 2 -ParentId 1 -Activity $it.Rel -PercentComplete (Get-Pct $got $it.Size)
            }
            if ($CanKey -and [Console]::KeyAvailable) {
                $k = [Console]::ReadKey($true)
                if ($k.Key -eq 'Q') { return @{ Q = $true } }
            }
        }
        [void]$h.TransformFinalBlock($bytes, 0, 0)
        if ($got -ne $it.Size) { throw "при сверке с $who прочитано $got байт, а по списку $($it.Size)" }
        return @{ Hash = [System.BitConverter]::ToString($h.Hash).Replace('-', '') }
    } finally {
        if ($s) { try { $s.Dispose() } catch { } }
        if ($h) { try { $h.Dispose() } catch { } }
    }
}
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
            $Side = 'цель'
            [void][System.IO.Directory]::CreateDirectory((Get-Long $dstPath.Substring(0, $dstPath.LastIndexOf('\'))))
            [void][System.IO.Directory]::CreateDirectory((Get-Long $TmpDir[$it.Target]))
            $part = (Get-Long $TmpDir[$it.Target]) + '\' + $RunId + '_' + $i + '.part'
            $Side = 'источник'
            $in = [System.IO.FileStream]::new((Get-Long $srcPath), [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read, $BufSize)
            $Side = 'цель'
            $out = [System.IO.FileStream]::new($part, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None, $BufSize)
            $sha = [System.Security.Cryptography.SHA256CryptoServiceProvider]::new()
            while ($true) {
                $Side = 'источник'
                $rt = $in.ReadAsync($bytes, 0, $BufSize)
                if (-not $rt.Wait($TimeoutMs)) { $Hung = "чтение с $SrcName ($($Root[$SrcName]))"; break }
                $n = $rt.Result
                if ($n -le 0) { break }
                if ($FakeErr.ContainsKey($it.Rel)) { throw [System.IO.IOException]::new('имитация ошибки чтения (-TestReadError)', $FakeErr[$it.Rel]) }
                $Side = 'цель'
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
                $Side = 'цель'
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
                    [System.IO.File]::Move($part, (Get-Long $dstPath))
                    $result = if ($it.Hash) { 'скопирован, размер и SHA-256 совпали' } else { 'скопирован, размер совпал' }
                    if ($it.Spare) { $result += " (запасной экземпляр вместо «$($it.Spare)»)" }
                    try {
                        [System.IO.File]::SetCreationTimeUtc((Get-Long $dstPath), $sInfo.CreationTimeUtc)
                        [System.IO.File]::SetLastWriteTimeUtc((Get-Long $dstPath), $sInfo.LastWriteTimeUtc)
                    } catch { $result += ' (дату файла поставить не удалось)' }
                    $Copied++
                    $CopiedBytes += $it.Size
                }
            }
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
    if ($sha) { try { $sha.Dispose() } catch { } }
    # Несколько ошибок подряд - признак сбоя диска: дальше не идём, чтобы не усугублять.
    # 2.7: «занят», «нет прав» на источнике и запрещённое имя - не сбой диска: в счёт не идут и том не проверяют
    $NotDisk = @('занят', 'права', 'имя') -contains $Kind
    if ($result -like 'ОШИБКА*') { if (-not $NotDisk) { $ErrorsInRow++ } } elseif ($result -like 'скопирован*' -or $result -like 'уже есть*') { $ErrorsInRow = 0 }
    if (-not $Stopped -and -not $NotDisk -and ($result -eq 'нет источника' -or $result -like 'ОШИБКА*')) {
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
    if ($result -like 'уже есть*' -or $result -eq 'нет источника' -or $result -like 'КОНФЛИКТ*' -or $result -like 'размер источника*') { $Skipped++ }
    if ($result -eq 'нет источника' -or $result -like 'КОНФЛИКТ*' -or $result -like 'размер источника*') { $Problems++ }
    if ($it.Changes -and ($result -like 'скопирован*' -or $result -like 'уже есть*' -or $result -like 'КОНФЛИКТ*')) { $result += " (имя изменено: $($it.Changes))" }
    # Запасной экземпляр дубля (2.4): этот файл не удался - следующей строкой следующий дубль с тем же SHA-256 на свой путь.
    # «уже есть, SHA-256 совпал» (2.5) - копия подтверждена, запасной не нужен; другой SHA-256 того же размера - КОНФЛИКТ.
    if ($it.Hash -and -not $Stopped -and ($result -eq 'нет источника' -or $result -like 'размер источника*' -or $result -like 'КОНФЛИКТ*' -or
            $result -like 'ОШИБКА*')) {
        $key = "$($it.Target)|$($it.Hash)"
        if ($Spare.ContainsKey($key) -and $Spare[$key].Count -gt 0) {
            $next = $Spare[$key].Dequeue()
            $of = if ($it.Spare) { $it.Spare } else { $it.Rel }
            $Todo.Insert($idx + 1, (New-Row $it.Target $next $it.Size $it.Hash $of))
            $Total += $it.Size
            $result += " | следующим берётся запасной экземпляр «$next»"
        }
    }
    $Done += $it.Size
    # 2.4: дата изменения источника (секунды UTC, как в описи) - хеш прочитанного привязан к версии файла
    $srcMtime = ''
    try { if ($sInfo -and $sInfo.Exists) { $srcMtime = [string][int64][math]::Floor(($sInfo.LastWriteTimeUtc - [datetime]'1970-01-01').TotalSeconds) } } catch { }
    $Log.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`t{7}" -f (Get-Date -Format 'HH:mm:ss'), $it.Target, $result, $it.Size, $readHash, $srcPath, $dstPath, $srcMtime))
    # 2.7: отдельный список в конце - всё, что не скопировано (кроме остановки по Q), и скопированное под другим именем
    if ($result -like 'скопирован*' -or $result -like 'уже есть*') { if ($it.Changes) { $Renamed.Add("$($it.Target): $srcPath -> $dstPath") } }
    elseif ($result -notlike 'ОСТАНОВЛЕНО*') {
        $g = if (@('занят', 'права', 'имя', 'сбой') -contains $Kind) { $Kind } else { 'прочее' }
        $ProblemList.Add([pscustomobject]@{ Group = $g; Text = "$($it.Target): $srcPath - $result" })
    }
    $color = if ($result -like 'скопирован*' -or $result -like 'уже есть*') { 'Gray' } else { 'Yellow' }
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
    try { if ([System.IO.Directory]::Exists((Get-Long $TmpDir[$t])) -and -not [System.IO.Directory]::EnumerateFileSystemEntries((Get-Long $TmpDir[$t])).GetEnumerator().MoveNext()) { [System.IO.Directory]::Delete((Get-Long $TmpDir[$t])) } } catch { }
}
$sumColor = if ($Errors -gt 0 -or $Hung) { 'Red' } else { 'Cyan' }
Write-Host ("Итог: скопировано {0}, пропущено {1}, ошибок {2}{3}. Время {4:N1} мин." -f $Copied, $Skipped, $Errors, $tail, $mins) -ForegroundColor $sumColor
if ($Errors -gt 0) { Write-Host 'Есть ошибки: строки со словом ОШИБКА в журнале.' -ForegroundColor Red }
if ($Missing.Count) { Write-Host ('Не подключены: ' + ($Missing -join ', ') + ' - для них запустите задание ещё раз, когда подключите.') -ForegroundColor Yellow }
Write-Host "Журнал: $LogPath"
# 2.7: отдельный список проблемных файлов - на экране и в файле рядом с журналом. Эти файлы не скопированы, поэтому
# программа не переместит их в «Скопировано на …» (перемещение берёт только подтверждённые копии).
# 2.7: строки, до которых не дошло (остановка), и строки неподключённых целей - тоже в списке, одной строкой с причиной
$NotDone = $Todo.Count - $Processed
if ($NotDone -gt 0) {
    $stopWhy = if ($Hung) { "диск не отвечает ($Hung)" } elseif ($QStop) { 'остановлено клавишей Q' } elseif ($Failing) { $Why } else { 'остановка' }
    $ProblemList.Add([pscustomobject]@{ Group = 'прочее'; Text = "не обработано строк: $NotDone - причина: $stopWhy. Запустите задание ещё раз" })
}
foreach ($t in $Missing) {
    $cnt = @($Items | Where-Object { $_.Target -eq $t }).Count
    if ($cnt) { $ProblemList.Add([pscustomobject]@{ Group = 'прочее'; Text = "${t}: не обработано строк: $cnt - причина: диск не подключён. Запустите задание ещё раз, когда подключите" }) }
}
if ($ProblemList.Count -or $Renamed.Count) {
    $Help = [ordered]@{
        'занят' = 'Файл занят другой программой. Закройте её (фоторедактор, плеер, облачный клиент) и нажмите «Повторить копирование».'
        'права' = 'Нет прав на чтение. Программа права НЕ меняет. Правой кнопкой по файлу или папке - Свойства - Безопасность - Дополнительно - Владелец «Изменить» (нужны права администратора); или запустите задание от имени администратора (правой кнопкой по «Запустить.cmd»). Потом - «Повторить копирование».'
        'имя'   = 'Имя, которое Windows не открывает (< > : " | ? * или управляющий символ), или имя, которое после замены совпало с другим файлом. Программа такие файлы не копирует и не перемещает. Переименуйте их вручную (символы - на компьютере, где файлы записаны: Mac, Linux).'
        'сбой'  = 'Сбойный сектор или ошибка ввода-вывода. Файл не скопирован и перемещён не будет. Проверьте диск; «Повторить копирование» иногда читает со второго раза.'
        'прочее' = 'Прочие: нет источника, конфликт в цели, изменившийся размер, другие ошибки - причина в строке.'
    }
    $txt = New-Object System.Collections.Generic.List[string]
    $txt.Add("Проблемные файлы - копирование $Stamp. Журнал: $LogPath")
    foreach ($g in $Help.Keys) {
        $rows = @($ProblemList | Where-Object { $_.Group -eq $g })
        if (-not $rows.Count) { continue }
        $txt.Add(''); $txt.Add(("{0} ({1})" -f $Help[$g], $rows.Count))
        foreach ($r in $rows) { $txt.Add('  ' + $r.Text) }
    }
    if ($Renamed.Count) {
        $txt.Add(''); $txt.Add(("Скопированы под другим именем - Windows не разрешает исходное (источник -> копия; соответствие - в журнале) ({0}):" -f $Renamed.Count))
        foreach ($r in $Renamed) { $txt.Add('  ' + $r) }
    }
    $ProbPath = Join-Path $Here "Проблемные файлы $Stamp.txt"
    try { [System.IO.File]::WriteAllLines($ProbPath, $txt, [System.Text.UTF8Encoding]::new($true)) } catch { $ProbPath = "(файл записать не удалось: $(Get-InnerMessage $_))" }
    Write-Host ''
    Write-Host ("ПРОБЛЕМНЫЕ ФАЙЛЫ: не скопировано {0}, скопировано под другим именем {1}. Список: {2}" -f $ProblemList.Count, $Renamed.Count, $ProbPath) -ForegroundColor Yellow
    $shown = 0
    foreach ($line in $txt | Select-Object -Skip 1) {
        if ($shown -ge 40) { Write-Host '  … остальное - в файле списка' -ForegroundColor Yellow; break }
        Write-Host $line -ForegroundColor Yellow; $shown++
    }
}
Write-Host 'Повторный запуск продолжит с места остановки: уже скопированные файлы сверяются по SHA-256 и не копируются заново.'
# код выхода (очередь окна: 10 и 11 - дальше, остальное - стоп): 2 завис > 3 Q > 4 авария > 1/11 не всё > 0/10 всё
$code = if ($QStop) { 3 } elseif ($Failing) { 4 } elseif ($Errors -gt 0 -or $Problems -gt 0 -or $Missing.Count -gt 0) { $CodeIncomplete } else { $CodeOk }
if ($Confirmed) { Write-Host "Код завершения для очереди: $code" }
if (-not $NoPause) { [void](Read-Host 'Enter - закрыть') }
if ($Hung) { [Environment]::Exit(2) }
exit $code
