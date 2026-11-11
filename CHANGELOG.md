# Changelog

## Unreleased

- **Stream quality** (first section of OBSplit Setup): one choice (Recommended / Sharper 1440p / Light 720p) sets the best video format your graphics card supports (AV1, HEVC or H.264), a bitrate from YouTube's table that fits your upload, 2-second keyframes, constant bitrate, Limited color range and OBS's automatic bitrate drop. Optional upload test with M-Lab's open speed test (the one Google's speed test uses), or type in your upload from any speed test. After each stream it checks dropped frames and YouTube's stream health and adjusts the bitrate for next time. Only changes settings while you're not live; your old settings are saved first and **Undo** puts them back exactly.

- **Audio+ → Mix check:** "Keep my voice on top" (steady, never rises when you stop talking), live voice-vs-everything-else reading, 15-second "hear what viewers hear" check recording, optional "Dip game while I talk", per-game volume memory.
- **Audio+:** clearer controls: "On stream" switch and a "Recording: Mic / Game / Discord / off" dropdown replace the Rec 2/3/4 chips and the legend line.
- **Scenes+:** clicking a scene says "switch", not "go live"; the current scene is tagged CURRENT.
- **Sources+** (new panel): the current scene's sources with show/hide, lock, move, properties and filters; **📌 always on top / always at bottom** layers that hold in every scene; ＋ Game, ＋ Discord, ＋ Screen region and ＋ More (common source types or an existing source), to one scene or all scenes. The add buttons moved here from Scenes+.
- **＋ Discord** works before Discord is open.
- **Backup launcher:** a second, independent OBS script starts the helper before the panels load if the main launcher can't be loaded (for example, its file is briefly locked while OBS starts), so the panels never open to "Couldn't load that page".
- **+ New: Low latency by default** (about 5–10 s behind instead of up to a minute with Normal). Each option now says roughly how far behind viewers will be; your choice is remembered once you pick one yourself.
- **YT Chat: instant sending.** Your message appears the moment you press Enter (dimmed until YouTube confirms it), and chat checks for new messages every half second for a few seconds after you send. If sending fails, your text is put back in the box.
- **Quieter launcher:** a routine helper restart no longer pops up OBS's Script Log window. It only warns, once, if the helper keeps stopping (4 times within a minute).
- **Fix: panels said Live for a stream that hadn't started.** Right after creating a stream, YouTube's public page can briefly look live; OBSplit now treats "upcoming" correctly and, when YouTube is connected, confirms with YouTube before showing Live (at most once a minute while live, every 10 minutes while upcoming).
- **Fix: the thumbnail file picker opened on a strange "PJP File" filter.** It now shows JPG and PNG files plainly.
- **Fix: unlisted streams showed as offline** and their chat didn't load. YouTube's public "live" page only shows public streams; while OBS is streaming, OBSplit now also asks YouTube directly (1 unit a minute) and finds unlisted streams too.
- **Stream keys list:** your own keys come first; the dozens of leftover keys XSplit and Restream created (one per stream) are folded behind one "Show older keys" entry, with plain labels like "Made by Restream, May 15, 2023".
- **Stream keys:** if YouTube has a server hiccup while listing your stream keys, OBSplit asks again with fewer details instead of showing an error.
- **Fix: privacy and title changes looked like they failed.** YT Stream Info now shows what YouTube confirmed when saving, instead of re-reading right away and briefly getting the old values. **+ New** no longer says "Couldn't find that stream" when YouTube takes a few seconds to list a stream it just created.
- **OBSplit Setup:** Chat source shows as done once it knows your channel; the setup steps explain what to do when Google's **Publish app** button is greyed out.
- **YT Stream Info → + New:** create a stream (now or scheduled) with all its settings, linked to your stream key, so Start Streaming in OBS goes straight live; **Use in OBS** puts your YouTube stream key into OBS without copy-pasting.
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
