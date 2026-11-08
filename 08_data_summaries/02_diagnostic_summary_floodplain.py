# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize diagnostic species cover patterns within floodplains
# Author: Timm Nawrocki
# Last Updated: 2026-10-24
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize diagnostic species cover patterns within floodplains" calculates the proportion of each diagnostic species set within the Nome-Beaver floodplains and creates a treemap plot.
# ---------------------------------------------------------------------------

# Define variables
plot_height = 400
nodata_value = -128

# Import packages
import os
import time
import numpy as np
import pandas as pd
import rasterio
import plotly.express as px
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
schema_folder = os.path.join(drive, root_folder, 'Repositories/foliar-cover')
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
surficial_geopackage = os.path.join(project_folder, 'data_input/surficial_data',
                                    'surficial_correction_manual_3338.gpkg')
type_folder = os.path.join(project_folder, 'data_output/veg_types')
surficial_folder = os.path.join(project_folder, 'data_output/surficial_data')
covariate_folder = os.path.join(project_folder, 'data_input/covariate_data')
water_folder = os.path.join(project_folder, 'data_output/water_data')
output_folder = os.path.join(project_folder, 'data_output/summary_data')

# Define input files
zone_layer = 'surficial_floodplains_3338'
schema_input = os.path.join(schema_folder, 'AKVEG_Schema_FoliarCover.csv')
type_input = os.path.join(type_folder, 'types_800mmu_2m_3338.tif')
floodplain_input = os.path.join(surficial_folder, 'intermediate_data/floodplain_2m_3338.tif')
foliar_input = os.path.join(covariate_folder, 'foliar_zonal_2m_3338.tif')
water_input = os.path.join(water_folder, 'surface_water_2m_3338.tif')

# Define intermediate files
diagnostic_intermediate = os.path.join(output_folder, 'diagnostic_cover_floodplain.csv')

# Define output files
diagnostic_output = os.path.join(output_folder, 'diagnostic_cover_floodplain.html')

# Define diagnostic sets
diagnostic_sets = ['alnus', 'betshr', 'bettre', 'dryas', 'dsalix', 'erivag',
                   'feather', 'forb', 'lichen', 'mwcalama', 'ndsalix', 'nerishr',
                   'picgla', 'picmar', 'poptre', 'populbt', 'rhoshr', 'sphagn',
                   'vaculi', 'vacvit', 'wetforb', 'wetsed']

# Define color dictionary
color_dict = {'alnus': '242B40',
              'betshr': '97A2C4',
              'bettre': 'D1D6E5',
              'dryas': 'AC97C4',
              'dsalix': 'AC97C4',
              'erivag': '942A2A',
              'feather': 'B4B279',
              'forb': 'B479B0',
              'lichen': 'FFF6E6',
              'mwcalama': 'B4D5C9',
              'ndsalix': '4B5A86',
              'nerishr': 'B48479',
              'picgla': '4B864B',
              'picmar': '2A4B2A',
              'poptre': 'D1D6E5',
              'populbt': 'D1D6E5',
              'rhoshr': 'B48479',
              'sphagn': '3B6858',
              'vaculi': 'B48479',
              'vacvit': 'B48479',
              'wetforb': '5EA58B',
              'wetsed': '5EA58B',
              'other': 'E1E1E1',
              'surface_water': 'BEE8FF'}

# Identify band indices for foliar input raster
with rasterio.open(foliar_input) as src:
    foliar_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        foliar_band_dict = {name: foliar_band_map[name] for name in diagnostic_sets}
    except KeyError as e:
        raise KeyError(f'Requested zonal band {e} was not found in raster band descriptions.')

#### CALCULATE DIAGNOSTIC SET ZONAL STATISTICS TABLE
####____________________________________________________

# Calculate zonal statistics for each diagnostic species set if table does not exist
if not os.path.exists(diagnostic_intermediate):
    # Prepare raster zone mask
    with (rasterio.open(floodplain_input) as floodplain_raster,
          rasterio.open(type_input) as type_raster):
        # Read raster data
        floodplain_data = floodplain_raster.read(1)
        type_data = type_raster.read(1)

        # Define 2D boolean type masks
        exclude_mask = np.isin(type_data, [995, 996])
        split_mask = np.isin(type_data, [176, 224, 250, 998])
        type_mask = np.isin(type_data, [212, 213, 214, 221, 222, 223])

        # Define active floodplain zonal boolean mask
        zone_mask = (floodplain_data == 1) & (type_mask | split_mask) & (~exclude_mask)

    # Initialize empty list to store summary data
    diagnostic_stats_list = []
    count = 1

    # Calculate zonal statistics for diagnostic species sets using foliar raster
    with rasterio.open(foliar_input) as foliar_raster:
        for diagnostic_set in diagnostic_sets:
            print(f'Calculating zonal summary for diagnostic set {count} of {len(diagnostic_sets)}...')
            start_time = time.time()

            # Indentify and read band
            diagnostic_band_idx = foliar_band_dict.get(diagnostic_set)
            band_data = foliar_raster.read(diagnostic_band_idx)

            # Mask pixels within active zone and valid cover range [0, 100]
            valid_pixels = band_data[zone_mask & (band_data >= 0) & (band_data <= 100)]
            mean_value = valid_pixels.mean() if valid_pixels.size > 0 else 0

            # Create summary data row
            summary_data = pd.DataFrame({'target_abbr': [diagnostic_set],
                                         'cover_percent': [round(mean_value, 1)]})
            diagnostic_stats_list.append(summary_data)
            count += 1
            end_timing(start_time)

    # Calculate zonal statistics for surface water using surface water raster
    print('Calculating zonal summary for surface water...')
    start_time = time.time()
    with rasterio.open(water_input) as water_raster:
        water_data = water_raster.read(1)
        valid_pixels = water_data[zone_mask & (water_data >= 0) & (water_data <= 100)]
        mean_value = valid_pixels.mean() if valid_pixels.size > 0 else 0
    summary_data = pd.DataFrame({'target_abbr': ['surface_water'], 'cover_percent': [round(mean_value, 1)]})
    diagnostic_stats_list.append(summary_data)
    end_timing(start_time)

    # Concatenate and export the compiled summary data to a CSV table
    diagnostic_stats = pd.concat(diagnostic_stats_list, ignore_index=True)
    diagnostic_stats.to_csv(diagnostic_intermediate, header=True, index=False, sep=',', encoding='utf-8')

#### PLOT DIAGNOSTIC COVER STATISTICS
####____________________________________________________

# Read schema data
print('Creating summary plot...')
start_time = time.time()
schema_data = pd.read_csv(schema_input)[['target_abbr', 'target']].drop_duplicates()

# Read diagnostic stats
diagnostic_stats = pd.read_csv(diagnostic_intermediate)

# Retain only rows where target_abbr is present in diagnostic_sets
target_sets = diagnostic_sets + ['surface_water']
diagnostic_stats = diagnostic_stats[diagnostic_stats['target_abbr'].isin(target_sets)].copy()

# Segregate sets with cover < 3%
main_categories = diagnostic_stats[diagnostic_stats['cover_percent'] >= 3.0].copy()
minor_categories = diagnostic_stats[diagnostic_stats['cover_percent'] < 3.0]

# Merge any set with < 3% cover into "other"
if not minor_categories.empty:
    other_cover = round(minor_categories['cover_percent'].sum(), 1)
    other_row = pd.DataFrame({'target_abbr': ['other'], 'cover_percent': [other_cover]})
    diagnostic_stats = pd.concat([main_categories, other_row], ignore_index=True)
else:
    diagnostic_stats = main_categories.copy()

# Join full schema names to stats
diagnostic_stats = pd.merge(diagnostic_stats, schema_data, on='target_abbr', how='left')
diagnostic_stats = diagnostic_stats.rename(columns={'target': 'name'})

# Assign default display names for surface water and aggregated categories
diagnostic_stats['name'] = np.where(diagnostic_stats['target_abbr'] == 'surface_water',
                                    'Surface Water', diagnostic_stats['name'])
diagnostic_stats['name'] = np.where(diagnostic_stats['target_abbr'] == 'other',
                                    'Other (Sets < 3%)', diagnostic_stats['name'])

# Define custom display name overrides and line breaks (target_abbr -> formatted display string)
label_overrides = {
    'vaculi': 'Low Blueberry',
    'mwcalama': 'Mesic-Wet<br>Calamagrostis',
    'wetsed': 'Wetland<br>Sedges',
    'sphagn': 'Sphagnum',
    'alnus': 'Alder<br>Shrubs'
}

# Apply custom overrides where specified; keep original schema name otherwise
diagnostic_stats['name'] = diagnostic_stats['target_abbr'].map(label_overrides).fillna(diagnostic_stats['name'])

# Format color_dict values into valid '#' hex codes
hex_color_map = {abbr: f"#{hex_code.lstrip('#')}" for abbr, hex_code in color_dict.items()}

# Build color map keyed directly by display category name
diagnostic_colors = dict(zip(diagnostic_stats['name'], diagnostic_stats['target_abbr'].map(hex_color_map)))

# Create diagnostic species treemap plot
diagnostic_plot = px.treemap(
    diagnostic_stats,
    path=[px.Constant(' '), 'name'], # Add total sum root
    values='cover_percent',
    color='name',
    color_discrete_map=diagnostic_colors
)

# Force the canvas root node background to be white
colors = list(diagnostic_plot.data[0].marker.colors)
for i, label in enumerate(diagnostic_plot.data[0].labels):
    if label == ' ':  # Isolate only the background root
        colors[i] = 'white'
diagnostic_plot.data[0].marker.colors = tuple(colors)

# Update plot formatting
diagnostic_plot.update_traces(
    # Remove inner padding that exposes the root node
    tiling=dict(pad=0),
    # Turn off the gray pathbar header
    pathbar=dict(visible=False),
    # Set tile borders to white (blends into background)
    marker=dict(line=dict(color='white', width=2)),
    # Increase label font size
    textfont=dict(size=14),
    # Display label and percentage directly on the plot
    texttemplate='<b>%{label}</b><br>%{value:.1f}%',
    # Restrict hover to show only the label and the mean value (formatted)
    hovertemplate='<b>%{label}</b><br>Cover Percent: %{value:.1f}%<extra></extra>'
)

# Update layout for margins, dimensions, and background color
diagnostic_plot.update_layout(
    template='plotly_white',
    uniformtext=dict(minsize=14, mode='show'),
    margin=dict(t=0, l=0, r=0, b=0),
    autosize=True,
    width=None,
    height=plot_height,
    paper_bgcolor='white',
    plot_bgcolor='white'
)

# Export to HTML (interactive) and PNG (publication)
diagnostic_plot.write_html(diagnostic_output, config={'responsive': True})
diagnostic_plot.write_image(diagnostic_output.replace('.html', '.png'), width=800, height=plot_height, scale=10)
end_timing(start_time)