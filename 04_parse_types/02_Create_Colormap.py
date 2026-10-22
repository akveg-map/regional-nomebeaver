# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Create colormap
# Author: Timm Nawrocki
# Last Updated: 2026-10-19
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Create colormap' converts the color field of the schema table to a colormap file.
# ---------------------------------------------------------------------------

# Import packages
import os
import dbf
import pandas as pd
from google.cloud import storage
from akutils import *

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'types_800mmu_2m_3338.clr'
final_gcs_output = f'{gcs_base}/veg_types/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
output_folder = os.path.join(project_folder, 'data_output/veg_types')
schema_folder = os.path.join(drive, root_folder, 'Repositories/class-descriptions')

# Define input files
schema_input = os.path.join(schema_folder, 'AKVEG_MapClass_Schema.csv')
attribute_input = os.path.join(output_folder, 'types_800mmu_2m_3338.tif.vat.dbf')

# Define output files
color_output = os.path.join(output_folder, output_name)

#### CREATE COLOR MAP
####____________________________________________________

# Read attribute table to get valid values
print('Reading valid values from attribute table...')
attribute_table = dbf.Table(attribute_input)

# Convert attribute values to valid set
valid_values = set()
with attribute_table.open(mode=dbf.READ_ONLY) as attribute_read:
    for record in attribute_read:
        # Read value field
        valid_values.add(record.VALUE)

# Remove existing colormap if it exists
if os.path.exists(color_output):
    os.remove(color_output)

# Read the color data from schema table
schema_data = pd.read_csv(schema_input)
value_colors = dict(zip(schema_data['code'], schema_data['color']))

# Write colormap
print('Writing colormap...')
with open(color_output, 'w') as f:
    for value, hex_color in value_colors.items():
        if value in valid_values:
            hex_str = str(hex_color).strip().lstrip('#')
            r, g, b = tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
            f.write(f'{int(value)} {r} {g} {b}\n')
    f.write('END\n')

# Upload colormap to GCS
print('Uploading colormap to Google Cloud...')
upload_to_gcs(color_output, final_gcs_output, storage_client)
