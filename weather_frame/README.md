# AvianVisitors Weather Frame

Procedural daily forecast artwork for the AvianVisitors 13.3-inch e-ink frame.
It is a sibling project: nothing in `frame/` changes, and the bird display keeps
working unless you explicitly run weather output against the physical panel.

The default renderer uses a limited-palette woodblock treatment inspired by the
repository's local `art examples` folder. It draws every image with Pillow from
sky fields, sun, layered landforms, clouds, virga or rain, snow, wind lines,
hatching, and stippling. It does not use an image-generation API.

The preferred no-cost artwork source is a pre-generated watercolor scene library under
`assets/scenes/`. It uses the same pattern as the bird illustrations: an offline
Gemini generator combines a detailed prompt with positive style references,
saves ordinary PNG assets, and the Raspberry Pi only reads local files. No paid
API call occurs during the morning display update.

An opt-in live `ai` source instead sends today's forecast through the sibling
`season` package, passes its five highest-ranked activities to Gemini, and asks
the model to depict one or two of them. This mode makes one paid image request
each time the weather-frame command renders.

When no generated scene matches, the procedural renderer falls back to the
component library under `assets/mountains/`, organized into aligned `sun`,
`snow`, `clouds`, and `melting_snow` variants. See
[`assets/README.md`](assets/README.md) for both asset contracts.

## How it is isolated

- Weather configuration, images, and refresh state live in `~/.weatherframe/`.
- `frame/display.py` is imported only for its panel dimensions,
  quiet-hours/state helpers, and Inky update function. Weather preview
  quantization is isolated in `weather_frame/eink.py`.
- The bird collage renderer, bird signatures, installer, and systemd units are
  not modified.
- Preview and ordinary render commands cannot update the panel.

Only one scheduled process should own an e-ink panel. The weather timer refuses
to install while `birdframe.timer` is active or enabled.

## Preview setup

Run commands from the AvianVisitors repository root:

```bash
python3 -m venv weather_frame/.venv
weather_frame/.venv/bin/pip install -r weather_frame/requirements.txt
mkdir -p ~/.weatherframe
cp weather_frame/config.example.toml ~/.weatherframe/config.toml
```

Edit `location` in `~/.weatherframe/config.toml`, then generate a six-ink
preview:

```bash
weather_frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --preview weather-preview.png
```

This fetches the forecast and writes only `weather-preview.png`. It never writes
refresh state or imports the Inky hardware driver.

For an interactive desktop preview, launch the small Tkinter application:

```bash
weather_frame/.venv/bin/python -m weather_frame.preview_app
```

Enter a city or postal code and select **Generate E-Ink Preview**. The window
fetches today's forecast, chooses a generated scene or procedural fallback, and
shows the result after conversion with the same saturation-dependent palette
math and Floyd–Steinberg dithering used by Pimoroni's 13.3-inch driver. The
on-screen image is area-averaged to represent normal viewing distance and avoid
scaling artifacts. **Save PNG…** writes the native 1600×1200 six-color dither.
Monitor colors remain an approximation because the real panel uses reflective
pigments and ambient light. This application never updates the physical display
or writes refresh state.

The **Blue bias** control selectively pulls existing cyan, blue, and indigo
source pixels toward the driver's blue matching point before dithering. It
defaults to `0.50`; adjust in `0.05` increments. A value of `0` disables the
adjustment.

If `~/.weatherframe/config.toml` exists, its location and artwork settings
prefill the controls. A different configuration or initial location can be
supplied explicitly:

```bash
weather_frame/.venv/bin/python -m weather_frame.preview_app \
  --config weather_frame/config.example.toml \
  --location "Salt Lake City, UT"
```

Tkinter ships with most desktop Python installations. On Debian or Raspberry
Pi OS, install `python3-tk` if Python reports that `_tkinter` is unavailable.
The GUI is intended for a desktop session, not the headless systemd service.

Render the full RGB source image configured by `output` without touching the
panel:

```bash
weather_frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml
```

## Configuration

```toml
provider = "open_meteo"
location = "Denver, CO"
country_code = "US"
# location_label = "Home"

units = "imperial"       # or "metric"; affects an enabled caption only
style = "woodblock"      # or "ink_wash"
caption = false
scene_source = "auto"    # auto, generated, procedural, or live "ai"
environment = "auto"     # rotate available scenes, or choose a catalog slug
# gemini_key = ""         # prefer exporting GEMINI_API_KEY for live AI

output = "~/.weatherframe/weather.png"
state = "~/.weatherframe/state.json"
timeout = 30
quiet_start = 22
quiet_end = 6
heal_hours = 24

rotate = 90
saturation = 0.6
blue_bias = 0.5          # selectively increases blue-ink pixel assignment
# panel = "el133uf1"
```

The location is resolved through the
[Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api).
Use a city plus region and `country_code` to avoid ambiguous place names. The
selected place and coordinates are logged before rendering.

For `scene_source = "ai"`, keep the `season/` project beside
`AvianVisitors/` (as in this workspace), or install it as a Python package. The
adapter uses apparent temperature, UV, humidity, visibility, and snow depth
when Open-Meteo supplies them. AQI defaults to 50 because this provider does
not currently fetch the separate air-quality API.

The [forecast request](https://open-meteo.com/en/docs) uses `timezone=auto` and
one local day. Daily temperatures, precipitation, snow, sunrise/sunset, and
wind are combined with hourly clouds and precipitation timing. All internal
values are canonical metric values regardless of caption units.

## Artwork behavior

- Clear and warm forecasts use open sky and a visible sun.
- A high of at least 30°C with less than 1 mm precipitation produces sparse,
  desert-like landforms.
- Clouds accumulate according to forecast cloud cover.
- Expected precipitation below 0.5 mm appears as virga; larger amounts reach
  the horizon as rain shafts.
- The strongest hourly precipitation period places weather toward the morning,
  afternoon, or evening side of the composition.
- Snow uses pale landforms and textured flakes.
- Wind at 30 km/h, or gusts at 45 km/h, adds directional cloud lines and
  wind-swept grasses.

The output is always the panel's native 1600×1200 landscape resolution. Artwork
fills every pixel; there is no simulated mat or white border around the scene.
For hardware output, the app pre-rotates this landscape image before passing it
through the existing `frame.display` update helper, avoiding resizing or
distortion.

## Watercolor scene generation

For a live activity-aware scene, export the key and select the AI source:

```bash
export GEMINI_API_KEY='your-key'
# In ~/.weatherframe/config.toml: scene_source = "ai"
weather_frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --preview weather-preview.png
```

The prompt lists exactly five ranked candidates and directs Gemini to show one
or two as small figures or recognizable equipment while preserving the
weather-dominant landscape composition.

The generator uses Gemini 3.1 Flash Lite Image at native 4:3, 1K output. It
attaches one of the three local `../goalimages/` files as a positive style
reference:

- the first image for clear, warm, and partly cloudy scenes;
- the second for snow, ice, and melting-snow scenes;
- the third for rain, fog, wind, and thunderstorms.

The prompt lives in
[`scene_prompt.template.md`](scene_prompt.template.md). It requests full-bleed
4:3 watercolor with recognizable geography, integrated weather, paper and
pigment texture, and strong value groups that survive Spectra-6 quantization.

Generation is explicit and missing-only. Preview one planned request without a
key or network call:

```bash
python3 -m weather_frame.generate_scenes \
  --environment mount_timpanogos \
  --condition clear \
  --dry-run
```

Generate that one scene with the paid Gemini API:

```bash
# From the repository root, put GEMINI_API_KEY=your-key in the ignored .env file.
python3 -m weather_frame.generate_scenes \
  --environment mount_timpanogos \
  --condition clear
```

The static generator reads `GEMINI_API_KEY` from the process environment first,
then from the repository's ignored `.env` file. Copy `.env.example` to `.env` for
a fresh setup. The key's Google Cloud project must have Gemini API billing and
quota enabled for Flash Lite Image.

Repeat `--condition` to generate a small useful set. Supplying only an
environment generates every weather treatment for that environment:

```bash
python3 -m weather_frame.generate_scenes \
  --environment mount_timpanogos \
  --condition clear \
  --condition partly_cloudy \
  --condition rain_showers \
  --condition snow \
  --condition thunderstorm
```

`--all` requests the complete environment × weather matrix: 105 possible paid
calls for the current catalog (currently 90 are missing). It is never implied.
`--limit` bounds any selection, existing PNGs are skipped, and `--force` is
required to replace one.

### Curated activity-scene trials

Activity variants are generated from completed weather scenes and stored under
`assets/activity_scenes/`, so they cannot replace the weather-only library.
Preview the four curated jobs without an API call:

```bash
python3 -m weather_frame.generate_activity_scenes --all --dry-run
```

Generate one activity or all four:

```bash
python3 -m weather_frame.generate_activity_scenes --activity rock_climbing
python3 -m weather_frame.generate_activity_scenes --all
```

The initial catalog deliberately pairs each activity with believable weather:
rock climbing in mostly sunny Moab, paddleboarding on clear and calm Bear Lake,
hammocking below partly cloudy Mount Timpanogos, and cross-country skiing during
Uinta snow showers. Paddleboarding cannot select a windy scene, and skiing can
only select a snow-covered mountain scene. Existing variants are skipped unless
the exact selection is regenerated with `--force`.

Optional geography references follow the bird generator's anatomy-reference
pattern. Place a photo at
`weather_frame/assets/references/environments/<environment>.jpg`; it is attached
for landform identity and viewpoint while the goal image controls watercolor
style. Local references are gitignored.

Available environment slugs:

- `mount_timpanogos`, `moab_red_rocks`, `zion_cliffs`
- `uinta_alpine_lake`, `bear_lake`

The condition catalog covers clear, mostly sunny, partly cloudy, overcast, fog,
drizzle, rain, heavy rain, freezing rain, snow, heavy snow, snow grains, rain
showers, violent showers, snow showers, thunderstorms, hail, wind, hot/dry
weather, melting snow, and virga. Freezing drizzle forecasts use the freezing
rain artwork so every Open-Meteo WMO code still maps to an active asset.

`scene_source = "auto"` uses a matching generated scene when present and falls
back procedurally when absent. Use `"generated"` to require an asset and fail
safely if missing, `"procedural"` to ignore the generated library, or `"ai"`
to generate a live forecast- and activity-aware image.

### Manual generation with ChatGPT Plus

[`manual_prompt_pack.md`](manual_prompt_pack.md) contains one complete prompt for
every active weather condition, distributed across the active environments.
Each entry identifies the Goal Image to upload and the exact destination path
for the downloaded PNG.

Regenerate the pack after changing the prompt template or catalog:

```bash
python3 -m weather_frame.generate_manual_prompts
```

## Physical panel

The original frame installer creates `frame/.venv` with Pillow and the Inky
driver. Use that environment for a deliberate one-time weather update:

```bash
frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --display
```

The image is hashed after driver-matched Spectra-6 quantization using the
configured `saturation`. An unchanged image is not pushed again unless
`heal_hours` has elapsed. State is saved only after a successful hardware
update. Fetch, render, or panel failures leave the previous panel image and
refresh state intact.

`--force` bypasses quiet hours and signature checks:

```bash
frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --display --force
```

## Optional 6:05 AM timer

The timer is deliberately opt-in. The Pi's timezone should match the configured
forecast location.

If the bird timer currently owns the panel, disable it yourself before
installing weather mode:

```bash
sudo systemctl disable --now birdframe.timer
./weather_frame/install_timer.sh
```

The installer checks for the weather config and existing frame virtual
environment, substitutes the current user and clone paths into the service, and
enables a persistent 06:05 local timer. It never edits or disables bird mode.

Return the panel to birds with:

```bash
sudo systemctl disable --now weatherframe.timer
sudo systemctl enable --now birdframe.timer
```

## Tests

Tests use recorded API-shaped fixtures and never require network or panel
hardware:

```bash
python3 -m unittest discover -s weather_frame/tests -v
```
