# AvianVisitors

*A live, rarity-weighted bird collage from your window, with optional e-ink bird and weather displays.*

See it running at [bird.onethreenine.net](https://bird.onethreenine.net).

<img alt="avianvisitors collage" src="docs/thumb.png" />

---

## What it does

- Runs BirdNET-Pi on a Raspberry Pi and turns detections into a responsive illustrated collage.
- Defaults to the last seven days, with `1H`, `12H`, `24H`, `7D`, and `ALL` views.
- Sizes each bird from `calls in the selected window × local rarity weight`, so repeatedly heard uncommon visitors can outrank everyday birds. Local rarity is based on lifetime calls per observed day and is capped at `12×`.
- Includes stats, a life-list atlas, species details, recordings, and the BirdNET-Pi administration tools in one web interface.
- Ships 498 illustrations for 249 species, including perched and flight poses, plus tools for generating regional additions.
- Can drive a landscape or portrait 13.3-inch Spectra 6 e-ink display from the live mic, BirdWeather, or an already-rendered image.
- Includes a separate morning weather-art renderer using real Open-Meteo forecasts, generated watercolor scenes, and a procedural scene fallback.

The bird display and weather display share the repository but keep separate configuration, state, and timers. Only one timer should own a physical panel at a time.

---

## BOM

| Qty | Description | Price | Link | Notes |
|-----|-------------|-------|------| ----- |
| 1 | Raspberry Pi (4B / 5 / Zero 2W) | ~$35-80 | [Amazon](https://amzn.to/43yLDZJ) | [See note for RPi20](https://github.com/mcguirepr89/BirdNET-Pi/wiki/RPi0W2-Installation-Guide) |
| 1 | Micro SD Card (≥32 GB) | ~$10 | [Amazon](https://amzn.to/4eGy7te) | |
| 1 | USB lavalier microphone | $16.95 | [Amazon](https://amzn.to/4vLSaMK) | |
| 1 | Pi power supply | ~$10 | - | |

Optional: a [Gemini API key](https://aistudio.google.com/apikey) to restyle bird illustrations or pre-generate weather scenes, and an [eBird API key](https://ebird.org/api/keygen) to filter species by region or fill sparse BirdWeather locations.

### Kits

I offer the bird mic and the wall frame as separate electronics kits. I put up a store for some of my open-source projects and will soon be able to offer kits cheaper than buying all the components individually, once I start buying in bulk.

- [Bird mic kit](https://theodore.net/store/avian-mic/)
- [Frame kit](https://theodore.net/store/avian-visitors/)

---

## 1. Flash the SD card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Pick Raspberry Pi OS Lite (64-bit). In the customisation dialog set:

- Username
- WiFi SSID + password
- Hostname: `birdnet`
- Enable SSH with password auth

Plug the USB mic into the Pi. Place the capsule in a window or mount it outside. Boot.

---

## 2. Run the installer

Installer assumes passwordless sudo (Raspberry Pi OS Lite default - if you've tightened it, run `sudo raspi-config` -> *System Options* -> restore the default first).

```bash
ssh <your-username>@birdnet.local
curl -s https://raw.githubusercontent.com/Twarner491/AvianVisitors/avian-visitors/newinstaller.sh | bash
```

Clones this fork, installs BirdNET-Pi, symlinks the AvianVisitors overlay into the Caddy web root. Takes 20-40 minutes. Reboots when done.

Collage: `http://birdnet.local/`. Stock BirdNET-Pi UI: `http://birdnet.local/index.php`. The menu button in the top right opens an admin overlay with settings, system, log, and tool panels.

---

## 3. (Optional) Restyle the illustrations

The repo ships with 498 bundled illustrations (249 species, perched + flight). To restyle them or generate a set for your own region:

```bash
pip install -r ~/BirdNET-Pi/avian/scripts/requirements.txt
export GEMINI_API_KEY='your-key'  # image generation requires billing enabled

# generate on a cream ground, cut the ground off, rebuild the collage masks
python3 ~/BirdNET-Pi/avian/scripts/pregen.py --labels ~/BirdNET-Pi/model/labels.txt --force
python3 ~/BirdNET-Pi/avian/scripts/cutout.py
python3 ~/BirdNET-Pi/avian/scripts/build_masks.py
```

Filter to your region with `--ebird-region US-CA` (needs `EBIRD_API_KEY`). The full pipeline, prompt, reference images, and per-species tuning live in [`avian/scripts/README.md`](avian/scripts/README.md). Style lives in [`prompt.template.md`](avian/scripts/prompt.template.md).

---

## 4. (Optional) Forward off your LAN

See [`avian/forwarding/`](avian/forwarding/) for three independent recipes:

- **Cloudflare Tunnel** for a public HTTPS URL.
- **Home Assistant REST sensor** that exposes the latest detection.
- **MQTT bridge** that publishes every new detection.

---

## Repo layout

```
avian/                  # everything we add to BirdNET-Pi
├── frontend/           # static HTML/JS/CSS for the collage
├── assets/             # 498 bundled illustrations + photo-cutout fallbacks
├── api/                # PHP shims served by BirdNET-Pi's PHP-FPM
├── scripts/            # generate -> cutout -> masks pipeline + prompt
└── forwarding/         # optional HA / MQTT / Cloudflare configs
frame/                  # optional landscape/portrait e-ink bird display
weather_frame/          # optional Open-Meteo weather-art display + macOS preview app
```

Everything outside `avian/`, `frame/`, and `weather_frame/` is upstream BirdNET-Pi.

---

## Wall frame

An optional e-ink frame mirrors the seven-day collage onto a 13.3-inch Spectra 6 panel. The layout responds directly to the panel orientation, including a full-width landscape arrangement. It can render from your BirdNET mic, run standalone from BirdWeather for a ZIP code, or fetch an already-rendered image. Build and installation instructions are in [`frame/README.md`](frame/README.md).

For BirdNET-backed collages, bird area is ranked by the rarity-weighted score described above. Hovering a bird in the web viewer shows its call count, rarity multiplier, and resulting size score.

## Weather frame

[`weather_frame/`](weather_frame/README.md) is an opt-in morning forecast display built on the same panel support. It makes real Open-Meteo geocoding and forecast calls, selects a pre-generated watercolor scene when one exists, and otherwise renders a deterministic procedural scene. An optional live AI source ranks five activities through the sibling `season` project and asks Gemini to include one or two in today's image.

On macOS, the Tkinter preview app lets you choose a location, scene source, environment, caption setting, and fixture/live weather before touching e-ink hardware:

```bash
python3 -m venv weather_frame/.venv
weather_frame/.venv/bin/pip install -r weather_frame/requirements.txt
weather_frame/.venv/bin/python -m weather_frame.preview_app
```

The preview app loads its default location and artwork settings from `~/.weatherframe/config.toml`. Full setup, scene-generation, timer, and panel-safety instructions are in [`weather_frame/README.md`](weather_frame/README.md).

## Tests

The weather renderer and its preview integration use the standard-library test runner:

```bash
python3 -m unittest discover -s weather_frame/tests -v
```

The frame utilities also support non-destructive PNG previews before a physical refresh; see each component README for its preview command.

---

## License

CC-BY-NC-SA-4.0, inherited from [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi/blob/main/LICENSE). Non-commercial use only. See the [BirdNET-Pi README](https://github.com/Nachtzuster/BirdNET-Pi/blob/main/README.md) for full Cornell attribution.

---

- [Fork this repository](https://github.com/Twarner491/AvianVisitors/fork)
- [Watch this repo](https://github.com/Twarner491/AvianVisitors/subscription)
- [Create issue](https://github.com/Twarner491/AvianVisitors/issues/new)
