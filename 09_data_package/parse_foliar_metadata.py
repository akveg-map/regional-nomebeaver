# Import packages
import os
import glob
import fiona
import geopandas as gpd
import rasterio
from pyproj import Transformer

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
template_folder = os.path.join(project_folder, 'data_input/templates')
output_folder = os.path.join(project_folder,
                             'data_output/data_package/20261029_NomeBeaver_DataPackage/metadata')

# Ensure output folder exists
os.makedirs(output_folder, exist_ok=True)

# Define input files
region_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
cover_input = os.path.join(template_folder, 'diagnostic_cvr_2m_3338.xml')
distribution_input = os.path.join(template_folder, 'diagnostic_dst_2m_3338.xml')
derived_input = os.path.join(template_folder, 'diagnostic_der_2m_3338.xml')

zonal_foliar = {'alnus': 'Alder Shrubs',
                'betshr': 'Birch Shrubs',
                'bettre': 'Birch Trees',
                'brotre': 'Broadleaf Trees',
                'dryas': 'Dryas Dwarf Shrubs',
                'dsalix': 'Willow Dwarf Shrubs',
                'empnig': 'Crowberry',
                'erivag': 'Tussock Cottongrass',
                'feather': 'Feathermoss',
                'forb': 'Forbs',
                'gramin': 'Graminoids',
                'lichen': 'Lichens',
                'mwcalama': 'Mesic-Wet Calamagrostis',
                'ndsalix': 'Willow Shrubs',
                'neetre': 'Needleleaf Trees',
                'nerishr': 'Needleleaf Ericaceous Shrubs',
                'picgla': 'White Spruce',
                'picmar': 'Black Spruce',
                'poptre': 'Aspen',
                'populbt': 'Balsam Poplar',
                'rhoshr': 'Rhododendron Shrubs',
                'sphagn': 'Sphagnum',
                'vaculi': 'Low Blueberry Shrubs',
                'vacvit': 'Lingonberry',
                'wetforb': 'Wetland Forbs',
                'wetsed': 'Wetland Sedges'}
zonal_dist = {'bromos': 'Hydrophytic Brown Mosses',
              'wetgram': 'Wetland Graminoids'}
zonal_sum = {'eridwarf': 'Ericaceous Dwarf Shrubs',
             'erishrub': 'Ericaceous Shrubs',
             'herbac': 'Herbaceous Plants',
             'ndshrub': 'Non-dwarf Shrubs',
             'shrub': 'All Shrubs',
             'trees': 'All Trees',
             'wetind': 'Wetland Indicator (Sphagnum + Wetland Sedges)'}
zonal_ratio = {'deciduous_ratio': 'Deciduous Tree Ratio',
               'picea_ratio': 'White Spruce Ratio',
               'tussock_ratio': 'Tussock Ratio'}

#### CALCULATE RASTER BOUNDS
####____________________________________________________

# Setup pyproj transformer for EPSG:3338 to EPSG:4269
transformer = Transformer.from_crs('EPSG:3338', 'EPSG:4269', always_xy=True)

# Read raster bounds
with rasterio.open(region_input) as src:
    bounds = src.bounds

# Convert raster bounds from EPSG:3338 to EPSG:4269
west_4269, south_4269 = transformer.transform(bounds.left, bounds.bottom)
east_4269, north_4269 = transformer.transform(bounds.right, bounds.top)

# Assign EPSG:4269 bounding coordinates rounded to 5 decimal places to variables
west_coordinate = str(round(west_4269, 5))
east_coordinate = str(round(east_4269, 5))
south_coordinate = str(round(south_4269, 5))
north_coordinate = str(round(north_4269, 5))
print(west_coordinate, east_coordinate, south_coordinate, north_coordinate)


#### FILL METADATA
####____________________________________________________

# Helper function to process replacement and export
def process_metadata(template_path, output_path, replacements):
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()

    for key, value in replacements.items():
        content = content.replace(key, str(value))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)


# Common bounding box replacements
base_replacements = {
    '{east_bound}': east_coordinate,
    '{west_bound}': west_coordinate,
    '{south_bound}': south_coordinate,
    '{north_bound}': north_coordinate
}

# Fill cover metadata
for diagnostic_abbr, diagnostic_set in zonal_foliar.items():
    metadata_output = os.path.join(output_folder, f'{diagnostic_abbr}_cvr_2m_3338.xml')
    replacements = {**base_replacements, '{diagnostic_set}': diagnostic_set}
    process_metadata(cover_input, metadata_output, replacements)

# Fill distribution metadata
for diagnostic_abbr, diagnostic_set in zonal_dist.items():
    metadata_output = os.path.join(output_folder, f'{diagnostic_abbr}_dst_2m_3338.xml')
    replacements = {**base_replacements, '{diagnostic_set}': diagnostic_set}
    process_metadata(distribution_input, metadata_output, replacements)

# Fill derived summary metadata
for diagnostic_abbr, diagnostic_set in zonal_sum.items():
    metadata_output = os.path.join(output_folder, f'{diagnostic_abbr}_cvr_2m_3338.xml')
    replacements = {**base_replacements, '{diagnostic_set}': diagnostic_set}
    process_metadata(derived_input, metadata_output, replacements)

# Fill derived ratio metadata
for diagnostic_abbr, diagnostic_set in zonal_ratio.items():
    metadata_output = os.path.join(output_folder, f'{diagnostic_abbr}_2m_3338.xml')
    replacements = {**base_replacements, '{diagnostic_set}': diagnostic_set}
    process_metadata(derived_input, metadata_output, replacements)
