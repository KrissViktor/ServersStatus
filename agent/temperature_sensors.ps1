#Requires -Version 5.1
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$items=New-Object 'System.Collections.Generic.List[object]'
# Read only the existing Windows ACPI provider. No hardware drivers or helpers.
try{
    Get-CimInstance -Namespace root\wmi -ClassName MSAcpi_ThermalZoneTemperature -OperationTimeoutSec 2 -ErrorAction Stop | Select-Object -First 64 | ForEach-Object {
        $items.Add([pscustomobject]@{id=('acpi:'+([string]$_.InstanceName));label=[string]$_.InstanceName;device='ACPI thermal zone';component='ACPI';current=([double]$_.CurrentTemperature/10-273.15);source='ACPI'})
    }
}catch{}
ConvertTo-Json -InputObject @($items.ToArray()) -Depth 4 -Compress
