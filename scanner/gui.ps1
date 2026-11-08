param([switch]$SmokeTest, [switch]$IntegrationTest)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$ErrorActionPreference = 'Stop'
$script:worker = $null
$script:stopping = $false
$script:progressFile = $null
$script:operation = ''
$AppVersion = '1.3.1'

$form = New-Object Windows.Forms.Form
$form.Text = "Анализ фото и видео на дисках и флешках — версия $AppVersion"
$form.Size = New-Object Drawing.Size(1090, 916)
$form.MinimumSize = New-Object Drawing.Size(900, 600)
$form.AutoScroll = $true
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI', 10)
$bold = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
$big = New-Object Drawing.Font('Segoe UI', 13, [Drawing.FontStyle]::Bold)

function Add-Group($text, $x, $y, $w, $h) {
    $g = New-Object Windows.Forms.GroupBox
    $g.Text = $text; $g.SetBounds($x,$y,$w,$h); $g.Font = $bold; $form.Controls.Add($g)
    return $g
}
function Add-Label($parent, $text, $x, $y, $w, $h = 24, $font = $null) {
    $c = New-Object Windows.Forms.Label
    $c.Text = $text; $c.SetBounds($x,$y,$w,$h); $c.AutoEllipsis = $true
    $c.Font = $(if ($font) { $font } else { $form.Font })
    $parent.Controls.Add($c)
    return $c
}
function Add-Button($parent, $text, $x, $y, $w, $action) {
    $c = New-Object Windows.Forms.Button
    $c.Text = $text; $c.SetBounds($x,$y,$w,36); $c.Font = $form.Font; $c.Add_Click($action); $parent.Controls.Add($c)
    return $c
}
function Folder($title) {
    $d = New-Object Windows.Forms.FolderBrowserDialog
    $d.Description = $title
    if ($d.ShowDialog() -eq 'OK') { return $d.SelectedPath }
}
function Failure($message) { if ($SmokeTest -or $IntegrationTest) { throw $message }; [Windows.Forms.MessageBox]::Show([string]$message,'Не удалось выполнить действие','OK','Error') | Out-Null }
function Read-Json($path) { return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json) }
function Status-Text($status) {
    switch ([string]$status) {
        'complete' { return 'завершён' }
        'complete_with_inventory_errors' { return 'завершён (есть недоступные папки)' }
        'complete_with_unread_files' { return 'завершён (есть непрочитанные файлы)' }
        'interrupted' { return 'остановлен, можно продолжить' }
        'error' { return 'остановлен из-за ошибки' }
        'running' { return 'не завершён (или идёт сейчас)' }
        default { return 'не завершён' }
    }
}
function Format-Duration($seconds) {
    if ($null -eq $seconds) { return 'оценивается…' }
    $s = [double]$seconds
    if ($s -lt 60) { return 'меньше минуты' }
    $t = [TimeSpan]::FromSeconds($s)
    $h = [math]::Floor($t.TotalHours)
    if ($h -gt 0) { return ('{0} ч {1:00} мин' -f $h, $t.Minutes) }
    return ('{0} мин' -f $t.Minutes)
}
function Finish-Time($seconds) {
    $t = (Get-Date).AddSeconds([double]$seconds)
    if ($t.Date -eq (Get-Date).Date) { return 'сегодня в ' + $t.ToString('HH:mm') }
    if ($t.Date -eq (Get-Date).Date.AddDays(1)) { return 'завтра в ' + $t.ToString('HH:mm') }
    return $t.ToString('dd.MM в HH:mm')
}
function GB($bytes) { return ('{0:N1} ГБ' -f ([double]$bytes / 1e9)) }

# Earlier jobs in the results folder, used to recognise a disk under any letter.
function Get-Jobs($folder) {
    $found = New-Object System.Collections.ArrayList
    if (-not $folder -or -not (Test-Path -LiteralPath $folder -PathType Container)) { return ,$found }
    # Layout: <results>\<HDDxx - модель - ёмкость - метка>\<задание>; older jobs may lie directly in <results>.
    $dirs = New-Object System.Collections.ArrayList
    foreach ($top in @(Get-ChildItem -LiteralPath $folder -Directory -ErrorAction SilentlyContinue | Where-Object { -not $_.Name.StartsWith('_') })) {
        [void]$dirs.Add($top)
        foreach ($sub in @(Get-ChildItem -LiteralPath $top.FullName -Directory -ErrorAction SilentlyContinue)) { [void]$dirs.Add($sub) }
    }
    foreach ($dir in $dirs) {
        $file = Join-Path $dir.FullName 'job.json'
        if (-not (Test-Path -LiteralPath $file)) { continue }
        try {
            $job = Read-Json $file
            $state = 'не завершён'
            $resultFile = Join-Path $dir.FullName 'result.json'
            if (Test-Path -LiteralPath $resultFile) { $state = Status-Text (Read-Json $resultFile).status }
            if ($job.policy.version -ne 2) { $state += ' · старые правила, нужен добор' }
            [void]$found.Add([pscustomobject]@{Path=$dir.FullName; DiskId=[string]$job.disk_id; Serial=[string]$job.record.hardware_serial
                Bytes=[int64]$job.record.physical_bytes; VolumeSerial=[string]$job.record.volume_serial; VolumeBytes=[int64]$job.record.volume_bytes
                Flash=([string]$job.record.identify_by -eq 'volume'); State=$state})
        } catch { }
    }
    return ,$found
}
# A disk is recognised by device serial and size plus volume serial; a flash drive
# or memory card only by volume serial and size (a card reader has one serial for all cards).
function Prior-Jobs($jobs, $serial, $bytes, $volumeSerial, $volumeBytes) {
    return @($jobs | Where-Object {
        if ($_.Flash) { $_.VolumeSerial -eq $volumeSerial -and $_.VolumeBytes -eq $volumeBytes }
        else { $serial -and $_.Serial -eq $serial -and $_.Bytes -eq $bytes -and $_.VolumeSerial -eq $volumeSerial }
    })
}
function Next-FlashId($jobs) {
    $max = 0
    foreach ($j in $jobs) { if ($j.DiskId -match '^Flash([0-9]{2,})$' -and [int]$matches[1] -gt $max) { $max = [int]$matches[1] } }
    return ('Flash{0:00}' -f ($max + 1))
}

# 1. Disk selection
$g1 = Add-Group '1. Диск для сканирования' 12 8 1045 248
$list = New-Object Windows.Forms.ListView
$list.SetBounds(12,26,1020,172); $list.View = 'Details'; $list.FullRowSelect = $true; $list.MultiSelect = $false; $list.HideSelection = $false; $list.Font = $form.Font
foreach ($col in @(@('Буква / метка',200),@('Модель',215),@('Размер',95),@('Свободно',95),@('Тип',70),@('Подключение',105),@('Уже сканирован',235))) {
    [void]$list.Columns.Add($col[0],$col[1])
}
$g1.Controls.Add($list)
function Refresh-Disks {
    $form.UseWaitCursor = $true
    try {
        $list.Items.Clear()
        $jobs = Get-Jobs $output.Text
        $physical = @(Get-PhysicalDisk -ErrorAction SilentlyContinue)
        # Volumes from Win32_LogicalDisk: this also lists memory cards without a partition table.
        $volumes = @{}
        foreach ($l in @(Get-CimInstance Win32_LogicalDisk -ErrorAction SilentlyContinue)) {
            if ($l.DeviceID -and $l.Size -and [int]$l.DriveType -in @(2,3)) { $volumes[$l.DeviceID.Substring(0,1)] = $l }
        }
        $partitions = @{}
        foreach ($p in @(Get-Partition -ErrorAction SilentlyContinue | Where-Object DriveLetter)) { $partitions[[string]$p.DriveLetter] = $p }
        foreach ($letter in @($volumes.Keys | Sort-Object)) {
            try {
                $l = $volumes[$letter]
                $volumeSerial = [string]$l.VolumeSerialNumber
                $model = '—'; $serial = ''; $bytes = [int64]0; $bus = ''; $system = $false
                $type = $(if ([int]$l.DriveType -eq 2) { 'Съёмный' } else { 'Не определён' })
                if ($partitions.ContainsKey($letter)) {
                    $d = Get-Disk -Number $partitions[$letter].DiskNumber
                    $model = [string]$d.FriendlyName; $serial = ([string]$d.SerialNumber).Trim(); $bytes = [int64]$d.Size
                    $bus = [string]$d.BusType; $system = ($d.IsBoot -or $d.IsSystem)
                    $match = @($physical | Where-Object { ([string]$_.SerialNumber).Trim() -eq $serial -and $_.Size -eq $d.Size })
                    if ($match.Count -eq 1 -and [string]$match[0].MediaType -in @('HDD','SSD')) { $type = [string]$match[0].MediaType }
                }
                # @() is required: a single match comes back as one object, which has no Count in PowerShell 5.1.
                $prior = @(Prior-Jobs $jobs $serial $bytes $volumeSerial ([int64]$l.Size))
                $seen = '—'
                if ($prior.Count -gt 0) { $seen = ($prior | ForEach-Object { "$($_.DiskId): $($_.State)" }) -join '; ' }
                $item = New-Object Windows.Forms.ListViewItem("${letter}:  $($l.VolumeName)")
                foreach ($value in @($model, ('{0:N0} ГБ' -f ($l.Size/1e9)), ('{0:N0} ГБ' -f ($l.FreeSpace/1e9)), $type, $bus, $seen)) { [void]$item.SubItems.Add($value) }
                $item.Tag = [pscustomobject]@{Letter=$letter; Serial=$serial; VolumeSerial=$volumeSerial; Removable=([int]$l.DriveType -eq 2); System=$system; Prior=$prior}
                if ($item.Tag.System) { $item.Text += ' [системный]'; $item.ForeColor = [Drawing.Color]::Gray }
                elseif ($prior.Count -gt 0) { $item.ForeColor = [Drawing.Color]::DarkGreen }
                [void]$list.Items.Add($item)
            } catch { }
        }
        if ($flash.Checked -and $id.Text -notmatch '^Flash[0-9]{2,}$') { $id.Text = Next-FlashId $jobs }
    } catch { Failure $_.Exception.Message }
    finally { $form.UseWaitCursor = $false }
}
$refresh = Add-Button $g1 'Обновить список дисков' 12 204 230 { Refresh-Disks }
$null = Add-Label $g1 'Носитель узнаётся по серийным номерам, а не по букве. Зелёным — уже сканированные в выбранной папке.' 255 212 775

# 2. Parameters
$g2 = Add-Group '2. Параметры' 12 262 1045 136
$null = Add-Label $g2 'Вид носителя:' 12 30 240
$diskKind = New-Object Windows.Forms.RadioButton; $diskKind.Text = 'Диск HDD или SSD (номера HDD…)'; $diskKind.SetBounds(255,28,330,26); $diskKind.Font = $form.Font; $diskKind.Checked = $true; $g2.Controls.Add($diskKind)
$flash = New-Object Windows.Forms.RadioButton; $flash.Text = 'Флешка или карта памяти (номера Flash…)'; $flash.SetBounds(595,28,430,26); $flash.Font = $form.Font; $g2.Controls.Add($flash)
$null = Add-Label $g2 'Номер в общем реестре:' 12 64 240
$id = New-Object Windows.Forms.TextBox; $id.SetBounds(255,61,110,28); $id.Text='HDD03'; $id.Font=$form.Font; $g2.Controls.Add($id)
$idHint = Add-Label $g2 'HDD01 и HDD02 заняты. Один номер — только одному физическому диску.' 380 64 650
$script:lastDiskId = 'HDD03'
$flash.Add_CheckedChanged({
    if ($flash.Checked) {
        if ($id.Text -match '^HDD') { $script:lastDiskId = $id.Text }
        $id.Text = Next-FlashId (Get-Jobs $output.Text)
        $idHint.Text = 'Предложен следующий свободный номер. Подпишите флешку или карту этим номером.'
    } else {
        $id.Text = $script:lastDiskId
        $idHint.Text = 'HDD01 и HDD02 заняты. Один номер — только одному физическому диску.'
    }
})
$null = Add-Label $g2 'Папка результатов:' 12 98 240
$output = New-Object Windows.Forms.TextBox; $output.SetBounds(255,95,620,28); $output.Font=$form.Font
# The chosen results folder is remembered on this computer.
$settingsFile = Join-Path $env:LOCALAPPDATA 'HDDScanner\settings.json'
$output.Text = Join-Path $env:LOCALAPPDATA 'HDDScanner\results'
try { if (-not $IntegrationTest -and (Test-Path -LiteralPath $settingsFile)) { $saved = [string](Read-Json $settingsFile).output; if ($saved -and (Test-Path -LiteralPath $saved -PathType Container)) { $output.Text = $saved } } } catch { }
$g2.Controls.Add($output)
function Save-Settings {
    if ($IntegrationTest -or $SmokeTest) { return }
    try { [void][IO.Directory]::CreateDirectory((Split-Path $settingsFile)); [IO.File]::WriteAllText($settingsFile, ([pscustomobject]@{output=$output.Text} | ConvertTo-Json), (New-Object Text.UTF8Encoding($false))) } catch { }
}
$browse = Add-Button $g2 'Выбрать папку…' 885 91 147 { $p=Folder 'Папка результатов на внутреннем диске'; if ($p) { $output.Text=$p; Save-Settings; Refresh-Disks } }

# 3. Actions
$g3 = Add-Group '3. Действия' 12 404 1045 104
function Busy { return ($script:worker -and -not $script:worker.HasExited) }
function Read-LiveLog($path) {
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return '' }
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}
function Launch($arguments, $label) {
    if (Busy) { Failure 'Дождитесь завершения текущей операции или нажмите «Остановить». Чтобы сканировать другой диск параллельно, откройте второе окно.'; return }
    # Window logs live inside the results folder, so copying that folder from
    # another computer brings them along; '_' keeps them out of the register.
    # Temporary progress/stop signals stay in the local profile.
    $logs = Join-Path $output.Text '_Журналы окна'
    $temp = Join-Path $env:LOCALAPPDATA 'HDDScanner\run'
    if ($IntegrationTest) { $logs = Join-Path $script:testFolder 'logs'; $temp = $logs }
    try { [void][IO.Directory]::CreateDirectory($logs) } catch { $logs = Join-Path $env:LOCALAPPDATA 'HDDScanner\logs'; [void][IO.Directory]::CreateDirectory($logs) }
    [void][IO.Directory]::CreateDirectory($temp)
    # Readable names: date, operation and disk number, plus a short unique suffix.
    $token = (Get-Date -Format 'yyyy-MM-dd_HH-mm-ss') + '_' + $label + '_' + [guid]::NewGuid().ToString('N').Substring(0,6)
    $script:stdout = Join-Path $logs ($token+'.out.txt')
    $script:stderr = Join-Path $logs ($token+'.err.txt')
    $script:stopFile = Join-Path $temp ($token+'.stop')
    $script:progressFile = Join-Path $temp ($token+'.progress.json')
    $script:operation = $label
    $python = Join-Path $PSScriptRoot '..\runtime\python.exe'
    $app = Join-Path $PSScriptRoot 'portable.py'
    if ($IntegrationTest) { $app = $script:testApp }
    # Arguments are passed directly to Python, never evaluated as shell code.
    $all = @('-X','utf8','-B',$app,'--stop-file',$script:stopFile,'--progress-file',$script:progressFile) + $arguments
    foreach ($arg in $all) { if ([string]$arg -match '["\r\n]') { throw 'Недопустимый символ в пути.' } }
    $quoted = ($all | ForEach-Object { '"' + ([string]$_ -replace '(\\+)$','$1$1') + '"' }) -join ' '
    Reset-Progress
    $script:worker = Start-Process -FilePath $python -ArgumentList $quoted -WindowStyle Hidden -PassThru -RedirectStandardOutput $script:stdout -RedirectStandardError $script:stderr
    $null = $script:worker.Handle # Retain process handle so ExitCode remains available in Windows PowerShell.
    $script:stopping = $false
    $status.ForeColor = [Drawing.Color]::Black
    $status.Text='Выполняется. Окно можно оставить открытым; автоматический сон компьютера на время работы отключён.'
    $log.Clear(); $timer.Start()
}

$start = Add-Button $g3 'Начать сканирование' 12 24 250 {
    try {
        if ($list.SelectedItems.Count -ne 1) { throw 'Выберите диск в таблице.' }
        $selected = $list.SelectedItems[0]; $disk = $selected.Tag
        if ($disk.System) { throw 'Системный диск не выбирается для анализа архивов.' }
        if (-not [IO.Path]::IsPathRooted($output.Text)) { throw 'Выберите полный путь папки результатов.' }
        if ([IO.Path]::GetPathRoot($output.Text) -eq ($disk.Letter+':\')) { throw 'Результаты нельзя сохранять на сканируемый том.' }
        $prior = @($disk.Prior)
        if ($prior.Count -gt 0) {
            $p = $prior[0]
            $text = "Этот диск уже сканировался (найден по серийному номеру, буква не важна):`n`nНомер: $($p.DiskId)`nСостояние: $($p.State)`nПапка: $($p.Path)`n`nДа — продолжить это задание (готовые хеши сохранятся; по старым правилам — дочитать мелкие фото и видео).`nНет — начать сканирование заново под тем же номером.`nОтмена — ничего не делать."
            $answer = [Windows.Forms.MessageBox]::Show($text,'Диск уже знаком','YesNoCancel','Warning')
            if ($answer -eq 'Yes') { Launch @('resume',$p.Path) ('resume_'+$p.DiskId); return }
            if ($answer -ne 'No') { return }
            if ($id.Text -ne $p.DiskId) { $id.Text = $p.DiskId; throw "Этому диску уже назначен номер $($p.DiskId). Номер подставлен в поле; нажмите «Начать сканирование» ещё раз." }
        }
        if ($flash.Checked) {
            if ($id.Text -notmatch '^Flash[0-9]{2,}$' -or [int]$id.Text.Substring(5) -lt 1) { throw 'Укажите номер флешки или карты, например Flash01.' }
            if (-not $disk.VolumeSerial -or $disk.VolumeSerial -eq '00000000') { throw 'У тома нет серийного номера — такой носитель нельзя надёжно узнать при следующем подключении.' }
        } else {
            if ($id.Text -notmatch '^HDD[0-9]{2,}$' -or [int]$id.Text.Substring(3) -lt 3) { throw 'Укажите назначенный номер, например HDD03. HDD01 и HDD02 уже заняты. Для флешки или карты выберите «Флешка или карта памяти».' }
            if (-not $disk.Serial) { throw 'Windows не сообщает серийный номер этого устройства. Если это флешка или карта памяти, выберите вид носителя «Флешка или карта памяти».' }
        }
        $known = Get-Jobs $output.Text
        $taken = @($known | Where-Object { $_.DiskId -eq $id.Text -and @(Prior-Jobs @($_) $disk.Serial $_.Bytes $disk.VolumeSerial $_.VolumeBytes).Count -eq 0 })
        if ($taken.Count -gt 0) { throw "Номер $($id.Text) уже назначен другому носителю (папка $($taken[0].Path)). Выберите другой номер." }
        $kindText = $(if ($flash.Checked) { "Флешка или карта памяти`nСерийный номер тома: $($disk.VolumeSerial)" } else { "Диск HDD/SSD`nСерийный номер: $($disk.Serial)" })
        $message = "Носитель: $($selected.Text)`nМодель: $($selected.SubItems[1].Text)`nВид: $kindText`nНомер архива: $($id.Text)`nРезультаты: $($output.Text)`n`nБудут прочитаны метаданные и рассчитаны SHA-256: фото JPEG/HEIC от 50 КБ, прочие изображения и RAW от 150 КБ, видео любого размера. Файлы на носителе не изменяются. Начать?"
        if ([Windows.Forms.MessageBox]::Show($message,'Проверьте выбранный диск','YesNo','Question') -eq 'Yes') {
            Save-Settings
            Launch @('start','--disk',$id.Text,'--letter',$disk.Letter,'--output',$output.Text,'--yes') ('start_'+$id.Text)
        }
    } catch { Failure $_.Exception.Message }
}
$start.Font = $bold
$resume = Add-Button $g3 'Продолжить сканирование…' 272 24 250 {
    try { $p=Folder 'Выберите папку прежнего задания с файлом job.json'; if ($p) {
        $file = Join-Path $p 'job.json'
        if (-not (Test-Path -LiteralPath $file)) { throw 'В выбранной папке нет job.json.' }
        Launch @('resume',$p) ('resume_'+[string](Read-Json $file).disk_id)
    } } catch { Failure $_.Exception.Message }
}
$stop = Add-Button $g3 'Остановить с сохранением' 532 24 250 {
    if (Busy) { [IO.File]::WriteAllText($script:stopFile,'stop'); $script:stopping=$true; $status.Text='Останавливаемся и сохраняем результаты. Не закрывайте окно.' }
}
$export = Add-Button $g3 'Экспорт на флешку…' 12 62 250 {
    try {
        if (Busy) { throw 'Сначала дождитесь завершения операции.' }
        $answer = [Windows.Forms.MessageBox]::Show("Да — выгрузить все завершённые задания из папки результатов:`n$($output.Text)`n(уже выгруженные без изменений пропускаются).`n`nНет — выбрать одно задание.",'Экспорт на флешку','YesNoCancel','Question')
        if ($answer -eq 'Yes') { $dest=Folder 'Папка на флешке (например, HDD_RESULTS)'; if ($dest) { Launch @('export-all',$output.Text,$dest) 'export-all' } }
        elseif ($answer -eq 'No') { $job=Folder 'Папка завершённого задания'; if ($job) { $dest=Folder 'Папка назначения на флешке'; if ($dest) { Launch @('export',$job,$dest) 'export' } } }
    } catch { Failure $_.Exception.Message }
}
$import = Add-Button $g3 'Импорт с флешки…' 272 62 250 {
    # Imports go straight into the results folder, into the folder of their disk.
    try { if (Busy) { throw 'Сначала дождитесь завершения операции.' }; $job=Folder 'Папка на флешке: одно задание или папка с несколькими (например, HDD_RESULTS)'; if ($job) {
        if ([Windows.Forms.MessageBox]::Show("Все найденные задания будут проверены по контрольным суммам и помещены в папки своих дисков внутри:`n$($output.Text)`n`nПродолжить?",'Импорт','YesNo','Question') -eq 'Yes') { Launch @('import',$job,$output.Text) 'import' }
    } } catch { Failure $_.Exception.Message }
}
$open = Add-Button $g3 'Открыть папку результатов' 532 62 250 {
    try { if (Test-Path -LiteralPath $output.Text -PathType Container) { Start-Process explorer.exe -ArgumentList ('"'+$output.Text+'"') } } catch { Failure $_.Exception.Message }
}
$register = Add-Button $g3 'Открыть реестр дисков' 792 62 240 {
    try {
        $file = Join-Path $output.Text 'Реестр дисков.csv'
        if (-not (Test-Path -LiteralPath $file)) { throw 'В выбранной папке результатов ещё нет реестра. Он создаётся после сканирования или импорта.' }
        Start-Process -FilePath $file
    } catch { Failure $_.Exception.Message }
}

# 4. Progress
$g4 = Add-Group 'Ход работы' 12 514 1045 182
$phase = Add-Label $g4 'Ожидание запуска' 12 26 1020 30 $big
$bar = New-Object Windows.Forms.ProgressBar; $bar.SetBounds(12,62,880,30); $bar.Minimum=0; $bar.Maximum=1000; $g4.Controls.Add($bar)
$percent = Add-Label $g4 '' 902 62 130 30 $big
$amount = Add-Label $g4 '' 12 100 1020 24
$eta = Add-Label $g4 '' 12 126 1020 24 $bold
$identity = Add-Label $g4 '' 12 152 1020 24
function Reset-Progress {
    $phase.Text = 'Запуск…'; $bar.Value = 0; $percent.Text = ''; $amount.Text = ''; $eta.Text = ''; $identity.Text = ''
    $script:lastStatus = ''; $script:lastUnread = 0
}
function Show-Progress {
    if (-not $script:progressFile -or -not (Test-Path -LiteralPath $script:progressFile)) { return }
    $raw = Read-LiveLog $script:progressFile
    if (-not $raw) { return }
    try { $p = $raw | ConvertFrom-Json } catch { return }
    $phase.Text = ([string]$p.phase_title) + '  —  ' + ([string]$p.disk_id)
    $script:lastStatus = [string]$p.status
    if ($p.unread_files) { $script:lastUnread = [int]$p.unread_files }
    if ($null -ne $p.percent) {
        $value = [int][math]::Round([double]$p.percent * 10)
        $bar.Value = [math]::Max(0, [math]::Min(1000, $value))
        $percent.Text = ('{0:N1} %' -f [double]$p.percent)
    }
    if ($p.phase -eq 'inventory') {
        $amount.Text = ('Найдено файлов: {0:N0} · просмотрено {1} из ~{2} занятого места · ошибок доступа: {3}' -f [double]$p.files_done, (GB $p.bytes_done), (GB $p.bytes_total), $p.errors)
        $eta.Text = 'Опись идёт быстро; прогноз полного времени появится на этапе контрольных сумм. Прошло ' + (Format-Duration $p.elapsed_seconds)
    } elseif ($null -ne $p.bytes_total) {
        $speed = ''
        if ($null -ne $p.rate_bytes_per_second) { $speed = (' · скорость {0:N0} МБ/с' -f ([double]$p.rate_bytes_per_second / 1e6)) }
        $amount.Text = ('Готово {0} из {1} · файлов {2:N0} из {3:N0}' -f (GB $p.bytes_done), (GB $p.bytes_total), [double]$p.files_done, [double]$p.files_total) + $speed
        if ($p.phase -eq 'done') { $eta.Text = 'Завершено. Общее время работы: ' + (Format-Duration $p.elapsed_seconds) }
        elseif ($p.phase -in @('stopped','error')) { $eta.Text = 'Работа прервана. Прошло ' + (Format-Duration $p.elapsed_seconds) + '. Готовые хеши сохранены.' }
        elseif ($null -eq $p.eta_seconds) { $eta.Text = 'Осталось: оценивается (нужно около минуты работы) · прошло ' + (Format-Duration $p.elapsed_seconds) }
        else { $eta.Text = 'Осталось ≈ ' + (Format-Duration $p.eta_seconds) + ' · завершение ' + (Finish-Time $p.eta_seconds) + ' · прошло ' + (Format-Duration $p.elapsed_seconds) }
    }
    $parts = @("Диск: $($p.model)", "серийный № $($p.hardware_serial)", "том $($p.volume_serial)")
    if ($p.letter) { $parts += "сейчас буква $($p.letter):" }
    if ($p.bus_type) { $parts += [string]$p.bus_type }
    if ($p.media_type -in @('HDD','SSD')) { $parts += [string]$p.media_type }
    $identity.Text = $parts -join ' · '
}

$status = New-Object Windows.Forms.Label; $status.SetBounds(12,702,1045,40); $status.Text='Готово к работе. Выберите диск и папку результатов.'; $form.Controls.Add($status)
$log = New-Object Windows.Forms.TextBox; $log.SetBounds(12,744,1045,120); $log.Multiline=$true; $log.ScrollBars='Vertical'; $log.ReadOnly=$true; $log.Font=New-Object Drawing.Font('Consolas',9); $log.Anchor='Top,Bottom,Left,Right'; $form.Controls.Add($log)
$timer = New-Object Windows.Forms.Timer; $timer.Interval=1000
function Update-Worker {
    try {
        $text = (Read-LiveLog $script:stdout) + (Read-LiveLog $script:stderr)
        $text = $text.Replace('JOB (save this path for resume/export):','Папка задания для продолжения и экспорта:')
        if ($log.Text -ne $text) { $log.Text=$text; $log.SelectionStart=$log.TextLength; $log.ScrollToCaret() }
        Show-Progress
        if ($script:worker.HasExited) {
            $script:worker.WaitForExit()
            $timer.Stop()
            if ($script:worker.ExitCode -eq 0 -and $script:lastUnread -gt 0) { $status.ForeColor = [Drawing.Color]::DarkOrange; $status.Text="Сканирование завершено, но $($script:lastUnread) файл(ов) не удалось прочитать (обычно — нет доступа). Список и причины — в журнале ниже и в log.txt; после исправления доступа продолжите сканирование: дочитаются только они." }
            elseif ($script:worker.ExitCode -eq 0) { $status.ForeColor = [Drawing.Color]::DarkGreen; $status.Text='Операция завершена успешно. Журнал задания — log.txt в его папке; журналы окна — в «_Журналы окна» папки результатов.' }
            elseif ($script:stopping) { $status.ForeColor = [Drawing.Color]::DarkOrange; $status.Text='Сканирование остановлено. Чтобы продолжить, выберите диск и нажмите «Начать сканирование» — программа предложит продолжить.' }
            else { $status.ForeColor = [Drawing.Color]::DarkRed; $status.Text='Операция остановлена с ошибкой. Подробности ниже; готовые хеши сохранены.' }
            if (-not $IntegrationTest -and $script:operation -match '^(start|resume)') { Refresh-Disks }
        }
    } catch {
        if ($IntegrationTest) { throw }
        $status.Text='Не удалось обновить журнал. Сканирование может продолжаться. Подробности: '+$_.Exception.Message
    }
}
$timer.Add_Tick({ Update-Worker })
$form.Add_FormClosing({
    param($sender,$event)
    if (Busy) { $event.Cancel=$true; [Windows.Forms.MessageBox]::Show('Сначала нажмите «Остановить с сохранением» и дождитесь остановки.','Идёт работа') | Out-Null }
})
if ($IntegrationTest) {
    $script:testFolder = Join-Path ([IO.Path]::GetTempPath()) ('HDD GUI тест '+[guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($testFolder)
    $script:testApp = Join-Path $testFolder 'worker.py'
    [IO.File]::WriteAllText($script:testApp, @'
import argparse, json, pathlib, sys, time
p=argparse.ArgumentParser(); p.add_argument('--stop-file'); p.add_argument('--progress-file'); p.add_argument('--mode'); p.add_argument('--folder'); a=p.parse_args()
assert pathlib.Path(a.folder).is_dir(), a.folder
pathlib.Path(a.progress_file).write_text(json.dumps({'phase': 'hashing', 'phase_title': 'Этап 2 из 2: контрольные суммы', 'disk_id': 'HDD99',
    'percent': 42.5, 'bytes_done': 425e9, 'bytes_total': 1e12, 'files_done': 10, 'files_total': 20, 'rate_bytes_per_second': 1e8,
    'eta_seconds': 5400, 'elapsed_seconds': 3600, 'model': 'Тестовый диск', 'hardware_serial': 'S1', 'volume_serial': 'V1',
    'letter': 'Z', 'bus_type': 'USB', 'media_type': 'HDD'}, ensure_ascii=False), encoding='utf-8')
print('Журнал работает: готовых хешей=5', flush=True)
print('Диагностическое сообщение', file=sys.stderr, flush=True)
for i in range(50):
    if pathlib.Path(a.stop_file).exists():
        print('Остановлено с сохранением', flush=True)
        sys.exit(2)
    time.sleep(.1)
sys.exit(0 if a.mode == 'complete' else 3)
'@, (New-Object Text.UTF8Encoding($false)))
    try {
        $form.Show()
        [Windows.Forms.Application]::DoEvents()
        foreach ($mode in @('complete','error','stop')) {
            Launch @('--mode',$mode,'--folder',($testFolder+'\')) ('test_'+$mode)
            $deadline = [DateTime]::Now.AddSeconds(20)
            $sawLiveOutput = $false
            while (Busy) {
                if ([DateTime]::Now -gt $deadline) { throw 'Integration worker timeout' }
                Start-Sleep -Milliseconds 100
                Update-Worker
                if ($log.Text.Contains('готовых хешей=5') -and $log.Text.Contains('Диагностическое сообщение')) {
                    $sawLiveOutput=$true
                    if ($mode -eq 'stop') { $stop.PerformClick() }
                }
            }
            Update-Worker
            if (-not $sawLiveOutput) { throw 'No live stdout/stderr while worker was running' }
            if ($bar.Value -ne 425) { throw "Progress bar not updated: $($bar.Value)" }
            if (-not $eta.Text.Contains('1 ч 30 мин') -or -not $identity.Text.Contains('буква Z:')) { throw "Forecast/identity missing: $($eta.Text) | $($identity.Text)" }
            $expected = @{complete=0; error=3; stop=2}[$mode]
            if ($script:worker.ExitCode -ne $expected) { throw "Wrong exit code for ${mode}: $($script:worker.ExitCode). Log: $($log.Text)" }
            if ($mode -eq 'stop' -and -not $status.Text.Contains('Сканирование остановлено')) { throw 'Stop status missing' }
            Write-Output "PASS: $mode; live UTF-8 stdout/stderr, progress 42.5%, forecast '$($eta.Text)', exit=$expected"
        }
    } finally {
        $timer.Stop()
        if (Busy) { [IO.File]::WriteAllText($script:stopFile,'stop'); [void]$script:worker.WaitForExit(5000) }
        $form.Dispose()
        # Only our exact unique temporary test directory is removed.
        if (-not (Busy)) { [IO.Directory]::Delete($testFolder,$true) }
    }
} elseif ($SmokeTest) {
    $fixture = New-Object Windows.Forms.ListViewItem('E:  Тестовый архив')
    foreach ($value in @('Тестовый HDD','2 000 ГБ','100 ГБ','HDD','USB','—')) { [void]$fixture.SubItems.Add($value) }
    [void]$list.Items.Add($fixture)
    [pscustomobject]@{DiskRows=$list.Items.Count; Columns=$list.Columns.Count; Controls=$form.Controls.Count; OutputChooser=$browse.Text; ScanButton=$start.Text} | ConvertTo-Json -Compress
    $form.Dispose()
} else {
    $form.Add_Shown({ Refresh-Disks })
    [void]$form.ShowDialog()
}
