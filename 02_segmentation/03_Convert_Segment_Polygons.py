# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Convert segment polygons
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in an ArcGIS Pro Python 3.11+ installation.
# Description: 'Convert segment polygons' migrates the results of raster to polygon conversion (run manually in ArcGIS Pro) to geopackage.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import arcpy
from akutils import *

# Enable overwrite outputs
arcpy.env.overwriteOutput = True

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')

# Define input files
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')

# Define output files
gpkg_workspace = os.path.join(segment_folder, 'segments_simplified_2m_3338.gpkg')
layer_name = 'segments_simplified_2m_3338'
segment_output = os.path.join(gpkg_workspace, layer_name)

#### CONVERT RASTER TO POLYGON
####____________________________________________________

# Create the geopackage database if it does not already exist
if not arcpy.Exists(gpkg_workspace):
    print('Creating geopackage workspace...')
    arcpy.management.CreateSQLiteDatabase(gpkg_workspace, 'GEOPACKAGE')

# Create segment polygons
print(f'Converting raster segments to polygons...')
start_time = time.time()
memory_layer = r'memory\temp_segments'
arcpy.conversion.RasterToPolygon(
    in_raster=segment_input,
    out_polygon_features=memory_layer,
    simplify='SIMPLIFY',
    raster_field='VALUE',
    create_multipart_features='SINGLE_OUTER_PART'
)
arcpy.management.CopyFeatures(memory_layer, segment_output)
arcpy.management.Delete(memory_layer)
end_timing(start_time)
