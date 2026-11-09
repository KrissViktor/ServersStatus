$ErrorActionPreference='Stop'
$scriptFile=Join-Path $PSScriptRoot '../agent/temperature_sensors.ps1'
function Get-CimInstance {
    param($Namespace,$ClassName,$OperationTimeoutSec,$ErrorAction)
    if($Namespace -ne 'root\wmi' -or $ClassName -ne 'MSAcpi_ThermalZoneTemperature') { throw 'Unexpected provider' }
    if($script:missing) { throw 'No ACPI sensor' }
    [pscustomobject]@{InstanceName='ACPI\zone_0';CurrentTemperature=3000}
}
$script:missing=$false
$rows=@((. $scriptFile) | ConvertFrom-Json)
if($rows.Count -ne 1 -or $rows[0].source -ne 'ACPI' -or [Math]::Abs($rows[0].current-26.85) -gt .01) { throw 'Wrong native ACPI reading' }
$script:missing=$true
$result=. $scriptFile
if($result.Trim() -ne '[]') { throw 'Unavailable sensor must return an empty array' }
Write-Output 'PASS native ACPI and unavailable sensor'
