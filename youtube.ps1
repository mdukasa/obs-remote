# Fills in OBS's "YouTube Broadcast Setup" dialog and clicks "Create broadcast and start streaming".
# Run by youtube.py for the phone's Go live button, when OBS is signed in to a YouTube account.
#
# The phone has already saved its choices as OBS's remembered YouTube settings (SetProfileParameter), so the
# dialog opens with them filled in. This script opens the dialog with OBS's own Manage Broadcast button, checks
# that it shows those choices (setting the text boxes and tick boxes if not), and starts the broadcast.
# Drop-down lists can't be changed from outside OBS, so if one of those is wrong it cancels instead.
#
# Input (JSON in the OBS_REMOTE_YOUTUBE environment variable, which keeps emoji intact): title, description, privacy, category, latency (names as OBS shows them in English),
#                      kids, dvr (true/false)
# Output (stdout, JSON, non-ASCII as \u escapes): {"ok": true} or {"ok": false, "error": "..."}
# -DryRun fills in and checks the dialog, then cancels it (for testing without going live).
# Keep this file ASCII-only: Windows PowerShell 5 reads scripts without a BOM as the ANSI code page.

param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$IDP = $AE::AutomationIdProperty

function Out-Result($ok, $err) {
    $j = @{ ok = $ok; error = $err } | ConvertTo-Json -Compress
    [regex]::Replace($j, '[^\x00-\x7f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value }); exit 0
}

$want = $env:OBS_REMOTE_YOUTUBE | ConvertFrom-Json

$obs = Get-Process obs64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $obs) { Out-Result $false "OBS isn't open." }
$byPid = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $obs.Id)

# Search inside OBS's main window: an open drop-down list hides the dialog from a search of the whole desktop.
function Get-Main {
    $AE::RootElement.FindAll($TS::Children, $byPid) | Where-Object { $_.Current.ClassName -eq 'OBSBasic' } | Select-Object -First 1
}
function Find-Id($root, $id) { $root.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($IDP, $id))) }
function Get-Pat($el, $pat) { $el.GetCurrentPattern($pat::Pattern) }
function Invoke-Async($el) {
    # Clicking a button that opens a dialog may not return until the dialog closes, so click from another thread.
    $ps = [powershell]::Create()
    [void]$ps.AddScript({ param($e) $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }).AddArgument($el)
    [void]$ps.BeginInvoke()
}

$main = Get-Main
if (-not $main) { Out-Result $false "Can't find OBS's main window." }

$D = 'OBSApp.OBSYoutubeActions'
$F = "$D.tabWidget.qt_tabwidget_stackedwidget.ytEventCreate.scrollArea_2.qt_scrollarea_viewport.scrollAreaWidgetContents_3."

$dlg = Find-Id $main $D
if (-not $dlg) {
    $btn = Find-Id $main 'OBSApp.OBSBasic.controlsDock.OBSBasicControls.controlsFrame.broadcastButton'
    # No such button: OBS isn't signed in to YouTube (it uses a stream key), so it can simply start streaming.
    if (-not $btn -or $btn.Current.IsOffscreen) { @{ ok = $false; noAccount = $true; error = "OBS isn't signed in to YouTube." } | ConvertTo-Json -Compress; exit 0 }
    if (-not $btn.Current.IsEnabled) { Out-Result $false "OBS's Manage Broadcast button is greyed out." }
    # OBS's "No Broadcast Configured" message (left by a Start Streaming without a broadcast) has a button with
    # the same name as OBS's own: use that one. Any other OBS window in front would block the dialog: say so.
    $other = @($main.FindAll($TS::Children, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window))))
    if ($other.Count) {
        $same = $other[0].FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button))) |
            Where-Object { $_.Current.Name -eq $btn.Current.Name } | Select-Object -First 1
        if ($other.Count -gt 1 -or -not $same) { Out-Result $false ("OBS has a window open on the PC: " + $other[0].Current.Name + ". Close it and try again.") }
        $btn = $same
    }
    Invoke-Async $btn
    for ($i = 0; $i -lt 40 -and -not $dlg; $i++) { Start-Sleep -Milliseconds 250; $dlg = Find-Id $main $D }
    if (-not $dlg) { Out-Result $false "OBS's YouTube dialog didn't open." }
}

function Cancel-Dialog($why) {
    $c = Find-Id $main "$D.widget.cancelButton"
    if ($c) { (Get-Pat $c ([System.Windows.Automation.InvokePattern])).Invoke() }
    Out-Result $false $why
}

try {
    # "Create New Broadcast" tab (the first one)
    $tabs = $dlg.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)))
    if ($tabs.Count) { (Get-Pat $tabs[0] ([System.Windows.Automation.SelectionItemPattern])).Select(); Start-Sleep -Milliseconds 200 }

    $VP = [System.Windows.Automation.ValuePattern]; $TP = [System.Windows.Automation.TogglePattern]
    $SP = [System.Windows.Automation.SelectionItemPattern]
    function Field($n) { $e = Find-Id $dlg ($F + $n); if (-not $e) { Cancel-Dialog "OBS's YouTube dialog has changed (no $n). Finish on the PC." }; $e }

    foreach ($p in @(@('title', $want.title), @('description', $want.description))) {
        $e = Field $p[0]; $v = Get-Pat $e $VP
        if ($v.Current.Value -ne [string]$p[1]) { $v.SetValue([string]$p[1]) }
        if ($v.Current.Value -ne [string]$p[1]) { Cancel-Dialog "Couldn't set the $($p[0]) in OBS. Finish on the PC." }
    }
    if (-not $want.title.Trim()) { Cancel-Dialog "The title can't be empty." }

    # Drop-downs: only checkable when OBS's interface is in English; otherwise trust the remembered settings.
    $known = @{ privacyBox = @('Public', 'Unlisted', 'Private'); latencyBox = @('Normal', 'Low', 'Ultra low')
                categoryBox = @('Sports', 'Travel and Events', 'Gaming', 'People and blogs', 'Comedy', 'Entertainment', 'News and Politics',
                                'How-to and Style', 'Education', 'Science and Technology', 'Non-profits and Activism') }
    foreach ($p in @(@('privacyBox', $want.privacy, 'privacy'), @('categoryBox', $want.category, 'category'), @('latencyBox', $want.latency, 'latency'))) {
        $cur = (Get-Pat (Field $p[0]) $VP).Current.Value
        if ($known[$p[0]] -contains $cur -and $cur -ne $p[1]) { Cancel-Dialog "OBS shows $($p[2]) '$cur', not '$($p[1])'. Nothing was started; finish on the PC." }
    }

    $kid = Field ($(if ($want.kids) { 'yesMakeForKids' } else { 'notMakeForKids' }))
    $ks = Get-Pat $kid $SP; if (-not $ks.Current.IsSelected) { $ks.Select() }
    if (-not $ks.Current.IsSelected) { Cancel-Dialog "Couldn't set 'made for kids' in OBS. Finish on the PC." }

    # Tick boxes: DVR as asked; not scheduled for later (that would create the broadcast without going live);
    # Remember on, so OBS keeps these choices (they are the phone's starting point next time).
    foreach ($p in @(@('checkDVR', [bool]$want.dvr), @('checkScheduledLater', $false), @('checkRememberSettings', $true))) {
        $t = Get-Pat (Field $p[0]) $TP
        $on = $t.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
        if ($on -ne $p[1]) { $t.Toggle() }
        if (($t.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) -ne $p[1]) { Cancel-Dialog "Couldn't set $($p[0]) in OBS. Finish on the PC." }
    }

    $ok = Find-Id $dlg "$D.widget.okButton"
    if (-not $ok -or -not $ok.Current.IsEnabled) { Cancel-Dialog "OBS's 'Create broadcast and start streaming' button isn't available." }
    if ($DryRun) { (Get-Pat (Find-Id $dlg "$D.widget.cancelButton") ([System.Windows.Automation.InvokePattern])).Invoke(); Out-Result $true 'dry run: filled in and checked, then cancelled' }
    $before = @($main.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, 'QMessageBox')))).Count
    Invoke-Async $ok
} catch {
    Cancel-Dialog ("Couldn't fill in OBS's YouTube dialog: " + $_.Exception.Message)
}

# OBS now asks YouTube to create the broadcast, showing "Creating a new Live Broadcast, please wait..." (a message
# box without buttons). The dialog closes when that worked. An error is a message box with a button to dismiss it.
# OBS is busy while the dialog closes, so a check can fail half-way: just look again.
$byButton = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$byText = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Text)
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 250
    $err = $null
    try {
        $main = Get-Main
        if (-not $main) { continue }
        if (-not (Find-Id $main $D)) { Out-Result $true $null }
        $msg = @($main.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, 'QMessageBox'))))
        if ($msg.Count -gt $before) { $err = $msg | Where-Object { $_.FindFirst($TS::Descendants, $byButton) } | Select-Object -Last 1 }
        if ($err) { $text = ($err.FindAll($TS::Descendants, $byText) | ForEach-Object { $_.Current.Name } | Where-Object { $_ }) -join ' '; $title = $err.Current.Name }
    } catch { continue }
    if ($err) { Out-Result $false ("OBS says: " + $title + ". " + $text + " (The message is still open on the PC.)") }
}
Out-Result $false "OBS's YouTube dialog is still open after 45 seconds. Check the PC."
