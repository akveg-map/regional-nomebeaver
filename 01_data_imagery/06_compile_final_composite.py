# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Compile final image composite
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Compile final image composite' compiles the Vivid 2023 and custom composite images using the image selection raster to inform which data to retain.
# ---------------------------------------------------------------------------

# Import packages
import glob
import os
import time
import numpy as np
from osgeo import gdal
import rasterio
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()

# Define nodata value
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'composite_2m_3338.tif'
final_gcs_output = f'{gcs_base}/imagery/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data')
imagery_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/imagery')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
select_input = os.path.join(imagery_folder, 'vivid2023_omission_2m_3338.tif')
vivid_input = os.path.join(imagery_folder, 'vivid2023_2m_3338.tif')
custom_tiles = glob.glob(f'{imagery_folder}/export/*.tif')

# Define intermediate files
custom_vrt = os.path.join(imagery_folder, 'custom_merged.vrt')
merged_intermediate = os.path.join(imagery_folder, 'image_merged.tif')

# Define output files
image_output = os.path.join(imagery_folder, output_name)

#### PROCESS MERGED RASTER
####____________________________________________________

# Create merged raster if it does not already exist
if not os.path.exists(merged_intermediate):

    # Read area bounds
    area_bounds = raster_bounds(area_input)

    # Merge custom tiles
    print(f'Merging {len(custom_tiles)} tiles...')
    start_time = time.time()
    # Merge raster tiles
    vrt_data = gdal.BuildVRT(custom_vrt,
                             custom_tiles,
                             outputSRS='EPSG:3338',
                             xRes=2,
                             yRes=2,
                             VRTNodata=nodata_value,
                             outputBounds=area_bounds)
    vrt_data = None
    end_timing(start_time)

    # Merge image datasets
    print(f'Merging image datasets...')
    start_time = time.time()
    area_raster = rasterio.open(area_input)
    output_profile = area_raster.profile.copy()
    output_profile.update({
        'count': 4,
        'nodata': nodata_value,
        'dtype': 'int16',
        'compress': 'lzw',
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Prepare raster data
    select_raster = rasterio.open(select_input)
    vivid_raster = rasterio.open(vivid_input)
    custom_raster = rasterio.open(custom_vrt)

    # Combine image rasters
    with rasterio.open(merged_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = []
        for block_index, window in area_raster.block_windows(1):
            window_list.append(window)
        # Iterate processing through raster blocks
        count = 1
        progress = 0
        for block_index, window in area_raster.block_windows(1):
            # Read area block as 3D array (1, height, width) for smooth 4-band broadcasting
            area_block = area_raster.read(window=window)
            select_block = select_raster.read(window=window)

            # Read 4 bands using the identical grid window
            custom_block = custom_raster.read(window=window)
            vivid_block = vivid_raster.read(window=window, out_dtype='int16')

            # Re-scale custom block to match Vivid 2023 imagery
            custom_scaled = custom_block.astype('float32') * 0.15
            custom_block = np.where(custom_block == nodata_value, nodata_value, custom_scaled).astype(np.int16)

            # Select images
            image_block = np.where(select_block == 2, custom_block, vivid_block)

            # Enforce study area boundary
            image_block = np.where(area_block == 1, image_block, nodata_value)

            # Write 4 band output
            dst.write(image_block, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)
    end_timing(start_time)

    # Close rasters
    for raster in [area_raster, select_raster, vivid_raster, custom_raster]:
        raster.close()

#### EXPORT CLOUD-OPTIMIZED GEOTIFF
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
        'RESAMPLING=AVERAGE',
        'OVERVIEW_RESAMPLING=AVERAGE'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Converting to cloud-optimized geotiff...')
start_time = time.time()
cog_data = gdal.Translate(image_output, merged_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Upload post-processed raster to GCS
start_time = time.time()
print('Uploading cloud-optimized geotiff to Google Cloud...')
upload_to_gcs(image_output, final_gcs_output, storage_client)
end_timing(start_time)
