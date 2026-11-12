# OBSplit

**Make OBS Studio feel like XSplit.**

OBSplit adds a set of panels to OBS Studio for people coming from XSplit: one-click game, Discord and screen-region sources, scene thumbnails, a simpler audio mixer that keeps your voice on top, and a full YouTube and Twitch toolkit (set up streams, chat, moderation, title and thumbnail editing while live, and stream stats), all without opening a browser.

It isn't an OBS plugin. Everything uses features OBS already has: custom browser docks, the built-in Lua scripting and the built-in WebSocket server. A small local helper program runs while OBS is open and closes itself after OBS closes. If it ever stops, OBS restarts it within a few seconds, and the panels keep their content while it reconnects.

---

## Features

### Scenes+
- **Scene thumbnails** for every scene. Click one to switch to it. This only changes scenes; **Start Streaming** in OBS still decides when you're live. Studio Mode is supported (click = preview, double-click = switch).
- **Drag to reorder** scenes, **+ Scene**, and right-click to **rename** or **delete**. OBS's own Scenes list follows the same order from the next time OBS starts (OBS can't reorder scenes while running, so OBSplit applies it right after OBS closes).
- **Per-scene audio:** small mic / speaker switches on each scene. For example, mute the mic automatically whenever you switch to your "Starting soon" scene.
- Scenes that are black when they aren't showing, such as videos that only play while their scene is on screen, show the last picture from when they were.

### Sources+
- The current scene's sources, top layer first, laid out like OBS's own list: show/hide, lock, move up/down (on hover), double-click for Properties, and a menu (Filters, bring to front, send to back, remove).
- **Pinned layers:** mark a source **Always on top** or **Always at bottom**. It stays there in **every scene**, whatever you add or move later. Useful for alerts on top and backgrounds at the bottom.
- **+ Game:** pick a running game and get **one source with picture and sound together**, fitted to the screen and placed under your alerts. It follows the game by its program file, so changing window titles don't break it. You can also switch an existing game source to a different game.
- **+ Discord:** adds Discord voice audio in one click, to one scene or **all scenes**, even before Discord is open. It reuses your existing Discord source instead of creating duplicates, and fixes OBS's default matching, which can latch onto Chrome or other apps when your Discord channel changes.
- **+ Screen region:** your screen dims. **Drag a box** or **click a window** and you get a Display Capture cropped to exactly that area. You can re-select the area later.
- **+ More:** image, media file, browser, text, color, slideshow, camera / capture card, window, display, audio input or app audio, opened straight into OBS's setup window. You can also add a source you already have (like OBS's "Paste (Reference)"), to one scene or all scenes.

### Audio+
- A simpler mixer: mute, volume with a live meter, and a headphones button (play it in your headphones).
- **Mic settings** (gear button on microphones): pick the device and set boost, noise gate, background-noise removal, "even out my voice" and clipping protection in plain language, with a live level meter.
- Instead of OBS's track grid, each source has an **On stream** switch and a **Recording** dropdown named after what's on each track (Mic, Game, Discord…).
- **Mix check:**
  - **Keep my voice on top:** one switch keeps everything else on the stream at least 6–16 dB below your voice (you choose), all the time and for anything you add later. Nothing gets louder when you stop talking, and it remembers your usual voice level so it works through quiet stretches. Turning it off puts your volumes back.
  - **Right now:** a live reading of your voice vs. everything else, measured after volumes and filters, exactly as viewers get it.
  - **Hear what viewers hear:** records 15 seconds of only the stream audio and plays it back in the panel. Your recording settings are put back and the test file is deleted afterwards.
  - **Dip game while I talk** (optional): game and music dip while you speak, using OBS's own Compressor keyed to your mic.
  - Volumes you set for a game are remembered per game.
- **This scene** shows only what's in the current scene (plus mic and desktop audio). Sources that can't make sound are tucked away, including videos whose soundtrack turns out to be silent.

### Controls+
- **Go live** with a button that says where it goes (YouTube, Twitch, or both) and shows what viewers will see on each: your YouTube stream's title and visibility, your Twitch title and category.
- **A check before going live**, with one-click fixes: Twitch in test mode, a muted mic, OBS pointed at the wrong platform, no YouTube stream waiting for your key, a Private YouTube stream, or OBS needing a restart for a new video format. They're warnings, not blocks.
- **While live:** a row per platform with a timer, a health dot and its own **Stop**, plus **Stop all**.
- Recording (start, pause, stop), Virtual Camera and Studio Mode. OBS's own Settings window stays in OBS's Controls panel.

### YouTube and Twitch
**Controls+** has a **YouTube**, a **Twitch** and a **YouTube + Twitch** button at the top. Clicking one switches Chat+, Stream Info and Stats+ (and the account part of OBSplit Setup) to that platform, and points OBS's stream key at it, so **Start Streaming** goes where you're looking (never while you're live). Scenes+, Sources+ and Audio+ are the same for both.

#### YouTube + Twitch at the same time
- Streams to both at once, **each with its own settings** (for example YouTube in AV1 at 10 Mbps and Twitch in H.264 at 6 Mbps). No Restream and no plugin: YouTube uses OBS's own stream and OBSplit adds a second one through OBS's built-in scripting.
- **Start Streaming** starts both. **Controls+** shows each stream (live time, health, and why one stopped if it did) with a **Stop** button for each; **Stats+** shows each platform's numbers inside shared tiles.
- **Chat+** shows both chats with a small logo on each message; send to both or just one. **Stream Info** has a tab for each.
- **OBSplit Setup** checks first: both streams together need roughly the sum of their bitrates in upload (about 16 Mbps by default) and a graphics-card encoder. If your upload is too slow, a service like Restream, which only needs one upload, is the better choice. You can also test Twitch without broadcasting.

#### YouTube
- **Chat+**, a Chatty-style chat:
  - every message in real time (not the filtered "Top chat"), with badges, emoji, Super Chats, stickers, memberships and gifted memberships as cards
  - a **FIRST** tag on someone's first message ever in your chat
  - your name and chosen words highlighted, plus a filter box
  - hover a message to delete it, time the user out or ban them
  - click a name for a user card: their message history across streams, time-outs from 10 s to 24 h, ban/unban, make moderator
  - Tab completes @names
- **Set up a new stream without a browser (+ New):** title, description, category, tags, visibility, "go live when I press Start Streaming" or schedule for later, Made for Kids, auto-start/stop, latency and DVR, pre-filled from your last stream. It's linked to your stream key automatically, so **Start Streaming in OBS goes straight live**.
- **Use my YouTube stream key in OBS:** one click puts your reusable YouTube stream key into OBS's stream settings (or creates one). The key goes from YouTube straight into OBS; it's never shown.
- **Stream Info:** picks your live or next scheduled stream automatically. Edit the **title, description, category, visibility, tags and thumbnail at any time, including while live.** Drag and drop a thumbnail to upload it.
- **Stats+:** viewers (and peak), likes, chat per minute, chatters, first-timers, Super Chat totals, new members, and **stream health** with YouTube's warnings. (How long you've been live is in Controls+; API usage is in OBSplit Setup.)

#### Twitch
- **Chat+:** Twitch chat in real time with badges (broadcaster, mod, VIP, subscriber), Twitch emotes, bits, and cards for subs, gifted subs, raids and new follows. First-time chatters are tagged. Delete, time-out, ban, unban and make moderator, same as for YouTube. Chat can be read without signing in by entering a channel name.
- **Stream Info:** change your **title, category** (with search) and **tags** at any time, including while live. **Use my Twitch key in OBS** puts your stream key into OBS without copy-pasting.
- **Stats+:** viewers (and peak), followers (and new this session), chat per minute, chatters, bits, new subs and total subscribers.
- Signing in takes a few seconds: click **Connect Twitch** in OBSplit Setup and enter the code shown at twitch.tv/activate. No developer setup, and no daily limits.

### OBSplit Setup
- Connecting YouTube (one-time setup, see below) or Twitch (enter a short code), and the channel to read chat from before you connect.
- **Stream quality:** pick **Recommended for my PC**, **Sharper on YouTube (1440p)** or **Light (720p)** and click Apply. With Twitch selected it uses Twitch's limits instead (H.264, up to 6 Mbps at 1080p). OBSplit chooses the best video format your graphics card supports (AV1, then HEVC, then H.264), a bitrate from YouTube's own table that fits your connection, 2-second keyframes, constant bitrate, Limited color range (what YouTube expects) and OBS's automatic bitrate drop when the connection struggles. **Test my upload** measures your upload speed with M-Lab's open speed test (or type in your speed from any test) so the bitrate fits. After every stream it checks dropped frames, encoder overload and YouTube's stream health, and lowers the bitrate for next time if your connection struggled (or eases it back up after smooth streams). It only changes settings while you're not live, saves your old settings first and has an **Undo**. OBS only switches its video format when it starts, so OBSplit offers a **Restart OBS now** button that closes and reopens OBS for you, keeping your layout. Switching between YouTube and Twitch switches stream quality too, using your choice for each platform.
- **Update notice:** when a newer OBSplit is released, Setup shows what's new and a **Download** button. Close OBS and run the new installer; your panels, layout, sign-ins and settings are kept.
- **Keep my panel layout:** arrange your panels, click **Keep my layout**, and close OBS once. After that, OBS's own **View → Docks → Lock Docks** decides what happens: while it's on, OBSplit puts your exact layout and window size back every time OBS closes, so it can't be lost to a reset or a connected account's separate layout; turn it off to rearrange, and the layout you close OBS with is kept. No extra saving needed.

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
3. Start OBS. The new panels are in the **Docks** menu: **Chat+, Stream Info, Stats+, Scenes+, Sources+, Audio+, Controls+, OBSplit Setup**. Drag them where you like.
4. In **OBSplit Setup**, click **Keep my layout** once you're happy with the arrangement, then turn on **View → Docks → Lock Docks** in OBS, and connect YouTube if you want the YouTube features.

### What the installer changes in OBS

To be transparent, here is everything it does:

| Change | Why |
|---|---|
| Turns on OBS's built-in **WebSocket server** (password-protected; a random password is created if you don't have one) | Scenes+, Sources+ and Audio+ talk to OBS through it |
| Adds 7 **custom browser docks** (all pointing to `http://127.0.0.1:47821`) | The panels |
| Adds 3 scripts to each **scene collection** (`obsplit-launcher.lua`, `obsplit-backup-launcher.lua`, `auto-audio-setup.lua`) | Starts the helper with OBS (the backup starts it if the main one ever can't load); auto audio setup |

A backup of every OBS file it touches is saved to `%APPDATA%\obs-studio\obsplit-backups\` first. **Uninstalling reverses all of it**, including switching the WebSocket server back off if it was off before. To reconnect later, for example after creating a new scene collection, use **Start menu → OBSplit → OBSplit - Connect to OBS**.

## YouTube setup (optional)

Open the **OBSplit Setup** panel. It links straight to each page:

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Set up the sign-in screen (External) and **Publish** it. Otherwise Google signs you out every 7 days. If **Publish app** is greyed out, add your YouTube channel link as the home page and privacy policy link on the **Branding** page, with `youtube.com` as an authorized domain.
3. Create an OAuth client of type **Desktop app**, download the JSON and drop it on the setup panel.
4. Click **Connect YouTube account**. Google will say the app isn't verified; that's expected for your own app (**Advanced → Go to OBSplit**).
5. In **Stream Info**, click **+ New** and use **Use in OBS** in the stream key box. From then on, set up each stream there and press **Start Streaming** in OBS.

Each user brings their own key, so everyone gets their own free daily allowance (10,000 units). Reading chat uses none. Typical costs: create a stream about 150, send a message 20, delete 25, time-out or ban 200, save stream info 51, thumbnail 50, stats about 240 an hour while live. A normal stream uses roughly 1,000–2,500.

## Privacy

- Everything runs on your PC, on `127.0.0.1`. Nothing is sent anywhere except to YouTube and Google, Twitch (when you use the Twitch features), GitHub (once a day, to check for a new OBSplit version), and to [M-Lab](https://www.measurementlab.net/)'s open speed test only when you click **Test my upload** (10 seconds of random data to a nearby M-Lab server). M-Lab publishes every test result, including your IP address, as public research data; if you'd rather not, type your upload speed in instead.
- Chat is read from YouTube's public live-chat page, the same way the pop-out chat works.
- Your YouTube stream key goes from YouTube straight into OBS's own stream settings. OBSplit never shows it or saves it anywhere else.
- Your sign-in, settings and chat history are stored in `%LOCALAPPDATA%\OBSplit\app\data`. The uninstaller asks whether to delete them.

## Coming from XSplit?

See **[docs/xsplit-to-obs.md](docs/xsplit-to-obs.md)**: where XSplit's features live in OBS, plus recommended audio and encoder settings.

## Troubleshooting

| Problem | Fix |
|---|---|
| Panels show **"Reconnecting…"** | Nothing to do: the helper is restarting and the launcher brings it back within about 10 seconds. If it never clears, check **Tools → Scripts** lists `obsplit-launcher.lua` and `obsplit-backup-launcher.lua`; if not, run **OBSplit - Connect to OBS** with OBS closed. |
| Scenes+ / Sources+ / Audio+ say **"OBS offline"** | **Tools → WebSocket Server Settings**: make sure the server is enabled. |
| Panels are missing after creating a new scene collection | Close OBS and run **OBSplit - Connect to OBS**. |
| My panel layout keeps changing | Use **Keep my panel layout** in OBSplit Setup and turn on **View → Docks → Lock Docks** in OBS. |
| Game not in the + Game list | Start the game first, then click the refresh button. Games under a Steam/Epic/GOG/Xbox library or running fullscreen are listed first; everything else is under "Other windows". |

## Building from source

```powershell
./installer/build.ps1 -Version 0.1.0          # needs Python 3.11+ and Inno Setup 6
./installer/build.ps1 -Version 0.1.0 -RuntimeOnly
```

Pushing a tag like `v0.1.0` builds the installer on GitHub Actions and attaches it to a release.

To run from source without installing: `python app/server.py`, then add the dock URLs from the setup panel in **Docks → Custom Browser Docks**.

## License

[MIT](LICENSE)
