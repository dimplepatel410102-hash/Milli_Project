<#
.SYNOPSIS
  Exercises a running Milli backend with synthetic images (no camera needed).

.EXAMPLE
  .\scripts\smoke_test.ps1 -DeviceKey "<api key printed by app.tools.device_key>"
#>
param(
    [Parameter(Mandatory = $true)] [string]$DeviceKey,
    [string]$DeviceId = "dev-cam-01",
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$root = Split-Path -Parent $PSScriptRoot
$samples = Join-Path $root "samples"
if (-not (Test-Path (Join-Path $samples "truncated.jpg"))) {
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "make_sample_images.py") | Out-Null
}

$registerJson = Join-Path $env:TEMP "milli-register.json"
'{"firmware_version":"0.1.0","hardware_model":"ESP32-S3-N16R8"}' | Set-Content -Encoding ascii $registerJson

$capture = "$BaseUrl/api/v1/camera/capture"
$auth = @("-H", "X-Device-ID: $DeviceId", "-H", "X-Device-Key: $DeviceKey")
$script:failures = 0

function Test-Call([string]$Name, [int]$Expected, [string[]]$CurlArgs) {
    $output = & curl.exe -s -w "`n%{http_code}" @CurlArgs
    $lines = @($output)
    $code = [int]$lines[-1]
    $body = if ($lines.Count -gt 1) { ($lines[0..($lines.Count - 2)] -join " ") } else { "" }
    if ($body.Length -gt 110) { $body = $body.Substring(0, 110) + "..." }
    if ($code -eq $Expected) { $status = "PASS" } else { $status = "FAIL"; $script:failures++ }
    "{0}  {1,-34} expected {2} got {3}  {4}" -f $status, $Name, $Expected, $code, $body
}

Test-Call "health"                      200 @("$BaseUrl/health")
Test-Call "swagger docs"                200 @("-o", "NUL", "$BaseUrl/docs")
Test-Call "register device"             200 (@("-X", "POST", "$BaseUrl/api/v1/devices/register", "-H", "Content-Type: application/json", "--data-binary", "@$registerJson") + $auth)
Test-Call "capture multipart JPEG"      200 (@("-X", "POST", $capture, "-F", "image=@$samples\sample.jpg") + $auth)
Test-Call "capture raw PNG"             200 (@("-X", "POST", $capture, "-H", "Content-Type: application/octet-stream", "--data-binary", "@$samples\sample.png") + $auth)
Test-Call "capture raw BMP"             200 (@("-X", "POST", $capture, "-H", "Content-Type: image/bmp", "--data-binary", "@$samples\sample.bmp") + $auth)
Test-Call "wrong API key"               401 @("-X", "POST", $capture, "-H", "X-Device-ID: $DeviceId", "-H", "X-Device-Key: wrong", "--data-binary", "@$samples\sample.jpg")
Test-Call "missing credentials"         401 @("-X", "POST", $capture, "--data-binary", "@$samples\sample.jpg")
Test-Call "not an image"                415 (@("-X", "POST", $capture, "--data-binary", "@$samples\not_an_image.txt") + $auth)
Test-Call "GIF (not allowed by default)" 415 (@("-X", "POST", $capture, "--data-binary", "@$samples\sample.gif") + $auth)
Test-Call "truncated JPEG"              422 (@("-X", "POST", $capture, "--data-binary", "@$samples\truncated.jpg") + $auth)
Test-Call "empty body"                  400 (@("-X", "POST", $capture, "-H", "Content-Type: application/octet-stream") + $auth)
Test-Call "multipart without 'image'"   400 (@("-X", "POST", $capture, "-F", "photo=@$samples\sample.jpg") + $auth)

Remove-Item $registerJson -ErrorAction SilentlyContinue
if ($script:failures -gt 0) { "`n$($script:failures) check(s) failed"; exit 1 } else { "`nAll checks passed" }
