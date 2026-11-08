# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize type proportion patterns within map domain
# Author: Timm Nawrocki
# Last Updated: 2026-10-24
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize type proportion patterns within map domain" calculates summary plots for Icy Cape.
# ---------------------------------------------------------------------------

# Define variables
plot_height = 400
nodata_value = -32768

# Import packages
import os
import time
import pandas as pd
import geopandas as gpd
from rasterstats import zonal_stats
import kaleido
from akutils import *

# Initialize kaleido
kaleido.get_chrome_sync()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
schema_folder = os.path.join(drive, root_folder, 'Repositories/class-descriptions')
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')
surficial_geopackage = os.path.join(project_folder, 'data_input/surficial_data',
                                    'surficial_correction_manual_3338.gpkg')
type_folder = os.path.join(project_folder, 'data_output/veg_types')
output_folder = os.path.join(project_folder, 'data_output/summary_data')

# Define input files
region_layer = 'nomebeaver_domain_3338'
floodplain_layer = 'surficial_floodplains_3338'
schema_input = os.path.join(schema_folder, 'AKVEG_MapClass_Schema.csv')
type_input = os.path.join(type_folder, 'types_800mmu_2m_3338.tif')

# Define intermediate files
domain_intermediate = os.path.join(output_folder, 'type_proportions_domain.csv')
floodplain_intermediate = os.path.join(output_folder, 'type_proportions_floodplain.csv')

# Define output files
type_output = os.path.join(output_folder, 'type_proportions_comparison.xlsx')

#### CALCULATE DOMAIN TYPE ZONAL STATISTICS
####____________________________________________________

# Calculate zonal statistics for vegetation types if table does not exist
if not os.path.exists(domain_intermediate):
    print('Calculating domain zonal summary for vegetation types...')
    start_time = time.time()

    # Read study area domain geometry
    zone_data = gpd.read_file(region_geopackage, layer=region_layer)

    # Calculate the total area of the zone
    total_area = zone_data.geometry.area.sum()

    # Calculate zonal statistics for vegetation types
    type_columns = ['raster_value', 'count']
    type_stats = zonal_stats(zone_data, type_input, categorical=True, nodata=nodata_value)
    if isinstance(type_stats, list):
        stats_dict = type_stats[0]
    else:
        stats_dict = type_stats
    type_stats = pd.DataFrame(list(stats_dict.items()), columns=['raster_value', 'count'])

    # Convert counts to area percents
    type_stats['cover_percent'] = round(((type_stats['count'] * (2*2)) / total_area) * 100, 1)

    # Export the compiled summary data to a data frame
    type_stats.to_csv(domain_intermediate, header=True, index=False, sep=',', encoding='utf-8')
    end_timing(start_time)

#### CALCULATE FLOODPLAIN TYPE ZONAL STATISTICS
####____________________________________________________

# Calculate zonal statistics for vegetation types if table does not exist
if not os.path.exists(floodplain_intermediate):
    print('Calculating floodplain zonal summary for vegetation types...')
    start_time = time.time()

    # Read study area domain geometry
    zone_data = gpd.read_file(surficial_geopackage, layer=floodplain_layer)

    # Calculate the total area of the zone
    total_area = zone_data.geometry.area.sum()

    # Calculate zonal statistics for vegetation types
    type_columns = ['raster_value', 'count']
    type_stats = zonal_stats(zone_data, type_input, categorical=True, nodata=nodata_value)
    if isinstance(type_stats, list):
        stats_dict = type_stats[0]
    else:
        stats_dict = type_stats
    type_stats = pd.DataFrame(list(stats_dict.items()), columns=['raster_value', 'count'])

    # Convert counts to area percents
    type_stats['cover_percent'] = round(((type_stats['count'] * (2*2)) / total_area) * 100, 1)

    # Export the compiled summary data to a data frame
    type_stats.to_csv(floodplain_intermediate, header=True, index=False, sep=',', encoding='utf-8')
    end_timing(start_time)

#### CREATE SORTED COMPARISON TABLE
####____________________________________________________

# Read schema data
print('Creating summary table...')
start_time = time.time()
schema_data = pd.read_csv(schema_input)[['code', 'map_class']].drop_duplicates()
schema_data = schema_data.rename(columns={'code': 'raster_value'})
schema_data['raster_value'] = pd.to_numeric(schema_data['raster_value'], errors='coerce')

# Read domain stats
domain_stats = pd.read_csv(domain_intermediate)
domain_stats = domain_stats.rename(columns={'cover_percent': 'Domain Proportion (%)'})
domain_stats['raster_value'] = pd.to_numeric(domain_stats['raster_value'], errors='coerce')

# Read floodplain stats
floodplain_stats = pd.read_csv(floodplain_intermediate)
floodplain_stats = floodplain_stats.rename(columns={'cover_percent': 'Floodplain Proportion (%)'})
floodplain_stats['raster_value'] = pd.to_numeric(floodplain_stats['raster_value'], errors='coerce')

# Merge domain and floodplain stats
comparison_stats = pd.merge(domain_stats, floodplain_stats, on='raster_value', how='outer')
comparison_stats = comparison_stats.fillna(0)

# Merge comparison and schema
comparison_stats = pd.merge(comparison_stats, schema_data, on='raster_value', how='left')

# Arrange columns
comparison_stats = comparison_stats[['map_class', 'Floodplain Proportion (%)', 'Domain Proportion (%)']]
comparison_stats = comparison_stats.rename(columns={'map_class': 'Vegetation (or Abiotic) Type'})

# Filter out vegetation types where both domain and floodplain proportions are < 1.0%
valid_mask = ((comparison_stats['Floodplain Proportion (%)'] >= 1.0)
              | (comparison_stats['Domain Proportion (%)'] >= 1.0))
truncated_stats = comparison_stats[valid_mask].copy()

# Sort tables
comparison_stats = comparison_stats.sort_values(by='Floodplain Proportion (%)', ascending=False)
truncated_stats = truncated_stats.sort_values(by='Floodplain Proportion (%)', ascending=False)

# Export tables to Excel sheets
with pd.ExcelWriter(type_output) as writer:
    comparison_stats.to_excel(writer, sheet_name='complete', index=False)
    truncated_stats.to_excel(writer, sheet_name='truncated', index=False)
end_timing(start_time)
