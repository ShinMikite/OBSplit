-- OBSplit launcher
-- Starts the OBSplit helper (hidden, no console window) when OBS starts, and keeps it running:
-- every few seconds it checks the helper's heartbeat and restarts it if it ever stops answering.
-- The helper shuts itself down about a minute after OBS closes.

obs = obslua
local ffi = require("ffi")

ffi.cdef[[
void* ShellExecuteA(void* hwnd, const char* op, const char* file, const char* params, const char* dir, int show);
void Sleep(uint32_t ms);
void* OpenProcess(uint32_t access, int inherit, uint32_t pid);
int GetExitCodeProcess(void* process, uint32_t* code);
int CloseHandle(void* handle);
]]
local shell32 = ffi.load("shell32")

local python, server, appdir, datadir = nil, nil, nil, nil
local last_launch = 0
local CHECK_MS = 3000      -- how often to check the helper
local STALE_S = 7          -- heartbeat older than this = not answering (it beats every 2 s)
local RETRY_S = 10         -- don't restart more often than this

local function exists(path)
    local f = io.open(path, "r")
    if f then f:close() return true end
    return false
end

-- Is the helper process (pid in data\server.pid) actually running right now?
local function helper_running()
    if not datadir then return false end
    local f = io.open(datadir .. "server.pid", "r")
    if not f then return false end
    local pid = tonumber(f:read("*l") or "")
    f:close()
    if not pid then return false end
    local h = ffi.C.OpenProcess(0x1000, 0, pid)   -- PROCESS_QUERY_LIMITED_INFORMATION
    if h == nil then return false end
    local code = ffi.new("uint32_t[1]")
    local ok = ffi.C.GetExitCodeProcess(h, code)
    ffi.C.CloseHandle(h)
    return ok ~= 0 and code[0] == 259              -- STILL_ACTIVE
end

local function find_files(settings_python)
    local here = script_path():gsub("/", "\\")
    -- installed layout: <app>\obs-scripts\this.lua + <app>\app\server.py ; flat layout: server.py next to this
    for _, cand in ipairs({ here .. "..\\app\\", here }) do
        if exists(cand .. "server.py") then
            server = cand .. "server.py"
            datadir = cand .. "data\\"
            appdir = cand
            break
        end
    end
    local tries = {}
    if settings_python and settings_python ~= "" then table.insert(tries, settings_python) end
    table.insert(tries, here .. "..\\python\\pythonw.exe")       -- bundled by the installer
    local la = os.getenv("LOCALAPPDATA") or ""
    for v = 314, 311, -1 do table.insert(tries, la .. "\\Programs\\Python\\Python" .. v .. "\\pythonw.exe") end
    python = nil
    for _, p in ipairs(tries) do
        if exists(p) then python = p break end
    end
end

local function launch(wait)
    if not (python and server) then return end
    last_launch = os.time()
    local ready = datadir .. "ready"
    if wait then os.remove(ready) end
    shell32.ShellExecuteA(nil, "open", python, '"' .. server .. '" --with-obs', appdir, 0)
    if wait then
        -- wait (max 4 s) so the panels find the helper when OBS creates them
        for _ = 1, 40 do
            if exists(ready) then break end
            ffi.C.Sleep(100)
        end
    end
end

local function heartbeat_age()
    local f = io.open(datadir .. "heartbeat", "r")
    if not f then return 9999 end
    local t = tonumber(f:read("*l") or "")
    f:close()
    if not t then return 9999 end
    return os.time() - t
end

local function watchdog()
    if not (python and server) then return end
    if heartbeat_age() > STALE_S and os.time() - last_launch > RETRY_S then
        obs.script_log(obs.LOG_WARNING, "OBSplit helper not answering; restarting it")
        launch(false)
    end
end

function script_description()
    return [[<b>OBSplit</b><br>
Starts the OBSplit panels with OBS and restarts them automatically if they ever stop.<br>
Panels are in the <b>Docks</b> menu (YT Chat, YT Stream Info, YT Stats, Scenes+, Audio+, OBSplit Setup).]]
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_path(p, "python", "pythonw.exe (leave empty to find it automatically)",
        obs.OBS_PATH_FILE, "pythonw.exe", nil)
    return p
end

function script_update(s)
    find_files(obs.obs_data_get_string(s, "python"))
end

function script_load(s)
    find_files(obs.obs_data_get_string(s, "python"))
    if not server then
        obs.script_log(obs.LOG_WARNING, "OBSplit: server.py not found next to this script")
        return
    end
    if not python then
        obs.script_log(obs.LOG_WARNING, "OBSplit: pythonw.exe not found (set it in this script's settings)")
        return
    end
    launch(true)
    obs.script_log(obs.LOG_INFO, "OBSplit helper " .. (exists(datadir .. "ready") and "ready" or "starting"))
    obs.timer_add(watchdog, CHECK_MS)
end

function script_unload()
    obs.timer_remove(watchdog)
end
