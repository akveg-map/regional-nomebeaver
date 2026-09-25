# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Extract training data
# Author: Timm Nawrocki
# Last Updated: 2026-08-30
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Extract training data' extracts labeled training data points from the AKVEG categorical map to use in a transfer learning model.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import math
import geopandas as gpd
from osgeo import gdal
from akutils import *

# Configure GDAL
gdal.UseExceptions()

# Define nodata value
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/Data')
region_folder = os.path.join(project_folder, 'Data_Input/region_data')
training_folder = os.path.join(project_folder, 'Data_Input/training_data')
veg_folder = os.path.join(project_folder, 'Data_Input/vegetation_data')

# Define input files
domain_input = os.path.join(region_folder, 'NomeBeaver_MapDomain_3338.shp')

grid_input = os.path.join(veg_folder, 'AlaskaYukon_Categorical_MapTiles_010_v2p1_3338.shp')

# Define intermediate files
domain_intermediate = os.path.join(project_folder, 'Data_Input/NomeBeaver_MapDomain_Int_2m_3338.tif')

# Define output files
domain_output = os.path.join(project_folder, 'Data_Input/NomeBeaver_MapDomain_2m_3338.tif')

# Define resolution in meters
resolution_m = 2.0

#### DOWNLOAD RAW AKVEG MAP TILES
####____________________________________________________

# Read vector data
domain_data = gpd.read_file(domain_input)
grid_data = gpd.read_file(grid_input)

# Clip the grid data to the domain data
grid_data = grid_data.clip(domain_data)

# Create list of raster tiles from grid data
grid_list = []
for grid in grid_data['grid_code']:
    raster_tile = f'type_{grid}_10m_3338.tif'
    grid_list.append(raster_tile)

# Identify all raster tiles in target folder on Google Cloud Storage
raster_tiles = gcs_list_files(f'gs://akveg-data/veg_type_v2p1/rasters_gridded', storage_client, extension='.tif')
# Keep all raster_tiles that appear in grid_list

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
    raster_file = os.path.join(veg_folder, 'unprocessed', file_name)
    # Download raster tile
    download_from_gcs(raster_uri, raster_file, storage_client)
    # Check and update nodata value if it does not match the specified nodata value
    with rasterio.open(raster_file, 'r+') as src:
        current_nodata = src.nodata
        if current_nodata != nodata_value:
            # Read the pixel array
            data = src.read(1)
            # Replace erroneous nodata values
            data = np.where(data == current_nodata, nodata_value, data)
            # Write the updated array back to disk
            src.write(data, 1)
            # Update the file's internal metadata
            src.nodata = nodata_value
    # Increase count
    tile_count += 1

# Report outcome
end_timing(start_time)

#### SAMPLE RANDOM POINTS
####____________________________________________________

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