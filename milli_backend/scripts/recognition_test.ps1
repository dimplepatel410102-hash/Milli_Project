<#
.SYNOPSIS
  End-to-end face recognition check against a running backend (MILLI_FACE_RECOGNITION=true).

  Enrolls two photos as TEST-A and TEST-B, uploads three probe photos to /api/v1/camera/capture
  and checks the recognition result, then deletes TEST-A and TEST-B again.
  Defaults to the public-domain portraits in tests\face_photos (scripts\download_test_faces.py).

.EXAMPLE
  .\scripts\recognition_test.ps1 -DeviceId milli-cam-01 -DeviceKey "<key>"
.EXAMPLE
  .\scripts\recognition_test.ps1 -DeviceId milli-cam-01 -DeviceKey "<key>" `
      -Person1 me.jpg -Person2 colleague.jpg -Probe1 me2.jpg -Probe2 colleague2.jpg -Stranger other.jpg
#>
param(
    [Parameter(Mandatory = $true)] [string]$DeviceKey,
    [string]$DeviceId = "milli-cam-01",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Person1 = "",
    [string]$Person2 = "",
    [string]$Probe1 = "",
    [string]$Probe2 = "",
    [string]$Stranger = ""
)

$photos = Join-Path (Split-Path -Parent $PSScriptRoot) "tests\face_photos"
if (-not $Person1) { $Person1 = Join-Path $photos "person_a.jpg" }
if (-not $Person2) { $Person2 = Join-Path $photos "person_b.jpg" }
if (-not $Probe1) { $Probe1 = $Person1 }
if (-not $Probe2) { $Probe2 = $Person2 }
if (-not $Stranger) { $Stranger = Join-Path $photos "person_c.jpg" }

$auth = @("-H", "X-Device-ID: $DeviceId", "-H", "X-Device-Key: $DeviceKey")
$script:failures = 0

function Invoke-Api([string[]]$CurlArgs) {
    $output = @(& curl.exe -s -w "`n%{http_code}" @CurlArgs)
    $body = if ($output.Count -gt 1) { $output[0..($output.Count - 2)] -join "" } else { "" }
    [pscustomobject]@{ Code = [int]$output[-1]; Json = if ($body) { $body | ConvertFrom-Json } else { $null } }
}

function Report([bool]$Ok, [string]$Text) {
    if ($Ok) { "PASS  $Text" } else { "FAIL  $Text"; $script:failures++ }
}

foreach ($id in "TEST-A", "TEST-B") {
    Invoke-Api (@("-X", "DELETE", "$BaseUrl/api/v1/faces/$id") + $auth) | Out-Null
}

foreach ($item in @(@("TEST-A", $Person1), @("TEST-B", $Person2))) {
    $r = Invoke-Api (@("-X", "POST", "$BaseUrl/api/v1/faces/enroll?employee_id=$($item[0])",
                       "--data-binary", "@$($item[1])") + $auth)
    $detail = if ($r.Code -eq 200) { $r.Json.message } else { "HTTP $($r.Code) $($r.Json.error.code): $($r.Json.error.message)" }
    Report ($r.Code -eq 200) ("enroll {0,-7} {1}" -f $item[0], $detail)
}

foreach ($probe in @(@($Probe1, "TEST-A"), @($Probe2, "TEST-B"), @($Stranger, $null))) {
    $r = Invoke-Api (@("-X", "POST", "$BaseUrl/api/v1/camera/capture", "--data-binary", "@$($probe[0])") + $auth)
    if ($r.Code -ne 200) {
        Report $false ("capture {0}: HTTP {1} {2}" -f (Split-Path -Leaf $probe[0]), $r.Code, $r.Json.error.message)
        continue
    }
    $rec = $r.Json.recognition
    $ok = if ($probe[1]) { $rec.status -eq "recognized" -and $rec.employee_id -eq $probe[1] } else { $rec.label -eq "Unknown" }
    $expected = if ($probe[1]) { $probe[1] } else { "Unknown" }
    Report $ok ("capture {0,-14} expected {1,-7} got label={2} employee={3} similarity={4} ({5})" -f `
        (Split-Path -Leaf $probe[0]), $expected, $rec.label, $rec.employee_id, $rec.similarity, $rec.status)
}

foreach ($id in "TEST-A", "TEST-B") {
    Invoke-Api (@("-X", "DELETE", "$BaseUrl/api/v1/faces/$id") + $auth) | Out-Null
}
if ($script:failures -gt 0) { "`n$($script:failures) check(s) failed"; exit 1 } else { "`nAll checks passed" }
