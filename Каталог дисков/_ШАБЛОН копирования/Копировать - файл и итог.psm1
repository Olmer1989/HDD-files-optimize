# ЕДИНЫЙ ШАБЛОН КОПИРОВАНИЯ 2.8 - часть «файл и итог». Отдельно не запускается: её подгружает Копировать.ps1.
# Копировать.ps1 хранит SHA-256 текста этой части (таблица $PartSha): правите часть - обновите SHA-256 там
# (тест test_file_sizes_other подскажет новое значение), иначе задание не начнётся (код 5).
# Функции выполняются в области сценария Копировать.ps1 и читают и пишут его переменные; разделы
# вызываются с точкой (. Step-…) - как будто их код стоит в Копировать.ps1 на месте вызова.

# Файла в цели нет: копирование через .part в своей временной папке с SHA-256 прочитанного (тело ветки else цикла по файлам)
function Step-CopyFile {
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

# Строка обработана: счётчики, «5 ошибок подряд», проверка тома, запасной экземпляр, строка журнала, список проблем
function Step-RowEnd {
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
}

function Step-Problems {
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
}
