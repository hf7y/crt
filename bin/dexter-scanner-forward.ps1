# Forwards a USB 1D barcode scanner plugged into dexter to crt-vm, the
# same way dexter-whisper-server.py/dexter-audio-server.py bridge audio
# across the host/guest boundary -- except the direction is reversed here:
# dexter has the hardware, crt-vm needs the data, so THIS script pushes.
#
# The scanner (VID_0145&PID_0012, confirmed via
# `Get-PnpDevice -PresentOnly | Where Class -eq HIDClass` on dexter,
# 2026-07-21) enumerates as a generic "HID Keyboard Device" -- normal
# keyboard-wedge emulation, not a distinct serial/HID-report device. That
# means it types into whatever window has focus like a real keyboard,
# which would be useless/dangerous if left to hit the desktop or an
# arbitrary window. Instead of relying on focus, this uses the Win32
# RawInput API (RegisterRawInputDevices + WM_INPUT on a hidden
# message-only window, RIDEV_INPUTSINK) to read keystrokes from ALL
# keyboards system-wide regardless of focus, then filters by device
# handle to the scanner's own HID device path -- so a human typing at the
# real keyboard is never captured or forwarded, only this one VID/PID.
#
# Assembles keystrokes into a line (scanners send characters then Enter
# for each barcode) and POSTs each completed line to crt-vm's
# crt-scanner-feed.py listener over the NAT port-forward set up for this
# (see bin/../HANDOFF.md and the `natpf1 scanner` rule added on dexter,
# host port 8993 -> guest port 8993).
#
# STATUS: written 2026-07-21, NOT yet load-tested against a real scan --
# RawInput device-handle filtering is the standard technique for this but
# has not been exercised on this specific dexter/PowerShell combo. If scans
# aren't arriving, first check with -DebugAll to see whether ANY raw input
# reaches the window at all before suspecting the VID/PID filter.
#
# Run on dexter (persistent, foreground or via Task Scheduler "At log on"):
#   powershell -ExecutionPolicy Bypass -File dexter-scanner-forward.ps1
#
# Params:
#   -CrtVmUrl   Where to POST decoded scans (default http://127.0.0.1:8993/scan
#               -- the NAT port-forward makes crt-vm reachable via dexter's
#               own loopback, same trick the ssh port-forward already relies on).
#   -DeviceMatch  Substring to match against the raw-input device's HID path.
#               Default matches the scanner's known VID/PID from 2026-07-21;
#               override if the scanner is ever swapped for different hardware.
#   -DebugAll   Log every raw-input keystroke seen (any device), not just
#               ones matching -DeviceMatch. Use this to confirm capture is
#               working at all before debugging the device filter.

param(
    [string]$CrtVmUrl = "http://127.0.0.1:8993/scan",
    [string]$DeviceMatch = "VID_0145&PID_0012",
    [switch]$DebugAll
)

Add-Type -Namespace CrtScanner -Name RawInput -MemberDefinition @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct RAWINPUTDEVICE {
    public ushort usUsagePage;
    public ushort usUsage;
    public uint dwFlags;
    public IntPtr hwndTarget;
}

[StructLayout(LayoutKind.Sequential)]
public struct RAWINPUTHEADER {
    public uint dwType;
    public uint dwSize;
    public IntPtr hDevice;
    public IntPtr wParam;
}

[StructLayout(LayoutKind.Sequential)]
public struct RAWKEYBOARD {
    public ushort MakeCode;
    public ushort Flags;
    public ushort Reserved;
    public ushort VKey;
    public uint Message;
    public uint ExtraInformation;
}

public const int RIDEV_INPUTSINK = 0x00000100;
public const int RIM_TYPEKEYBOARD = 1;
public const int WM_INPUT = 0x00FF;
public const int RID_INPUT = 0x10000003;
public const int RIDI_DEVICENAME = 0x20000007;

[DllImport("user32.dll", SetLastError = true)]
public static extern bool RegisterRawInputDevices(RAWINPUTDEVICE[] pRawInputDevices, uint uiNumDevices, uint cbSize);

[DllImport("user32.dll")]
public static extern uint GetRawInputData(IntPtr hRawInput, uint uiCommand, IntPtr pData, ref uint pcbSize, uint cbSizeHeader);

[DllImport("user32.dll")]
public static extern uint GetRawInputDeviceInfo(IntPtr hDevice, uint uiCommand, System.Text.StringBuilder pData, ref uint pcbSize);
"@

Add-Type -AssemblyName System.Windows.Forms

# Hidden message-only window so we get a WndProc to receive WM_INPUT
# without a visible UI on dexter's desktop.
$form = New-Object System.Windows.Forms.Form
$form.WindowState = 'Minimized'
$form.ShowInTaskbar = $false
$form.Opacity = 0

$rid = New-Object CrtScanner.RawInput+RAWINPUTDEVICE
$rid.usUsagePage = 0x01   # Generic Desktop
$rid.usUsage = 0x06       # Keyboard
$rid.dwFlags = [CrtScanner.RawInput]::RIDEV_INPUTSINK
$rid.hwndTarget = $form.Handle
$devices = [CrtScanner.RawInput+RAWINPUTDEVICE[]]@($rid)
$ok = [CrtScanner.RawInput]::RegisterRawInputDevices($devices, 1, [System.Runtime.InteropServices.Marshal]::SizeOf([type][CrtScanner.RawInput+RAWINPUTDEVICE]))
if (-not $ok) {
    Write-Error "RegisterRawInputDevices failed"
    exit 1
}

$script:lineBuf = New-Object System.Text.StringBuilder
$deviceNameCache = @{}

function Get-DeviceName([IntPtr]$hDevice) {
    if ($deviceNameCache.ContainsKey($hDevice)) { return $deviceNameCache[$hDevice] }
    $size = 0
    [void][CrtScanner.RawInput]::GetRawInputDeviceInfo($hDevice, [CrtScanner.RawInput]::RIDI_DEVICENAME, $null, [ref]$size)
    $sb = New-Object System.Text.StringBuilder $size
    [void][CrtScanner.RawInput]::GetRawInputDeviceInfo($hDevice, [CrtScanner.RawInput]::RIDI_DEVICENAME, $sb, [ref]$size)
    $name = $sb.ToString()
    $deviceNameCache[$hDevice] = $name
    return $name
}

function Send-Scan([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    try {
        $bodyJson = (@{ text = $text } | ConvertTo-Json -Compress)
        Invoke-RestMethod -Uri $CrtVmUrl -Method Post -ContentType "application/json" -Body $bodyJson -TimeoutSec 5 | Out-Null
        Write-Host "[dexter-scanner] -> $text"
    } catch {
        Write-Warning "[dexter-scanner] POST failed: $_"
    }
}

# VK -> char map for the digits/letters a 1D barcode scanner actually
# emits (numeric barcodes are the overwhelming common case; letters
# included for Code128/alphanumeric labels).
function VKey-ToChar([int]$vk, [bool]$shift) {
    if ($vk -ge 0x30 -and $vk -le 0x39) { return [char]$vk }         # 0-9
    if ($vk -ge 0x41 -and $vk -le 0x5A) {                            # A-Z
        $c = [char]$vk
        if (-not $shift) { return [char]::ToLower($c) }
        return $c
    }
    if ($vk -ge 0x60 -and $vk -le 0x69) { return [char](0x30 + ($vk - 0x60)) }  # numpad 0-9
    if ($vk -eq 0xBD) { return '-' }
    if ($vk -eq 0xBE) { return '.' }
    return $null
}

$script:shiftDown = $false

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 15

# Subclass the hidden form to intercept WM_INPUT (0x00FF) via WndProc.
$formType = $form.GetType()
$wndProcField = [System.Windows.Forms.Control].GetMethod("WndProc", [System.Reflection.BindingFlags]"NonPublic,Instance")

# Simpler than a full subclass: use a native window hook via
# System.Windows.Forms.NativeWindow so we don't have to derive a custom
# Form class in this single-file script.
Add-Type -Namespace CrtScanner -Name Hook -MemberDefinition @"
"@ -PassThru | Out-Null

class ScannerWindow : System.Windows.Forms.NativeWindow {
    [scriptblock]$OnInput
    [void] WndProc([ref]$m) {}
}

# PowerShell classes can't easily override WndProc with the message struct
# by reference across this boundary reliably in all PS versions, so instead
# poll GetRawInputBuffer-free approach: register a message filter via
# Application.AddMessageFilter, which DOES let us inspect WM_INPUT without
# subclassing.
Add-Type -AssemblyName System.Windows.Forms

class RawInputFilter : System.Windows.Forms.IMessageFilter {
    [scriptblock]$Handler
    [bool] PreFilterMessage([ref][System.Windows.Forms.Message]$m) {
        if ($this.Handler) { & $this.Handler $m.Value }
        return $false
    }
}

$filter = [RawInputFilter]::new()
$filter.Handler = {
    param($msg)
    if ($msg.Msg -ne [CrtScanner.RawInput]::WM_INPUT) { return }

    $size = 0
    [void][CrtScanner.RawInput]::GetRawInputData($msg.LParam, [CrtScanner.RawInput]::RID_INPUT, [IntPtr]::Zero, [ref]$size, [uint32][System.Runtime.InteropServices.Marshal]::SizeOf([type][CrtScanner.RawInput+RAWINPUTHEADER]))
    if ($size -eq 0) { return }
    $buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    try {
        [void][CrtScanner.RawInput]::GetRawInputData($msg.LParam, [CrtScanner.RawInput]::RID_INPUT, $buf, [ref]$size, [uint32][System.Runtime.InteropServices.Marshal]::SizeOf([type][CrtScanner.RawInput+RAWINPUTHEADER]))
        $header = [System.Runtime.InteropServices.Marshal]::PtrToStructure($buf, [type][CrtScanner.RawInput+RAWINPUTHEADER])
        if ($header.dwType -ne [CrtScanner.RawInput]::RIM_TYPEKEYBOARD) { return }

        $devName = Get-DeviceName $header.hDevice
        $isScanner = $devName -like "*$DeviceMatch*"

        $kbOffset = [System.Runtime.InteropServices.Marshal]::SizeOf([type][CrtScanner.RawInput+RAWINPUTHEADER])
        $kbPtr = [IntPtr]::Add($buf, $kbOffset)
        $kb = [System.Runtime.InteropServices.Marshal]::PtrToStructure($kbPtr, [type][CrtScanner.RawInput+RAWKEYBOARD])

        if ($DebugAll) {
            Write-Host "[raw] dev=$devName vk=$($kb.VKey) msg=$($kb.Message)"
        }

        if (-not $isScanner) { return }

        # WM_KEYDOWN = 0x0100, WM_KEYUP = 0x0101
        if ($kb.Message -eq 0x0101) {
            if ($kb.VKey -eq 0x10 -or $kb.VKey -eq 0xA0 -or $kb.VKey -eq 0xA1) { $script:shiftDown = $false }
            return
        }
        if ($kb.Message -ne 0x0100) { return }

        if ($kb.VKey -eq 0x10 -or $kb.VKey -eq 0xA0 -or $kb.VKey -eq 0xA1) { $script:shiftDown = $true; return }

        if ($kb.VKey -eq 0x0D) {  # Enter: end of barcode
            $line = $script:lineBuf.ToString()
            $script:lineBuf.Clear() | Out-Null
            Send-Scan $line
            return
        }

        $ch = VKey-ToChar $kb.VKey $script:shiftDown
        if ($ch) { [void]$script:lineBuf.Append($ch) }
    } finally {
        [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf)
    }
}

[System.Windows.Forms.Application]::AddMessageFilter($filter)

Write-Host "[dexter-scanner] listening for raw HID input matching '$DeviceMatch', forwarding to $CrtVmUrl"
Write-Host "[dexter-scanner] Ctrl+C to stop"
[System.Windows.Forms.Application]::Run()
