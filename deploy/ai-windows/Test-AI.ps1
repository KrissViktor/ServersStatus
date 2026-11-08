#Requires -Version 5.1
#Requires -RunAsAdministrator
param([string]$Question='Ответь коротко по-русски: для чего нужен мониторинг серверов?')
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI'
$key=[IO.File]::ReadAllText("$root\api-key.txt").Trim()
$headers=@{Authorization='Bearer '+$key}
try{$health=Invoke-RestMethod -Uri 'http://127.0.0.1:8091/health' -Headers $headers -TimeoutSec 10}catch{throw 'Model is unavailable/loading/paused. Check logs\service.log and Get-Service ServersStatusAI.'}
Write-Host ('Health: '+$health.status)
$body=@{model='serversstatus-local';messages=@(@{role='system';content='Отвечай по-русски. Не утверждай, что имеешь интернет или доступ к данным сервера.'},@{role='user';content=$Question});max_tokens=256;temperature=0.6;stream=$false} | ConvertTo-Json -Depth 8
$watch=[Diagnostics.Stopwatch]::StartNew()
$result=Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8091/v1/chat/completions' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 600
$watch.Stop()
Write-Output $result.choices[0].message.content
Write-Host ('Elapsed: '+[Math]::Round($watch.Elapsed.TotalSeconds,1)+' s; completion tokens: '+$result.usage.completion_tokens)
if($result.timings.predicted_per_second){Write-Host ('Generation: '+[Math]::Round($result.timings.predicted_per_second,2)+' tokens/s')}
