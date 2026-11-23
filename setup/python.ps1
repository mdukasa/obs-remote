# Find-Python: the newest Python 3.8+ on this PC (not the Microsoft Store stub), or $null.
# Dot-sourced by install.ps1 and uninstall.ps1. Keep this file ASCII-only (Windows PowerShell 5.1).
function Find-Python {
    $cands = @()
    foreach ($cmd in 'py', 'python') {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notmatch 'WindowsApps') {
            try {
                $args2 = @(); if ($cmd -eq 'py') { $args2 = @('-3') }
                $exe = & $c.Source @args2 -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { $cands += $exe.Trim() }
            } catch {}
        }
    }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object FullName
    foreach ($p in $cands) {
        if (Test-Path $p) {
            $v = & $p -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -and [version]$v -ge [version]'3.8') { return $p }
        }
    }
    return $null
}
