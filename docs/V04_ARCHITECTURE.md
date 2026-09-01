# v0.4 composition layer

v0.4 deliberately adds sliced Bambu Studio 3MF import as a small composition layer instead of rewriting the stable v0.3 route module.

`app/server.py` imports the existing `app.main` application, installs quote-input validation, adds the read-only `/api/import/3mf` endpoint, and gives Jinja a v0.4 order-form override. Docker starts `app.server:app`.

This keeps the v0.3 order/statistics/export implementation unchanged while the 3MF workflow is validated in real use. A later refactor can fold the composition layer into a router-based application structure together with the planned database migration layer.

External ownership rules remain unchanged: no writes to Spoolman, Bambuddy, Home Assistant, the printer, or Bambu Cloud.
