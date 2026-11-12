# Changelog

## 0.2.1 (2026-11-11)

- **Switching between YouTube and Twitch also switches stream quality**, using the choice you made for each platform (for example H.264 at Twitch's limits, AV1 for YouTube). Never while you're live.
- **Restart OBS now:** when a new video format needs OBS to restart, Stream quality offers a button that closes and reopens OBS for you, keeping your panel layout.
- The helper finishes its after-OBS work (layout lock, scene order) a few seconds after OBS closes, instead of up to a minute later.

## 0.2.0 (2026-11-11)

- **Twitch support.** Chat+, Stream Info and Stats+ get a YouTube and a Twitch button; clicking one switches them (and the account part of OBSplit Setup) to that platform. Twitch chat with badges, emotes, bits, subs, gifted subs, raids and new follows, plus moderation; title, category and tags; your Twitch stream key into OBS; viewers, followers, bits and subs. Sign in with a short code at twitch.tv/activate, or read a channel's chat without signing in. Stream quality uses Twitch's limits when Twitch is selected. Switching also points OBS's stream key at that platform (never while you're live), so Start Streaming goes where you're looking. Stream quality warns when OBS is set to AV1 or HEVC while Twitch is selected (Twitch takes H.264 from OBS).
- **Panels renamed** for both platforms: YT Chat is now **Chat+**, YT Stream Info **Stream Info**, YT Stats **Stats+**. Existing docks keep their names; the installer uses the new ones.
- **Update notice:** OBSplit Setup tells you when a newer version is on GitHub, with what's new and a Download button (it checks once a day).
- Reinstalling or upgrading keeps OBSplit's scripts as they were in OBS (their order and any settings), instead of adding them again.

## 0.1.0 (2026-11-11)

First release.

### Scenes+
- Scene thumbnails; click to switch (Studio Mode: click = preview, double-click = switch). The current scene is tagged CURRENT.
- Drag scenes to reorder (OBS's own list follows after OBS closes), + Scene, rename and delete.
- Per-scene mic and desktop audio switches.

### Sources+
- The current scene's sources with show/hide, lock, move, properties and filters.
- Always on top / always at bottom layers that hold in every scene.
- + Game (picture and sound in one source), + Discord (works before Discord is open), + Screen region (drag a box or click a window) and + More, to one scene or all scenes.

### Audio+
- Simple mixer with live meters, an "On stream" switch and a "Recording" dropdown named after what's on each track; hides sources that can't make sound.
- Mic settings in plain language: device, boost, noise gate, noise removal, "even out my voice", clipping protection.
- Mix check: "Keep my voice on top" (steady, never rises when you stop talking), a live voice-vs-everything-else reading, a 15-second "hear what viewers hear" recording, optional "Dip game while I talk", per-game volume memory.

### YouTube
- YT Chat: real-time chat with badges, emoji, Super Chats, memberships, highlights, first-time chatter tags, user cards with history, delete / time-out / ban / unban / make moderator, @name completion. Your messages appear instantly.
- YT Stream Info: edit title, description, category, visibility, tags and thumbnail at any time, including while live. **+ New** creates a stream (now or scheduled, Low latency by default) linked to your stream key, so Start Streaming in OBS goes straight live; **Use in OBS** puts your YouTube stream key into OBS without copy-pasting. Leftover stream keys from XSplit and Restream are folded out of the way.
- YT Stats: viewers, peak, uptime, likes, chat speed, chatters, Super Chat totals, new members, stream health, API usage.
- Public and unlisted streams are both found automatically.

### OBSplit Setup
- **Stream quality:** Recommended / Sharper (1440p) / Light (720p). Picks the best video format your graphics card supports (AV1, HEVC or H.264), a bitrate from YouTube's table that fits your upload, 2-second keyframes, constant bitrate, Limited color range and OBS's automatic bitrate drop. Upload test with M-Lab's open speed test, or type your upload in. Checks every stream afterwards and adjusts the bitrate for next time. Only changes settings while you're not live; Undo puts your old settings back exactly.
- Step-by-step YouTube connection with your own free Google API key.
- **Lock my panel layout:** your exact layout and window size are put back every time OBS closes.

### Under the hood
- Auto Audio Setup OBS script: new media, browser and capture-card sources get the right audio settings.
- Panels keep their content and reconnect on their own; the launcher (plus a backup launcher) restarts the helper automatically, quietly.
- Windows installer with a bundled Python. Connecting to OBS keeps any panels you already have where they are, backs up every OBS file it touches, and uninstalling reverses it.
