param([ValidateSet('info','scan','install')][string]$Action='info')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$session=New-Object -ComObject Microsoft.Update.Session
$searcher=$session.CreateUpdateSearcher()
function Stamp($date) { if ($date) { return [DateTimeOffset]::new($date.ToUniversalTime()).ToUnixTimeSeconds() }; return $null }
if ($Action -eq 'info') {
    $history=@(); $hotfixes=@(); $historyStatus='unavailable'; $hotfixStatus='unavailable'
    try {
        $count=$searcher.GetTotalHistoryCount()
        if ($count -gt 0) {
            $history=@($searcher.QueryHistory(0,[Math]::Min($count,100)) | Where-Object {$_.Operation -eq 1} | Select-Object -First 10 | ForEach-Object {
                @{title=$_.Title;installed_at=(Stamp $_.Date);result=[int]$_.ResultCode}
            })
        }
        $historyStatus='available'
    } catch {}
    try {
        $hotfixes=@(Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 10 | ForEach-Object {
            @{kb=$_.HotFixID;description=$_.Description;installed_at=(Stamp $_.InstalledOn)}
        })
        $hotfixStatus='available'
    } catch {}
    @{history=$history;hotfixes=$hotfixes;history_status=$historyStatus;hotfix_status=$hotfixStatus} | ConvertTo-Json -Depth 5 -Compress
    exit 0
}
# Respect the machine's configured update source (including WSUS). Drivers and optional updates are excluded.
$result=$searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
$updates=New-Object -ComObject Microsoft.Update.UpdateColl
$titles=@();$availableCount=0
foreach ($update in $result.Updates) {
    if ($update.BrowseOnly -or $update.InstallationBehavior.CanRequestUserInput) { continue }
    if (@($update.Categories | Where-Object {$_.CategoryID -eq '3689bdc8-b205-4af4-8d4a-a63924c5e9d5'}).Count -gt 0) { continue }
    $availableCount++
    if ($titles.Count -lt 20) {$titles+=@{title=$update.Title.Substring(0,[Math]::Min(300,$update.Title.Length));size_bytes=[long]$update.MaxDownloadSize}}
    if ($Action -eq 'install') {
        if (-not $update.EulaAccepted) {$update.AcceptEula()}
        [void]$updates.Add($update)
    }
}
if ($Action -eq 'scan') { @{available=$titles;count=$availableCount} | ConvertTo-Json -Depth 5 -Compress; exit 0 }
if ($updates.Count -eq 0) { @{count=0;installed=0;failed=0;reboot_required=$false} | ConvertTo-Json -Compress; exit 0 }
$downloader=$session.CreateUpdateDownloader();$downloader.Updates=$updates
$download=$downloader.Download()
$ready=New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($update in $updates) { if ($update.IsDownloaded) {[void]$ready.Add($update)} }
$installed=0;$failed=$updates.Count-$ready.Count;$reboot=$false
if ($ready.Count -gt 0) {
    $installer=$session.CreateUpdateInstaller();$installer.Updates=$ready
    $installation=$installer.Install();$reboot=$installation.RebootRequired
    for ($i=0;$i -lt $ready.Count;$i++) {
        if ($installation.GetUpdateResult($i).ResultCode -eq 2) {$installed++} else {$failed++}
    }
}
@{count=$updates.Count;installed=$installed;failed=$failed;reboot_required=$reboot} | ConvertTo-Json -Compress
