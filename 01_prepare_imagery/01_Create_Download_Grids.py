# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Create download grids
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Create download grids' creates 1 km grids covering the map domain that are sized appropriately for server requests for the imagery download step.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import math
import geopandas as gpd
from shapely.geometry import box
from akutils import *

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')

# Define input files
domain_layer = 'nomebeaver_domain_3338'

# Define output files
grid_layer = 'tiles_001_3338'

# Define grid size in meters
dimension_m = 1000

# Define the fields to retain in the final outputs
export_fields = ['grid_code', 'shape_length', 'shape_area', 'geometry']

#### GENERATE GRIDS
####____________________________________________________

# Read the map domain
print(f'Creating grids...')
start_time = time.time()
domain_data = gpd.read_file(region_geopackage, layer=domain_layer)
crs_3338 = domain_data.crs

# Get bounding box of the domain
xmin, ymin, xmax, ymax = domain_data.total_bounds

# Snap bounds to 0,0 origin
start_x = math.floor(xmin / dimension_m) * dimension_m
start_y = math.floor(ymin / dimension_m) * dimension_m
end_x = math.ceil(xmax / dimension_m) * dimension_m
end_y = math.ceil(ymax / dimension_m) * dimension_m

# Calculate number of columns and rows
num_cols = int((end_x - start_x) / dimension_m)
num_rows = int((end_y - start_y) / dimension_m)

# Create the full grid within the snapped bounds
grid_records = []

# Loop through columns (X) and rows (Y)
for col in range(num_cols):
    for row in range(num_rows):
        # Calculate geometric bounds for this specific cell
        c_xmin = start_x + (col * dimension_m)
        c_ymin = start_y + (row * dimension_m)
        c_xmax = c_xmin + dimension_m
        c_ymax = c_ymin + dimension_m

        # Create polygon geometry
        grid_poly = box(c_xmin, c_ymin, c_xmax, c_ymax)

        # Create a unique grid code
        grid_code = f'C{col + 1:03d}R{num_rows - row:03d}'

        # Append attributes and geometry
        grid_records.append({
            'grid_code': grid_code,
            'geometry': grid_poly
        })

# Convert records to a geodataframe
grid_data = gpd.GeoDataFrame(grid_records, crs=crs_3338)

# Perform spatial join to retain grids that intersect the map domain
print('Filtering grids to intersect with map domain...')
grid_data = gpd.sjoin(grid_data, domain_data, how='inner', predicate='intersects')

# Calculate geometric length (perimeter) and area
grid_data['shape_length'] = grid_data.geometry.length
grid_data['shape_area'] = grid_data.geometry.area

# Restrict fields for export
grid_data = grid_data[export_fields]

# Save selected grids to GeoPackage layer
print(f'Exporting grids...')
grid_data.to_file(region_geopackage, layer=grid_layer, driver='GPKG')
end_timing(start_time)
