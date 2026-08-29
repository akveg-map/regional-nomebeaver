# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Create domain raster
# Author: Timm Nawrocki
# Last Updated: 2026-08-18
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Create domain raster' creates a raster to define the valid data area and grid alignment of the map domain. This script requires the manual creation of a map domain polygon feature class as a prerequisite.
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

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/Data')
region_folder = os.path.join(project_folder, 'Data_Input/region_data')

# Define input files
domain_input = os.path.join(region_folder, 'NomeBeaver_MapDomain_3338.shp')

# Define intermediate files
domain_intermediate = os.path.join(project_folder, 'Data_Input/NomeBeaver_MapDomain_Int_2m_3338.tif')

# Define output files
domain_output = os.path.join(project_folder, 'Data_Input/NomeBeaver_MapDomain_2m_3338.tif')

# Define resolution in meters
resolution_m = 2.0

#### CONVERT FEATURE TO RASTER
####____________________________________________________

# Read the feature polygon and calculate bounds
domain_data = gpd.read_file(domain_input)
xmin, ymin, xmax, ymax = domain_data.total_bounds

# Snap bounds to align perfectly with the 0,0 origin
snap_xmin = math.floor(xmin / resolution_m) * resolution_m
snap_ymin = math.floor(ymin / resolution_m) * resolution_m
snap_xmax = math.ceil(xmax / resolution_m) * resolution_m
snap_ymax = math.ceil(ymax / resolution_m) * resolution_m

# Calculate area bounds
area_bounds = [snap_xmin, snap_ymin, snap_xmax, snap_ymax]

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
    xRes=resolution_m,
    yRes=resolution_m,
    initValues=[-128],
    burnValues=[1],
    noData=-128,
    allTouched=False
)

# Convert the feature to raster
if not os.path.exists(domain_intermediate):
    print('Converting feature to raster...')
    start_time = time.time()
    gdal.Rasterize(domain_intermediate, domain_input, options=convert_options)
    end_timing(start_time)

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
print('Converting raster to cloud-optimized geotiff...')
start_time = time.time()
gdal.Translate(domain_output, domain_intermediate, options=cog_options)
end_timing(start_time)

# Remove intermediate data
if os.path.exists(domain_intermediate):
    os.remove(domain_intermediate)
