# Windows 10 内置 OCR 提取设计图文字（中文）
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime] | Out-Null

$sb = New-Object System.Text.StringBuilder

foreach ($i in 1,2,3) {
    $path = "E:\workspace\智能差旅报销系统\前端$i.png"
    [void]$sb.AppendLine("===== 前端$i.png =====")
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-CN"))
        if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        foreach ($line in $result.Lines) {
            [void]$sb.AppendLine($line.Text)
        }
    } catch {
        [void]$sb.AppendLine("OCR FAILED: $($_.Exception.Message)")
    }
}

[System.IO.File]::WriteAllText("E:\workspace\智能差旅报销系统\ocr_result.txt", $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
