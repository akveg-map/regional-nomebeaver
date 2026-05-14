# Nome-Beaver Creek — SNIC Segmentation

SNIC-based image segmentation for the Nome-Beaver Creek VHR product delivery.

## Script

**`261_segmentation.py`** — Runs SNIC segmentation on a single VHR strip and exports the result as a GEE asset.

```bash
~/miniconda3/bin/conda run -n ee python3 261_segmentation.py \
  --image projects/akveg-map/assets/reflectance_vhr/ortho_toa_images/<STRIP_ID> \
  --asset-id projects/akveg-map/assets/segments/nomebeaver/<STRIP_ID>
```

**Parameters (edit top of script):**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `KERNEL_SIZES` | `[1]` | Gaussian pre-smoothing kernel radius (pixels) |
| `SNIC_SIZES` | `[10, 15]` | SNIC superpixel target size (pixels at 2 m) |
| `THRESHOLD_SPECTRAL` | `0.005` | Spectral merge threshold |
| `THRESHOLD_SIZE` | `5` | Minimum segment size (pixels) |

## Inputs

- `MS_SRLite_02p00m_<STRIP_ID>.tif` — 2 m multispectral surface reflectance COGs at
  `gs://akveg-data/vhr/nome_beaver/processed/<STRIP_ID>/225_srlite/`
- Bands expected: `blue`, `green`, `red`, `nir`

## Outputs

GEE image assets at `projects/akveg-map/assets/segments/nomebeaver/`:
- One asset per kernel × size combination, named `<STRIP_ID>_SNIC_kernel_01_size_10`, etc.

## Implementation plan

See `nome_beaver_segmentation_plan.md` for the full plan including AOI setup, mosaic priority rules, and gap-fill decisions.

## Upstream pipeline

Reflectance processing (Steps 200–230) is in
[akveg-map/akveg-vhr: 02b_data_reflectance_vhr_gcp](https://github.com/akveg-map/akveg-vhr/tree/main/02b_data_reflectance_vhr_gcp).
All 20 nome-beaver strips are complete.
