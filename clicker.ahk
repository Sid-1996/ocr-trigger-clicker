#Requires AutoHotkey v2.0
#SingleInstance
CoordMode "Mouse", "Screen"

; === Winsock TCP Client ===
WSAData := Buffer(400)
DllCall("ws2_32\WSAStartup", "UShort", 0x0202, "Ptr", WSAData)

PORT := 12345
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

loop {
    buf := Buffer(4096)
    bytes := DllCall("ws2_32\recv", "Ptr", s, "Ptr", buf, "Int", 4095, "Int", 0, "Int")
    if bytes <= 0
        break

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
