param(
    [string]$Directory = $PSScriptRoot,
    [string]$ExpectedHash = 'DE85DB6B8F1E38522428E88E33C0E2CB760C37073762E700F88C45723C0CFF96',
    [string]$ReuseCertificate = '',
    [int[]]$CodeByteOffsets = @(0xA15D, 0xA2A9)
)
$ErrorActionPreference = 'Stop'
$directory = (Resolve-Path -LiteralPath $Directory).Path
$unsignedPath = Join-Path $directory 'UsbNcm.patched.sys'
$signedPath = Join-Path $directory 'UsbNcm.test.sys'
$signingPath = Join-Path $directory 'signing.json'
$tool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe'

if ((Get-FileHash -LiteralPath $unsignedPath -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'The unsigned patched file does not match the reviewed patch.'
}
if ((Test-Path -LiteralPath $signedPath) -or (Test-Path -LiteralPath $signingPath)) {
    throw 'Signing artifacts already exist. Inspect them before signing again.'
}

# The private key stays in the current user's certificate store and is not exported.
if ($ReuseCertificate) {
    $certificate = Get-Item -LiteralPath ('Cert:\CurrentUser\My\' + $ReuseCertificate)
    if (-not $certificate.HasPrivateKey) { throw 'The test certificate has no private key.' }
}
else {
    $certificate = New-SelfSignedCertificate -Type CodeSigningCert `
        -Subject 'CN=UsbNcm NTB Fix - Local Test Only' `
        -FriendlyName 'UsbNcm NTB boundary fix local test' `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
        -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddYears(1)
}
Copy-Item -LiteralPath $unsignedPath -Destination $signedPath
$signOutput = & $tool sign /v /fd SHA256 /ph /s My /sha1 $certificate.Thumbprint $signedPath 2>&1
$signResult = $LASTEXITCODE
$signOutput | Set-Content -LiteralPath (Join-Path $directory 'signing.log') -Encoding UTF8
if ($signResult -ne 0) { throw "SignTool failed: $signResult" }

$null = Export-Certificate -Cert $certificate -FilePath (Join-Path $directory 'UsbNcmTest.cer')
$signature = Get-AuthenticodeSignature -LiteralPath $signedPath
if ($signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
    throw 'The signature does not identify the new test certificate.'
}

# Signing adds a certificate table and a PE checksum; it must not alter other code.
$original = [IO.File]::ReadAllBytes((Join-Path $directory 'UsbNcm.original.sys'))
$signed = [IO.File]::ReadAllBytes($signedPath)
$peOffset = [BitConverter]::ToInt32($original, 0x3C)
$optionalOffset = $peOffset + 24
$allowed = @($CodeByteOffsets)
$allowed += ($optionalOffset + 64)..($optionalOffset + 67)
$allowed += ($optionalOffset + 144)..($optionalOffset + 151)
for ($i = 0; $i -lt $original.Length; $i++) {
    if ($original[$i] -ne $signed[$i] -and $allowed -notcontains $i) {
        throw ('Signing changed unexpected image data at 0x{0:X}' -f $i)
    }
}
foreach ($offset in $CodeByteOffsets) {
    if ($signed[$offset] -ne 2 -or $original[$offset] -ne 1) { throw 'The patch is missing.' }
}

$record = [ordered]@{
    Subject = $certificate.Subject
    Thumbprint = $certificate.Thumbprint
    NotAfter = $certificate.NotAfter.ToString('o')
    SignedSha256 = (Get-FileHash -LiteralPath $signedPath -Algorithm SHA256).Hash
    UnsignedSha256 = $expectedHash
    SignatureStatusBeforeMachineTrust = [string]$signature.Status
    OriginalLength = $original.Length
    SignedLength = $signed.Length
    UnexpectedImageChanges = 0
    SignedAt = (Get-Date).ToString('o')
}
$record | ConvertTo-Json | Set-Content -LiteralPath $signingPath -Encoding UTF8
$record | ConvertTo-Json
