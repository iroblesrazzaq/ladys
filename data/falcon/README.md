# FALCON NWB layout

The inventory notebook (`tutorials/falcon_inventory.ipynb`) reads public FALCON
calibration files from this directory. Git ignores `*.nwb`; download them locally.

## Download

From the repo root (`dandi` is already a LaDyS dependency):

```bash
pip install -e ".[benchmarks]"
bash data/download_falcon.sh
```

That is the same as:

```bash
dandi download DANDI:000954 -o data/falcon/H1     # human reach/grasp
dandi download DANDI:000950 -o data/falcon/H2     # human handwriting
dandi download DANDI:000941 -o data/falcon/M1-A   # monkey L reach/grasp + EMG
dandi download DANDI:001209 -o data/falcon/M1-B   # monkey X reach/grasp + EMG
dandi download DANDI:000953 -o data/falcon/M2     # monkey N fingers (~16 GB)
dandi download DANDI:001046 -o data/falcon/B1     # zebra finch song
```

DANDI writes `<output>/<dandiset-id>/sub-...`, which is the tree the notebook walks:

```
data/falcon/H1/000954/sub-HumanPitt-held-in-calib/*.nwb
data/falcon/H1/000954/sub-HumanPitt-held-in-minival/*.nwb
data/falcon/H1/000954/sub-HumanPitt-held-out-calib/*.nwb
```

About 19 GB total. `held-in-minival` is a duplicate of held-in; the notebook lists
those files then ignores them.

If the NWBs already live somewhere else:

```bash
ln -s /path/to/existing/falcon data/falcon
```
