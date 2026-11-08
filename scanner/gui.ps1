param([switch]$SmokeTest, [switch]$IntegrationTest)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$ErrorActionPreference = 'Stop'
$script:worker = $null
$script:stopping = $false
$script:progressFile = $null
$script:operation = ''
$AppVersion = '1.1.0'

$form = New-Object Windows.Forms.Form
$form.Text = "Анализ фото и видео на дисках — версия $AppVersion"
$form.Size = New-Object Drawing.Size(1090, 880)
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
    foreach ($dir in @(Get-ChildItem -LiteralPath $folder -Directory -ErrorAction SilentlyContinue)) {
        $file = Join-Path $dir.FullName 'job.json'
        if (-not (Test-Path -LiteralPath $file)) { continue }
        try {
            $job = Read-Json $file
            $state = 'не завершён'
            $resultFile = Join-Path $dir.FullName 'result.json'
            if (Test-Path -LiteralPath $resultFile) { $state = Status-Text (Read-Json $resultFile).status }
            [void]$found.Add([pscustomobject]@{Path=$dir.FullName; DiskId=[string]$job.disk_id; Serial=[string]$job.record.hardware_serial
                Bytes=[int64]$job.record.physical_bytes; VolumeSerial=[string]$job.record.volume_serial; State=$state})
        } catch { }
    }
    return ,$found
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
        $serials = @{}
        foreach ($l in @(Get-CimInstance Win32_LogicalDisk -ErrorAction SilentlyContinue)) { if ($l.DeviceID) { $serials[$l.DeviceID.Substring(0,1)] = [string]$l.VolumeSerialNumber } }
        foreach ($p in @(Get-Partition | Where-Object DriveLetter)) {
            try {
                $d = Get-Disk -Number $p.DiskNumber
                $v = Get-Volume -DriveLetter $p.DriveLetter
                $letter = [string]$p.DriveLetter
                $serial = ([string]$d.SerialNumber).Trim()
                $type = 'Не определён'
                $match = @($physical | Where-Object { ([string]$_.SerialNumber).Trim() -eq $serial -and $_.Size -eq $d.Size })
                if ($match.Count -eq 1 -and [string]$match[0].MediaType -in @('HDD','SSD')) { $type = [string]$match[0].MediaType }
                $prior = @($jobs | Where-Object { $_.Serial -eq $serial -and $_.Bytes -eq [int64]$d.Size -and $_.VolumeSerial -eq $serials[$letter] })
                $seen = '—'
                if ($prior.Count -gt 0) { $seen = ($prior | ForEach-Object { "$($_.DiskId): $($_.State)" }) -join '; ' }
                $item = New-Object Windows.Forms.ListViewItem("${letter}:  $($v.FileSystemLabel)")
                foreach ($value in @([string]$d.FriendlyName, ('{0:N0} ГБ' -f ($v.Size/1e9)), ('{0:N0} ГБ' -f ($v.SizeRemaining/1e9)), $type, [string]$d.BusType, $seen)) { [void]$item.SubItems.Add($value) }
                $item.Tag = [pscustomobject]@{Letter=$letter; Serial=$serial; System=($d.IsBoot -or $d.IsSystem); Prior=$prior}
                if ($item.Tag.System) { $item.Text += ' [системный]'; $item.ForeColor = [Drawing.Color]::Gray }
                elseif ($prior.Count -gt 0) { $item.ForeColor = [Drawing.Color]::DarkGreen }
                [void]$list.Items.Add($item)
            } catch { }
        }
    } catch { Failure $_.Exception.Message }
    finally { $form.UseWaitCursor = $false }
}
$refresh = Add-Button $g1 'Обновить список дисков' 12 204 230 { Refresh-Disks }
$null = Add-Label $g1 'Диск узнаётся по серийному номеру, а не по букве. Зелёным — диски, уже сканированные в выбранной папке.' 255 212 775

# 2. Parameters
$g2 = Add-Group '2. Параметры' 12 262 1045 100
$null = Add-Label $g2 'Номер диска в общем реестре:' 12 30 240
$id = New-Object Windows.Forms.TextBox; $id.SetBounds(255,27,110,28); $id.Text='HDD03'; $id.Font=$form.Font; $g2.Controls.Add($id)
$null = Add-Label $g2 'HDD01 и HDD02 заняты. Один номер — только одному физическому диску.' 380 30 650
$null = Add-Label $g2 'Папка результатов:' 12 64 240
$output = New-Object Windows.Forms.TextBox; $output.SetBounds(255,61,620,28); $output.Font=$form.Font
$output.Text = Join-Path $env:LOCALAPPDATA 'HDDScanner\results'; $g2.Controls.Add($output)
$browse = Add-Button $g2 'Выбрать папку…' 885 57 147 { $p=Folder 'Папка результатов на внутреннем диске'; if ($p) { $output.Text=$p; Refresh-Disks } }

# 3. Actions
$g3 = Add-Group '3. Действия' 12 368 1045 104
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
    $logs = Join-Path $env:LOCALAPPDATA 'HDDScanner\logs'
    if ($IntegrationTest) { $logs = Join-Path $script:testFolder 'logs' }
    [void][IO.Directory]::CreateDirectory($logs)
    # Readable names: date, operation and disk number, plus a short unique suffix.
    $token = (Get-Date -Format 'yyyy-MM-dd_HH-mm-ss') + '_' + $label + '_' + [guid]::NewGuid().ToString('N').Substring(0,6)
    $script:stdout = Join-Path $logs ($token+'.out.txt')
    $script:stderr = Join-Path $logs ($token+'.err.txt')
    $script:stopFile = Join-Path $logs ($token+'.stop')
    $script:progressFile = Join-Path $logs ($token+'.progress.json')
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
            $text = "Этот диск уже сканировался (найден по серийному номеру, буква не важна):`n`nНомер: $($p.DiskId)`nСостояние: $($p.State)`nПапка: $($p.Path)`n`nДа — продолжить это задание (готовые хеши сохранятся).`nНет — начать сканирование заново под тем же номером.`nОтмена — ничего не делать."
            $answer = [Windows.Forms.MessageBox]::Show($text,'Диск уже знаком','YesNoCancel','Warning')
            if ($answer -eq 'Yes') { Launch @('resume',$p.Path) ('resume_'+$p.DiskId); return }
            if ($answer -ne 'No') { return }
            if ($id.Text -ne $p.DiskId) { $id.Text = $p.DiskId; throw "Этому диску уже назначен номер $($p.DiskId). Номер подставлен в поле; нажмите «Начать сканирование» ещё раз." }
        }
        if ($id.Text -notmatch '^HDD[0-9]{2,}$' -or [int]$id.Text.Substring(3) -lt 3) { throw 'Укажите назначенный номер, например HDD03. HDD01 и HDD02 уже заняты.' }
        $known = Get-Jobs $output.Text
        $taken = @($known | Where-Object { $_.DiskId -eq $id.Text -and $_.Serial -ne $disk.Serial })
        if ($taken.Count -gt 0) { throw "Номер $($id.Text) уже назначен другому диску (папка $($taken[0].Path)). Выберите другой номер." }
        $message = "Диск: $($selected.Text)`nМодель: $($selected.SubItems[1].Text)`nСерийный номер: $($disk.Serial)`nНомер архива: $($id.Text)`nРезультаты: $($output.Text)`n`nБудут прочитаны метаданные и рассчитаны SHA-256 фото/видео от 1 МиБ. Файлы на диске не изменяются. Начать?"
        if ([Windows.Forms.MessageBox]::Show($message,'Проверьте выбранный диск','YesNo','Question') -eq 'Yes') {
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
    try { if (Busy) { throw 'Сначала дождитесь завершения операции.' }; $job=Folder 'Папка завершённого задания'; if ($job) { $dest=Folder 'Папка назначения на флешке'; if ($dest) { Launch @('export',$job,$dest) 'export' } } } catch { Failure $_.Exception.Message }
}
$import = Add-Button $g3 'Импорт с флешки…' 272 62 250 {
    try { if (Busy) { throw 'Сначала дождитесь завершения операции.' }; $job=Folder 'Папка экспортированного задания на флешке'; if ($job) { $dest=Folder 'Локальная папка импорта на основном компьютере'; if ($dest) { Launch @('import',$job,$dest) 'import' } } } catch { Failure $_.Exception.Message }
}
$open = Add-Button $g3 'Открыть папку результатов' 532 62 250 {
    try { if (Test-Path -LiteralPath $output.Text -PathType Container) { Start-Process explorer.exe -ArgumentList ('"'+$output.Text+'"') } } catch { Failure $_.Exception.Message }
}

# 4. Progress
$g4 = Add-Group 'Ход работы' 12 478 1045 182
$phase = Add-Label $g4 'Ожидание запуска' 12 26 1020 30 $big
$bar = New-Object Windows.Forms.ProgressBar; $bar.SetBounds(12,62,880,30); $bar.Minimum=0; $bar.Maximum=1000; $g4.Controls.Add($bar)
$percent = Add-Label $g4 '' 902 62 130 30 $big
$amount = Add-Label $g4 '' 12 100 1020 24
$eta = Add-Label $g4 '' 12 126 1020 24 $bold
$identity = Add-Label $g4 '' 12 152 1020 24
function Reset-Progress {
    $phase.Text = 'Запуск…'; $bar.Value = 0; $percent.Text = ''; $amount.Text = ''; $eta.Text = ''; $identity.Text = ''
}
function Show-Progress {
    if (-not $script:progressFile -or -not (Test-Path -LiteralPath $script:progressFile)) { return }
    $raw = Read-LiveLog $script:progressFile
    if (-not $raw) { return }
    try { $p = $raw | ConvertFrom-Json } catch { return }
    $phase.Text = ([string]$p.phase_title) + '  —  ' + ([string]$p.disk_id)
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

$status = New-Object Windows.Forms.Label; $status.SetBounds(12,666,1045,40); $status.Text='Готово к работе. Выберите диск и папку результатов.'; $form.Controls.Add($status)
$log = New-Object Windows.Forms.TextBox; $log.SetBounds(12,708,1045,120); $log.Multiline=$true; $log.ScrollBars='Vertical'; $log.ReadOnly=$true; $log.Font=New-Object Drawing.Font('Consolas',9); $log.Anchor='Top,Bottom,Left,Right'; $form.Controls.Add($log)
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
            if ($script:worker.ExitCode -eq 0) { $status.ForeColor = [Drawing.Color]::DarkGreen; $status.Text='Операция завершена успешно. Итог — в журнале ниже; полный журнал сохранён и в папке задания (log.txt).' }
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
