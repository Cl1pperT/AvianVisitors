"""Small Tkinter application for weather-art e-ink previews.

This module only fetches and renders previews. It never writes refresh state or
calls the physical panel driver.
"""
from __future__ import annotations

import argparse
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from frame import display as panel

from .app import DEFAULTS, fetch_forecast, load_config, validate_config
from .renderer import STYLES, render_forecast
from .scene_catalog import ENVIRONMENTS, generated_scene_path
from .weather import DailyForecast, ForecastProvider


@dataclass(frozen=True)
class PreviewResult:
    """Forecast metadata and the final six-color preview image."""

    forecast: DailyForecast
    image: Image.Image
    environment: str
    condition: str
    source_path: Path | None


def generate_eink_preview(
    cfg: Mapping[str, Any],
    provider: ForecastProvider | None = None,
) -> PreviewResult:
    """Fetch, render, and quantize a preview without state or hardware access."""
    validate_config(cfg)
    forecast = fetch_forecast(cfg, provider)
    artwork = render_forecast(
        forecast,
        style=str(cfg["style"]),
        caption=bool(cfg["caption"]),
        units=str(cfg["units"]),
        scene_source=str(cfg["scene_source"]),
        environment=str(cfg["environment"]),
    )
    preview = panel.quantize_spectra6(artwork).convert("RGB")

    environment, condition, scene_path = generated_scene_path(
        forecast, str(cfg["environment"])
    )
    uses_scene = str(cfg["scene_source"]) != "procedural" and scene_path.is_file()
    return PreviewResult(
        forecast=forecast,
        image=preview,
        environment=environment,
        condition=condition,
        source_path=scene_path if uses_scene else None,
    )


def _initial_config(path: str) -> dict[str, Any]:
    expanded = os.path.expanduser(path)
    if os.path.isfile(expanded):
        return load_config(expanded)
    return dict(DEFAULTS)


def _launch_gui(initial_cfg: Mapping[str, Any]) -> None:
    # Tk is imported lazily so headless systems can still import and test the
    # preview-generation function.
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        from PIL import ImageTk
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter is unavailable; install the operating system's python3-tk package"
        ) from exc

    class WeatherPreviewWindow:
        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title("Weather Frame E-Ink Preview")
            self.root.minsize(900, 720)

            self.base_cfg = dict(initial_cfg)
            self.results: queue.Queue[tuple[str, object]] = queue.Queue()
            self.preview_result: PreviewResult | None = None
            self.photo = None

            self.location = tk.StringVar(value=str(initial_cfg.get("location") or ""))
            self.country = tk.StringVar(
                value=str(initial_cfg.get("country_code") or "")
            )
            self.environment = tk.StringVar(
                value=str(initial_cfg.get("environment") or "auto")
            )
            self.scene_source = tk.StringVar(
                value=str(initial_cfg.get("scene_source") or "auto")
            )
            self.style = tk.StringVar(value=str(initial_cfg.get("style") or "woodblock"))
            self.caption = tk.BooleanVar(value=bool(initial_cfg.get("caption")))
            self.status = tk.StringVar(
                value="Enter a city or postal code, then generate a preview."
            )
            self.details = tk.StringVar(value="")

            self._build()
            self.root.after(100, self._poll_results)

        def _build(self) -> None:
            outer = ttk.Frame(self.root, padding=14)
            outer.grid(row=0, column=0, sticky="nsew")
            self.root.rowconfigure(0, weight=1)
            self.root.columnconfigure(0, weight=1)
            outer.columnconfigure(1, weight=1)
            outer.rowconfigure(3, weight=1)

            ttk.Label(outer, text="Location").grid(
                row=0, column=0, sticky="w", padx=(0, 8)
            )
            location_entry = ttk.Entry(outer, textvariable=self.location, width=34)
            location_entry.grid(row=0, column=1, sticky="ew")
            location_entry.bind("<Return>", lambda _event: self.generate())

            ttk.Label(outer, text="Country").grid(
                row=0, column=2, sticky="w", padx=(14, 8)
            )
            ttk.Entry(outer, textvariable=self.country, width=6).grid(
                row=0, column=3, sticky="w"
            )

            options = ttk.Frame(outer)
            options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 10))

            ttk.Label(options, text="Landscape").grid(row=0, column=0, padx=(0, 6))
            environment_values = ("auto", *tuple(ENVIRONMENTS))
            ttk.Combobox(
                options,
                textvariable=self.environment,
                values=environment_values,
                state="readonly",
                width=23,
            ).grid(row=0, column=1, padx=(0, 14))

            ttk.Label(options, text="Source").grid(row=0, column=2, padx=(0, 6))
            ttk.Combobox(
                options,
                textvariable=self.scene_source,
                values=("auto", "generated", "procedural"),
                state="readonly",
                width=11,
            ).grid(row=0, column=3, padx=(0, 14))

            ttk.Label(options, text="Style").grid(row=0, column=4, padx=(0, 6))
            ttk.Combobox(
                options,
                textvariable=self.style,
                values=tuple(STYLES),
                state="readonly",
                width=11,
            ).grid(row=0, column=5, padx=(0, 14))
            ttk.Checkbutton(
                options, text="Forecast caption", variable=self.caption
            ).grid(row=0, column=6)

            actions = ttk.Frame(outer)
            actions.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 10))
            self.generate_button = ttk.Button(
                actions, text="Generate E-Ink Preview", command=self.generate
            )
            self.generate_button.pack(side="left")
            self.save_button = ttk.Button(
                actions, text="Save PNG…", command=self.save, state="disabled"
            )
            self.save_button.pack(side="left", padx=(8, 0))
            ttk.Label(actions, textvariable=self.status).pack(
                side="left", padx=(14, 0)
            )

            self.image_frame = tk.Frame(
                outer,
                background="#202124",
                borderwidth=12,
                relief="sunken",
            )
            self.image_frame.grid(
                row=3, column=0, columnspan=4, sticky="nsew"
            )
            self.image_frame.rowconfigure(0, weight=1)
            self.image_frame.columnconfigure(0, weight=1)
            self.image_label = tk.Label(
                self.image_frame,
                text="Six-color Spectra preview appears here",
                background="#202124",
                foreground="#d6d6d6",
            )
            self.image_label.grid(row=0, column=0, sticky="nsew")
            self.image_label.bind("<Configure>", self._resize_preview)

            ttk.Label(outer, textvariable=self.details).grid(
                row=4, column=0, columnspan=4, sticky="w", pady=(10, 0)
            )
            location_entry.focus_set()

        def _request_config(self) -> dict[str, Any]:
            cfg = dict(self.base_cfg)
            cfg.update(
                {
                    "location": self.location.get().strip(),
                    "country_code": self.country.get().strip().upper(),
                    "environment": self.environment.get(),
                    "scene_source": self.scene_source.get(),
                    "style": self.style.get(),
                    "caption": bool(self.caption.get()),
                }
            )
            return cfg

        def generate(self) -> None:
            if not self.location.get().strip():
                messagebox.showerror("Location required", "Enter a city or postal code.")
                return
            self.generate_button.configure(state="disabled")
            self.save_button.configure(state="disabled")
            self.status.set("Fetching forecast and rendering…")
            self.details.set("")
            cfg = self._request_config()

            def worker() -> None:
                try:
                    result = generate_eink_preview(cfg)
                except Exception as exc:  # Presented in the GUI on the main thread.
                    self.results.put(("error", exc))
                else:
                    self.results.put(("result", result))

            threading.Thread(target=worker, daemon=True).start()

        def _poll_results(self) -> None:
            try:
                kind, payload = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.generate_button.configure(state="normal")
                if kind == "error":
                    self.status.set("Preview failed.")
                    messagebox.showerror("Weather preview failed", str(payload))
                else:
                    self._show_result(payload)
            self.root.after(100, self._poll_results)

        def _show_result(self, payload: object) -> None:
            result = payload
            if not isinstance(result, PreviewResult):
                raise TypeError("unexpected preview result")
            self.preview_result = result
            self.save_button.configure(state="normal")
            self.status.set("Preview ready — no hardware or refresh state was touched.")
            self._resize_preview()

            forecast = result.forecast
            if self.base_cfg.get("units") == "metric":
                temperatures = f"{forecast.high_c:.0f}°C / {forecast.low_c:.0f}°C"
                wind = f"{forecast.wind_speed_max_kmh:.0f} km/h"
            else:
                high_f = forecast.high_c * 9 / 5 + 32
                low_f = forecast.low_c * 9 / 5 + 32
                temperatures = f"{high_f:.0f}°F / {low_f:.0f}°F"
                wind = f"{forecast.wind_speed_max_kmh / 1.609344:.0f} mph"
            source = (
                f"{ENVIRONMENTS[result.environment].name} generated scene"
                if result.source_path
                else "procedural fallback"
            )
            condition = result.condition.replace("_", " ").title()
            self.details.set(
                f"{forecast.location_name} · {condition} · High/low {temperatures} · "
                f"Precipitation {forecast.precipitation_probability}% · "
                f"Wind {wind} · {source}"
            )

        def _resize_preview(self, _event=None) -> None:
            if not self.preview_result:
                return
            width = max(320, self.image_label.winfo_width() - 8)
            height = max(240, self.image_label.winfo_height() - 8)
            image = self.preview_result.image.copy()
            # Keep the screen representation inside the same six-color palette.
            # A smoothing resampler would invent intermediate monitor colors.
            image.thumbnail((width, height), Image.Resampling.NEAREST)
            self.photo = ImageTk.PhotoImage(image)
            self.image_label.configure(image=self.photo, text="")

        def save(self) -> None:
            if not self.preview_result:
                return
            path = filedialog.asksaveasfilename(
                title="Save e-ink preview",
                defaultextension=".png",
                filetypes=(("PNG image", "*.png"),),
                initialfile="weather-eink-preview.png",
            )
            if not path:
                return
            self.preview_result.image.save(path, format="PNG")
            self.status.set(f"Saved {path}")

        def run(self) -> None:
            self.root.mainloop()

    WeatherPreviewWindow().run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a desktop GUI that simulates Weather Frame artwork in six e-ink colors."
    )
    parser.add_argument(
        "--config",
        default="~/.weatherframe/config.toml",
        help="optional Weather Frame TOML used to prefill controls",
    )
    parser.add_argument(
        "--location",
        default="",
        help="initial city or postal code (overrides the configured location)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = _initial_config(args.config)
        if args.location:
            cfg["location"] = args.location
        _launch_gui(cfg)
    except Exception as exc:
        print(f"weather preview failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
