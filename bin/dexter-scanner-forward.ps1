# Forwards a USB 1D barcode scanner plugged into dexter to crt-vm, the
# same way dexter-whisper-server.py/dexter-audio-server.py bridge audio
# across the host/guest boundary -- except the direction is reversed here:
# dexter has the hardware, crt-vm needs the data, so THIS script pushes.
#
# The scanner (VID_0145&PID_0012, confirmed via
# `Get-PnpDevice -PresentOnly | Where Class -eq HIDClass` on dexter,
# 2026-07-21) enumerates as a generic "HID Keyboard Device" -- normal
# keyboard-wedge emulation, not a distinct serial/HID-report device (no
# COM-port/CDC config option in this scanner's manual either, checked
# 2026-07-21 -- ruling that out as an easier fix). That means it types
# into whatever window has focus like a real keyboard -- confirmed
# 2026-07-21 when a real scan landed as literal keystrokes in crt-vm's
# tmux pane because the VirtualBox GUI window happened to have focus on
# dexter's desktop. This script uses the Win32 RawInput API
# (RegisterRawInputDevices + WM_INPUT via an IMessageFilter,
# RIDEV_INPUTSINK) to read keystrokes from ALL keyboards system-wide
# regardless of focus, then filters by device handle to the scanner's own
# HID device path -- a human typing at the real keyboard is never
# captured or forwarded, only this one VID/PID.
#
# SUPPRESSION (added 2026-07-21, second live bug): RawInput only OBSERVES
# input, it never blocks it -- the scanner's keystrokes were STILL
# reaching whatever had focus (crt-vm's VirtualBox window, which IS the
# CRT display, so "just don't focus it" isn't an option here) in
# parallel with being forwarded over HTTP. That's not cosmetic for this
# app specifically: window 0 of the tmux session is a LIVE Claude Code
# agent, so an unsuppressed scan could type a raw ISBN straight into a
# real prompt (burning an API turn on garbage) or blindly confirm/dismiss
# whatever permission prompt happened to be on screen. Fixed with a
# WH_KEYBOARD_LL low-level keyboard hook (SetWindowsHookEx), which CAN
# block propagation (return a nonzero value instead of calling
# CallNextHookEx) -- unlike RawInput. The low-level hook API doesn't
# expose which physical device sent an event, so this can't filter by
# VID/PID the way the RawInput path does; instead it distinguishes by
# TIMING -- a barcode scanner emits characters far faster than any human
# can type (SCAN_KEY_INTERVAL_MS below), so keys arriving faster than
# that threshold are assumed to be the scanner and are swallowed (both
# from reaching whatever's focused AND from the OS's normal input queue
# entirely), while normal-speed human typing is untouched and passed
# through immediately. STATUS: NOT tested against the real device yet --
# the timing threshold is a first guess (SCANNER.md's own acceptance bar
# applies: needs a live human to confirm it doesn't eat real fast-typing,
# and that it reliably catches every real scan).
#
# Everything (raw-input capture, the message filter, and the HTTP POST)
# lives in one Add-Type C# block below rather than split across C#
# interop + PowerShell classes -- an earlier version tried `class Foo :
# <Add-Type'd type>` in the same script and PowerShell couldn't resolve
# the base type (PS parses the whole script, including class
# definitions, before any statement -- including the Add-Type call --
# actually runs, so a class can't derive from a type Add-Type hasn't
# loaded yet). Doing it all in C# sidesteps that entirely.
#
# Assembles keystrokes into a line (scanners send characters then Enter
# for each barcode) and POSTs each completed line to crt-vm's
# crt-scanner-feed.py listener over the NAT port-forward set up for this
# (see SCANNER.md and HANDOFF.md -- `natpf1 scanner` rule added on
# dexter, host port 8993 -> guest port 8993).
#
# Run on dexter (persistent, foreground or via Task Scheduler "At log on"):
#   powershell -ExecutionPolicy Bypass -File dexter-scanner-forward.ps1
#
# Params:
#   -CrtVmUrl     Where to POST decoded scans (default
#                 http://127.0.0.1:8993/scan -- the NAT port-forward makes
#                 crt-vm reachable via dexter's own loopback, same trick
#                 the ssh port-forward already relies on).
#   -DeviceMatch  Substring to match against the raw-input device's HID
#                 path. Default matches the scanner's known VID/PID from
#                 2026-07-21; override if the scanner is ever swapped.
#   -DebugAll     Print every raw-input keystroke seen (any device), not
#                 just ones matching -DeviceMatch. Use this to confirm
#                 capture is working at all before debugging the device
#                 filter.
#   -ScanKeyIntervalMs  Max ms between keydowns to count as scanner-speed
#                 (default 30 -- a real barcode scanner's keyboard-wedge
#                 output is typically well under 10ms/char; humans rarely
#                 sustain under ~60ms even typing fast). Tune UP if real
#                 scans are still leaking through as keystrokes; tune DOWN
#                 if fast human typing starts getting eaten.
#   -BurstGapTimeoutMs  How long a gap ends a detected burst (default 300)
#                 -- keeps the LAST key of a scan (often Enter) suppressed
#                 even if its own inter-key gap ticks slightly over
#                 -ScanKeyIntervalMs.
#   -NoSuppress   Disable the keystroke-suppression hook entirely, falling
#                 back to RawInput-only (old behavior, keystrokes still
#                 leak to whatever has focus) -- for comparing behavior
#                 while tuning the timing thresholds above.

param(
    [string]$CrtVmUrl = "http://127.0.0.1:8993/scan",
    [string]$DeviceMatch = "VID_0145&PID_0012",
    [switch]$DebugAll,
    [int]$ScanKeyIntervalMs = 30,
    [int]$BurstGapTimeoutMs = 300,
    [switch]$NoSuppress
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CrtScanner
{
    [StructLayout(LayoutKind.Sequential)]
    struct RAWINPUTDEVICE
    {
        public ushort usUsagePage;
        public ushort usUsage;
        public uint dwFlags;
        public IntPtr hwndTarget;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct RAWINPUTHEADER
    {
        public uint dwType;
        public uint dwSize;
        public IntPtr hDevice;
        public IntPtr wParam;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct RAWKEYBOARD
    {
        public ushort MakeCode;
        public ushort Flags;
        public ushort Reserved;
        public ushort VKey;
        public uint Message;
        public uint ExtraInformation;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct KBDLLHOOKSTRUCT
    {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);

    static class Native
    {
        public const int RIDEV_INPUTSINK = 0x00000100;
        public const int RIM_TYPEKEYBOARD = 1;
        public const int WM_INPUT = 0x00FF;
        public const uint RID_INPUT = 0x10000003;
        public const uint RIDI_DEVICENAME = 0x20000007;

        public const int WH_KEYBOARD_LL = 13;
        public const int WM_KEYDOWN = 0x0100;
        public const int WM_SYSKEYDOWN = 0x0104;

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool RegisterRawInputDevices(RAWINPUTDEVICE[] pRawInputDevices, uint uiNumDevices, uint cbSize);

        [DllImport("user32.dll")]
        public static extern uint GetRawInputData(IntPtr hRawInput, uint uiCommand, IntPtr pData, ref uint pcbSize, uint cbSizeHeader);

        [DllImport("user32.dll")]
        public static extern uint GetRawInputDeviceInfo(IntPtr hDevice, uint uiCommand, StringBuilder pData, ref uint pcbSize);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool UnhookWindowsHookEx(IntPtr hhk);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        public static extern IntPtr GetModuleHandle(string lpModuleName);
    }

    // Swallows scanner-speed keystrokes system-wide before they reach
    // whatever window has focus -- see the file header for why RawInput
    // alone (read-only, can't block) isn't enough. Timing-based, not
    // device-identity-based: WH_KEYBOARD_LL doesn't expose which
    // physical device sent an event, unlike RawInput's device handle.
    // KNOWN LIMITATION (untested live, flag don't lose): the very FIRST
    // character of a scan burst can still leak through -- there's no way
    // to know a burst is starting until a second fast keystroke confirms
    // it, so that one key's inter-key gap looks like ordinary typing at
    // the time it arrives. Every character after that, including the
    // terminating Enter, is suppressed. If even that first stray
    // character turns out to matter in practice, the fix is a small
    // fixed lookback buffer (hold each keydown a few ms before releasing
    // it, retroactively swallow if the next one arrives fast) --
    // deliberately not built now since it adds real input latency for a
    // problem that may turn out not to matter once tested live.
    public static class KeySuppressor
    {
        public static int ScanKeyIntervalMs = 30;
        public static int BurstGapTimeoutMs = 300;
        public static bool Enabled = true;

        private static IntPtr hookId = IntPtr.Zero;
        private static LowLevelKeyboardProc proc = HookCallback; // keep alive -- GC'd delegates crash native callbacks
        private static long lastTickMs = 0;
        private static bool burstActive = false;

        public static void Install()
        {
            if (!Enabled) return;
            IntPtr hMod = Native.GetModuleHandle(null);
            hookId = Native.SetWindowsHookEx(Native.WH_KEYBOARD_LL, proc, hMod, 0);
            if (hookId == IntPtr.Zero)
                Console.WriteLine("[dexter-scanner] SetWindowsHookEx FAILED: " + Marshal.GetLastWin32Error());
            else
                Console.WriteLine("[dexter-scanner] keystroke suppression active (>=" + ScanKeyIntervalMs + "ms/char treated as human, faster treated as scanner and swallowed)");
        }

        public static void Uninstall()
        {
            if (hookId != IntPtr.Zero) Native.UnhookWindowsHookEx(hookId);
        }

        private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
        {
            if (nCode >= 0 && ((int)wParam == Native.WM_KEYDOWN || (int)wParam == Native.WM_SYSKEYDOWN))
            {
                // Environment.TickCount, not TickCount64: this dexter's
                // Windows PowerShell 5.1 targets an older .NET Framework
                // that doesn't have TickCount64, and Add-Type's compile
                // error on it was silently hanging the whole process on
                // every launch (the giant compiler-error dump filled the
                // Start-Process-redirected stderr pipe with nobody
                // reading it, so the process sat there "running" but
                // never reached Application.Run -- every scan since this
                // was introduced leaked straight to whatever had focus
                // instead of ever being captured). int wraps every ~24.9
                // days of uptime; irrelevant for a single keystroke-gap
                // delta like this.
                long now = Environment.TickCount;
                long dt = lastTickMs == 0 ? long.MaxValue : now - lastTickMs;
                lastTickMs = now;

                bool looksLikeScanner = dt < ScanKeyIntervalMs;
                if (looksLikeScanner) burstActive = true;
                else if (dt > BurstGapTimeoutMs) burstActive = false;

                if (looksLikeScanner || burstActive)
                {
                    return (IntPtr)1; // swallow: block propagation, no CallNextHookEx
                }
            }
            return Native.CallNextHookEx(hookId, nCode, wParam, lParam);
        }
    }

    public class ScannerCapture : Form, IMessageFilter
    {
        public string DeviceMatch = "";
        public bool DebugAll = false;
        public string PostUrl = "";

        private StringBuilder lineBuf = new StringBuilder();
        private bool shiftDown = false;
        private Dictionary<IntPtr, string> nameCache = new Dictionary<IntPtr, string>();

        public ScannerCapture()
        {
            WindowState = FormWindowState.Minimized;
            ShowInTaskbar = false;
            Opacity = 0;
            Load += (s, e) => { RegisterDevice(); KeySuppressor.Install(); };
            FormClosed += (s, e) => KeySuppressor.Uninstall();
        }

        private void RegisterDevice()
        {
            var rid = new RAWINPUTDEVICE
            {
                usUsagePage = 0x01,
                usUsage = 0x06,
                dwFlags = Native.RIDEV_INPUTSINK,
                hwndTarget = this.Handle
            };
            var devices = new RAWINPUTDEVICE[] { rid };
            bool ok = Native.RegisterRawInputDevices(devices, 1, (uint)Marshal.SizeOf(typeof(RAWINPUTDEVICE)));
            if (!ok)
            {
                Console.WriteLine("[dexter-scanner] RegisterRawInputDevices FAILED: " + Marshal.GetLastWin32Error());
            }
            else
            {
                Console.WriteLine("[dexter-scanner] listening for raw HID input matching '" + DeviceMatch + "', forwarding to " + PostUrl);
            }
            Application.AddMessageFilter(this);
        }

        private string GetDeviceName(IntPtr hDevice)
        {
            string cached;
            if (nameCache.TryGetValue(hDevice, out cached)) return cached;
            uint size = 0;
            Native.GetRawInputDeviceInfo(hDevice, Native.RIDI_DEVICENAME, null, ref size);
            var sb = new StringBuilder((int)size);
            Native.GetRawInputDeviceInfo(hDevice, Native.RIDI_DEVICENAME, sb, ref size);
            string name = sb.ToString();
            nameCache[hDevice] = name;
            return name;
        }

        private char? VKeyToChar(int vk, bool shift)
        {
            if (vk >= 0x30 && vk <= 0x39) return (char)vk;                     // 0-9
            if (vk >= 0x41 && vk <= 0x5A)                                       // A-Z
            {
                char c = (char)vk;
                return shift ? c : char.ToLower(c);
            }
            if (vk >= 0x60 && vk <= 0x69) return (char)(0x30 + (vk - 0x60));    // numpad 0-9
            if (vk == 0xBD) return '-';
            if (vk == 0xBE) return '.';
            return null;
        }

        private void SendScan(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return;
            try
            {
                using (var wc = new WebClient())
                {
                    wc.Headers[HttpRequestHeader.ContentType] = "application/json";
                    string json = "{\"text\":\"" + text.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"}";
                    wc.UploadString(PostUrl, "POST", json);
                }
                Console.WriteLine("[dexter-scanner] -> " + text);
            }
            catch (Exception ex)
            {
                Console.WriteLine("[dexter-scanner] POST failed: " + ex.Message);
            }
        }

        public bool PreFilterMessage(ref Message m)
        {
            if (m.Msg != Native.WM_INPUT) return false;

            uint size = 0;
            uint headerSize = (uint)Marshal.SizeOf(typeof(RAWINPUTHEADER));
            Native.GetRawInputData(m.LParam, Native.RID_INPUT, IntPtr.Zero, ref size, headerSize);
            if (size == 0) return false;

            IntPtr buf = Marshal.AllocHGlobal((int)size);
            try
            {
                Native.GetRawInputData(m.LParam, Native.RID_INPUT, buf, ref size, headerSize);
                var header = (RAWINPUTHEADER)Marshal.PtrToStructure(buf, typeof(RAWINPUTHEADER));
                if (header.dwType != Native.RIM_TYPEKEYBOARD) return false;

                string devName = GetDeviceName(header.hDevice);
                bool isScanner = devName.IndexOf(DeviceMatch, StringComparison.OrdinalIgnoreCase) >= 0;

                IntPtr kbPtr = (IntPtr)((long)buf + headerSize);
                var kb = (RAWKEYBOARD)Marshal.PtrToStructure(kbPtr, typeof(RAWKEYBOARD));

                if (DebugAll)
                {
                    Console.WriteLine("[raw] dev=" + devName + " vk=" + kb.VKey + " msg=0x" + kb.Message.ToString("X"));
                }

                if (!isScanner) return false;

                if (kb.Message == 0x0101) // WM_KEYUP
                {
                    if (kb.VKey == 0x10 || kb.VKey == 0xA0 || kb.VKey == 0xA1) shiftDown = false;
                    return false;
                }
                if (kb.Message != 0x0100) return false; // not WM_KEYDOWN

                if (kb.VKey == 0x10 || kb.VKey == 0xA0 || kb.VKey == 0xA1) { shiftDown = true; return false; }

                if (kb.VKey == 0x0D) // Enter: end of barcode
                {
                    string line = lineBuf.ToString();
                    lineBuf.Length = 0;
                    SendScan(line);
                    return false;
                }

                var ch = VKeyToChar(kb.VKey, shiftDown);
                if (ch.HasValue) lineBuf.Append(ch.Value);
            }
            finally
            {
                Marshal.FreeHGlobal(buf);
            }
            return false;
        }
    }
}
"@

[CrtScanner.KeySuppressor]::ScanKeyIntervalMs = $ScanKeyIntervalMs
[CrtScanner.KeySuppressor]::BurstGapTimeoutMs = $BurstGapTimeoutMs
[CrtScanner.KeySuppressor]::Enabled = -not $NoSuppress

$form = New-Object CrtScanner.ScannerCapture
$form.DeviceMatch = $DeviceMatch
$form.DebugAll = [bool]$DebugAll
$form.PostUrl = $CrtVmUrl

[System.Windows.Forms.Application]::Run($form)
