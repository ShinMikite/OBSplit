# OBSplit

**Make OBS Studio feel like XSplit.**

OBSplit adds a set of panels to OBS Studio for people coming from XSplit: one-click game, Discord and screen-region sources, scene thumbnails, a simpler audio mixer, and a full YouTube toolkit (chat, moderation, title and thumbnail editing while live, and stream stats).

It isn't an OBS plugin. Everything uses features OBS already has: custom browser docks, the built-in Lua scripting and the built-in WebSocket server. A small local helper program runs while OBS is open and closes itself after OBS closes.

---

## Features

### Scenes+
- **Scene thumbnails** for every scene. Click one to switch to it. This only changes scenes; **Start Streaming** in OBS still decides when you're live. Studio Mode is supported (click = preview, double-click = switch).
- **＋ Game:** pick a running game and get **one source with picture and sound together**, fitted to the screen and placed under your alerts. It follows the game by its program file, so changing window titles don't break it. You can also switch an existing game source to a different game.
- **＋ Discord:** adds Discord voice audio in one click and reuses your existing Discord source instead of creating duplicates. It also fixes OBS's default matching, which can latch onto Chrome or other apps when your Discord channel changes.
- **＋ Screen region:** your screen dims. **Drag a box** or **click a window** and you get a Display Capture cropped to exactly that area. You can re-select the area later.
- **Per-scene audio:** small 🎙 / 🔈 switches on each scene. For example, mute the mic automatically whenever you switch to your "Starting soon" scene.
- Scenes that are black when they aren't showing, such as videos that only play while their scene is on screen, show the last picture from when they were.

### Audio+
- A simpler mixer: mute, volume with a live meter, and **🎧 Hear** (play it in your headphones).
- Instead of OBS's track grid, each source has an **On stream** switch and a **Recording** dropdown named after what's on each track (Mic, Game, Discord…).
- **Mix check:**
  - **Keep my voice on top:** one switch keeps everything else on the stream at least 6–16 dB below your voice (you choose), all the time and for anything you add later. Nothing gets louder when you stop talking, and it remembers your usual voice level so it works through quiet stretches. Turning it off puts your volumes back.
  - **Right now:** a live reading of your voice vs. everything else, measured after volumes and filters, exactly as viewers get it.
  - **Hear what viewers hear:** records 15 seconds of only the stream audio and plays it back in the panel. Your recording settings are put back and the test file is deleted afterwards.
  - **Dip game while I talk** (optional): game and music dip while you speak, using OBS's own Compressor keyed to your mic.
  - Volumes you set for a game are remembered per game.
- **This scene** shows only what's in the current scene (plus mic and desktop audio). Sources that can't make sound are tucked away, including videos whose soundtrack turns out to be silent.

### YouTube
- **YT Chat**, a Chatty-style chat:
  - every message in real time (not the filtered "Top chat"), with badges, emoji, Super Chats, stickers, memberships and gifted memberships as cards
  - a **FIRST** tag on someone's first message ever in your chat
  - your name and chosen words highlighted, plus a filter box
  - hover a message to delete it, time the user out or ban them
  - click a name for a user card: their message history across streams, time-outs from 10 s to 24 h, ban/unban, make moderator
  - Tab completes @names
- **YT Stream Info:** picks your live or next scheduled stream automatically. Edit the **title, description, category, visibility, tags and thumbnail at any time, including while live.** Drag and drop a thumbnail to upload it.
- **YT Stats:** viewers (and peak), uptime, likes, chat per minute, chatters, first-timers, Super Chat totals, new members, **stream health** with YouTube's warnings, and API usage.

### Auto Audio Setup (OBS script)
New media, browser and capture-card sources automatically get **Monitor and Output**. New browser sources (alerts) get **Control audio via OBS**, so alert sounds actually reach your stream. Mic, desktop, game and app audio are left alone to avoid echo.

---

## Requirements

- Windows 10 or 11 (64-bit)
- OBS Studio 30 or newer
- Optional, for YouTube sending, moderation, editing and stats: a free Google API key for your own account. The setup panel walks you through it in about 5 minutes. Reading chat works without it.

## Install

1. Download **`OBSplit-Setup-x.y.z.exe`** from [Releases](https://github.com/ShinMikite/OBSplit/releases).
2. **Close OBS**, then run the installer. No admin rights are needed; it installs to `%LOCALAPPDATA%\OBSplit`.
   Windows may show "Windows protected your PC" because the installer isn't code-signed yet. Click **More info → Run anyway**.
3. Start OBS. The new panels are in the **Docks** menu: **YT Chat, YT Stream Info, YT Stats, Scenes+, Audio+, OBSplit Setup**. Drag them where you like, then use **Docks → Lock Docks**.
4. Open **OBSplit Setup** for the optional YouTube connection.

### What the installer changes in OBS

To be transparent, here is everything it does:

| Change | Why |
|---|---|
| Turns on OBS's built-in **WebSocket server** (password-protected; a random password is created if you don't have one) | Scenes+ and Audio+ talk to OBS through it |
| Adds 6 **custom browser docks** (all pointing to `http://127.0.0.1:47821`) | The panels |
| Adds 2 scripts to each **scene collection** (`obsplit-launcher.lua`, `auto-audio-setup.lua`) | Starts the helper with OBS; auto audio setup |

A backup of every OBS file it touches is saved to `%APPDATA%\obs-studio\obsplit-backups\` first. **Uninstalling reverses all of it**, including switching the WebSocket server back off if it was off before. To reconnect later, for example after creating a new scene collection, use **Start menu → OBSplit → OBSplit - Connect to OBS**.

## YouTube setup (optional)

Open the **OBSplit Setup** panel. It links straight to each page:

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Set up the sign-in screen (External) and **Publish** it. Otherwise Google signs you out every 7 days.
3. Create an OAuth client of type **Desktop app**, download the JSON and drop it on the setup panel.
4. Click **Connect YouTube account**. Google will say the app isn't verified; that's expected for your own app (**Advanced → Go to OBSplit**).

Each user brings their own key, so everyone gets their own free daily allowance (10,000 units). Reading chat uses none. Typical costs: send a message 20, delete 25, time-out or ban 200, save stream info 51, thumbnail 50, stats about 240 an hour while live.

## Privacy

- Everything runs on your PC, on `127.0.0.1`. Nothing is sent anywhere except to YouTube and Google.
- Chat is read from YouTube's public live-chat page, the same way the pop-out chat works.
- Your sign-in, settings and chat history are stored in `%LOCALAPPDATA%\OBSplit\app\data`. The uninstaller asks whether to delete them.

## Coming from XSplit?

See **[docs/xsplit-to-obs.md](docs/xsplit-to-obs.md)**: where XSplit's features live in OBS, plus recommended audio and encoder settings.

## Troubleshooting

| Problem | Fix |
|---|---|
| Panels say **"Panel server not running"** | Check **Tools → Scripts** lists `obsplit-launcher.lua`. If not, run **OBSplit - Connect to OBS** with OBS closed. |
| Scenes+ / Audio+ say **"OBS offline"** | **Tools → WebSocket Server Settings**: make sure the server is enabled. |
| Panels are missing after creating a new scene collection | Close OBS and run **OBSplit - Connect to OBS**. |
| Game not in the ＋ Game list | Start the game first, then click ⟳. Games under a Steam/Epic/GOG/Xbox library or running fullscreen are listed first; everything else is under "Other windows". |

## Building from source

```powershell
./installer/build.ps1 -Version 0.1.0          # needs Python 3.11+ and Inno Setup 6
./installer/build.ps1 -Version 0.1.0 -RuntimeOnly
```

Pushing a tag like `v0.1.0` builds the installer on GitHub Actions and attaches it to a release.

To run from source without installing: `python app/server.py`, then add the dock URLs from the setup panel in **Docks → Custom Browser Docks**.

## License

[MIT](LICENSE)
