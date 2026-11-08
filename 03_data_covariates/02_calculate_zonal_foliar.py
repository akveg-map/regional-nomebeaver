# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Calculate zonal foliar cover
# Author: Timm Nawrocki
# Last Updated: 2026-10-19
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Calculate zonal foliar cover" reads cloud-optimized geotiffs from Google Cloud Storage to calculate per segment zonal mean statistics for foliar cover data and derivatives for use in programmatic key.
# ---------------------------------------------------------------------------

# Set environment
import os
os.environ['GDAL_GCS_BINARY_READ'] = 'YES'

# Import packages
import time
import numpy as np
from osgeo import gdal
import rasterio
from rasterio.enums import Resampling
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()
gdal.SetCacheMax(1073741824)  # Cap GDAL memory cache at 1 GB

# Define nodata value
nodata_value = -128

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'foliar_zonal_2m_3338.tif'
final_gcs_output = f'{gcs_base}/covariate_data/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
vrt_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/vrt_data')
segment_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/segment_data')
output_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/covariate_data')

# Define input files
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')

# Define intermediate files
zonal_intermediate = os.path.join(output_folder, 'zonal_stats_inter_2m_3338.tif')

# Define output files
zonal_output = os.path.join(output_folder, output_name)

# Define covariate sets
predictor_foliar = ['alnus', 'betshr', 'bettre', 'brotre', 'dryas', 'dsalix',
                    'empnig', 'erivag', 'feather', 'forb', 'gramin',
                    'lichen', 'mwcalama', 'ndsalix', 'neetre', 'nerishr',
                    'picgla', 'picmar', 'poptre', 'populbt', 'rhoshr',
                    'sphagn', 'vaculi', 'vacvit', 'wetforb', 'wetsed']
predictor_dist = ['bromos', 'wetgram']
predictor_sum = ['eridwarf', 'erishrub', 'herbac', 'ndshrub', 'shrub', 'trees', 'wetind']
predictor_ratio = ['deciduous_ratio', 'picea_ratio', 'tussock_ratio']

# Dynamically build predictor_all list from input arguments
predictor_names = ['foliar', 'dist', 'sum', 'ratio']
predictor_map = {
    'foliar': predictor_foliar,
    'dist': predictor_dist,
    'sum': predictor_sum,
    'ratio': predictor_ratio
}
predictor_all = []
for name in predictor_names:
    if name in predictor_map:
        predictor_all.extend(predictor_map[name])
    else:
        print(f'Warning: Predictor set {name} not recognized and will be skipped.')
if not predictor_all:
    raise ValueError('No valid predictor sets were provided. Exiting.')

# Create band map
band_map = {name: i for i, name in enumerate(predictor_all, start=1)}

#### PREPARE RASTER COVARIATES
####____________________________________________________

# Set VRT configuration
vrt_options = gdal.BuildVRTOptions(resampleAlg='bilinear', resolution='highest')

# Define raster paths for foliar covariates
foliar_sources = {}
for name in predictor_foliar:
    foliar_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_final/{name}_cvr_10m_3338.tif'

# Define raster paths for distribution covariates
dist_sources = {}
for name in predictor_dist:
    dist_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_final/{name}_dst_10m_3338.tif'

# Define raster paths for sum covariates
sum_sources = {}
for name in predictor_sum:
    sum_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_summary/{name}_cvr_10m_3338.tif'

# Define raster paths for ratio covariates
ratio_sources = {}
for name in predictor_ratio:
    ratio_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_summary/{name}_10m_3338.tif'

#### CALCULATE BLOCK ZONAL STATISTICS
####____________________________________________________

# Identify maximum segment ID
print('Identifying segment raster for maximum ID...')
start_time = time.time()
max_seg_id = 0
with rasterio.open(segment_input) as segment_raster:
    # Identify segment no data value
    segment_nodata = segment_raster.nodata if segment_raster.nodata is not None else 0
    # Calculate maximum segment ID across blocks
    for block_index, window in segment_raster.block_windows(1):
        # Read segment data
        segment_data = segment_raster.read(1, window=window)
        # Identify valid data
        valid_mask = segment_data > 0
        if segment_nodata is not None and segment_nodata != 0:
            valid_mask &= (segment_data != segment_nodata)
        # Process valid data for maximum segment ID
        valid_segs = segment_data[valid_mask]
        if valid_segs.size > 0:
            block_max = int(np.max(valid_segs))
            if block_max > max_seg_id:
                max_seg_id = block_max
end_timing(start_time)

# Initialize accumulation arrays
sum_arrays = {b: np.zeros(max_seg_id + 1, dtype=np.float64) for b in predictor_all}
count_arrays = {b: np.zeros(max_seg_id + 1, dtype=np.int32) for b in predictor_all}

# Combine all single-band sources into one lookup
single_band_sources = {
    **foliar_sources,
    **dist_sources,
    **sum_sources,
    **ratio_sources
}

# Calculate zonal sums and counts
with rasterio.open(segment_input) as segment_raster:
    start_time = time.time()

    # Find number of raster blocks
    window_list = []
    for block_index, window in segment_raster.block_windows(1):
        window_list.append(window)

    # Establish raster count
    count = 1
    progress = 0

    # Open single-band VRTs once before block loop
    single_band_vrts = {}
    for name, path in single_band_sources.items():
        if name in band_map:
            src_handle = rasterio.open(path)
            vrt_handle = rasterio.vrt.WarpedVRT(
                src_handle,
                crs='EPSG:3338',
                resampling=Resampling.bilinear,
                nodata=nodata_value
            )
            single_band_vrts[name] = (src_handle, vrt_handle)

    try:
        # Calculate zonal statistics for each block in the segment raster
        print('Calculating zonal sums and counts across blocks...')
        for block_index, window in segment_raster.block_windows(1):
            # Read raster block
            segment_data = segment_raster.read(1, window=window)

            # Define the output profile based on master resolutions
            left, bottom, right, top = segment_raster.window_bounds(window)
            dst_height, dst_width = window.height, window.width

            # Dictionary to hold computed chunk data before accumulating
            cov_data = {}

            # ---------------------------------------------------------
            # Read pre-opened single-band covariates
            # ---------------------------------------------------------
            for name, (src_h, vrt_h) in single_band_vrts.items():
                cov_data[name] = vrt_h.read(1, window=vrt_h.window(left, bottom, right, top),
                                            out_shape=(dst_height, dst_width)).astype(np.int16)

            # ---------------------------------------------------------
            # Calculate zonal sums and counts for all block data
            # ---------------------------------------------------------
            for name in predictor_all:
                if name in cov_data:
                    # Select block data
                    data = cov_data[name]
                    # Identify valid data
                    valid_mask = (segment_data > 0) & (data != nodata_value)
                    if segment_nodata != 0:
                        valid_mask &= (segment_data != segment_nodata)
                    # Restrict block data to valid data mask
                    seg_valid = segment_data[valid_mask]
                    data_valid = data[valid_mask]
                    # Calculate sums and counts for blocks that contain valid data
                    if len(seg_valid) > 0:
                        sum_arrays[name] += np.bincount(seg_valid, weights=data_valid, minlength=max_seg_id + 1)
                        count_arrays[name] += np.bincount(seg_valid, minlength=max_seg_id + 1)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    finally:
        # Close all open single-band VRTs and sources
        for src_h, vrt_h in single_band_vrts.values():
            vrt_h.close()
            src_h.close()

    # End timing
    end_timing(start_time)

# Calculate block means
print('Calculating zonal means...')
start_time = time.time()
mean_arrays = {}
for name in predictor_all:
    with np.errstate(divide='ignore', invalid='ignore'):
        means = sum_arrays[name] / count_arrays[name]
    means = np.nan_to_num(means, nan=nodata_value, posinf=nodata_value, neginf=nodata_value)
    mean_arrays[name] = np.round(means).astype(np.int16)
end_timing(start_time)

# Clear aggregation arrays from memory
del sum_arrays, count_arrays

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal means from all blocks to output raster
with rasterio.open(segment_input) as segment_raster:
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': len(predictor_all),
        'dtype': 'int8',
        'nodata': nodata_value,
        'compress': 'lzw',
        'predictor': 2,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Process output raster
    with rasterio.open(zonal_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = []
        for block_index, window in segment_raster.block_windows(1):
            window_list.append(window)

        # Establish raster count
        count = 1
        progress = 0

        # Define band names
        dst.descriptions = tuple(predictor_all)

        # Load segment data
        for block_index, window in segment_raster.block_windows(1):
            # Read segment data
            segment_data = segment_raster.read(1, window=window)

            # Identify valid data
            valid_mask = (segment_data > 0)
            if segment_nodata != 0:
                valid_mask &= (segment_data != segment_nodata)

            # Map invalid segment IDs (e.g. nodata) to 0
            safe_segment_data = np.where(valid_mask, segment_data, 0)

            # Perform aggregation
            for name, b_idx in band_map.items():
                out_data = mean_arrays[name][safe_segment_data]

                # Limit output to valid data
                out_data = np.where(valid_mask, out_data, nodata_value)

                # Write data to output raster
                dst.write(out_data.astype(np.int8), b_idx, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    # End timing
    end_timing(start_time)

#### PROCESS CLOUD-OPTIMIZED GEOTIFFS
####____________________________________________________

# Set translation options for GDAL COG driver
cog_options = gdal.TranslateOptions(
    format='COG',
    creationOptions=[
        'COMPRESS=DEFLATE',
        'PREDICTOR=STANDARD',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=AVERAGE',
        'OVERVIEW_RESAMPLING=AVERAGE'
    ]
)

# Translate raster to cloud-optimized geotiff
print(f'Creating cloud-optimized geotiff...')
start_time = time.time()
cog_ds = gdal.Translate(zonal_output, zonal_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate datasets
if os.path.exists(zonal_intermediate):
    os.remove(zonal_intermediate)

# Upload dataset to Google Cloud
print('Uploading final multi-band zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(zonal_output, final_gcs_output, storage_client)
end_timing(start_time)
