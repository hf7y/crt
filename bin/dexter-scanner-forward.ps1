# Forwards a USB 1D barcode scanner plugged into dexter to crt-vm, the
# same way dexter-whisper-server.py/dexter-audio-server.py bridge audio
# across the host/guest boundary -- except the direction is reversed here:
# dexter has the hardware, crt-vm needs the data, so THIS script pushes.
#
# The scanner (VID_0145&PID_0012, confirmed via
# `Get-PnpDevice -PresentOnly | Where Class -eq HIDClass` on dexter,
# 2026-07-21) enumerates as a generic "HID Keyboard Device" -- normal
# keyboard-wedge emulation, not a distinct serial/HID-report device. That
# means it types into whatever window has focus like a real keyboard --
# confirmed 2026-07-21 when a real scan landed as literal keystrokes in
# crt-vm's tmux pane because the VirtualBox GUI window happened to have
# focus on dexter's desktop at the time. That's not a reliable delivery
# path (depends on what's focused), so this script uses the Win32
# RawInput API (RegisterRawInputDevices + WM_INPUT via an IMessageFilter,
# RIDEV_INPUTSINK) to read keystrokes from ALL keyboards system-wide
# regardless of focus, then filters by device handle to the scanner's own
# HID device path -- a human typing at the real keyboard is never
# captured or forwarded, only this one VID/PID, and it works with no
# window ever needing focus.
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

param(
    [string]$CrtVmUrl = "http://127.0.0.1:8993/scan",
    [string]$DeviceMatch = "VID_0145&PID_0012",
    [switch]$DebugAll
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

    static class Native
    {
        public const int RIDEV_INPUTSINK = 0x00000100;
        public const int RIM_TYPEKEYBOARD = 1;
        public const int WM_INPUT = 0x00FF;
        public const uint RID_INPUT = 0x10000003;
        public const uint RIDI_DEVICENAME = 0x20000007;

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool RegisterRawInputDevices(RAWINPUTDEVICE[] pRawInputDevices, uint uiNumDevices, uint cbSize);

        [DllImport("user32.dll")]
        public static extern uint GetRawInputData(IntPtr hRawInput, uint uiCommand, IntPtr pData, ref uint pcbSize, uint cbSizeHeader);

        [DllImport("user32.dll")]
        public static extern uint GetRawInputDeviceInfo(IntPtr hDevice, uint uiCommand, StringBuilder pData, ref uint pcbSize);
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
            Load += (s, e) => RegisterDevice();
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

$form = New-Object CrtScanner.ScannerCapture
$form.DeviceMatch = $DeviceMatch
$form.DebugAll = [bool]$DebugAll
$form.PostUrl = $CrtVmUrl

[System.Windows.Forms.Application]::Run($form)
