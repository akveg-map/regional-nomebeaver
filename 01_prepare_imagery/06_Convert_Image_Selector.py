# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Convert image selector
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Convert image selector' converts a manually delineated image selector polygon feature class to raster, where values of 1 indicate selection of the Vivid 2023 composite and values of 2 indicate selection of the custom composite imagery.
# ---------------------------------------------------------------------------

# Set execution parameters
nodata_value = -128

# Import packages
import os
import time
from osgeo import gdal
from akutils import *

# Configure GDAL
gdal.UseExceptions()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work/Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data'

# Define folder structure
imagery_folder = os.path.join(drive, root_folder, 'data_input/imagery')
omission_geopackage = os.path.join(imagery_folder, 'vivid2023_omission_3338.gpkg')

# Define input files
area_input = os.path.join(drive, root_folder, 'data_input/nomebeaver_domain_2m_3338.tif')
select_layer = 'vivid2023_omission_3338'

# Define intermediate files
select_intermediate = os.path.join(imagery_folder, 'vivid2023_omission_inter_2m_3338.tif')

# Define output files
select_output = os.path.join(imagery_folder, 'vivid2023_omission_2m_3338.tif')

#### CONVERT RANGE TO RASTER
####____________________________________________________

# Read area bounds
area_bounds = raster_bounds(area_input)

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
    initValues=[1],
    burnValues=[2],
    noData= nodata_value,
    allTouched=False,
    layers=[select_layer]
)

# Convert the selector polygons to raster
if not os.path.exists(select_intermediate):
    print('Converting range to raster...')
    start_time = time.time()
    inter_data = gdal.Rasterize(select_intermediate, omission_geopackage, options=convert_options)
    inter_data = None
    end_timing(start_time)

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
start_time = time.time()
cog_data = gdal.Translate(select_output, select_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Remove intermediate file
if os.path.exists(select_intermediate):
    os.remove(select_intermediate)
