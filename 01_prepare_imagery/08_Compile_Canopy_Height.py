# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Compile canopy height
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Compile canopy height' compiles the modeled canopy height from tiles exported through Google Earth Engine.
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

# Define no data
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'canopyheight_initial_2m_3338.tif'
final_gcs_output = f'{gcs_base}/canopy_height/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data')
canopy_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/canopy_height')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
canopy_tiles = glob.glob(f'{canopy_folder}/export/*.tif')

# Define intermediate files
merged_vrt = os.path.join(canopy_folder, 'canopy_merged.vrt')
merged_intermediate = os.path.join(canopy_folder, 'canopy_merged.tif')

# Define output files
canopy_output = os.path.join(canopy_folder, output_name)

#### PROCESS MERGED RASTER
####____________________________________________________

# Create merged raster if it does not already exist
if not os.path.exists(merged_intermediate):

    # Read area bounds
    area_bounds = raster_bounds(area_input)

    # Merge canopy tiles
    print(f'Merging {len(canopy_tiles)} tiles...')
    start_time = time.time()
    # Merge raster tiles
    vrt_data = gdal.BuildVRT(merged_vrt,
                             canopy_tiles,
                             outputSRS='EPSG:3338',
                             xRes=2,
                             yRes=2,
                             VRTNodata=nodata_value,
                             outputBounds=area_bounds)
    vrt_data = None
    end_timing(start_time)

    # Merge canopy height datasets
    print(f'Merging canopy height datasets...')
    start_time = time.time()
    area_raster = rasterio.open(area_input)
    output_profile = area_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'nodata': nodata_value,
        'dtype': 'int16',
        'compress': 'lzw',
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Prepare raster data
    canopy_raster = rasterio.open(merged_vrt)
    src_nodata = canopy_raster.nodata

    # Combine and re-scale canopy height rasters
    with rasterio.open(merged_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = []
        for block_index, window in area_raster.block_windows(1):
            window_list.append(window)
        # Iterate processing through raster blocks
        count = 1
        progress = 0
        for block_index, window in area_raster.block_windows(1):
            # Read raster blocks
            area_block = area_raster.read(1, window=window, masked=False)
            canopy_block = canopy_raster.read(1, window=window, masked=False)

            # Re-scale canopy height to cm
            canopy_scaled = np.round((canopy_block/10), 0)

            # Correct nodata values
            invalid_mask = (canopy_block == 0.0) | (np.isnan(canopy_block))
            if src_nodata is not None:
                invalid_mask = invalid_mask | (canopy_block == src_nodata)
            out_block = np.where(invalid_mask, nodata_value, canopy_scaled).astype(np.int16)

            # Enforce study area boundary
            out_block = np.where(area_block == 1, out_block, nodata_value)

            # Write output
            dst.write(out_block, 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)
    end_timing(start_time)

    # Close rasters
    for raster in [area_raster, canopy_raster]:
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
cog_data = gdal.Translate(canopy_output, merged_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Upload post-processed raster to GCS
start_time = time.time()
print('Uploading cloud-optimized geotiff to Google Cloud...')
upload_to_gcs(canopy_output, final_gcs_output, storage_client)
end_timing(start_time)
