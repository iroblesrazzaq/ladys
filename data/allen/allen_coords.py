"""Brain coordinates of every Allen Visual Coding Neuropixels unit, without the NWBs.

Downloads the public channels.csv (6.6 MB) from the ecephys cache and writes
tables/unit_coords.parquet: one row per row of tables/units.parquet, with the Allen CCF
coordinates (µm; +AP posterior, +DV ventral, +LR right) of the unit's peak channel.

Coordinates are NaN when Allen gives none: AP / LR = -1000 marks an unregistered probe
(6 BO sessions have no registered probe), and some units' peak channels are not in
channels.csv. Channels above the brain keep their negative DV.

    python data/allen/allen_coords.py --tables data/allen/tables
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

URL = 'https://allen-brain-observatory.s3.amazonaws.com/visual-coding-neuropixels/ecephys-cache/channels.csv'
CCF = {'ap_ccf_um': 'anterior_posterior_ccf_coordinate', 'dv_ccf_um': 'dorsal_ventral_ccf_coordinate',
       'lr_ccf_um': 'left_right_ccf_coordinate'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tables', default='data/allen/tables')
    args = ap.parse_args()
    tables = Path(args.tables)
    path = tables / 'channels.csv'
    if not path.exists():
        pd.read_csv(URL).to_csv(path, index=False)
    ch = pd.read_csv(path).set_index('id')[list(CCF.values())].rename(columns={v: k for k, v in CCF.items()})
    ch = ch.astype(float)
    ch[(ch.ap_ccf_um < 0) | (ch.lr_ccf_um < 0)] = np.nan

    units = pd.read_parquet(tables / 'units.parquet')
    coords = units[['session_id', 'unit_id']].join(ch, on=units.peak_channel_id)
    coords.to_parquet(tables / 'unit_coords.parquet', index=False)
    has = coords[list(CCF)].notna().all(axis=1)
    print(f'{int(has.sum())} of {len(coords)} units have CCF coordinates '
          f'({int(has[units.qc].sum())} of {int(units.qc.sum())} QC units) -> {tables / "unit_coords.parquet"}')


if __name__ == '__main__':
    main()
