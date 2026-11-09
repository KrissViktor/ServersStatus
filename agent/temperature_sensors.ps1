#Requires -Version 5.1
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$items=New-Object 'System.Collections.Generic.List[object]'
foreach($namespace in @('root\LibreHardwareMonitor','root\OpenHardwareMonitor')){
    try{
        $sensors=@(Get-CimInstance -Namespace $namespace -ClassName Sensor -Filter "SensorType='Temperature'" -OperationTimeoutSec 2 -ErrorAction Stop | Select-Object -First 512)
        if(!$sensors.Count){continue}
        $hardware=@{}
        try{Get-CimInstance -Namespace $namespace -ClassName Hardware -OperationTimeoutSec 2 -ErrorAction Stop | ForEach-Object {$hardware[[string]$_.Identifier]=$_}}catch{}
        foreach($sensor in $sensors){
            $parent=$hardware[[string]$sensor.Parent]
            $items.Add([pscustomobject]@{id=($namespace+':'+[string]$sensor.Identifier);label=[string]$sensor.Name;device=if($parent){[string]$parent.Name}else{[string]$sensor.Parent};component=if($parent){[string]$parent.HardwareType}else{''};current=$sensor.Value;source=$namespace})
        }
        break # Prefer one hardware monitor to avoid duplicate physical sensors.
    }catch{}
}
try{
    Get-CimInstance -Namespace root\wmi -ClassName MSAcpi_ThermalZoneTemperature -OperationTimeoutSec 2 -ErrorAction Stop | Select-Object -First 64 | ForEach-Object {
        $items.Add([pscustomobject]@{id=('acpi:'+([string]$_.InstanceName));label=[string]$_.InstanceName;device='ACPI thermal zone';component='ACPI';current=([double]$_.CurrentTemperature/10-273.15);source='ACPI'})
    }
}catch{}
ConvertTo-Json -InputObject @($items.ToArray()) -Depth 4 -Compress
