from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from frame import display as real_panel

from weather_frame import app
from weather_frame.activities import recommend_activities
from weather_frame.eink import (
    DISPLAY_APPEARANCE_PALETTE,
    apply_blue_bias,
    driver_matching_palette,
    quantize_spectra6,
)
from weather_frame.generate_manual_prompts import PROMPT_JOBS
from weather_frame.generate_scenes import (
    build_daily_prompt,
    build_prompt,
    discover_style_references,
)
from weather_frame.preview_app import generate_eink_preview
from weather_frame.renderer import CAPTION_HEIGHT, STYLES, render_forecast
from weather_frame.renderer import (
    available_mountains,
    mountain_component_for_forecast,
    mountain_condition_for_forecast,
)
from weather_frame.scene_catalog import (
    ENVIRONMENTS,
    SCENE_CONDITIONS,
    condition_slug_for_forecast,
)
from weather_frame.weather import (
    Condition,
    DailyForecast,
    OpenMeteoProvider,
    PrecipitationPeriod,
    condition_for_code,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    with (FIXTURES / name).open() as handle:
        return json.load(handle)


def sample_forecast(**changes):
    forecast = DailyForecast(
        date=date(2026, 7, 5),
        timezone="UTC",
        location_name="Test Valley",
        latitude=39.7,
        longitude=-105.0,
        weather_code=0,
        condition=Condition.CLEAR,
        high_c=27.0,
        low_c=13.0,
        precipitation_probability=5,
        precipitation_mm=0.0,
        rain_mm=0.0,
        snowfall_cm=0.0,
        cloud_cover_mean=15.0,
        wind_speed_max_kmh=12.0,
        wind_gust_max_kmh=20.0,
        wind_direction_deg=250.0,
        sunrise=datetime(2026, 7, 5, 5, 30),
        sunset=datetime(2026, 7, 5, 20, 30),
        precipitation_period=PrecipitationPeriod.NONE,
    )
    return replace(forecast, **changes)


class ProviderTests(unittest.TestCase):
    def test_wmo_classification(self):
        expected = {
            0: Condition.CLEAR,
            1: Condition.CLEAR,
            2: Condition.CLOUDY,
            45: Condition.FOG,
            61: Condition.RAIN,
            75: Condition.SNOW,
            95: Condition.THUNDER,
        }
        for code, condition in expected.items():
            self.assertEqual(condition_for_code(code), condition)

    def test_open_meteo_fetch_and_normalization(self):
        calls = []

        def transport(url, timeout):
            calls.append((url, timeout))
            if "geocoding-api" in url:
                return fixture("geocode_denver.json")
            return fixture("forecast_afternoon_rain.json")

        forecast = OpenMeteoProvider(transport).fetch_today(
            "Denver, CO", country_code="us", timeout=17
        )
        self.assertEqual(forecast.location_name, "Denver, Colorado")
        self.assertEqual(forecast.timezone, "America/Denver")
        self.assertEqual(forecast.condition, Condition.RAIN)
        self.assertEqual(forecast.precipitation_period, PrecipitationPeriod.AFTERNOON)
        self.assertAlmostEqual(forecast.high_c, 28.4)
        self.assertAlmostEqual(forecast.precipitation_mm, 4.5)
        self.assertGreater(forecast.cloud_cover_mean, 30)
        self.assertEqual(len(calls), 2)
        geocode_query = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0][0]).query)
        self.assertEqual(geocode_query["countryCode"], ["US"])
        forecast_query = urllib.parse.parse_qs(urllib.parse.urlparse(calls[1][0]).query)
        self.assertEqual(forecast_query["timezone"], ["auto"])
        self.assertIn("cloud_cover", forecast_query["hourly"][0])
        self.assertTrue(all(timeout == 17 for _, timeout in calls))

    def test_missing_location_is_a_clear_error(self):
        provider = OpenMeteoProvider(lambda url, timeout: {})
        with self.assertRaisesRegex(RuntimeError, "found no location"):
            provider.fetch_today("Nowhere")

    def test_city_region_falls_back_to_city_search(self):
        terms = []

        def transport(url, timeout):
            if "geocoding-api" not in url:
                return fixture("forecast_afternoon_rain.json")
            term = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["name"][0]
            terms.append(term)
            return {} if "," in term else fixture("geocode_denver.json")

        forecast = OpenMeteoProvider(transport).fetch_today("Denver, CO", country_code="US")
        self.assertEqual(terms, ["Denver, CO", "Denver"])
        self.assertEqual(forecast.location_name, "Denver, Colorado")


class RendererTests(unittest.TestCase):
    def test_manual_prompt_pack_covers_every_environment_and_condition(self):
        self.assertEqual(set(PROMPT_JOBS), set(ENVIRONMENTS))
        covered = {
            condition
            for conditions in PROMPT_JOBS.values()
            for condition in conditions
        }
        self.assertEqual(covered, set(SCENE_CONDITIONS))
        pack = Path(__file__).parents[1] / "manual_prompt_pack.md"
        content = pack.read_text()
        self.assertEqual(content.count("\n## "), 36)
        self.assertEqual(content.count("Save result as:"), 36)

    def test_scene_catalog_covers_wmo_conditions_and_utah_environments(self):
        expected = {
            0: "clear", 1: "mostly_sunny", 2: "partly_cloudy", 3: "overcast",
            45: "fog", 48: "fog", 51: "drizzle", 55: "drizzle",
            56: "freezing_drizzle", 57: "freezing_drizzle",
            61: "rain", 63: "rain", 65: "heavy_rain",
            66: "freezing_rain", 67: "freezing_rain",
            71: "snow", 73: "snow", 75: "heavy_snow", 77: "snow_grains",
            80: "rain_showers", 81: "rain_showers", 82: "violent_showers",
            85: "snow_showers", 86: "snow_showers",
            95: "thunderstorm", 96: "hail_thunderstorm", 99: "hail_thunderstorm",
        }
        for code, slug in expected.items():
            forecast = sample_forecast(
                weather_code=code,
                condition=condition_for_code(code),
                precipitation_mm=5 if code >= 50 else 0,
                precipitation_probability=70 if code >= 50 else 5,
                high_c=-3 if code in (71, 73, 75, 77, 85, 86) else 20,
            )
            with self.subTest(code=code):
                self.assertEqual(condition_slug_for_forecast(forecast), slug)
        self.assertIn("mount_timpanogos", ENVIRONMENTS)
        self.assertIn("great_salt_lake", ENVIRONMENTS)
        self.assertIn("moab_red_rocks", ENVIRONMENTS)
        self.assertIn("zion_cliffs", ENVIRONMENTS)
        self.assertGreaterEqual(len(ENVIRONMENTS), 10)
        self.assertGreaterEqual(len(SCENE_CONDITIONS), 20)

    def test_scene_prompt_and_goal_reference_routing(self):
        template = (
            "{environment_name}|{environment_description}|"
            "{weather_name}|{weather_description}"
        )
        prompt = build_prompt(template, "mount_timpanogos", "heavy_snow")
        self.assertIn("Mount Timpanogos", prompt)
        self.assertIn("limestone summit ridge", prompt)
        self.assertIn("Heavy Snow", prompt)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("01.png", "02.png", "03.png"):
                Image.new("RGB", (8, 8), "white").save(root / name)
            references = discover_style_references(root)
            self.assertEqual(references["sunny"].name, "01.png")
            self.assertEqual(references["snow"].name, "02.png")
            self.assertEqual(references["storm"].name, "03.png")

    def test_daily_prompt_passes_five_ranked_activities_to_the_model(self):
        template = Path(__file__).parents[1].joinpath("scene_prompt.template.md").read_text()
        activities = ("Hiking", "Golf", "Fishing", "Birdwatching", "Disc golf")
        prompt = build_daily_prompt(
            template,
            "mount_timpanogos",
            "clear",
            sample_forecast(),
            activities,
        )
        for activity in activities:
            self.assertIn(activity, prompt)
        self.assertIn("Choose exactly one or two", prompt)
        self.assertIn("high 27.0°C", prompt)

    def test_forecast_is_ranked_into_exactly_five_activity_names(self):
        activities = recommend_activities(sample_forecast())
        self.assertEqual(len(activities), 5)
        self.assertEqual(len(set(activities)), 5)

    def test_generated_scene_is_used_and_missing_generated_scene_is_explicit(self):
        forecast = sample_forecast()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clear.png"
            Image.new("RGB", (800, 600), (17, 91, 143)).save(path)
            selection = ("mount_timpanogos", "clear", path)
            with patch("weather_frame.renderer.generated_scene_path", return_value=selection):
                image = render_forecast(forecast, scene_source="generated")
            self.assertEqual(image.size, (1600, 1200))
            self.assertEqual(image.getpixel((800, 600)), (17, 91, 143))
        missing = ("mount_timpanogos", "clear", Path("/definitely/missing.png"))
        with patch("weather_frame.renderer.generated_scene_path", return_value=missing):
            with self.assertRaisesRegex(FileNotFoundError, "mount_timpanogos/clear"):
                render_forecast(forecast, scene_source="generated")

    def test_mountain_library_has_aligned_weather_variants(self):
        self.assertEqual(available_mountains(), ("alpine", "massif", "sawtooth"))
        clear = sample_forecast()
        cloudy = replace(clear, weather_code=3, condition=Condition.CLOUDY)
        snow = replace(
            clear, weather_code=75, condition=Condition.SNOW, high_c=-2, snowfall_cm=8
        )
        melting = replace(snow, high_c=5)
        forecasts = (clear, cloudy, snow, melting)
        self.assertEqual(
            [mountain_condition_for_forecast(item) for item in forecasts],
            ["sun", "clouds", "snow", "melting_snow"],
        )
        selections = [mountain_component_for_forecast(item) for item in forecasts]
        self.assertEqual(len({selection[0] for selection in selections}), 1)
        for selection in selections:
            _name, _condition, path = selection
            self.assertTrue(path.is_file())
            with Image.open(path) as component:
                self.assertEqual(component.mode, "RGBA")
                self.assertEqual(component.size, (1600, 420))

    def test_all_weather_scenarios_render_full_bleed_landscape(self):
        cases = [
            sample_forecast(),
            sample_forecast(high_c=36, precipitation_mm=0.0),
            sample_forecast(
                weather_code=61,
                condition=Condition.RAIN,
                precipitation_probability=60,
                precipitation_mm=0.2,
                cloud_cover_mean=75,
                precipitation_period=PrecipitationPeriod.AFTERNOON,
            ),
            sample_forecast(wind_speed_max_kmh=38, wind_gust_max_kmh=56),
            sample_forecast(
                weather_code=75,
                condition=Condition.SNOW,
                snowfall_cm=8,
                precipitation_mm=7,
                cloud_cover_mean=90,
            ),
            sample_forecast(weather_code=3, condition=Condition.CLOUDY, cloud_cover_mean=92),
            sample_forecast(weather_code=45, condition=Condition.FOG, cloud_cover_mean=100),
            sample_forecast(
                weather_code=95,
                condition=Condition.THUNDER,
                precipitation_probability=80,
                precipitation_mm=12,
                cloud_cover_mean=95,
                precipitation_period=PrecipitationPeriod.EVENING,
            ),
        ]
        for forecast in cases:
            with self.subTest(condition=forecast.condition, high=forecast.high_c):
                image = render_forecast(forecast)
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (real_panel.PANEL_H, real_panel.PANEL_W))
                self.assertNotEqual(image.getpixel((0, 0)), STYLES["woodblock"].paper)
                self.assertNotEqual(image.getpixel((image.width // 2, image.height // 2)),
                                    STYLES["woodblock"].paper)
                self.assertGreater(len(image.getcolors(maxcolors=2_000_000)), 10)

    def test_render_is_deterministic_and_styles_differ(self):
        forecast = sample_forecast(weather_code=2, condition=Condition.CLOUDY, cloud_cover_mean=55)
        first = render_forecast(forecast, style="woodblock", scene_source="procedural")
        second = render_forecast(forecast, style="woodblock", scene_source="procedural")
        wash = render_forecast(forecast, style="ink_wash", scene_source="procedural")
        digest = lambda image: hashlib.sha256(image.tobytes()).hexdigest()
        self.assertEqual(digest(first), digest(second))
        self.assertNotEqual(digest(first), digest(wash))

    def test_caption_is_optional_and_units_only_change_caption(self):
        forecast = sample_forecast()
        no_caption = render_forecast(forecast, caption=False, units="imperial")
        metric_no_caption = render_forecast(forecast, caption=False, units="metric")
        caption = render_forecast(forecast, caption=True, units="imperial")
        self.assertEqual(no_caption.tobytes(), metric_no_caption.tobytes())
        self.assertNotEqual(no_caption.tobytes(), caption.tobytes())
        difference = ImageChops.difference(no_caption, caption).getbbox()
        self.assertIsNotNone(difference)
        self.assertEqual(difference[1], caption.height - CAPTION_HEIGHT)


class FakeProvider:
    def __init__(self, forecast=None, error=None):
        self.forecast = forecast or sample_forecast()
        self.error = error

    def fetch_today(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.forecast


class FakePanel:
    def __init__(self, fail=False):
        self.pushes = []
        self.fail = fail

    quantize_spectra6 = staticmethod(real_panel.quantize_spectra6)
    load_state = staticmethod(real_panel.load_state)
    save_state = staticmethod(real_panel.save_state)
    in_quiet_hours = staticmethod(real_panel.in_quiet_hours)

    def push_panel(self, image, rotate, saturation, panel=""):
        if self.fail:
            raise RuntimeError("panel unavailable")
        self.pushes.append((image.size, rotate, saturation, panel))


class EinkPreviewTests(unittest.TestCase):
    def test_matching_palette_mirrors_driver_saturation_blend(self):
        self.assertEqual(
            driver_matching_palette(0.6),
            (
                (0, 0, 0),
                (198, 200, 201),
                (226, 216, 42),
                (195, 43, 45),
                (36, 35, 158),
                (34, 156, 42),
            ),
        )

    def test_quantization_uses_six_inks_and_honors_saturation(self):
        gradient = Image.new("RGB", (256, 64))
        gradient.putdata(
            [
                (x, round((x + y * 4) % 256), 255 - x)
                for y in range(64)
                for x in range(256)
            ]
        )
        low = quantize_spectra6(gradient, 0.2)
        high = quantize_spectra6(gradient, 0.8)
        self.assertNotEqual(low.tobytes(), high.tobytes())
        for image in (low, high):
            colors = image.getcolors(maxcolors=2_000_000)
            self.assertIsNotNone(colors)
            self.assertTrue(
                {color for _count, color in colors}.issubset(
                    set(DISPLAY_APPEARANCE_PALETTE)
                )
            )

    def test_blue_bias_is_selective_and_moves_blue_pixels_toward_blue_point(self):
        source_blue = (80, 120, 200)
        image = Image.new("RGB", (2, 1))
        image.putdata(((210, 60, 45), source_blue))
        biased = apply_blue_bias(image, amount=0.4, saturation=0.6)
        self.assertEqual(biased.getpixel((0, 0)), (210, 60, 45))

        blue_point = driver_matching_palette(0.6)[4]
        shifted_blue = biased.getpixel((1, 0))
        original_distance = sum(
            abs(channel - target)
            for channel, target in zip(source_blue, blue_point)
        )
        shifted_distance = sum(
            abs(channel - target)
            for channel, target in zip(shifted_blue, blue_point)
        )
        self.assertLess(shifted_distance, original_distance)

        pale_sky = Image.new("RGB", (256, 64), (120, 150, 190))
        normal = quantize_spectra6(pale_sky, saturation=0.4)
        boosted = quantize_spectra6(
            apply_blue_bias(pale_sky, amount=0.3, saturation=0.4),
            saturation=0.4,
        )
        physical_blue = DISPLAY_APPEARANCE_PALETTE[4]

        def blue_pixels(output):
            pixels = (
                output.get_flattened_data()
                if hasattr(output, "get_flattened_data")
                else output.getdata()
            )
            return sum(pixel == physical_blue for pixel in pixels)

        self.assertGreater(blue_pixels(boosted), blue_pixels(normal))


class PreviewAppTests(unittest.TestCase):
    def test_gui_preview_helper_is_six_color_and_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = dict(app.DEFAULTS)
            cfg.update(
                location="Test Valley",
                scene_source="procedural",
                output=str(Path(directory) / "weather.png"),
                state=str(Path(directory) / "state.json"),
            )
            result = generate_eink_preview(cfg, provider=FakeProvider())
            self.assertEqual(result.image.mode, "RGB")
            self.assertEqual(result.image.size, (real_panel.PANEL_H, real_panel.PANEL_W))
            colors = result.image.getcolors(maxcolors=2_000_000)
            self.assertIsNotNone(colors)
            self.assertLessEqual(len(colors), 6)
            self.assertTrue(
                {color for _count, color in colors}.issubset(
                    set(DISPLAY_APPEARANCE_PALETTE)
                )
            )
            self.assertIsNone(result.source_path)
            self.assertEqual(result.saturation, cfg["saturation"])
            self.assertEqual(result.blue_bias, cfg["blue_bias"])
            self.assertFalse(Path(cfg["output"]).exists())
            self.assertFalse(Path(cfg["state"]).exists())


class AppTests(unittest.TestCase):
    def config(self, directory):
        cfg = dict(app.DEFAULTS)
        cfg.update(
            location="Test Valley",
            output=str(Path(directory) / "weather.png"),
            state=str(Path(directory) / "state.json"),
            quiet_start=22,
            quiet_end=6,
        )
        return cfg

    def test_preview_never_writes_state_output_or_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            preview = str(Path(directory) / "preview.png")
            fake_panel = FakePanel()
            result = app.run(
                cfg,
                preview=preview,
                provider=FakeProvider(),
                panel_module=fake_panel,
            )
            self.assertEqual(result, "preview")
            self.assertTrue(Path(preview).exists())
            self.assertFalse(Path(cfg["output"]).exists())
            self.assertFalse(Path(cfg["state"]).exists())
            self.assertEqual(fake_panel.pushes, [])

    def test_ai_source_generates_from_five_activity_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            cfg.update(scene_source="ai", gemini_key="test-key")
            calls = []

            def fake_generator(forecast, activities, **kwargs):
                calls.append((forecast, activities, kwargs))
                return Image.new("RGB", (800, 600), (12, 34, 56))

            artwork, activities = app.create_artwork(
                cfg,
                sample_forecast(),
                ai_generator=fake_generator,
            )
            self.assertEqual(len(activities), 5)
            self.assertEqual(calls[0][1], activities)
            self.assertEqual(calls[0][2]["api_key"], "test-key")
            self.assertEqual(artwork.size, (1600, 1200))

    def test_signature_skips_second_update_and_force_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            fake_panel = FakePanel()
            now = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
            first = app.run(
                cfg, display=True, provider=FakeProvider(), panel_module=fake_panel, now=now
            )
            second = app.run(
                cfg,
                display=True,
                provider=FakeProvider(),
                panel_module=fake_panel,
                now=now + timedelta(hours=1),
            )
            forced = app.run(
                cfg,
                display=True,
                force=True,
                provider=FakeProvider(),
                panel_module=fake_panel,
                now=now + timedelta(hours=2),
            )
            self.assertEqual((first, second, forced), ("updated", "unchanged", "updated"))
            self.assertEqual(len(fake_panel.pushes), 2)
            self.assertTrue(all(push[0] == (real_panel.PANEL_W, real_panel.PANEL_H)
                                for push in fake_panel.pushes))

    def test_quiet_hours_and_panel_failure_do_not_write_state(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            quiet_panel = FakePanel()
            quiet = app.run(
                cfg,
                display=True,
                provider=FakeProvider(),
                panel_module=quiet_panel,
                now=datetime(2026, 7, 5, 23, tzinfo=timezone.utc),
            )
            self.assertEqual(quiet, "quiet")
            self.assertFalse(Path(cfg["state"]).exists())
            self.assertEqual(quiet_panel.pushes, [])

        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            with self.assertRaisesRegex(RuntimeError, "panel unavailable"):
                app.run(
                    cfg,
                    display=True,
                    provider=FakeProvider(),
                    panel_module=FakePanel(fail=True),
                    now=datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
                )
            self.assertFalse(Path(cfg["state"]).exists())

    def test_provider_failure_preserves_existing_output_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            output = Path(cfg["output"])
            state = Path(cfg["state"])
            output.write_bytes(b"old image")
            state.write_text('{"signature": "old", "last_refresh": 1}')
            with self.assertRaisesRegex(RuntimeError, "offline"):
                app.run(cfg, provider=FakeProvider(error=RuntimeError("offline")))
            self.assertEqual(output.read_bytes(), b"old image")
            self.assertEqual(state.read_text(), '{"signature": "old", "last_refresh": 1}')


if __name__ == "__main__":
    unittest.main()
