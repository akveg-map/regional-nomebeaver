# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Post-process surficial features
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Post-process surficial features" merges modeled and manually delineated data branches and performs smoothing and filling in grid tiles.
# ---------------------------------------------------------------------------

# Set execution parameters
processors = 1
processor = 1
nodata_value = -128

# Import packages
import os
import glob
import time
import math
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio import features
from osgeo import gdal
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
region_geopackage = os.path.join(region_folder, 'region_data_3338.gpkg')
input_folder = os.path.join(project_folder, 'data_input/surficial_data')
surficial_geopackage = os.path.join(input_folder, 'surficial_correction_manual_3338.gpkg')
output_folder = os.path.join(project_folder, 'data_output/surficial_data')
intermediate_folder = os.path.join(output_folder, 'intermediate_data')
tiles_folder = os.path.join(output_folder, 'tiles')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
surficial_input = os.path.join(output_folder, 'surficial_pre_2m_3338.tif')
domain_layer = 'nomebeaver_domain_3338'
grid_layer = 'tiles_001_3338'
anthropogenic_poly_layer = 'surficial_correction_anthropogenic_poly_3338'
barren_line_layer = 'surficial_correction_barren_line_3338'
barren_poly_layer = 'surficial_correction_barren_poly_3338'
trail_line_layer = 'surficial_correction_trail_line_3338'
water_line_layer = 'surficial_correction_water_line_3338'
water_poly_layer = 'surficial_correction_water_poly_3338'
floodplain_poly_layer = 'surficial_floodplains_3338'

# Define intermediate files
trail_buffer_layer = 'surficial_correction_trail_buffer_3338'
barren_merged_layer = 'surficial_correction_barren_merged_3338'
water_merged_layer = 'surficial_correction_water_merged_3338'
anthropogenic_intermediate = os.path.join(intermediate_folder, 'anthropogenic_2m_3338.tif')
barren_intermediate = os.path.join(intermediate_folder, 'barren_2m_3338.tif')
trail_intermediate = os.path.join(intermediate_folder, 'trail_2m_3338.tif')
water_intermediate = os.path.join(intermediate_folder, 'water_2m_3338.tif')
floodplain_intermediate = os.path.join(intermediate_folder, 'floodplain_2m_3338.tif')
vrt_intermediate = os.path.join(intermediate_folder, 'surficial_inter_2m_3338.vrt')
surficial_intermediate = os.path.join(intermediate_folder, 'surficial_inter_2m_3338.tif')

# Define output files
surficial_output = os.path.join(output_folder, 'surficial_2m_3338.tif')

#### PREPARE MANUAL DATA
####____________________________________________________

# Read domain data
print('Preparing vector data...')
start_time = time.time()
domain_data = gpd.read_file(region_geopackage, layer=domain_layer)

# Read line data
barren_line = gpd.read_file(surficial_geopackage, layer=barren_line_layer)
trail_line = gpd.read_file(surficial_geopackage, layer=trail_line_layer)
water_line = gpd.read_file(surficial_geopackage, layer=water_line_layer)

# Buffer lines
barren_line['geometry'] = barren_line.buffer(2.5)
trail_line['geometry'] = trail_line.buffer(2.5)
water_line['geometry'] = water_line.buffer(2.5)

# Read polygon data
barren_poly = gpd.read_file(surficial_geopackage, layer=barren_poly_layer)
water_poly = gpd.read_file(surficial_geopackage, layer=water_poly_layer)

# Merge buffer and polygon data
barren_merged = gpd.GeoDataFrame(
    pd.concat([barren_line[['geometry']], barren_poly[['geometry']]], ignore_index=True),
    crs=domain_data.crs
)
water_merged = gpd.GeoDataFrame(
    pd.concat([water_line[['geometry']], water_poly[['geometry']]], ignore_index=True),
    crs=domain_data.crs
)

# Write data back to geopackage
barren_merged.to_file(surficial_geopackage, layer=barren_merged_layer, driver='GPKG')
water_merged.to_file(surficial_geopackage, layer=water_merged_layer, driver='GPKG')
trail_line.to_file(surficial_geopackage, layer=trail_buffer_layer, driver='GPKG')
end_timing(start_time)

#### CONVERT MANUAL DATA TO RASTER
####____________________________________________________

# Read area bounds
area_bounds = raster_bounds(area_input)

# Create data layer list
data_layers = {anthropogenic_poly_layer: anthropogenic_intermediate,
               barren_merged_layer: barren_intermediate,
               trail_buffer_layer: trail_intermediate,
               water_merged_layer: water_intermediate,
               floodplain_poly_layer: floodplain_intermediate}

# Convert each data layer in list
for data_layer, raster_intermediate in data_layers.items():
    if not os.path.exists(raster_intermediate):
        print(f'Converting {data_layer}...')
        start_time = time.time()

        # Set output raster options
        convert_options = gdal.RasterizeOptions(
            format='GTiff',
            outputType=gdal.GDT_Int8,
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
            initValues=[-128],
            burnValues=[1],
            noData= nodata_value,
            allTouched=False,
            layers=[data_layer]
        )

        # Convert the selector polygons to raster
        inter_data = gdal.Rasterize(raster_intermediate, surficial_geopackage, options=convert_options)
        inter_data = None
        end_timing(start_time)

#### IDENTIFY PREDICTION GRIDS
####____________________________________________________

# Read grid data
grid_data = gpd.read_file(region_geopackage, layer=grid_layer)

# Define grid list
grid_list = grid_data['grid_code'].tolist()

# Override grid list for test purposes (uncomment lines below)
# target_grids = ['AK010H210V005', 'AK010H210V004', 'AK010H213V013', 'AK010H190V013', 'AK010H190V014',
#                'AK010H250V017', 'AK010H250V016', 'AK010H255V016']
# grid_list = [code for code in grid_list if code in target_grids]

# Partition grid list for spatially parallel processing
grid_chunks = np.array_split(grid_list, processors)
grid_list = grid_chunks[processor - 1].tolist()

# Create final grid data
grid_data = grid_data[grid_data['grid_code'].isin(grid_list)]
print(f'Predicting {len(grid_data)} grids...')

#### POST-PROCESS TILES
####____________________________________________________

# Create a dictionary of input names and paths
raster_paths = {
    'area': area_input,
    'surficial': surficial_input,
    'anthropogenic': anthropogenic_intermediate,
    'barren': barren_intermediate,
    'trail': trail_intermediate,
    'water': water_intermediate,
    'floodplain': floodplain_intermediate
}

# Iterate through input paths to open them into a dictionary
raster_sources = {}
for name, path in raster_paths.items():
    raster_sources[name] = rasterio.open(path)

# Define grid alignment from area_input
area_transform = raster_sources['area'].transform
align_x = area_transform[2]
align_y = area_transform[5]
res_x = area_transform[0]
res_y = abs(area_transform[4])

# Post-process each grid in grid list
grid_count = 1
for index, row in grid_data.iterrows():
    # Define grid code
    grid = row['grid_code']

    # Define output paths
    surficial_tile = os.path.join(tiles_folder, f'{grid}_2m_3338.tif')
    gcs_output = f'{gcs_base}/surficial_data/tiles/{grid}_2m_3338.tif'

    # Create output raster if it does not already exist in GCS
    if not gcs_blob_exists(gcs_output, storage_client):
        print(f'Post-processing {grid} ({grid_count} of {len(grid_list)})...')
        start_time = time.time()

        # Define processing geometry
        geometry_processing = row['geometry'].buffer(200)
        left_processing, bottom_processing, right_processing, top_processing = geometry_processing.bounds
        left_processing = align_x + math.floor((left_processing - align_x) / res_x) * res_x
        bottom_processing = align_y + math.floor((bottom_processing - align_y) / res_y) * res_y
        right_processing = align_x + math.ceil((right_processing - align_x) / res_x) * res_x
        top_processing = align_y + math.ceil((top_processing - align_y) / res_y) * res_y

        # Define window bounds for processing
        window_processing = (left_processing, bottom_processing, right_processing, top_processing)

        # Define export geometry
        geometry_export = row['geometry'].buffer(10)
        left_export, bottom_export, right_export, top_export = geometry_export.bounds
        left_export = align_x + math.floor((left_export - align_x) / res_x) * res_x
        bottom_export = align_y + math.floor((bottom_export - align_y) / res_y) * res_y
        right_export = align_x + math.ceil((right_export - align_x) / res_x) * res_x
        top_export = align_y + math.ceil((top_export - align_y) / res_y) * res_y

        # Define the output profile by the export geometry
        dst_transform = rasterio.transform.from_origin(left_export, top_export, res_x, res_y)
        dst_width = int(round((right_export - left_export) / res_x))
        dst_height = int(round((top_export - bottom_export) / res_y))

        # Calculate offsets to slice the processing buffer to the export buffer
        col_offset = int(round((left_export - left_processing) / res_x))
        row_offset = int(round((top_processing - top_export) / res_y))

        # Define output profile
        output_profile = {
            'driver': 'GTiff',
            'height': dst_height,
            'width': dst_width,
            'count': 1,
            'dtype': 'int8',
            'crs': 'EPSG:3338',
            'transform': dst_transform,
            'nodata': nodata_value,
            'compress': 'lzw',
            'tiled': True,
            'blockxsize': 512,
            'blockysize': 512
        }

        # Parse types
        with rasterio.open(surficial_tile, 'w', **output_profile) as dst:
            # Load raster data
            data = {}
            for name, src in raster_sources.items():
                data[name] = read_raster_block(src, window_processing)

            # Initialize block data
            block_data = data['surficial']

            # Correct barren
            block_data = np.where(data['barren'] == 1, 4, block_data)

            # Correct trail
            block_data = np.where(data['trail'] == 1, 6, block_data)

            # Correct water
            block_data = np.where(data['water'] == 1, 5, block_data)

            # Correct anthropogenic
            block_data = np.where((block_data == 4) & (data['anthropogenic'] == 1), 7, block_data)

            # Correct floodplain
            block_data = np.where((block_data == 3) & (data['floodplain'] == 1), 8, block_data)

            # Correct floodplain barren
            block_data = np.where((block_data == 4) & (data['floodplain'] == 1), 9, block_data)

            # Apply incremental sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(block_data.astype('int16'), size=25, connectivity=4)

            # Fill no data using a categorical nibble
            print('\tFilling no data...')
            nibble_data = categorical_nibble(sieve_data, nodata_value)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(nibble_data, window_size=3, iterations=2)

            # Apply sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(filter_data.astype('int16'), size=25, connectivity=4)
            sieve_data = features.sieve(sieve_data.astype('int16'), size=25, connectivity=4)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(sieve_data, window_size=3, iterations=1)

            # Extract to study area
            print('\tExtracting to study area...')
            export_data = np.where(data['area'] == 1, filter_data.astype('int8'), nodata_value)

            # Crop the export data to the export extent
            export_data = export_data[
                row_offset: row_offset + dst_height,
                col_offset: col_offset + dst_width
            ]

            # Write results
            dst.write(export_data, 1)

        # Upload and Clean Up
        print('Uploading raster dataset to Google Cloud Storage...')
        upload_to_gcs(surficial_tile, gcs_output, storage_client)
        end_timing(start_time)
    else:
        print(f'{grid} already exists.')

    # Increase count
    grid_count += 1

# Close all raster connections
for src in raster_sources.values():
    src.close()

#### PROCESS CLOUD-OPTIMIZED GEOTIFF
####____________________________________________________

# Create merged VRT raster
input_files = glob.glob(os.path.join(tiles_folder, '*.tif'))

# Merge raster tiles
print(f'Merging {len(input_files)} tiles...')
start_time = time.time()
vrt_data = gdal.BuildVRT(
    vrt_intermediate,
    input_files,
    outputSRS='EPSG:3338',
    xRes=2,
    yRes=2,
    VRTNodata=nodata_value,
    outputBounds=area_bounds)
vrt_data = None

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
print('Converting raster to cloud-optimized geotiff...')
cog_data = gdal.Translate(surficial_output, vrt_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)
