# Changelog

## Unreleased

- **Audio+ → Mix check:** "Keep my voice on top" (steady, never rises when you stop talking), live voice-vs-everything-else reading, 15-second "hear what viewers hear" check recording, optional "Dip game while I talk", per-game volume memory.
- **Audio+:** clearer controls: "On stream" switch and a "Recording: Mic / Game / Discord / off" dropdown replace the Rec 2/3/4 chips and the legend line.
- **Scenes+:** clicking a scene says "switch", not "go live"; the current scene is tagged CURRENT.
- **Sources+** (new panel): the current scene's sources with show/hide, lock, move, properties and filters; **📌 always on top / always at bottom** layers that hold in every scene; ＋ Game, ＋ Discord, ＋ Screen region and ＋ More (common source types or an existing source), to one scene or all scenes. The add buttons moved here from Scenes+.
- **＋ Discord** works before Discord is open.
- **Scenes+:** drag scenes to reorder (OBS's own list follows after OBS closes), + Scene, rename and delete.
- **Look:** simple single-colour line icons like OBS's own instead of emoji, a plain status dot instead of a badge, quieter tags.
- **Fix: buttons stopped responding** once 7 panels were open. Panels now get live updates over WebSockets, which don't use up the browser's limit of 6 connections per address; leftover request data can no longer break the next click.
- **Layout lock** (OBSplit Setup): saves your exact panel layout and window size when OBS closes, then puts them back every time OBS closes if anything changed them. The locked layout is also used for OBS's account-specific (e.g. YouTube) layout.
- **Audio+ → ⚙ Mic:** pick the microphone and adjust boost, noise gate, noise removal, "even out my voice" and clipping protection in plain language, with a live level meter.
- **Reliability:** panels keep their content and show "Reconnecting…" during a hiccup instead of an error; the launcher restarts the helper automatically if it stops or freezes; background tasks can no longer stop silently.

## 0.1.0 (2026-11-11)

First release.

- **Scenes+:** scene thumbnails, one-click ＋ Game / ＋ Discord / ＋ Screen region, per-scene mic and desktop audio switches, Studio Mode support.
- **Audio+:** simple mixer with Stream / Rec / monitor switches, live meters; hides sources that can't make sound.
- **YT Chat:** real-time chat with badges, emoji, Super Chats, memberships, highlights, first-time chatter tags, user cards with history, delete / time-out / ban / unban / make moderator, @name completion.
- **YT Stream Info:** edit title, description, category, visibility, tags and thumbnail at any time, including while live.
- **YT Stats:** viewers, peak, uptime, likes, chat speed, chatters, Super Chat totals, new members, stream health, API usage.
- **Auto Audio Setup** OBS script.
- Windows installer that connects OBSplit to OBS (and disconnects it on uninstall) with automatic backups.
