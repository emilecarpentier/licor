# Offline diagnostic only. No screen capture, game API, or live recommendations.
param(
    [Parameter(Mandatory = $true)][string]$FramesDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][double[]]$Seconds,
    [ValidateSet('v1', 'v2')][string]$Reader = 'v1'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Use Windows PowerShell 5.1 (powershell.exe), not pwsh.'
}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name.StartsWith('IAsyncOperation') -and
    $_.GetGenericArguments().Count -eq 1
} | Select-Object -First 1
function Wait-WinRT($Operation, [Type]$ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $task.Wait(10000)) { throw 'Windows OCR operation timed out' }
    $task.GetAwaiter().GetResult()
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
    [Windows.Globalization.Language]::new('en-US'))
if ($null -eq $engine) { throw 'Installed en-US OCR language required; nothing installed automatically.' }
$source = (Resolve-Path -LiteralPath $FramesDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw "Output already exists: $output" }
$null = New-Item -ItemType Directory -Path $output
$utf8 = [Text.UTF8Encoding]::new($false)
$writer = [IO.StreamWriter]::new((Join-Path $output 'raw.jsonl'), $false, $utf8)
# Frozen on frame35 (1920x1080). Do not adapt these to evaluation labels.
$regions = [ordered]@{
    race = [Drawing.Rectangle]::new(1690, 20, 220, 210)
    fuel = [Drawing.Rectangle]::new(1635, 1018, 215, 30)
}
try {
    foreach ($second in $Seconds) {
        if ([double]::IsNaN($second) -or [double]::IsInfinity($second) -or $second -lt 0) {
            throw 'Timestamp must be finite and nonnegative'
        }
        $stamp = $second.ToString('0.###', [Globalization.CultureInfo]::InvariantCulture)
        $file = Join-Path $source "frame_$stamp.png"
        $image = [Drawing.Bitmap]::FromFile($file)
        try {
            if ($image.Width -ne 1920 -or $image.Height -ne 1080) {
                throw "Unsupported frame dimensions: $file"
            }
            $row = [ordered]@{
                video_s = $second
                frame_sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
                reader = "windows_ocr_en-US_$Reader"
                ocr_confidence = $null
                live_authorized = $false
            }
            foreach ($name in $regions.Keys) {
                $rect = $regions[$name]
                $scale = if ($name -eq 'race') { 4 } else { 2 }
                $composite = $null
                if ($Reader -eq 'v2' -and $name -eq 'race') {
                    # Keep all white glyphs in the numeric slot; shorten only the blank gap.
                    # Never synthesize digits. Boundary contact rejects a possibly clipped value.
                    $left = 1900
                    $right = 1770
                    for ($x = 1770; $x -lt 1900; $x++) {
                        for ($y = 32; $y -lt 62; $y++) {
                            $p = $image.GetPixel($x, $y)
                            if ($p.R -gt 180 -and $p.G -gt 180 -and $p.B -gt 180) {
                                $left = [Math]::Min($left, $x)
                                $right = [Math]::Max($right, $x)
                            }
                        }
                    }
                    $usable = $left -gt 1771 -and $right -lt 1898 -and $right -ge $left
                    $width = if ($usable) { $right - $left + 5 } else { 130 }
                    $composite = [Drawing.Bitmap]::new(77 + $width, 50)
                    $cg = [Drawing.Graphics]::FromImage($composite)
                    try {
                        $cg.Clear([Drawing.Color]::FromArgb(18, 20, 28))
                        $cg.DrawImage($image, [Drawing.Rectangle]::new(10, 10, 49, 30), [Drawing.Rectangle]::new(1707, 32, 49, 30), [Drawing.GraphicsUnit]::Pixel)
                        if ($usable) {
                            $cg.DrawImage($image, [Drawing.Rectangle]::new(67, 10, $width, 30), [Drawing.Rectangle]::new($left - 2, 32, $width, 30), [Drawing.GraphicsUnit]::Pixel)
                        }
                    } finally { $cg.Dispose() }
                    $row['race_numeric_slot_usable'] = $usable
                    $rect = [Drawing.Rectangle]::new(0, 0, $composite.Width, $composite.Height)
                    $scale = 2
                }
                $crop = [Drawing.Bitmap]::new($rect.Width * $scale, $rect.Height * $scale)
                $graphics = [Drawing.Graphics]::FromImage($crop)
                $cropPath = Join-Path $output "frame_${stamp}_${name}.png"
                try {
                    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                    $sourceImage = if ($null -ne $composite) { $composite } else { $image }
                    $graphics.DrawImage($sourceImage, [Drawing.Rectangle]::new(0, 0, $crop.Width, $crop.Height), $rect, [Drawing.GraphicsUnit]::Pixel)
                    # White HUD glyphs -> black on white, including the pink fuel bar.
                    for ($y = 0; $name -eq 'fuel' -and $y -lt $crop.Height; $y++) {
                        for ($x = 0; $x -lt $crop.Width; $x++) {
                            $pixel = $crop.GetPixel($x, $y)
                            $color = if ($pixel.R -gt 180 -and $pixel.G -gt 180 -and $pixel.B -gt 180) {
                                [Drawing.Color]::Black
                            } else { [Drawing.Color]::White }
                            $crop.SetPixel($x, $y, $color)
                        }
                    }
                    $crop.Save($cropPath, [Drawing.Imaging.ImageFormat]::Png)
                } finally {
                    $graphics.Dispose(); $crop.Dispose()
                    if ($null -ne $composite) { $composite.Dispose() }
                }
                $storageFile = Wait-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($cropPath)) ([Windows.Storage.StorageFile])
                $stream = Wait-WinRT ($storageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
                $bitmap = $null
                $timer = [Diagnostics.Stopwatch]::StartNew()
                try {
                    $decoder = Wait-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
                    $bitmap = Wait-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
                    $result = Wait-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                    $row["${name}_text"] = $result.Text
                    $row["${name}_lines"] = @($result.Lines | ForEach-Object Text)
                    $row["${name}_crop"] = @($rect.X, $rect.Y, $rect.Width, $rect.Height)
                    $row["${name}_ocr_ms"] = $timer.Elapsed.TotalMilliseconds
                } finally {
                    $timer.Stop()
                    if ($null -ne $bitmap) { $bitmap.Dispose() }
                    $stream.Dispose()
                }
            }
            $writer.WriteLine(($row | ConvertTo-Json -Depth 5 -Compress))
            $writer.Flush()
            Write-Output "Read frame ${stamp}s"
        } finally { $image.Dispose() }
    }
} finally { $writer.Dispose() }
