# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ 2.8 - часть «проверки». Отдельно не запускается: её подгружает Копировать.ps1.
# Копировать.ps1 хранит SHA-256 текста этой части (таблица $PartSha): правите часть - обновите SHA-256 там
# (тест test_file_sizes_other подскажет новое значение), иначе задание не начнётся (код 5).
# Функции выполняются в области сценария Копировать.ps1 и читают и пишут его переменные; разделы
# вызываются с точкой (. Step-…) - как будто их код стоит в Копировать.ps1 на месте вызова.

# --- 1б. разбор.json (задания «Разбора носителя»): набор дисков задания фиксирован; манифест - только предупреждение ---
function Step-Razbor {
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
}

# 2.7: заменённое имя не должно совпасть с другим путём того же задания (a. и a_, CON.jpg и CON_.jpg - без учёта
# регистра, как в Windows): два разных исходника не сливаются в одну копию. Совпало - строка с заменой не копируется.
# 2.7: копия под заменённым именем уже в цели - признаётся, только если её записал этот же шаблон для этого же
# исходника (строка «скопирован…»/«уже есть…» прежних журналов задания). Иначе это может быть копия другого файла
# с таким именем - КОНФЛИКТ, даже при совпавшем SHA-256.
function Step-Names {
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
    $OwnCopy = @{}
    if (@($Items | Where-Object { $_.Changes -and -not $_.Bad }).Count) {
        foreach ($old in [System.IO.Directory]::GetFiles($Here, 'Журнал копирования *.tsv')) {
            foreach ($line in [System.IO.File]::ReadAllLines($old, $U8)) {
                $p = $line.Split("`t")
                if ($p.Count -ge 7 -and ($p[2] -like 'скопирован*' -or $p[2] -like 'уже есть*')) { $OwnCopy[(Get-CopyKey $p[1] $p[5] $p[6])] = $true }
            }
        }
    }
}

# Проверка места на целях (2.6: место нужно только под файлы, которых на месте назначения ещё нет)
function Step-Space {
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
}
