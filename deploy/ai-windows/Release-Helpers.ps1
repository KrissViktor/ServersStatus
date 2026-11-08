#Requires -Version 5.1
function Resolve-CpuRelease {
    param([object]$Release,[hashtable]$Headers)
    for($attempt=0;$attempt -lt 2;$attempt++){
        $assets=@($Release.assets | Where-Object {$_.name -match '^llama-.*-bin-win-cpu-x64\.zip$'})
        if($assets.Count -eq 1){return @{release=$Release;asset=$assets[0]}}
        if($assets.Count -gt 1){throw 'Ambiguous Windows CPU x64 ZIP assets; specify -EngineTag explicitly'}
        $pointers=@($Release.assets | Where-Object {$_.name -eq 'nightly-tag.txt'})
        if($attempt -ne 0 -or $pointers.Count -ne 1){throw ('No Windows CPU x64 ZIP in release '+$Release.tag_name+'. Specify a binary release with -EngineTag.')}
        $url=[string]$pointers[0].browser_download_url
        $expected='https://github.com/ggml-org/llama.cpp/releases/download/'+[Uri]::EscapeDataString([string]$Release.tag_name)+'/nightly-tag.txt'
        if($url -cne $expected){throw 'Unexpected nightly pointer URL'}
        $response=Invoke-WebRequest -UseBasicParsing -Uri $url -Headers $Headers
        $tag=([string]$response.Content).Trim()
        if($tag -notmatch '^b[0-9]{1,10}$'){throw 'Invalid official nightly tag'}
        Write-Host ('Release '+$Release.tag_name+' points to binary release '+$tag)
        $Release=Invoke-RestMethod -Uri ('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/'+$tag) -Headers $Headers
    }
    throw 'Could not resolve Windows CPU release'
}
