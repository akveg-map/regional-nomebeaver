# Import packages
import os
import geopandas as gpd

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
surficial_geopackage = os.path.join(project_folder, 'data_input/surficial_data',
                                    'surficial_correction_manual_3338.gpkg')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')
output_folder = os.path.join(project_folder, 'data_output/data_package/20261029_NomeBeaver_DataPackage')
output_geopackage = os.path.join(output_folder, 'nomebeaver_vector_data_3338.gpkg')

# Define input files
region_layer = 'nomebeaver_domain_3338'
floodplain_input = 'surficial_floodplains_3338'
floodplain_output = 'floodplain_active_boundaries_3338'

# Read data
floodplain_data = gpd.read_file(surficial_geopackage, layer=floodplain_input)
region_data = gpd.read_file(region_geopackage, layer=region_layer)

# Calculate geometric length (perimeter) and area
floodplain_data['shape_length'] = floodplain_data.geometry.length
floodplain_data['shape_area'] = floodplain_data.geometry.area

# Safely write/update the specific layer in append mode without overwriting other GeoPackage layers
floodplain_data.to_file(output_geopackage, layer=floodplain_output, driver='GPKG')
region_data.to_file(output_geopackage, layer=region_layer, driver='GPKG', mode='a')