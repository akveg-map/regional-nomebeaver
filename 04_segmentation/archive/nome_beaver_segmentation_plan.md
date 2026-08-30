# Nome Beaver Segmentation — Implementation Plan

**Prepared:** 2026-04-27  
**Repo:** `https://git.abrinc.com/mmacander/akveg-vhr.git` (branch: `main`)  
**Handoff context:** All 20 nome-beaver VHR strips are fully processed (Steps 200–230 complete on GCS). This plan covers generating two SNIC segmentation options clipped to the nome-beaver study area and building three output mosaics.

---

## Background

### Reference approach — Navy North Slope
Segmentation for the Navy North Slope delivery used `02b_data_reflectance_vhr_gcp/261_segmentation.py`:
- **Input:** `MS_SRLite_02p00m_*.tif` per strip (2m multispectral surface reflectance)
- **Algorithm:** SNIC in Google Earth Engine, kernel=1, SNIC size=10, compactness=1/10000, connectivity=4
- **Post-processing:** two rounds of spectral merging (threshold 0.005) + minimum size filter (5 px)
- **Bands used:** blue, green, red, nir + on-the-fly NDVI

The Navy review tested all combinations of kernel [0,1,2] × size [5,10,15]. The reviewed options are preserved in the GEE asset collection `projects/akveg-map/assets/segments/SNIC_segmentation` (27 assets, 3 sites × 9 parameter combos). The final delivery used `kernel_1_size_10` (stored in `SNIC_segmentation_final`).

### Parameter choices for nome-beaver
- **Moderate:** kernel=1, SNIC size=10 (same as Navy final)
- **Coarse:** kernel=1, SNIC size=15
- Size=5 (finest option) is explicitly **not** wanted

### Input imagery
All 20 `MS_SRLite_02p00m` strips are at:
```
gs://akveg-data/vhr/nome_beaver/processed/<STRIP_ID>/225_srlite/MS_SRLite_02p00m_<STRIP_ID>.tif
```
Strip IDs (sensor mix: 2× QB02, 2× GE01, 5× WV02, 11× WV03, years 2007–2024):
```
20070621_214244_QB02_1010010005B35C00   20190818_214939_WV03_104001004F377C00
20070811_215942_QB02_10100100070F9C00   20190818_215048_WV03_104001004E81AD00
20100823_213936_WV02_1030010006605800   20190818_215105_WV03_1040010050B5A700
20120822_212850_GE01_1050410000845300   20210719_212543_WV03_104001006C406B00
20130713_212615_WV02_1030010025161B00   20220712_214724_WV02_10300100D6D40F00
20160725_213211_WV03_1040010020905D00   20220712_214749_WV02_10300100D697EE00
20160818_212253_WV03_10400100209F8E00   20240623_212142_WV03_10400100982C3400
20190722_213845_GE01_10500100177F7300   20240623_212222_WV03_1040010097BADA00
20190818_214918_WV03_1040010052680700   20240623_212229_WV03_10400100980CE800
20190818_214939_WV03_104001004F377C00   20240623_212311_WV03_10400100988B6F00
                                        20240724_212901_WV02_103001010157B600
```

### Existing partial work
Several nome-beaver strips already have per-strip GEE segment assets at `kernel_1_size_10` in `projects/akveg-map/assets/segments/` (not clipped to AOI, not all 20 strips, no size-15 versions). These are useful for quick sanity checks in the GEE Code Editor but should **not** be used as final outputs — redo the full run clipped to the AOI.

### Visual reference for parameter selection
Before committing to the full 40-task run, visually compare size=10 vs size=15 in the GEE Code Editor using the existing Navy assets:
- `projects/akveg-map/assets/segments/SNIC_segmentation` — all 27 reviewed combos (3 Navy sites × kernel [0,1,2] × size [5,10,15])
- `projects/akveg-map/assets/segments/SNIC_segmentation_final` — the 3 final size=10 deliveries

Load one of the Icy Cape or Kuparuk assets at size=10 and size=15 side by side to confirm the coarse option is at the desired granularity before running nome-beaver.

### COG-backed ImageCollection pattern
The COG-backed collection approach for Step 1 already exists in this project. Use `projects/akveg-map/assets/reflectance_vhr/ortho_toa_images` as the reference implementation for how to register GCS COGs as a GEE ImageCollection without copying data.

---

## Prerequisites (must be resolved before starting)

**1. Nome-beaver AOI asset**  
The study area boundary must exist as a GEE FeatureCollection asset. Navy site boundaries are at `projects/akveg-map/assets/study_areas/` (IcyCape, McIntyre, Barrow). A nome-beaver equivalent needs to be created or confirmed there. The AOI should be significantly smaller than the full strip footprints.

**2. Mosaic priority rule**  
20 strips span 2007–2024 with varying sensors and dates. Where strips overlap in the AOI, define the priority order (e.g., most recent acquisition date, or ranked by sensor quality WV03 > WV02 > GE01 > QB02, or a hand-specified rank). This drives both segment and MS SRLite mosaic composition.

**3. Gap handling in segment mosaic**  
Cloud and shadow masked pixels produce nodata gaps in individual strip segments. Decide: should gaps in a higher-priority strip be filled by the next-priority strip, or left as nodata? Fill-from-next is more useful for continuous OBIA but more complex to implement.

---

## Step 1 — Register COG-backed ImageCollection in GEE

**New script:** `260_register_nome_beaver_cog_collection.py`

Register the 20 `MS_SRLite_02p00m` GCS COGs as a GEE ImageCollection asset without copying data, using the external COG manifest approach. Reference pattern: `projects/akveg-map/assets/reflectance_vhr/ortho_toa_images` (existing COG-backed collection in the same project).

Each image should carry properties: `strip_id`, `sensor`, `acquisition_date` (YYYYMMDD), `priority` (integer from mosaic priority rule above).

**Output asset:** `projects/akveg-map/assets/reflectance_vhr/nome_beaver_ms_srlite_02p00m`  
**Conda env:** `ee`

---

## Step 2 — Per-strip segmentation in GEE

**Modified script:** `261_segmentation.py`  
Current script hardcodes `KERNEL_SIZES = [1]` and `SNIC_SIZES = [10]`. Extend with:
- `--snic-sizes` CLI arg (list, e.g. `--snic-sizes 10 15`)
- `--aoi` CLI arg (GEE asset path for the AOI FeatureCollection)
- Load each strip from the registered ImageCollection by `strip_id` property rather than `ee.Image.loadGeoTIFF()`
- Export **directly to GCS** via `ee.batch.Export.image.toCloudStorage()` — no intermediate GEE asset step (the Navy `toAsset()` → `toCloudStorage()` two-hop was not optimised)

**On clipping:** Do **not** physically clip imagery before SNIC. Pass the AOI geometry (with a ~100m buffer) as the `region` parameter to the GEE export. GEE evaluates lazily so this confines computation without a pre-clip step. The buffer ensures segments straddling the boundary are complete; final mosaic clips to the unbuffered AOI.

**Segmentation parameters** (same as Navy, two sizes):
```python
KERNEL_SIZES    = [1]
SNIC_SIZES      = [10, 15]       # moderate, coarse
COMPACTNESS     = 1/10000
CONNECTIVITY    = 4
THRESHOLD_SPECTRAL = 0.005       # two passes
THRESHOLD_SIZE  = 5              # pixels
SCALE           = 2              # metres
```

**Output naming convention** (GCS):
```
gs://akveg-data/vhr/nome_beaver/segments/per_strip/
    <STRIP_ID>_SNIC_kernel_1_size_<N>.tif
```

**GEE export data type:** The SNIC `clusters` band is int64. Export as-is; do not cast.

**Total exports:** 20 strips × 2 sizes = 40 GEE tasks. Submit all from a single script run.  
**Conda env:** `ee`

---

## Step 3 — Export matching MS SRLite clips to GCS

From the same script run (or a companion), export each strip's `MS_SRLite_02p00m` clipped to AOI+buffer to GCS COG:
```
gs://akveg-data/vhr/nome_beaver/segments/ms_srlite_clips/
    MS_SRLite_02p00m_<STRIP_ID>_clip.tif
```
These feed the MS SRLite mosaic in Step 4. Use `toCloudStorage()` directly from the COG-backed ImageCollection — no intermediate asset needed.

**Export parameters:** scale=2, crs=EPSG:3338, format=GeoTIFF, cloudOptimized=True.

---

## Step 4 — Build three output mosaics (GCP Batch)

**New script:** `262_build_nome_mosaics.py` — runs as a GCP Batch job, consistent with the rest of the pipeline. Use `rasterio` with `/vsigs/` paths to read from GCS directly; write outputs to GCS via `CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE YES` (standard in the pipeline containers).

Inputs read from GCS per-strip outputs above, ordered by the mosaic priority rule. For each of the two SNIC sizes, produce:

### 4a. Segment ID mosaic
- Source: per-strip `*_SNIC_kernel_1_size_<N>.tif`
- Raw SNIC segment IDs, no renumbering — int64 output
- Mosaic using priority order; where higher-priority strip has nodata (cloud gap), fill from next-priority strip if gap filling is desired (see prerequisite 3)
- Clip to unbuffered AOI
- **Output:** `gs://akveg-data/vhr/nome_beaver/segments/mosaic/segment_id_SNIC_size_<N>.tif`

### 4b. Source image ID mosaic
- Rasterize a uint16 strip index (1–20) using each strip's valid-pixel footprint (non-nodata mask from the segment output), same priority
- Accompanies segment mosaic: tells you which strip each segment came from
- **Lookup table:** `source_image_lookup.csv` (index, strip_id, sensor, acquisition_date) committed to repo alongside the script
- **Output:** `gs://akveg-data/vhr/nome_beaver/segments/mosaic/source_image_id_SNIC_size_<N>.tif`

### 4c. MS SRLite mosaic
- Source: per-strip MS SRLite clips from Step 3
- Composite using the **same priority and gap-fill logic** as 4a so spatial correspondence is exact
- uint16, 4-band (blue, green, red, nir), 2m, EPSG:3338, COG with DEFLATE compression
- **Output:** `gs://akveg-data/vhr/nome_beaver/segments/mosaic/MS_SRLite_02p00m_mosaic.tif`

One MS SRLite mosaic is sufficient (it does not vary by SNIC size).

---

## Script summary

| Script | Status | Action |
|--------|--------|--------|
| `260_register_nome_beaver_cog_collection.py` | New | Register 20 MS SRLite COGs as GEE ImageCollection |
| `261_segmentation.py` | Modify | Add `--aoi`, `--snic-sizes`; load from collection; export direct to GCS |
| `262_build_nome_mosaics.py` | New | GCP Batch: build 5 output mosaics (2× segment ID + 2× source image ID + 1× MS SRLite) |
| `261b_segment_asset_to_gs.py` | Not needed | Superseded by direct `toCloudStorage()` export in Step 2 |

All scripts live in `02b_data_reflectance_vhr_gcp/`.  
Python environment for GEE scripts: `~/miniconda3/bin/conda run -n ee python3 <script>`  
GCP Batch scripts use the `vhr-cpu` container (`gcr.io/akveg-map/vhr-cpu:latest`).

---

## GCS output layout

```
gs://akveg-data/vhr/nome_beaver/segments/
    per_strip/
        <STRIP_ID>_SNIC_kernel_1_size_10.tif    (int64, 40 files total)
        <STRIP_ID>_SNIC_kernel_1_size_15.tif
    ms_srlite_clips/
        MS_SRLite_02p00m_<STRIP_ID>_clip.tif    (uint16, 4-band, 20 files)
    mosaic/
        segment_id_SNIC_size_10.tif             (int64)
        segment_id_SNIC_size_15.tif             (int64)
        source_image_id_SNIC_size_10.tif        (uint16)
        source_image_id_SNIC_size_15.tif        (uint16)
        MS_SRLite_02p00m_mosaic.tif             (uint16, 4-band)
        source_image_lookup.csv
```
