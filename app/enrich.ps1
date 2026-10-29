# Reads a UTF-8 JSON list of file paths and prints, for each, its signature status, signer and a 32px PNG icon.
param([string]$ListFile)
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
$paths = Get-Content -LiteralPath $ListFile -Raw -Encoding UTF8 | ConvertFrom-Json
$out = foreach ($p in @($paths)) {
    $status = 'Unknown'; $signer = ''; $icon = ''
    $sig = Get-AuthenticodeSignature -LiteralPath $p
    if ($sig) {
        $status = [string]$sig.Status
        if ($sig.SignerCertificate) {
            $subject = $sig.SignerCertificate.Subject
            if ($subject -match 'CN="?([^",]+)') { $signer = $Matches[1] } else { $signer = $subject }
        }
    }
    try {
        $ico = [System.Drawing.Icon]::ExtractAssociatedIcon($p)
        if ($ico) {
            $bmp = $ico.ToBitmap()
            $ms = New-Object System.IO.MemoryStream
            $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
            $icon = [Convert]::ToBase64String($ms.ToArray())
            $ms.Dispose(); $bmp.Dispose(); $ico.Dispose()
        }
    } catch {}
    [pscustomobject]@{ path = $p; status = $status; signer = $signer; icon = $icon }
}
@($out) | ConvertTo-Json -Compress -Depth 3
