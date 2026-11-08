#Requires -Version 5.1
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Release-Helpers.ps1')
$cpu=@{name='llama-b12110-bin-win-cpu-x64.zip';browser_download_url='https://github.com/ggml-org/llama.cpp/releases/download/b12110/llama-b12110-bin-win-cpu-x64.zip'}
$binary=@{tag_name='b12110';assets=@($cpu,@{name='llama-b12110-bin-win-cpu-arm64.zip'},@{name='llama-b12110-bin-win-cuda-13.4-x64.zip'})}
$stable=@{tag_name='v0.9.0';assets=@(@{name='nightly-tag.txt';browser_download_url='https://github.com/ggml-org/llama.cpp/releases/download/v0.9.0/nightly-tag.txt'})}
$script:calls=0
function Invoke-WebRequest {param([switch]$UseBasicParsing,$Uri,$Headers) $script:calls++;return @{Content=[Text.Encoding]::UTF8.GetBytes("b12110`n")}}
function Invoke-RestMethod {param($Uri,$Headers) if($Uri -ne 'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b12110'){throw 'Unexpected endpoint'};$script:calls++;return $binary}
$result=Resolve-CpuRelease -Release $binary -Headers @{}
if($result.asset.name -ne $cpu.name -or $script:calls -ne 0){throw 'Direct CPU selection failed'}
$result=Resolve-CpuRelease -Release $stable -Headers @{}
if($result.release.tag_name -ne 'b12110' -or $result.asset.name -ne $cpu.name -or $script:calls -ne 2){throw 'Stable pointer resolution failed'}
function Assert-Rejected([object]$Release){$rejected=$false;try{Resolve-CpuRelease -Release $Release -Headers @{}|Out-Null}catch{$rejected=$true};if(!$rejected){throw 'Unsafe or ambiguous release was accepted'}}
Assert-Rejected @{tag_name='b1';assets=@($cpu,$cpu)}
Assert-Rejected @{tag_name='b1';assets=@(@{name='llama-b1-bin-win-cpu-arm64.zip'})}
Assert-Rejected @{tag_name='v1';assets=@(@{name='nightly-tag.txt';browser_download_url='https://example.com/nightly-tag.txt'})}
function Invoke-WebRequest {param([switch]$UseBasicParsing,$Uri,$Headers) return @{Content='../unexpected'}}
Assert-Rejected $stable
Write-Host 'Passed: direct CPU x64 release, stable v0.9.0 -> b12110 pointer, no ARM/CUDA selection, ambiguity/foreign URL/invalid tag rejection. No network calls.'
