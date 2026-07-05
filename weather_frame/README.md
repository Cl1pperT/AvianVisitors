# AvianVisitors Weather Frame

Procedural daily forecast artwork for the AvianVisitors 13.3-inch e-ink frame.
It is a sibling project: nothing in `frame/` changes, and the bird display keeps
working unless you explicitly run weather output against the physical panel.

The default renderer uses a limited-palette woodblock treatment inspired by the
repository's local `art examples` folder. It draws every image with Pillow from
sky fields, sun, layered landforms, clouds, virga or rain, snow, wind lines,
hatching, and stippling. It does not use an image-generation API.

The preferred artwork source is a pre-generated watercolor scene library under
`assets/scenes/`. It uses the same pattern as the bird illustrations: an offline
Gemini generator combines a detailed prompt with positive style references,
saves ordinary PNG assets, and the Raspberry Pi only reads local files. No paid
API call occurs during the morning display update.

When no generated scene matches, the procedural renderer falls back to the
component library under `assets/mountains/`, organized into aligned `sun`,
`snow`, `clouds`, and `melting_snow` variants. See
[`assets/README.md`](assets/README.md) for both asset contracts.

## How it is isolated

- Weather configuration, images, and refresh state live in `~/.weatherframe/`.
- `frame/display.py` is imported only for its panel dimensions, Spectra-6
  preview, quiet-hours/state helpers, and Inky update function.
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

Edit `location` in `~/.weatherframe/config.toml`, then generate an approximate
six-ink preview:

```bash
weather_frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --preview weather-preview.png
```

This fetches the forecast and writes only `weather-preview.png`. It never writes
refresh state or imports the Inky hardware driver.

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
scene_source = "auto"    # generated scene when available, else procedural
environment = "auto"     # rotate available scenes, or choose a catalog slug

output = "~/.weatherframe/weather.png"
state = "~/.weatherframe/state.json"
timeout = 30
quiet_start = 22
quiet_end = 6
heal_hours = 24

rotate = 90
saturation = 0.6
# panel = "el133uf1"
```

The location is resolved through the
[Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api).
Use a city plus region and `country_code` to avoid ambiguous place names. The
selected place and coordinates are logged before rendering.

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

The generator uses the same Gemini 2.5 Flash Image endpoint and API-key header
pattern as the AvianVisitors bird generator. It attaches one of the three local
`../goalimages/` files as a positive style reference:

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
export GEMINI_API_KEY='your-key'
python3 -m weather_frame.generate_scenes \
  --environment mount_timpanogos \
  --condition clear
```

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

`--all` requests the complete environment × weather matrix and can make hundreds
of paid calls; it is never implied. `--limit` bounds any selection, existing PNGs
are skipped, and `--force` is required to replace one.

Optional geography references follow the bird generator's anatomy-reference
pattern. Place a photo at
`weather_frame/assets/references/environments/<environment>.jpg`; it is attached
for landform identity and viewpoint while the goal image controls watercolor
style. Local references are gitignored.

Available environment slugs:

- `mount_timpanogos`, `great_salt_lake`, `moab_red_rocks`, `zion_cliffs`
- `bryce_hoodoos`, `capitol_reef`, `uinta_alpine_lake`, `bonneville_salt_flats`
- `bear_lake`, `canyonlands`, `san_rafael_swell`, `cedar_breaks`

The condition catalog covers clear, mostly sunny, partly cloudy, overcast, fog,
drizzle, freezing drizzle, rain, heavy rain, freezing rain, snow, heavy snow,
snow grains, rain showers, violent showers, snow showers, thunderstorms, hail,
wind, hot/dry weather, melting snow, and virga. Every Open-Meteo WMO code maps
to one of these assets.

`scene_source = "auto"` uses a matching generated scene when present and falls
back procedurally when absent. Use `"generated"` to require an asset and fail
safely if missing, or `"procedural"` to ignore the generated library.

## Physical panel

The original frame installer creates `frame/.venv` with Pillow and the Inky
driver. Use that environment for a deliberate one-time weather update:

```bash
frame/.venv/bin/python -m weather_frame \
  --config ~/.weatherframe/config.toml \
  --display
```

The image is hashed after Spectra-6 preview quantization. An unchanged image is
not pushed again unless `heal_hours` has elapsed. State is saved only after a
successful hardware update. Fetch, render, or panel failures leave the previous
panel image and refresh state intact.

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
