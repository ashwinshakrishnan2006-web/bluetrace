# Bluetrace

Satellite oil spill screening and probable vessel source association. Complete local academic prototype for MDI3001 Advances in Web Technologies. Prepared for Rakesh N (24MID0218), Sanjay Ramaswamy S (24MID0346), and Ashwinsha P (24MID0226), guided by DEEPA D.

## Start on Windows

1. Extract the ZIP fully into a writable folder.
2. Install **Python 3.12** (64-bit) and include the Python launcher.
3. Double-click `start_windows.bat`. First launch requires internet to install Python dependencies.
4. Open **http://127.0.0.1:8000** in Chrome, Edge or Firefox. Keep the console running.
5. Choose **Run fictional vessel demo** for the complete geographic workflow, or **Screen a real SAR test image** for the trained detector.
6. Stop with Ctrl+C in the console.

The real SAR images, masks and trained model are already included. No dataset download or training is required to demonstrate the project. After dependencies are installed it works offline; the dataset reference hyperlink is external. macOS/Linux users with Python 3.12 can run `bash start_macos_linux.sh`.

Manual setup:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

If port 8000 is occupied: `python server.py --port 8001` and open http://127.0.0.1:8001.

## What is implemented

- Responsive HTML/CSS/JavaScript dashboard, new investigation form and methodology page.
- Real trained random-forest segmentation; image, mask and overlay views.
- PNG/JPEG validation, AIS CSV ingestion and geographic/environmental validation.
- Backtracking over nine assumed ages; source circles and SVG vessel tracks.
- Ranked candidate evidence, no-match results and chronological timeline.
- SQLite persistence, incident reopening/deletion, JSON and GeoJSON exports.
- Original public dataset pairs, publisher split manifests, pinned provenance and checksums.
- Training and evaluation scripts, model artifact, per-image results and automated tests.

## Data and evaluation

`data/public/` contains **173 real Sentinel-1 SAR-derived image/mask pairs** from J.R.M. Garcia, Oil Spill Segmentation Dataset (800x600), Garcia-INPE, version 0.2.1. Source: https://github.com/Garcia-INPE/oilspill-detection-dataset. Pinned commit: `1b9a62c30a9da9698eb470562aa976f9bd1e8fc3`. License: CC BY 4.0; see original LICENSE and CITATION.cff. Original image and mask bytes are unmodified. Model processing resizes images bilinearly to 200x150 and masks with nearest-neighbor resampling; nonzero labels map to slick. Actual files contain 0, 1 and 2, although the upstream dataset card describes 0/1. Both nonzero labels are combined, consistent with its documented `mask > 0` binary benchmark rule.

Splits: 108 training, 43 validation, 22 test tiles. Source-image groups are disjoint. Up to 500 pixels per class per training image are sampled with seed 42. A 48-tree random forest uses 12 image features, maximum depth 14 and minimum leaf size 8. Threshold 0.80 is selected by validation IoU from 0.20–0.80 in 0.05 steps. Test data is used only for final evaluation.

Measured held-out results at 200x150: IoU 53.26%, precision 56.59%, recall 90.07%, F1 69.51%, pixel accuracy 99.13%. Background dominates; pixel accuracy must not be interpreted as 99% oil detection reliability. Reference dark-percentile baseline IoU: 6.64%. These are our executed lightweight baseline results, not the publisher's full-resolution benchmark results. `reports/metrics.json` contains exact counts, parameters, runtime and environment; `reports/test_per_image.csv` contains all 22 image results.

`data/demo/` is separate: synthetic SAR-style image/mask, **57 fictional AIS rows for three fictional vessels**, environmental assumptions and ready-to-submit JSON. It is software demonstration data, not a recorded spill. Never pair these vessel tracks with the public SAR image as if they described the same incident.

## Reproduce

```sh
python scripts/make_demo.py
python scripts/train_model.py
python -m unittest discover -s tests -v
```

To reacquire original images (optional, network needed): `python scripts/download_dataset.py`. It pins the upstream commit and validates Git LFS SHA256 hashes. `data/public/provenance.json` records all downloaded file hashes.

Only load the included model or one produced by the training script. Joblib files are executable Python serialization; do not replace the model with untrusted downloads. The server never loads user-uploaded models.

## Input conventions

AIS CSV: `mmsi,timestamp,latitude,longitude` (optional `name`). MMSI must contain nine digits; timestamp must include timezone. Duplicate identical records are collapsed; conflicting positions are rejected. No extrapolation. Interpolation is blocked for gaps >30 minutes or implied speeds >25 m/s.

Geography: north-up bounds, west < east, south < north, maximum 5 degrees per axis; antimeridian tiles unsupported. Bounds must describe the uploaded image. Geographic analysis is optional. Enter current/wind velocity in m/s with east and north positive, windage fraction 0–0.1, and assumed age interval 0.25–48 hours.

For each connected predicted region of at least 12 working pixels, the application retains at most the 20 largest regions. Source velocity = current + windage × wind. Radius = 250 m + uncertainty × age in seconds; this is an assumed radius, not a confidence interval. Each vessel is ranked by its strongest spatial match plus temporal coverage and record completeness; scores are heuristic, not calibrated probabilities.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | /api/health | Server/model/data status |
| GET | /api/metrics | Executed held-out model results |
| GET | /api/dataset/sample | First public test image for image-only demonstration |
| GET | /api/incidents | Saved investigation summaries |
| POST | /api/incidents | Validate, analyze and save a JSON request |
| POST | /api/demo | Run the labelled synthetic geographic demo |
| GET | /api/incidents/{id} | Reopen complete result |
| GET | /api/incidents/{id}/report | Download JSON report |
| GET | /api/incidents/{id}/geojson | Download geographic features |
| POST | /api/incidents/{id}/delete | Delete record and its assets |

Use `data/demo/request.json` as the full request schema example. Assets are read at `/assets/{id}/image.png`, `mask.png`, `overlay.png`. Errors return `{ "error": "message" }`: 400 invalid input, 403 origin/host rejection, 404 unknown resource, 413 oversized request, 429 analysis already running, 500 unexpected failure.

## Project layout

- `static/`: complete frontend
- `server.py`: HTTP API, SQLite and assets
- `analysis.py`: image, AIS, drift and ranking logic
- `data/public/`: original licensed images, labels and split manifests
- `data/demo/`: reproducible fictional end-to-end fixture
- `models/segmenter.joblib`: trained model
- `scripts/`: data acquisition, fixture generation and training
- `tests/`: backend and data integrity test suite
- `reports/`: measured metrics, test log and generated analysis examples
- `runtime/`: automatically created SQLite database and incident PNG files

## Verification and boundaries

22 automated tests passed in the build environment. Tests cover dataset hashes and pair alignment, split leakage, metric arithmetic, image validation, AIS guards, HTTP analysis/reopen/export/delete, security checks and invalid input cleanup. JavaScript syntax passed `node --check static/app.js`. Browser interaction and desktop/mobile visual QA have not been executed in this environment; manually check the responsive UI before presenting. Windows launcher instructions have been prepared but execution was tested on Linux, not Windows.

This is a local single-analyst academic prototype. It binds to 127.0.0.1, validates Host/Origin, and uses a restrictive content security policy. It has no accounts, TLS, cloud hosting, multi-user access or production deployment. Do not expose it to the internet without a production server and authentication. Synthetic attribution is not real-world attribution validation; that requires incident-matched AIS, trustworthy acquisition bounds/time, measured environmental fields and known-source labels. The model cannot distinguish oil identity or assign legal responsibility.
