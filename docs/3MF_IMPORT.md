# Bambu Studio sliced `.3mf` import

The importer is intentionally a **pre-print input helper**. It does not contact the printer, Bambuddy, Spoolman or Bambu Cloud.

A Bambu Studio 3MF is a ZIP container. For quoting, the app reads only:

`Metadata/slice_info.config`

Bambu Studio's source defines this file as `SLICE_INFO_CONFIG_FILE` and writes one sliced `<plate>` block with metadata including:

- `index` — plate index;
- `prediction` — estimated normal-mode print time in seconds;
- `weight` — total sliced filament weight;
- `<filament ... used_g="...">` — per-filament grams;
- filament attributes such as `id`, `type`, `color`, `used_m`, and support/object flags.

The importer therefore does **not** estimate filament from model geometry. It consumes Bambu Studio's own sliced statistics.

## Safety

- The uploaded 3MF is not persisted by the app.
- Only `Metadata/slice_info.config` is read from the archive.
- The XML member has a 10 MiB uncompressed size limit.
- An unsliced project without slice info is rejected with an actionable message.
- A 3MF import intentionally does not invent a purchase price. After import, the user must select the real local/Spoolman spool or enter the price manually before a quote can be calculated or saved.
