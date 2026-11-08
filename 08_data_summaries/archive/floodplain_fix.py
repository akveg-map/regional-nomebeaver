# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Fix floodplain geometries
# Author: Timm Nawrocki
# Last Updated: 2026-10-24
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Fix floodplain geometries" strips the invalid Z and M dimensions from the geometries for the floodplain polygon feature class.
# ---------------------------------------------------------------------------

import os
import fiona
import geopandas as gpd

# Define file and layer paths
surficial_geopackage = 'C:/ACCS_Work/Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data/data_input/surficial_data/surficial_correction_manual_3338.gpkg'
layer_name = 'surficial_floodplains_3338'

# Read dataset
print(f'Loading layer {layer_name}...')
gdf = gpd.read_file(surficial_geopackage, layer=layer_name)

# Strip Z and M dimensions to force 2D (XY) geometries
print('Converting geometries to 2D...')
gdf['geometry'] = gdf.geometry.force_2d()

# Safely remove existing 3D/4D layer from the GeoPackage
if layer_name in fiona.listlayers(surficial_geopackage):
    print(f'Removing 3D/4D layer instance...')
    fiona.remove(surficial_geopackage, layer=layer_name)

# Export clean 2D layer back to GeoPackage in append mode
print(f'Writing updated 2D layer...')
gdf.to_file(surficial_geopackage, layer=layer_name, driver='GPKG', mode='a')
print('Conversion complete.')
