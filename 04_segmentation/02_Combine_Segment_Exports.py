# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Combine segment exports
# Author: Timm Nawrocki
# Last Updated: 2026-08-29
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Combine segment exports' merges the exported tiles for the segments and converts them to cloud-optimized geotiff.
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
nodata_value = -2147483648

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://akveg-data/regional_nomebeaver'

# Define final GCS path for the output
output_name = 'segments_2m_3338.tif'
final_gcs_output = f'{gcs_base}/segments/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data')
segment_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/segments')

# Define input files
area_input = os.path.join(region_folder, 'NomeBeaver_MapDomain_2m_3338.tif')
segment_tiles = glob.glob(f'{segment_folder}/export/*.tif')

# Define intermediate files
merged_vrt = os.path.join(segment_folder, 'custom_merged.vrt')
merged_intermediate = os.path.join(segment_folder, 'segment_merged.tif')

# Define output files
segment_output = os.path.join(segment_folder, output_name)

#### PROCESS MERGED RASTER
####____________________________________________________

# Create merged raster if it does not already exist
if not os.path.exists(merged_intermediate):

    # Read area bounds
    area_bounds = raster_bounds(area_input)

    # Merge segment tiles
    print(f'Merging {len(segment_tiles)} tiles...')
    start_time = time.time()
    # Merge raster tiles
    vrt_data = gdal.BuildVRT(merged_vrt,
                             segment_tiles,
                             outputSRS='EPSG:3338',
                             xRes=2,
                             yRes=2,
                             VRTNodata=nodata_value,
                             outputBounds=area_bounds)
    vrt_data = None
    end_timing(start_time)

    # Prepare output profile
    area_raster = rasterio.open(area_input)
    output_profile = area_raster.profile.copy()
    output_profile.update({
        'count': 1,
        'nodata': nodata_value,
        'dtype': 'int32',
        'compress': 'lzw',
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Prepare raster data
    segment_raster = rasterio.open(merged_vrt)

    # Prepare global variables for sequential ID mapping
    global_id_map = {}
    next_id = 1

    # Post-process segments
    print(f'Merging image datasets...')
    start_time = time.time()
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
            segment_block = segment_raster.read(1, window=window, masked=False)

            # Enforce study area boundary
            out_block = np.where(area_block == 1, segment_block, nodata_value)

            # Isolate valid pixels for ID reassignment
            valid_mask = out_block != nodata_value
            valid_pixels = out_block[valid_mask]

            # Re-map segment numerical ids
            if valid_pixels.size > 0:
                # Find all unique IDs in this block
                unique_ids = np.unique(valid_pixels)

                # Register new ids not overlapping previous blocks
                for uid in unique_ids:
                    if uid not in global_id_map:
                        global_id_map[uid] = next_id
                        next_id += 1

                # Assign the new ids to the segments
                sorted_unique = np.sort(unique_ids)
                new_id = np.array([global_id_map[uid] for uid in sorted_unique], dtype=np.int32)
                id_index = np.searchsorted(sorted_unique, valid_pixels)

                # Apply new mapped values back into the block
                out_block[valid_mask] = new_id[id_index]

                # Write single-band output
                dst.write(out_block.astype(np.int32), 1, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)
    end_timing(start_time)

    # Close rasters
    for raster in [area_raster, segment_raster]:
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
        'RESAMPLING=NEAREST',
        'OVERVIEW_RESAMPLING=NEAREST'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Converting to cloud-optimized geotiff...')
start_time = time.time()
cog_data = gdal.Translate(segment_output, merged_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Upload post-processed raster to GCS
start_time = time.time()
print('Uploading cloud-optimized geotiff to Google Cloud...')
upload_to_gcs(segment_output, final_gcs_output, storage_client)
end_timing(start_time)
