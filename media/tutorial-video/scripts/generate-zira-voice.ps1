param(
  [Parameter(Mandatory = $true)][string]$Text,
  [Parameter(Mandatory = $true)][string]$OutputPath,
  [Parameter(Mandatory = $true)][int]$Rate
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $zira = $synthesizer.GetInstalledVoices() |
    Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq "en-US" -and $_.VoiceInfo.Name -match "Zira" } |
    Select-Object -First 1
  if (-not $zira) {
    throw "Microsoft Zira en-US is required to regenerate tutorial narration."
  }
  $synthesizer.SelectVoice($zira.VoiceInfo.Name)
  $synthesizer.Rate = $Rate
  $synthesizer.Volume = 100
  $synthesizer.SetOutputToWaveFile($OutputPath)
  $synthesizer.Speak($Text)
} finally {
  $synthesizer.Dispose()
}
