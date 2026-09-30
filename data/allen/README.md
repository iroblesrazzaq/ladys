# Allen Visual Coding Neuropixels layout

The inventory notebook (`tutorials/allen_inventory.ipynb`) reads small extracted tables
from `data/allen/tables/` (21 MB, git-ignored). The NWBs behind them are about 146 GB
(the public bucket without LFP), so the tables are built on a machine with disk and
copied here.

## Build the tables

```bash
aws s3 sync --no-sign-request --exclude "*_lfp.nwb" \
    s3://allen-brain-observatory/visual-coding-neuropixels/ecephys-cache/ /big/disk/allen/data
cd /big/disk/allen
python /path/to/ladys/data/allen/allen_extract.py --data data --out tables
python /path/to/ladys/data/allen/allen_draft_counts.py
```

- `allen_extract.py`: writes `sessions`, `units` (noise units included) and `stimuli`
  parquet tables and `raster.npz` (spikes around the flash block of one session).
  Waveforms and spike amplitudes are never loaded.
- `allen_draft_counts.py`: per-unit flash and drifting-grating spike counts for the
  top-4 sessions of each type, used to guess the draft's Table 8 sessions.

`bucket_files.csv` (the S3 listing: key, bytes, session, kind) and `nwb_storage.csv`
(per-session bytes by NWB dataset) were written with one-off commands and have no
script here yet.

```
data/allen/tables/sessions.parquet
data/allen/tables/units.parquet
data/allen/tables/stimuli.parquet
data/allen/tables/draft_window_counts.parquet
data/allen/tables/raster.npz
data/allen/tables/bucket_files.csv
data/allen/tables/nwb_storage.csv
data/allen/tables/stim_samples/
```

`stim_samples/` holds the real stimuli shown in the notebook's stimulus gallery: 4 of the 118
natural-scene TIFFs and 6 frames of natural movie one, from the bucket's stimulus templates.
The movie `.h5` template is really a Python 2 `.npy` (uint8, 900 × 304 × 608, 96-byte header):

```bash
cd /big/disk/allen/data && mkdir -p ../tables/stim_samples
cp natural_scene_templates/natural_scene_{5,17,42,88}.tiff ../tables/stim_samples/
python -c "import numpy as np; m = np.memmap('natural_movie_templates/natural_movie_1.h5', np.uint8, 'r', \
    offset=96, shape=(900, 304, 608)); np.save('../tables/stim_samples/natural_movie_one_frames.npy', \
    np.array(m[::150]))"
```

If they already live somewhere else:

```bash
ln -s /path/to/allen_tables data/allen/tables
```
