
Add-Type -AssemblyName System.Speech
 = New-Object System.Speech.Synthesis.SpeechSynthesizer
.SetOutputToWaveFile('test_tts.wav')
.Speak('The single biggest secret to success is continuous action. When you work hard every single day, you develop strong habits and overcome every challenge that comes your way.')
.Dispose()
