# Generates the two sample WAV files with Windows built-in SAPI voices.
# The generated audio is original, contains no personal information and can be
# redistributed with this project.
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts/generate_samples.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$samplesDir = Join-Path $PSScriptRoot "..\samples"
$null = New-Item -ItemType Directory -Force -Path $samplesDir
$samplesDir = (Resolve-Path $samplesDir).Path

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

function New-Sample {
    param(
        [string]$VoiceName,
        [string]$Text,
        [string]$OutputFile
    )

    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $synth.SelectVoice($VoiceName)
        $synth.Rate = 0
        $synth.Volume = 100
        $synth.SetOutputToWaveFile($OutputFile, $format)
        $synth.Speak($Text)
    }
    finally {
        $synth.Dispose()
    }

    $info = Get-Item $OutputFile
    Write-Host ("Generated {0} ({1:N0} bytes)" -f $info.Name, $info.Length)
}

New-Sample `
    -VoiceName "Microsoft Huihui Desktop" `
    -Text "你好，欢迎使用本地语音识别系统。今天天气很好，适合在户外散步。" `
    -OutputFile (Join-Path $samplesDir "chinese.wav")

New-Sample `
    -VoiceName "Microsoft Zira Desktop" `
    -Text "Hello, welcome to the local speech recognition system. Today is a nice day for a walk outside." `
    -OutputFile (Join-Path $samplesDir "english.wav")

Write-Host "Done. Files written to $samplesDir"
