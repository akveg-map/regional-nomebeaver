# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Convert image grids to cloud-optimized geotiff
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Convert image grids to cloud-optimized geotiff' compiles image grids and creates a cloud-optimized geotiff version.
# ---------------------------------------------------------------------------

# Import packages
import glob
import os
import shutil
import time
import numpy as np
from osgeo import gdal
import rasterio
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()

# Define no data
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'vivid2023_2m_3338.tif'
final_gcs_output = f'{gcs_base}/imagery/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data')
input_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/imagery/tiles')
output_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/imagery')

# Remove tile folder if it already exists
if os.path.exists(input_folder):
    shutil.rmtree(input_folder)
    os.makedirs(input_folder)

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')

# Define intermediate files
vrt_intermediate = os.path.join(output_folder, 'image_merged.vrt')
merged_intermediate = os.path.join(output_folder, 'image_merged.tif')

# Define output files
image_output = os.path.join(output_folder, output_name)

# Create merged raster if it does not already exist
if not os.path.exists(merged_intermediate):

    #### DOWNLOAD RASTER TILES
    ####____________________________________________________

    # Identify all raster tiles in target folder on Google Cloud Storage
    raster_tiles = gcs_list_files(f'{gcs_base}/imagery/tiles', storage_client, extension='.tif')

    # Download each raster tile to local folder
    tile_count = 1
    print('Downloading raster tiles...')
    start_time = time.time()
    for raster_uri in raster_tiles:
        if tile_count % 1000 == 0 or tile_count == len(raster_tiles):
            print(f'\tDownloading tile {tile_count} of {len(raster_tiles)}...')
        # Extract filename from uri
        file_name = os.path.split(raster_uri)[1]
        # Define the local download path
        raster_file = os.path.join(input_folder, file_name)
        # Download raster tile
        download_from_gcs(raster_uri, raster_file, storage_client)
        # Increase count
        tile_count += 1

    # Report outcome
    end_timing(start_time)

    #### PROCESS MERGED RASTER
    ####____________________________________________________

    # Read area bounds
    area_bounds = raster_bounds(area_input)

    # Define input files
    input_files = glob.glob(f'{input_folder}/*.tif')

    # Merge tiles
    print(f'Merging {len(input_files)} tiles...')
    start_time = time.time()
    # Merge raster tiles
    vrt_data = gdal.BuildVRT(vrt_intermediate,
                             input_files,
                             outputSRS='EPSG:3338',
                             xRes=2,
                             yRes=2,
                             VRTNodata=nodata_value,
                             outputBounds=area_bounds)
    vrt_data = None
    end_timing(start_time)

    # Prepare output data profile
    print(f'Applying study area...')
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
    image_raster = rasterio.open(vrt_intermediate)

    # Post-process floodplain raster
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

            # Read 4 bands using the identical grid window
            image_block = image_raster.read(window=window, out_dtype='int16')

            # Enforce study area boundary
            image_block = np.where(area_block == 1, image_block, nodata_value)

            # Write 4 band output
            dst.write(image_block, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)
    end_timing(start_time)

    # Close rasters
    for raster in [area_raster, image_raster]:
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
        'RESAMPLING=BILINEAR',
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
