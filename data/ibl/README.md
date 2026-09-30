# IBL Brainwide Map layout

The inventory notebook (`tutorials/ibl_inventory.ipynb`) reads small extracted tables
from `data/ibl/tables/` (34 MB, git-ignored). The spike data behind them is about
322 GB, so the tables are built on a machine with disk and copied here.

## Build the tables

```bash
pip install ONE-api iblatlas
python data/ibl/ibl_download.py --cache /big/disk/ibl --units all   # keep-set, ~322 GB
python data/ibl/ibl_extract.py --cache /big/disk/ibl --out data/ibl/tables
python data/ibl/ibl_size_scan.py        # server-side sizes, no download
mv ibl_bwm_sizes.csv data/ibl/tables/server_sizes.csv
python data/ibl/ibl_coords.py --tables data/ibl/tables   # no bulk download, ~3 min
```

- `ibl_download.py`: default-revision `alf/` files (sorted spikes, unit QC, trials,
  wheel, licks, left-camera pose and motion energy) for the 459 Brainwide Map
  sessions. Raw ephys, raw video and waveforms are skipped. Safe to rerun.
- `ibl_extract.py`: writes `sessions`, `probes`, `units`, `trials` parquet tables and
  `raster.npz` (30 s of spikes from the median-units session).
- `ibl_size_scan.py`: sizes of the whole public release per session.
- `ibl_coords.py`: ML / AP / DV (µm from bregma) of every unit, from three small alf files
  per probe on the public server. Checks the atlas IDs against `units.parquet`.

The tables look like:

```
data/ibl/tables/sessions.parquet
data/ibl/tables/probes.parquet
data/ibl/tables/units.parquet
data/ibl/tables/trials.parquet
data/ibl/tables/raster.npz
data/ibl/tables/server_sizes.csv
data/ibl/tables/unit_coords.parquet
```

If they already live somewhere else:

```bash
ln -s /path/to/ibl_tables data/ibl/tables
```
