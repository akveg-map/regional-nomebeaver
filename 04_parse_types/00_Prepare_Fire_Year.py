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
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'fire_year_2m_3338.tif'
final_gcs_output = f'{gcs_base}/veg_types/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
surficial_geopackage = os.path.join(project_folder,
                                    'data_input/surficial_data/surficial_correction_manual_3338.gpkg')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
ancillary_folder = os.path.join(
    drive, root_folder,
    'Projects/VegetationEcology/AKVEG_Map/Data/Data_Input/ancillary_data/processed')
output_folder = os.path.join(project_folder, 'data_output/veg_types')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')
fire_input = os.path.join(ancillary_folder, 'AlaskaYukon_FireYear_10m_3338.tif')
correction_layer = 'surficial_correction_fire_poly_3338'

# Define intermediate files
correction_intermediate = os.path.join(output_folder, 'fire_correction_2m_3338.tif')
history_intermediate = os.path.join(output_folder, 'fire_corrected_2m_3338.tif')
fire_intermediate = os.path.join(output_folder, 'fire_inter_2m_3338.tif')

# Define output files
fire_output = os.path.join(output_folder, output_name)

#### PREPARE FIRE HISTORY RASTER
####____________________________________________________

# Read area bounds
area_bounds = raster_bounds(area_input)

# Convert correction layer to raster
if not os.path.exists(history_intermediate):
    print(f'Converting fire year corrections to raster...')
    start_time = time.time()

    # Set output raster options
    convert_options = gdal.RasterizeOptions(
        format='GTiff',
        outputType=gdal.GDT_Int16,
        creationOptions=[
            'COMPRESS=LZW',
            'TILED=YES',
            'BIGTIFF=YES',
            'NUM_THREADS=ALL_CPUS'
        ],
        outputBounds=area_bounds,
        outputSRS='EPSG:3338',
        xRes=2,
        yRes=2,
        initValues=[nodata_value],
        attribute='FIREYEAR',
        noData= nodata_value,
        allTouched=False,
        layers=[correction_layer]
    )

    # Convert the selector polygons to raster
    inter_data = gdal.Rasterize(correction_intermediate, surficial_geopackage, options=convert_options)
    inter_data = None
    end_timing(start_time)

# Process corrected fire year raster
print('Correcting fire history raster...')
start_time = time.time()
with rasterio.open(area_input) as area_raster:
    # Define output profile
    output_profile = area_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'dtype': 'int16',
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

    # Open raster data
    fire_raster = rasterio.open(fire_input)
    correction_raster = rasterio.open(correction_intermediate)

    # Process intermediate binary burn raster
    with rasterio.open(history_intermediate, 'w', **output_profile) as dst:
        for block_index, window in area_raster.block_windows(1):
            # Read area raster
            area_data = area_raster.read(1, window=window)

            # Retrieve window spatial bounds and target array dimensions
            left, bottom, right, top = area_raster.window_bounds(window)
            dst_height, dst_width = window.height, window.width

            # Read raster blocks
            fire_window = fire_raster.window(left, bottom, right, top)
            fire_data = fire_raster.read(
                1,
                window=fire_window,
                out_shape=(dst_height, dst_width),
                resampling=Resampling.nearest,
                boundless=True,
                fill_value=nodata_value
            )
            correction_window = correction_raster.window(left, bottom, right, top)
            correction_data = correction_raster.read(
                1,
                window=correction_window,
                out_shape=(dst_height, dst_width),
                resampling=Resampling.nearest,
                boundless=True,
                fill_value=nodata_value
            )

            # Correct fire history years
            export_data = np.where(correction_data >= 0, correction_data, fire_data)

            # Mask to study area domain
            export_data = np.where(area_data == 1, export_data, nodata_value)

            # Write single band data to raster
            dst.write(export_data.astype(np.int16), 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    # Close rasters
    for raster in [fire_raster, correction_raster]:
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

# Pre-scan fire raster for unique fire year values within segment data extent
print('Scanning fire raster for unique category values...')
start_time = time.time()
with (rasterio.open(segment_input) as segment_raster,
      rasterio.open(history_intermediate) as fire_raster):
    # Identify fire year raster nodata value
    fire_nodata = fire_raster.nodata if fire_raster.nodata is not None else nodata_value

    # Initialize unique years
    unique_years_set = set()

    # Process fire years by segment raster blocks
    for block_index, window in segment_raster.block_windows(1):
        # Obtain spatial bounds of the current segment block
        left, bottom, right, top = segment_raster.window_bounds(window)
        fire_window = fire_raster.window(left, bottom, right, top)

        # Read fire raster at native resolution within segment block bounds
        fire_data = fire_raster.read(1, window=fire_window)

        # Filter out nodata values and update unique set
        valid_year = fire_data[(fire_data != fire_nodata) & (fire_data != nodata_value)]
        if valid_year.size > 0:
            unique_years_set.update(np.unique(valid_year))

    # Convert years set to numpy array
    unique_years = np.array(sorted(list(unique_years_set)), dtype=np.int16)
end_timing(start_time)

# Identify the number of fire years represented in raster
num_categories = len(unique_years)
print(f'Identified {num_categories} unique fire year values.')
if num_categories == 0:
    raise ValueError('No valid fire year data found in fire_input raster.')

# Initialize 2D accumulation matrix (row = segment ID, col = fire year category index)
counts_matrix = np.zeros((max_seg_id + 1, num_categories), dtype=np.uint32)

# Calculate zonal category counts across blocks
print('Calculating zonal category counts across blocks...')
start_time = time.time()
with (rasterio.open(segment_input) as segment_raster,
      rasterio.open(history_intermediate) as fire_raster):
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

        # Read fire year data using nearest resampling to preserve discrete year values
        fire_window = fire_raster.window(left, bottom, right, top)
        fire_data = fire_raster.read(
            1,
            window=fire_window,
            out_shape=(dst_height, dst_width),
            resampling=Resampling.nearest,
            boundless=True,
            fill_value=fire_nodata
        ).astype(np.int16)

        # Define valid data mask
        valid_mask = (segment_data > 0) & (fire_data != nodata_value) & (fire_data != fire_nodata)
        if segment_nodata is not None and segment_nodata != 0:
            valid_mask &= (segment_data != segment_nodata)

        # Restrict block data to valid data mask
        seg_valid = segment_data[valid_mask]
        data_valid = fire_data[valid_mask]

        # Accumulate counts for segments present in this block
        if len(seg_valid) > 0:
            # Map fire years to category array indices
            cat_indices = np.searchsorted(unique_years, data_valid)
            # Accumulate counts into 2D frequency matrix
            np.add.at(counts_matrix, (seg_valid, cat_indices), 1)

        # Report progress
        count, progress = raster_block_progress(100, len(window_list), count, progress)
end_timing(start_time)

# Calculate zonal modes
print('Calculating zonal mode per segment...')
start_time = time.time()
total_counts = counts_matrix.sum(axis=1)
mode_indices = np.argmax(counts_matrix, axis=1)

# Assign mode fire year where segment has valid data
mode_array = np.where(total_counts > 0, unique_years[mode_indices], nodata_value).astype(np.int16)
end_timing(start_time)

# Clear matrix from memory
del counts_matrix

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal mode from all blocks to output raster
with rasterio.open(segment_input) as segment_raster:
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'dtype': 'int16',
        'nodata': nodata_value,
        'compress': 'lzw',
        'predictor': 1,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Process intermediate raster
    with rasterio.open(fire_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = [window for block_index, window in segment_raster.block_windows(1)]

        # Establish raster counts
        count = 1
        progress = 0

        # Define band description
        dst.descriptions = ('fire_year',)

        # Load segment data block by block
        for block_index, window in segment_raster.block_windows(1):
            # Read segment data
            segment_data = segment_raster.read(1, window=window)

            # Prepare valid data mask
            valid_mask = (segment_data > 0)
            if segment_nodata is not None and segment_nodata != 0:
                valid_mask &= (segment_data != segment_nodata)

            # Map invalid segment IDs to 0 safely for 1D array index lookup
            safe_segment_data = np.where(valid_mask, segment_data, 0)
            out_data = mode_array[safe_segment_data]

            # Mask out invalid cells
            out_data = np.where(valid_mask, out_data, nodata_value)

            # Write single band data to raster
            dst.write(out_data.astype(np.int16), 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    end_timing(start_time)

#### PROCESS CLOUD-OPTIMIZED GEOTIFFS
####____________________________________________________

# Set translation options for GDAL COG driver with NEAREST resampling for discrete year data
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
cog_ds = gdal.Translate(fire_output, fire_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate datasets
for inter_file in [correction_intermediate, history_intermediate, fire_intermediate]:
    if os.path.exists(inter_file):
        os.remove(inter_file)

# Upload dataset to Google Cloud
print('Uploading final zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(fire_output, final_gcs_output, storage_client)
end_timing(start_time)
