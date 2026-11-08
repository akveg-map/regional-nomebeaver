# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize surface water to segments
# Author: Timm Nawrocki
# Last Updated: 2026-10-21
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize surface water to segments" calculates peak growing season surface water percentage (dataset from AKVEG Map) as segment zonal means.
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
nodata_value = -128

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'surface_water_2m_3338.tif'
final_gcs_output = f'{gcs_base}/covariate_data/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
akveg_folder = os.path.join(drive, root_folder,
                            'Projects/VegetationEcology/AKVEG_Map/Data/Data_Output/rasters_final',
                            'version_20260415')
surficial_folder = os.path.join(project_folder, 'data_output/surficial_data')
output_folder = os.path.join(project_folder, 'data_input/water_data')

# Define input files
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')
water_input = os.path.join(akveg_folder, 'water_cvr_10m_3338.tif')
surficial_input = os.path.join(surficial_folder, 'surficial_pre_2m_3338.tif')

# Define intermediate files
water_intermediate = os.path.join(output_folder, 'water_inter_2m_3338.tif')

# Define output files
water_output = os.path.join(output_folder, output_name)

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

# Initialize 1D accumulation arrays
sum_array = np.zeros(max_seg_id + 1, dtype=np.float64)
count_array = np.zeros(max_seg_id + 1, dtype=np.int32)

# Calculate zonal sums and counts
print('Calculating zonal sums and counts across blocks...')
start_time = time.time()
with (rasterio.open(segment_input) as segment_raster,
      rasterio.open(water_input) as water_raster):
    # Find number of raster blocks
    window_list = [window for block_index, window in segment_raster.block_windows(1)]

    # Establish raster count
    count = 1
    progress = 0

    # Calculate zonal statistics for each block in the segment raster
    for block_index, window in segment_raster.block_windows(1):
        # Read segment block
        segment_data = segment_raster.read(1, window=window)

        # Retrieve window spatial bounds and target array dimensions
        left, bottom, right, top = segment_raster.window_bounds(window)
        dst_height, dst_width = window.height, window.width

        # Read water data directly for the window extent
        water_window = water_raster.window(left, bottom, right, top)
        water_data = water_raster.read(
            1,
            window=water_window,
            out_shape=(dst_height, dst_width),
            resampling=Resampling.bilinear
        ).astype(np.int16)

        # Identify valid data
        valid_mask = (segment_data > 0) & (water_data != nodata_value)
        if segment_nodata != 0:
            valid_mask &= (segment_data != segment_nodata)

        # Restrict block data to valid data mask
        seg_valid = segment_data[valid_mask]
        data_valid = water_data[valid_mask]

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
means = np.nan_to_num(means, nan=nodata_value, posinf=nodata_value, neginf=nodata_value)
mean_array = np.round(means).astype(np.int16)
end_timing(start_time)

# Clear aggregation arrays from memory
del sum_array, count_array

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal means from all blocks to output raster
with (rasterio.open(segment_input) as segment_raster,
      rasterio.open(surficial_input) as surficial_raster):
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': 1,
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
    with rasterio.open(water_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = [window for block_index, window in segment_raster.block_windows(1)]

        # Establish raster count
        count = 1
        progress = 0

        # Define band description
        dst.descriptions = ('surface_water',)

        # Load segment data block by block
        for block_index, window in segment_raster.block_windows(1):
            # Read segment data
            segment_data = segment_raster.read(1, window=window)

            # Retrieve window spatial bounds
            left, bottom, right, top = segment_raster.window_bounds(window)
            window_processing = (left, bottom, right, top)

            # Read input data
            surficial_data = read_raster_block(surficial_raster, window_processing)

            # Identify valid data
            valid_mask = (segment_data > 0)
            if segment_nodata != 0:
                valid_mask &= (segment_data != segment_nodata)

            # Map invalid segment IDs to 0 safely for 1D array index lookup
            safe_segment_data = np.where(valid_mask, segment_data, 0)
            out_data = mean_array[safe_segment_data]

            # Assign 100% where surficial indicates water
            out_data = np.where(surficial_data == 5, 100, out_data)

            # Mask out invalid cells
            out_data = np.where(valid_mask, out_data, nodata_value)

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
cog_ds = gdal.Translate(water_output, water_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate dataset
if os.path.exists(water_intermediate):
    os.remove(water_intermediate)

# Upload dataset to Google Cloud
print('Uploading final zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(water_output, final_gcs_output, storage_client)
end_timing(start_time)
