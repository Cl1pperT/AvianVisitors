# Generated activity-scene variants

Curated activity variants are stored separately from weather-only artwork:

```text
<activity>/<environment>/<condition>.png
```

Each 1600×1200 RGB PNG is generated from the matching weather-only scene. The
base scene is used as a positive reference and is never modified. Existing
activity variants are skipped unless `--force` is explicitly supplied.
