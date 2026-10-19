# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize most recent fire year
# Author: Timm Nawrocki
# Last Updated: 2026-10-18
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize most recent fire year" summarizes the per segment zonal majority for most recent fire year.
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
output_name = 'recently_burned_2m_3338.tif'
final_gcs_output = f'{gcs_base}/veg_types/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
mtbs_folder = os.path.join(drive, root_folder, 'Data/fire/MTBS')
output_folder = os.path.join(project_folder, 'data_output/veg_types')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')
mtbs_inputs = [os.path.join(mtbs_folder, f'mtbs_AK_{year}.tif') for year in range(2019, 2025)]
fire_input = os.path.join(output_folder, 'fire_year_2m_3338.tif')

# Define intermediate files
mtbs_intermediate = os.path.join(output_folder, 'mtbs_intermediate.tif')
burned_intermediate = os.path.join(output_folder, 'burned_inter_2m_3338.tif')

# Define output files
burned_output = os.path.join(output_folder, output_name)

#### AGGREGATE MTBS DATA
####____________________________________________________

# Open MTBS rasters
print('Aggregating MTBS data...')
start_time = time.time()
mtbs_rasters = [rasterio.open(f) for f in mtbs_inputs]

# Process intermediate raster
with rasterio.open(area_input) as area_raster:
    # Define output profile
    output_profile = area_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'dtype': 'int8',
        'nodata': nodata_value,
        'compress': 'lzw',
        'predictor': 1,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Find number of raster blocks
    window_list = [window for block_index, window in area_raster.block_windows(1)]

    # Establish raster counts
    count = 1
    progress = 0

    # Process intermediate binary burn raster
    with rasterio.open(mtbs_intermediate, 'w', **output_profile) as dst:
        for block_index, window in area_raster.block_windows(1):
            # Read area raster
            area_data = area_raster.read(1, window=window)

            # Retrieve window spatial bounds and target array dimensions
            left, bottom, right, top = area_raster.window_bounds(window)
            dst_height, dst_width = window.height, window.width

            # Accumulate MTBS burn severity across years (3 or 4 = burned)
            burn_mask = np.zeros((dst_height, dst_width), dtype=bool)
            for mtbs_src in mtbs_rasters:
                fire_window = mtbs_src.window(left, bottom, right, top)
                mtbs_data = mtbs_src.read(
                    1,
                    window=fire_window,
                    out_shape=(dst_height, dst_width),
                    resampling=Resampling.nearest,
                    boundless=True,
                    fill_value=0
                )
                burn_mask |= (mtbs_data == 3) | (mtbs_data == 4)

            # Mask to study area domain
            mtbs_binary = np.where(area_data == 1, burn_mask.astype(np.int8), nodata_value)

            # Write single band data to raster
            dst.write(mtbs_binary.astype(np.int8), 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

# Close rasters
for raster in mtbs_rasters:
    raster.close()
end_timing(start_time)

#### CALCULATE BLOCK ZONAL STATISTICS
####____________________________________________________

# Identify maximum segment ID
print('Identifying segment raster for maximum ID...')
start_time = time.time()
max_seg_id = 0
with rasterio.open(segment_input) as segment_raster:
    # Identify segment no data value
    segment_nodata = segment_raster.nodata

    # Calculate maximum segment ID across blocks
    for block_index, window in segment_raster.block_windows(1):
        # Read segment data
        segment_data = segment_raster.read(1, window=window)

        # Identify valid data
        valid_seg_mask = segment_data > 0
        if segment_nodata is not None and segment_nodata != 0:
            valid_seg_mask &= (segment_data != segment_nodata)

        # Process valid data for maximum segment ID
        valid_segs = segment_data[valid_seg_mask]
        if valid_segs.size > 0:
            block_max = int(np.max(valid_segs))
            if block_max > max_seg_id:
                max_seg_id = block_max
end_timing(start_time)

# Define binary categories for zonal mode (0 = unburned, 1 = recently burned)
unique_categories = np.array([0, 1], dtype=np.int16)
num_categories = len(unique_categories)

# Initialize 2D accumulation matrix (row = segment ID, col = category index)
counts_matrix = np.zeros((max_seg_id + 1, num_categories), dtype=np.uint32)

# Calculate zonal category counts across blocks
print('Calculating zonal category counts across blocks...')
start_time = time.time()
with rasterio.open(segment_input) as segment_raster, rasterio.open(mtbs_intermediate) as mtbs_raster:
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

        # Read processed mtbs data
        mtbs_window = mtbs_raster.window(left, bottom, right, top)
        mtbs_data = mtbs_raster.read(
            1,
            window=mtbs_window,
            out_shape=(dst_height, dst_width),
            resampling=Resampling.nearest,
            boundless=True,
            fill_value=nodata_value
        )

        # Define valid data mask
        valid_mask = (segment_data > 0) & (mtbs_data != nodata_value)
        if segment_nodata is not None and segment_nodata != 0:
            valid_mask &= (segment_data != segment_nodata)

        # Restrict block data to valid data mask
        seg_valid = segment_data[valid_mask]
        data_valid = mtbs_data[valid_mask]

        # Accumulate counts for segments present in this block
        if len(seg_valid) > 0:
            # Map recently burned categories to category array indices
            cat_indices = np.searchsorted(unique_categories, data_valid)
            # Accumulate counts into 2D frequency matrix
            np.add.at(counts_matrix, (seg_valid, cat_indices), 1)

        # Report progress
        count, progress = raster_block_progress(100, len(window_list), count, progress)
end_timing(start_time)

# Calculate zonal mode per segment
print('Calculating zonal mode per segment...')
start_time = time.time()
total_counts = counts_matrix.sum(axis=1)
mode_indices = np.argmax(counts_matrix, axis=1)

# Assign mode category where segment has valid data
mode_array = np.where(total_counts > 0, unique_categories[mode_indices], nodata_value).astype(np.int8)
end_timing(start_time)

# Clear matrix from memory
del counts_matrix

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal mode from all blocks to output raster
with (rasterio.open(segment_input) as segment_raster,
      rasterio.open(fire_input) as fire_raster):
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'dtype': 'int8',
        'nodata': nodata_value,
        'compress': 'lzw',
        'predictor': 1,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Process intermediate raster
    with rasterio.open(burned_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = [window for block_index, window in segment_raster.block_windows(1)]

        # Establish raster counts
        count = 1
        progress = 0

        # Define band description
        dst.descriptions = ('recent_burn',)

        # Load segment data block by block
        for block_index, window in segment_raster.block_windows(1):
            # Read segment data
            segment_data = segment_raster.read(1, window=window)

            # Retrieve window spatial bounds and target array dimensions
            left, bottom, right, top = segment_raster.window_bounds(window)
            dst_height, dst_width = window.height, window.width

            # Read raster blocks
            fire_window = fire_raster.window(left, bottom, right, top)
            fire_data = fire_raster.read(
                1,
                window=fire_window,
                out_shape=(dst_height, dst_width),
                resampling=Resampling.nearest,
                boundless=True,
                fill_value=-32768
            )

            # Prepare valid data mask
            valid_mask = (segment_data > 0)
            if segment_nodata is not None and segment_nodata != 0:
                valid_mask &= (segment_data != segment_nodata)

            # Map invalid segment IDs to 0 safely for 1D array index lookup
            safe_segment_data = np.where(valid_mask, segment_data, 0)
            out_data = mode_array[safe_segment_data]

            # Mask out invalid cells
            out_data = np.where(valid_mask, out_data, nodata_value)

            # Integrate data from fire history raster
            out_data = np.where(fire_data >= 2019, 1, out_data)

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
        'PREDICTOR=NO',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=NEAREST',
        'OVERVIEW_RESAMPLING=NEAREST'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Creating cloud-optimized geotiff...')
start_time = time.time()
cog_ds = gdal.Translate(burned_output, burned_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate datasets
for inter_file in [mtbs_intermediate, burned_intermediate]:
    if os.path.exists(inter_file):
        os.remove(inter_file)

# Upload dataset to Google Cloud
print('Uploading final zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(burned_output, final_gcs_output, storage_client)
end_timing(start_time)
