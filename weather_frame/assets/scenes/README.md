# Generated watercolor scenes

Gemini-generated scenes are stored as:

```text
<environment>/<condition>.png
```

Each PNG is normalized to 1600×1200 RGB. The runtime reads these files locally;
it never calls an image-generation API. Existing files are skipped by the
generator unless `--force` is explicitly supplied.

This README keeps the directory in the repository before any paid scenes have
been generated.

