# Import packages
import os
import fiona
import geopandas as gpd

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')

# Define input files
region_layer = 'nomebeaver_domain_3338'

# Read data
region_data = gpd.read_file(region_geopackage, layer=region_layer)

# Calculate geometric length (perimeter) and area
region_data['shape_length'] = region_data.geometry.length
region_data['shape_area'] = region_data.geometry.area

# Remove existing layer from GeoPackage if present to avoid duplicate/corrupted layer tables
if region_layer in fiona.listlayers(region_geopackage):
    fiona.remove(region_geopackage, layer=region_layer, driver='GPKG')

# Safely write/update the specific layer in append mode without overwriting other GeoPackage layers
region_data.to_file(region_geopackage, layer=region_layer, driver='GPKG', mode='a')