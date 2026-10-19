# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Calculate peat probability
# Author: Timm Nawrocki
# Last Updated: 2026-10-18
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Calculate peat probability" calculates the peat probability (dataset from Alaska Soils Data Bank) as segment zonal means.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import numpy as np
from osgeo import gdal
import rasterio
from rasterio.enums import Resampling
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()
gdal.SetCacheMax(1073741824) # Cap GDAL memory cache at 1 GB

# Define nodata value
src_nodata = 255
dst_nodata = -128

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'peat_probability_2m_3338.tif'
final_gcs_output = f'{gcs_base}/veg_types/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
soil_folder = os.path.join(drive, root_folder,
                           'Projects/VegetationEcology/AKSDB/Data/Data_Output/rasters_final/version_20260415')
output_folder = os.path.join(project_folder, 'data_output/veg_types')

# Define input files
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')
peat_input = os.path.join(soil_folder, 'Peat_Probability_Alaska_rf11.tif')

# Define intermediate files
peat_intermediate = os.path.join(output_folder, 'peat_inter_2m_3338.tif')

# Define output files
peat_output = os.path.join(output_folder, output_name)

#### CALCULATE BLOCK ZONAL STATISTICS
####____________________________________________________

# Identify maximum segment ID
print('Identifying segment raster for maximum ID...')
start_time = time.time()
max_seg_id = 0
with rasterio.open(segment_input) as segment_raster:
    for block_index, window in segment_raster.block_windows(1):
        segment_data = segment_raster.read(1, window=window)
        block_max = int(np.max(segment_data))
        if block_max > max_seg_id:
            max_seg_id = block_max
end_timing(start_time)

# Initialize 1D accumulation arrays
sum_array = np.zeros(max_seg_id + 1, dtype=np.float64)
count_array = np.zeros(max_seg_id + 1, dtype=np.int32)

# Calculate zonal sums and counts
print('Calculating zonal sums and counts across blocks...')
start_time = time.time()
with rasterio.open(segment_input) as segment_raster, rasterio.open(peat_input) as peat_raster:
    # Find number of raster blocks
    window_list = [window for block_index, window in segment_raster.block_windows(1)]

    # Establish raster count
    count = 1
    progress = 0

    # Identify nodata value
    segment_nodata = segment_raster.nodata if segment_raster.nodata is not None else 0

    # Calculate zonal statistics for each block in the segment raster
    for block_index, window in segment_raster.block_windows(1):
        # Read segment block
        segment_data = segment_raster.read(1, window=window)

        # Retrieve window spatial bounds and target array dimensions
        left, bottom, right, top = segment_raster.window_bounds(window)
        dst_height, dst_width = window.height, window.width

        # Read peat probability data directly for the window extent
        peat_window = peat_raster.window(left, bottom, right, top)
        peat_data = peat_raster.read(
            1,
            window=peat_window,
            out_shape=(dst_height, dst_width),
            resampling=Resampling.bilinear
        ).astype(np.int16)

        # Define valid data mask
        valid_mask = (segment_data > 0) & (peat_data != src_nodata)
        if segment_nodata is not None and segment_nodata != 0:
            valid_mask &= (segment_data != segment_nodata)

        # Restrict block data to valid data mask
        seg_valid = segment_data[valid_mask]
        data_valid = peat_data[valid_mask]

        # Accumulate sums and counts for segments present in this block
        if len(seg_valid) > 0:
            sum_array += np.bincount(seg_valid, weights=data_valid, minlength=max_seg_id + 1)
            count_array += np.bincount(seg_valid, minlength=max_seg_id + 1)

        # Report progress
        count, progress = raster_block_progress(100, len(window_list), count, progress)

end_timing(start_time)

# Calculate zonal means
print('Calculating zonal means...')
start_time = time.time()
with np.errstate(divide='ignore', invalid='ignore'):
    means = sum_array / count_array
means = np.nan_to_num(means, nan=dst_nodata)
mean_array = np.round(means).astype(np.int16)
end_timing(start_time)

# Clear aggregation arrays from memory
del sum_array, count_array

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal means from all blocks to output raster
with rasterio.open(segment_input) as segment_raster:
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'dtype': 'int8',
        'nodata': dst_nodata,
        'compress': 'lzw',
        'predictor': 2,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Process output raster
    with rasterio.open(peat_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = [window for block_index, window in segment_raster.block_windows(1)]

        # Establish raster count
        count = 1
        progress = 0

        # Define band description
        dst.descriptions = ('peat_probability',)

        # Load segment data block by block
        for block_index, window in segment_raster.block_windows(1):
            # Read segment data
            segment_data = segment_raster.read(1, window=window)

            # Map invalid segment IDs to 0 safely for 1D array index lookup
            safe_segment_data = np.where(segment_data > 0, segment_data, 0)
            out_data = mean_array[safe_segment_data]

            # Define valid mask
            valid_mask = (segment_data > 0)
            if segment_nodata is not None and segment_nodata != 0:
                valid_mask &= (segment_data != segment_nodata)

            # Mask out invalid cells
            out_data = np.where(valid_mask, out_data, dst_nodata)

            # Write single band data to raster
            dst.write(out_data.astype(np.int8), 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    end_timing(start_time)

#### PROCESS CLOUD-OPTIMIZED GEOTIFFS
####____________________________________________________

# Set translation options for GDAL COG driver
cog_options = gdal.TranslateOptions(
    format='COG',
    creationOptions=[
        'COMPRESS=DEFLATE',
        'PREDICTOR=YES',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=AVERAGE',
        'OVERVIEW_RESAMPLING=AVERAGE'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Creating cloud-optimized geotiff...')
start_time = time.time()
cog_ds = gdal.Translate(peat_output, peat_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate dataset
if os.path.exists(peat_intermediate):
    os.remove(peat_intermediate)

# Upload dataset to Google Cloud
print('Uploading final zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(peat_output, final_gcs_output, storage_client)
end_timing(start_time)
