-- OBSplit second stream
-- Streams to a second platform at the same time as OBS's own stream, with its own encoder and bitrate
-- (for example YouTube on OBS's stream with AV1, Twitch here with H.264). Uses only OBS's built-in scripting.
--
-- OBSplit's helper writes the settings (data\multistream.json) and starts/stops this stream together with
-- OBS's Start Streaming button (or on its own with "Stop Twitch"). This script only builds the stream from
-- those settings and notes why it stopped (data\multistream_status.json).

obs = obslua

local OUT_NAME = "obsplit_second"
local CHECK_MS = 2000
local datadir = nil
local output, venc, aenc, service = nil, nil, nil, nil
local built_rev = nil

local function exists(path)
    local f = io.open(path, "r")
    if f then f:close() return true end
    return false
end

local function find_datadir()
    local here = script_path():gsub("/", "\\")
    for _, cand in ipairs({ here .. "..\\app\\", here }) do
        if exists(cand .. "server.py") then return cand .. "data\\" end
    end
    return nil
end

local function write_status(text)
    if not datadir then return end
    local f = io.open(datadir .. "multistream_status.json", "w")
    if f then f:write(text) f:close() end
end

local function json_str(s)
    s = tostring(s or ""):gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", " "):gsub("\r", " ")
    return '"' .. s .. '"'
end

local function release_all()
    if output then
        if obs.obs_output_active(output) then obs.obs_output_force_stop(output) end
        obs.obs_output_release(output)
    end
    if venc then obs.obs_encoder_release(venc) end
    if aenc then obs.obs_encoder_release(aenc) end
    if service then obs.obs_service_release(service) end
    output, venc, aenc, service = nil, nil, nil, nil
    built_rev = nil
end

-- why the second stream stopped (OBS's own codes), for the panels
local STOP_TEXT = {
    [0] = "stopped",
    [-1] = "the server address is wrong",
    [-2] = "couldn't connect to the server",
    [-3] = "the stream key was rejected",
    [-4] = "the connection dropped",
    [-5] = "the encoder failed",
    [-6] = "OBS ran out of memory",
    [-7] = "the stream failed to start",
    [-8] = "the encoder failed",
    [-9] = "the server isn't supported",
}

local function on_stop(cd)
    local code = obs.calldata_int(cd, "code")
    local err = ""
    if output then err = obs.obs_output_get_last_error(output) or "" end
    write_status('{"state":"stopped","code":' .. code .. ',"reason":' .. json_str(STOP_TEXT[code] or ("error " .. code)) ..
                 ',"detail":' .. json_str(err) .. ',"at":' .. os.time() .. '}')
end

local function on_start(cd)
    write_status('{"state":"live","code":0,"reason":"","detail":"","at":' .. os.time() .. '}')
end

local function build(cfg, rev)
    release_all()
    local server = obs.obs_data_get_string(cfg, "server")
    local key = obs.obs_data_get_string(cfg, "key")
    local enc_id = obs.obs_data_get_string(cfg, "encoder")
    if server == "" or key == "" or enc_id == "" then return end

    local ss = obs.obs_data_create()
    obs.obs_data_set_string(ss, "server", server)
    obs.obs_data_set_string(ss, "key", key)
    obs.obs_data_set_bool(ss, "use_auth", false)
    service = obs.obs_service_create("rtmp_custom", "obsplit_second_service", ss, nil)
    obs.obs_data_release(ss)

    local es = obs.obs_data_get_obj(cfg, "encoder_settings")
    venc = obs.obs_video_encoder_create(enc_id, "obsplit_second_video", es, nil)
    obs.obs_data_release(es)
    obs.obs_encoder_set_video(venc, obs.obs_get_video())
    local w, h = obs.obs_data_get_int(cfg, "width"), obs.obs_data_get_int(cfg, "height")
    if w > 0 and h > 0 then
        local ovi = obs.obs_video_info()
        if obs.obs_get_video_info(ovi) and (ovi.output_width ~= w or ovi.output_height ~= h) then
            obs.obs_encoder_set_scaled_size(venc, w, h)
            if obs.obs_encoder_set_gpu_scale_type then obs.obs_encoder_set_gpu_scale_type(venc, obs.OBS_SCALE_LANCZOS) end
        end
    end

    local as = obs.obs_data_create()
    obs.obs_data_set_int(as, "bitrate", obs.obs_data_get_int(cfg, "audio_bitrate") > 0 and obs.obs_data_get_int(cfg, "audio_bitrate") or 160)
    aenc = obs.obs_audio_encoder_create("ffmpeg_aac", "obsplit_second_audio", as, 0, nil)
    obs.obs_data_release(as)
    obs.obs_encoder_set_audio(aenc, obs.obs_get_audio())

    output = obs.obs_output_create("rtmp_output", OUT_NAME, nil, nil)
    obs.obs_output_set_video_encoder(output, venc)
    obs.obs_output_set_audio_encoder(output, aenc, 0)
    obs.obs_output_set_service(output, service)
    local sh = obs.obs_output_get_signal_handler(output)
    obs.signal_handler_connect(sh, "stop", on_stop)
    obs.signal_handler_connect(sh, "start", on_start)
    built_rev = rev
    obs.script_log(obs.LOG_INFO, "OBSplit second stream ready (" .. obs.obs_data_get_string(cfg, "name") .. ", " .. enc_id .. ")")
end

local function check()
    if not datadir then return end
    local path = datadir .. "multistream.json"
    if not exists(path) then
        if output and not obs.obs_output_active(output) then release_all() end
        return
    end
    local cfg = obs.obs_data_create_from_json_file(path)
    if not cfg then return end
    local enabled = obs.obs_data_get_bool(cfg, "enabled")
    local rev = obs.obs_data_get_int(cfg, "rev")
    if not enabled then
        if output and not obs.obs_output_active(output) then release_all() end
    elseif rev ~= built_rev and not (output and obs.obs_output_active(output)) then
        build(cfg, rev)   -- new settings: rebuild, but never in the middle of a stream
    end
    obs.obs_data_release(cfg)
end

function script_description()
    return [[<b>OBSplit second stream</b><br>
Streams to YouTube and Twitch at the same time, each with its own settings. Turn it on with the
<b>YouTube + Twitch</b> button in OBSplit's panels.]]
end

function script_load(settings)
    datadir = find_datadir()
    if not datadir then
        obs.script_log(obs.LOG_WARNING, "OBSplit: app folder not found next to this script")
        return
    end
    check()
    obs.timer_add(check, CHECK_MS)
end

function script_unload()
    obs.timer_remove(check)
    release_all()
end
