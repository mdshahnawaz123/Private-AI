# Exercise the actual restart branch with mocked processes only.
$auditParseTokens=$null
$auditParseErrors=$null
$auditTree=[System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot '..\start_local.ps1'),[ref]$auditParseTokens,[ref]$auditParseErrors)
if($auditParseErrors.Count) { throw 'Launcher has parse errors' }
$auditNode=$auditTree.Find({param($n)
    $n -is [System.Management.Automation.Language.IfStatementAst] -and
    $n.Extent.Text.StartsWith('if (Get-NetTCPConnection -LocalPort $settings.port')
},$true)
if(-not $auditNode) { throw 'Restart branch not found' }
$auditBranch=[scriptblock]::Create($auditNode.Extent.Text)
$auditCases=@(
    @{name='unrelated';service='other-python-app';pid=424242;stop=$false},
    @{name='missing-pid';service='expo-design-ai';pid=$null;stop=$false},
    @{name='wrong-pid';service='expo-design-ai';pid=424243;stop=$false},
    @{name='verified';service='expo-design-ai';pid=424242;stop=$true}
)
foreach($auditCase in $auditCases) {
    $script:auditStopped=$false
    $script:auditCurrent=$auditCase
    function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction)
        if(-not $script:auditStopped) { [pscustomobject]@{OwningProcess=424242} }
    }
    function Invoke-RestMethod { param($Uri,$TimeoutSec)
        [pscustomobject]@{service=$script:auditCurrent.service;pid=$script:auditCurrent.pid}
    }
    function Get-CimInstance { param($ClassName,$Filter,$ErrorAction)
        [pscustomobject]@{Name='python.exe';CommandLine='python main.py'}
    }
    function Stop-Process { param($Id,[switch]$Force,$ErrorAction)
        if($Id -ne 424242) { throw 'Wrong process was targeted' }
        $script:auditStopped=$true
    }
    function Show-LocalService { }
    $settings=[pscustomobject]@{port=8090}
    $serviceUrl='http://fixture.invalid'
    $Restart=$true
    try { & $auditBranch } catch {
        if($auditCase.stop) { throw }
    }
    if($script:auditStopped -ne $auditCase.stop) { throw "Identity test failed: $($auditCase.name)" }
}
Write-Output 'PASS: unrelated, unknown and mismatched owners survive; only verified PID is restarted (all process operations mocked).'
