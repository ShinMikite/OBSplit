-- OBSplit launcher
-- Starts the local panel server (hidden, no console window) when OBS starts.
-- The server shuts itself down about a minute after OBS closes.

obs = obslua
local ffi = require("ffi")

ffi.cdef[[
void* ShellExecuteA(void* hwnd, const char* op, const char* file, const char* params, const char* dir, int show);
void Sleep(uint32_t ms);
]]
local shell32 = ffi.load("shell32")

local APP = os.getenv("LOCALAPPDATA") .. "\\OBSplit"
local DEFAULT_PY = APP .. "\\python\\pythonw.exe"  -- Python bundled by the OBSplit installer
local python = DEFAULT_PY

function script_description()
    return [[<b>OBSplit</b><br>
Starts the OBSplit panels with OBS.<br>
Panels are in the <b>Docks</b> menu (YT Chat, YT Stream Info, YT Stats, Scenes+, Audio+, OBSplit Setup).]]
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_path(p, "python", "pythonw.exe", obs.OBS_PATH_FILE, "pythonw.exe", nil)
    return p
end

function script_defaults(s)
    obs.obs_data_set_default_string(s, "python", DEFAULT_PY)
end

function script_update(s)
    local p = obs.obs_data_get_string(s, "python")
    if p ~= nil and p ~= "" then python = p end
end

local function exists(path)
    local f = io.open(path, "r")
    if f then f:close() return true end
    return false
end

function script_load(s)
    script_update(s)
    if not exists(python) then
        obs.script_log(obs.LOG_WARNING, "pythonw.exe not found at " .. python .. " (set it in this script's settings)")
        return
    end
    local ready = APP .. "\\app\\data\\ready"
    os.remove(ready)
    local params = '"' .. APP .. '\\app\\server.py" --with-obs'
    local r = shell32.ShellExecuteA(nil, "open", python, params, APP, 0)
    -- wait (max 4 s) so the panels find the server when OBS creates them
    for _ = 1, 40 do
        if exists(ready) then break end
        ffi.C.Sleep(100)
    end
    obs.script_log(obs.LOG_INFO, "panel server " .. (exists(ready) and "ready" or "not ready yet") ..
        " (ShellExecute=" .. tostring(tonumber(ffi.cast("intptr_t", r))) .. ")")
end
