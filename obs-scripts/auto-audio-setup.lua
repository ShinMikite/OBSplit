-- Auto Audio Setup
-- Makes new sources' audio work like XSplit: no manual trips to Advanced Audio Properties.
--  * New media / music / video files, VLC playlists, browser sources and capture cards
--    get "Monitor and Output" so you hear them AND they go to the stream.
--  * New browser sources get "Control audio via OBS" turned on, so alert/widget sounds
--    actually reach the stream instead of disappearing into (muted) Desktop Audio.
-- Mic, Desktop Audio, Application Audio and Game/Window capture are left alone:
-- you already hear those directly, so monitoring them would cause echo/double audio.
-- Existing sources are never changed; only sources created after OBS has loaded.

obs = obslua

local MONITORED = {
    ffmpeg_source  = true, -- Media Source (music, videos, sfx)
    vlc_source     = true, -- VLC Video Source (playlists)
    browser_source = true, -- alerts, widgets, wheels
    dshow_input    = true, -- Video Capture Device (capture cards, consoles)
}

local enabled_monitor = true
local enabled_browser = true
local loading = true  -- stays true until OBS has finished loading saved sources

function script_description()
    return [[<b>Auto Audio Setup</b><br>
New media, browser and capture-card sources automatically get
<i>Monitor and Output</i>, and new browser sources get <i>Control audio via OBS</i>.<br>
Mic, desktop, app and game audio are left alone (you already hear those).<br>
Existing sources are never changed.]]
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_bool(p, "monitor", "Turn on monitoring for new media / browser / capture card sources")
    obs.obs_properties_add_bool(p, "browser_audio", "Route new browser source audio through OBS")
    return p
end

function script_defaults(s)
    obs.obs_data_set_default_bool(s, "monitor", true)
    obs.obs_data_set_default_bool(s, "browser_audio", true)
end

function script_update(s)
    enabled_monitor = obs.obs_data_get_bool(s, "monitor")
    enabled_browser = obs.obs_data_get_bool(s, "browser_audio")
end

local function on_source_create(cd)
    if loading then return end
    local source = obs.calldata_source(cd, "source")
    if source == nil then return end
    if obs.obs_source_get_type(source) ~= obs.OBS_SOURCE_TYPE_INPUT then return end
    local id = obs.obs_source_get_unversioned_id(source)
    if not MONITORED[id] then return end

    if id == "browser_source" and enabled_browser then
        local settings = obs.obs_source_get_settings(source)
        if not obs.obs_data_get_bool(settings, "reroute_audio") then
            obs.obs_data_set_bool(settings, "reroute_audio", true)
            obs.obs_source_update(source, settings)
        end
        obs.obs_data_release(settings)
    end

    if enabled_monitor and obs.obs_source_get_monitoring_type(source) == obs.OBS_MONITORING_TYPE_NONE then
        obs.obs_source_set_monitoring_type(source, obs.OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT)
        obs.script_log(obs.LOG_INFO, "monitoring enabled for new source '" .. (obs.obs_source_get_name(source) or "?") .. "' (" .. id .. ")")
    end
end

local function on_frontend_event(event)
    if event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGING
        or event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP then
        loading = true
    elseif event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED
        or event == obs.OBS_FRONTEND_EVENT_FINISHED_LOADING then
        loading = false
    end
end

local function scenes_exist()
    local scenes = obs.obs_frontend_get_scenes()
    local n = scenes and #scenes or 0
    if scenes then obs.source_list_release(scenes) end
    return n > 0
end

function script_load(s)
    -- At OBS startup / collection switch this runs BEFORE saved sources load (no scenes yet),
    -- so we wait for FINISHED_LOADING / SCENE_COLLECTION_CHANGED. If the script is added
    -- by hand mid-session, scenes already exist and it's active right away.
    loading = not scenes_exist()
    obs.signal_handler_connect(obs.obs_get_signal_handler(), "source_create", on_source_create)
    obs.obs_frontend_add_event_callback(on_frontend_event)
    obs.script_log(obs.LOG_INFO, "Auto Audio Setup loaded")
end
