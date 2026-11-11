# Coming from XSplit

Where XSplit's features live in OBS Studio (with OBSplit installed), and settings worth changing on day one.

## XSplit → OBS cheat sheet

| In XSplit you… | In OBS you… |
|---|---|
| Add a game source | **Scenes+ → ＋ Game** (picture and sound in one source) |
| Add a screen region | **Scenes+ → ＋ Screen region** (drag a box or click a window) |
| Pick application audio | **Scenes+ → ＋ Discord**, or **＋ Game** for games. Anything else: **Sources → ＋ → Application Audio Capture** |
| See scene thumbnails | **Scenes+** panel |
| Use the Preview Editor (edit a scene without changing what viewers see) | Click **Studio Mode** (Controls panel). Left = preview you edit, right = what viewers see, **Transition** swaps them |
| Mark audio as stream-only / recording-only | **Audio+**: the **Stream** and **Rec** switches on each source |
| Mute the mic on certain scenes | **Scenes+**: the 🎙 switch on each scene |
| Drag an edge to crop | Hold **Alt** and drag an edge of the source |
| Open a source's settings | **Double-click** the source, or use the bar under the preview |
| Position, rotate, fit to screen | Right-click → **Transform** (**Ctrl+F** fit to screen, **Ctrl+E** edit transform) |
| Show the same overlay in every scene | Right-click source → **Copy**, then in another scene right-click → **Paste (Reference)**. It's the same source, so editing one edits all |
| Group sources | Select several → right-click → **Group Selected Items** |
| Lock a source | Click the 🔒 next to it in Sources |
| Run the setup wizard | **Tools → Auto-Configuration Wizard** |
| Edit YouTube title/thumbnail while live | **YT Stream Info** panel |
| Read and moderate chat | **YT Chat** panel |

## Panels: moving, resizing, combining

- **Resize:** drag the border between two panels.
- **Move:** drag a panel by its title bar or tab and drop it where the blue highlight shows.
- **Combine into tabs:** drop a panel onto the middle of another panel.
- **Pop out:** double-click the title bar; double-click again to put it back.
- **Docks → Lock Docks** stops accidental moves. Resizing still works while locked.

## Recommended settings

### Microphone
Right-click your mic in the mixer → **Filters** → add, in this order:

1. **Noise Suppression**, method *RNNoise*: removes background noise
2. **Compressor**: ratio 4:1, threshold -18 dB, attack 6 ms, release 60 ms. Evens out loud and quiet speech
3. **Limiter**: threshold -3 dB. Stops sudden peaks from clipping

If OBS shows your mic but no level, it may point at a device that no longer exists. Open the mic's **Properties** and pick the device again.

### Hearing your sources ("monitoring")
OBS doesn't play a source in your headphones unless you ask it to. The **🎧** button in Audio+ does that. Don't monitor your mic, desktop audio or game audio; you already hear those directly, and monitoring them causes echo.

### Encoder
If you have an NVIDIA RTX card, stream with **NVIDIA NVENC H.264** instead of x264. It frees your CPU for games.
**Settings → Output → Output Mode: Advanced → Streaming → Video Encoder.** For YouTube 1080p60: CBR 9,000-12,000 kbps, keyframe interval 2 s, preset P5, two-pass (quarter resolution).

### Stream delay
**Settings → Advanced → Stream Delay** is sometimes switched on by accident. Turn it off unless you need it; it adds lag between you and chat.

### YouTube
**Settings → Stream → Service: YouTube - RTMPS → Connect Account**. Use **Manage Broadcast** (Controls panel) before going live. While live, edit everything in **YT Stream Info**.
