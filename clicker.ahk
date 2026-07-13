#Requires AutoHotkey v2.0
#SingleInstance
CoordMode "Mouse", "Screen"

; F12 handled by Python via RegisterHotKey — see core/00_global_hotkey.py

; === Winsock TCP Client ===
WSAData := Buffer(400)
DllCall("ws2_32\WSAStartup", "UShort", 0x0202, "Ptr", WSAData)

PORT := A_Args.Length > 0 ? Integer(A_Args[1]) : 12345
HOST := 0x0100007F  ; 127.0.0.1
cmd_buffer := ""

while true {
    s := DllCall("ws2_32\socket", "Int", 2, "Int", 1, "Int", 0, "Ptr")
    if s = -1 {
        Sleep 1000
        continue
    }

    sockaddr := Buffer(16)
    NumPut("UShort", 2, sockaddr, 0)
    NumPut("UShort", DllCall("ws2_32\htons", "UShort", PORT, "UShort"), sockaddr, 2)
    NumPut("UInt", HOST, sockaddr, 4)

    if DllCall("ws2_32\connect", "Ptr", s, "Ptr", sockaddr, "Int", 16) = 0
        break

    DllCall("ws2_32\closesocket", "Ptr", s)
    Sleep 1000
}

; 設定接收超時 5 秒，recv 逾時時可檢查心跳
HEARTBEAT_TIMEOUT_MS := 30000
timeout_opt := 5000  ; SO_RCVTIMEO = 0x1006
DllCall("ws2_32\setsockopt", "Ptr", s, "Int", 1, "Int", 0x1006, "Int*", timeout_opt, "Int", 4)
last_cmd_time := A_TickCount
WSAETIMEDOUT := 10060

loop {
    buf := Buffer(4096)
    bytes := DllCall("ws2_32\recv", "Ptr", s, "Ptr", buf, "Int", 4095, "Int", 0, "Int")
    if bytes < 0
    {
        err := DllCall("ws2_32\WSAGetLastError")
        if err = WSAETIMEDOUT
        {
            if A_TickCount - last_cmd_time > HEARTBEAT_TIMEOUT_MS
            {
                ToolTip "心跳逾時，自動退出"
                Sleep 2000
                ToolTip
                ExitApp
            }
            continue
        }
        break
    }
    if bytes = 0
        break

    last_cmd_time := A_TickCount
    cmd_buffer .= StrGet(buf, bytes, "UTF-8")

    while InStr(cmd_buffer, "`n") {
        pos := InStr(cmd_buffer, "`n")
        cmd := Trim(SubStr(cmd_buffer, 1, pos - 1), "`r")
        cmd_buffer := SubStr(cmd_buffer, pos + 1)

        if cmd = "" {
            response := "OK`n"
            byteCount := StrPut(response, "UTF-8") - 1
            respBuf := Buffer(byteCount)
            StrPut(response, respBuf, byteCount, "UTF-8")
            DllCall("ws2_32\send", "Ptr", s, "Ptr", respBuf, "Int", byteCount, "Int", 0)
            continue
        }

        if cmd = "PING" {
            ; no action, just respond OK
        } else if cmd = "ESTOP" {
            Send "{Click Up}"
            Send "{LButton Up}"
            Send "{RButton Up}"
            Send "{MButton Up}"
            Send "{Control Up}"
            Send "{Shift Up}"
            Send "{Alt Up}"
            Send "{LWin Up}"
            Send "{RWin Up}"
        } else if SubStr(cmd, 1, 5) = "CLICK" {
            parts := StrSplit(cmd, ",")
            if parts.Length >= 4 {
                bx := Integer(parts[2])
                by := Integer(parts[3])
                btn := parts[4] = "right" ? "Right" : "Left"

                SendMode "Input"
                MouseMove bx, by, 0
                Sleep Random(10, 30)
                MouseClick btn, bx, by, 1, 0
                SendMode "Event"
            }
        } else if SubStr(cmd, 1, 4) = "MOVE" {
            parts := StrSplit(cmd, ",")
            if parts.Length >= 3 {
                MouseMove Integer(parts[2]), Integer(parts[3]), 0
            }
        } else if SubStr(cmd, 1, 3) = "KEY" {
            key := Trim(SubStr(cmd, 5))
            if key != "" {
                if RegExMatch(key, "[\^!+#]")
                    SendInput key
                else
                    SendInput "{" key "}"
            }
        } else if SubStr(cmd, 1, 4) = "DRAG" {
            parts := StrSplit(cmd, ",")
            if parts.Length >= 6 {
                x1 := Integer(parts[2]), y1 := Integer(parts[3])
                x2 := Integer(parts[4]), y2 := Integer(parts[5])
                btn := parts[6] = "right" ? "Right" : "Left"
                SendMode "Input"
                MouseMove x1, y1, 0
                MouseClick btn, x1, y1, 1, 0, "D"
                MouseMove x2, y2, 0
                MouseClick btn, x2, y2, 1, 0, "U"
                SendMode "Event"
            }
        } else if SubStr(cmd, 1, 6) = "SCROLL" {
            parts := StrSplit(cmd, ",")
            if parts.Length >= 3 {
                amount := Integer(parts[2])
                dir := parts[3]
                loop amount {
                    Send "{" dir "}"
                    Sleep 30
                }
            }
        } else if SubStr(cmd, 1, 7) = "HOLDKEY" {
            parts := StrSplit(cmd, ",")
            if parts.Length >= 3 {
                k := parts[2]
                dur := Integer(parts[3])
                if RegExMatch(k, "[\^!+#]")
                    SendInput "{" SubStr(k, 2) " down}"
                else
                    SendInput "{" k " down}"
                if dur > 0 {
                    Sleep dur
                    if RegExMatch(k, "[\^!+#]")
                        SendInput "{" SubStr(k, 2) " up}"
                    else
                        SendInput "{" k " up}"
                }
            }
        }

        response := "OK`n"
        byteCount := StrPut(response, "UTF-8") - 1
        respBuf := Buffer(byteCount)
        StrPut(response, respBuf, byteCount, "UTF-8")
        DllCall("ws2_32\send", "Ptr", s, "Ptr", respBuf, "Int", byteCount, "Int", 0)
    }
}

DllCall("ws2_32\closesocket", "Ptr", s)
DllCall("ws2_32\WSACleanup")
