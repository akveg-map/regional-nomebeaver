# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize height distributions
# Author: Timm Nawrocki
# Last Updated: 2026-10-26
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize height distributions" calculates and compares floodplain and non-floodplain histograms of canopy height using the rh90 segment summaries to represent community heights.
# ---------------------------------------------------------------------------

# Define variables
plot_height = 400

# Import packages
import os
import time
import numpy as np
import pandas as pd
import rasterio
import plotly.express as px
import kaleido
from akutils import *

# Initialize kaleido graphics exporter
kaleido.get_chrome_sync()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
schema_folder = os.path.join(drive, root_folder, 'Repositories/foliar-cover')
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
type_folder = os.path.join(project_folder, 'data_output/veg_types')
height_folder = os.path.join(project_folder, 'data_output/height_data')
output_folder = os.path.join(project_folder, 'data_output/summary_data')

# Define input files
type_input = os.path.join(type_folder, 'types_800mmu_2m_3338.tif')
height_input = os.path.join(height_folder, 'chm_segments_2m_3338_v20261020.tif')

# Define intermediate files
height_intermediate = os.path.join(output_folder, 'height_distribution.csv')

# Define output files
height_output = os.path.join(output_folder, 'height_distribution.html')

# Define raster band
height_band = 'chm_rh90_cm'

# Identify band index for canopy height input raster
with rasterio.open(height_input) as src:
    height_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        height_band_idx = height_band_map[height_band]
    except KeyError:
        raise KeyError(f"Requested height band '{height_band}' was not found in raster band descriptions.")

#### CALCULATE HEIGHT DISTRIBUTION TABLE
####____________________________________________________

# Calculate zonal distribution for domain and floodplain if table does not exist
if not os.path.exists(height_intermediate):
    print('Calculating canopy height distributions...')
    start_time = time.time()

    # Define custom unequal bin edges and display class labels
    bin_edges = [-0.5, 0.5, 50.5, 150.5, 300.5, 500.5, 1000.5, 4000.5]
    bin_labels = ['0', '1–50', '51–150', '151–300', '301–500', '501–1000', '> 1000']

    # Process height data
    with (rasterio.open(height_input) as height_raster,
          rasterio.open(type_input) as type_raster):
        # Read data
        height_data = height_raster.read(height_band_idx)
        type_data = type_raster.read(1)

        # Define 2D boolean type masks
        exclude_mask = np.isin(type_data, [176, 224, 250, 995, 996, 998])
        type_mask = np.isin(type_data, [212, 213, 214, 221, 222, 223])

        # Extract non-floodplain height values
        print('Extracting domain height pixels...')
        domain_values = height_data[(height_data >= 0) & (~exclude_mask) & (~type_mask)]

        # Compute non-floodplain histogram relative percentages
        domain_counts, _ = np.histogram(domain_values, bins=bin_edges)
        domain_percent = (domain_counts / len(domain_values)) * 100

        # Extract floodplain height values
        print('Extracting floodplain height pixels...')
        floodplain_values = height_data[(height_data >= 0) & (~exclude_mask) & (type_mask)]

        # Compute floodplain histogram relative percentages
        floodplain_counts, _ = np.histogram(floodplain_values, bins=bin_edges)
        floodplain_percent = (floodplain_counts / len(floodplain_values)) * 100

    # Compile height distribution data frame
    height_stats = pd.DataFrame({
        'height_class': bin_labels,
        'bin_min_cm': [0, 1, 51, 151, 301, 501, 1001],
        'bin_max_cm': [0, 50, 150, 300, 500, 1000, 3000],
        'domain_percent': np.round(domain_percent, 2),
        'floodplain_percent': np.round(floodplain_percent, 2)
    })

    # Export compiled table to CSV
    height_stats.to_csv(height_intermediate, index=False)
    end_timing(start_time)

#### PLOT CANOPY HEIGHT DISTRIBUTIONS
####____________________________________________________

# Read height stats table
print('Creating canopy height distribution bar plot...')
start_time = time.time()
height_stats = pd.read_csv(height_intermediate)

# Reshape data frame for Plotly Express grouped bar plotting
plot_data = pd.melt(
    height_stats,
    id_vars=['height_class'],
    value_vars=['domain_percent', 'floodplain_percent'],
    var_name='unit',
    value_name='proportion_percent'
)

# Assign readable category names for spatial regions
plot_data['unit'] = plot_data['unit'].map({
    'domain_percent': 'Non-Floodplain (or Inactive Floodplain)',
    'floodplain_percent': 'Active Floodplain'
})

# Define bar color palette
unit_colors = {
    'Non-Floodplain (or Inactive Floodplain)': '#B4BCD5',
    'Active Floodplain': '#242B40'
}

# Create canopy height distribution grouped bar chart
height_plot = px.bar(
    plot_data,
    x='height_class',
    y='proportion_percent',
    color='unit',
    barmode='group',
    color_discrete_map=unit_colors
)

# Update trace styles and hover formatting
height_plot.update_traces(
    hovertemplate='<b>%{fullData.name}</b><br>Height Class: %{x} cm<br>Proportion: %{y:.2f}%<extra></extra>'
)

# Update layout for margins, dimensions, axes, and legend
height_plot.update_layout(
    template='plotly_white',
    margin=dict(t=20, l=50, r=20, b=50),
    autosize=True,
    width=None,
    height=plot_height,
    paper_bgcolor='white',
    plot_bgcolor='white',
    xaxis=dict(
        title='Canopy Height Class (cm)',
        type='category',
        showgrid=False
    ),
    yaxis=dict(
        title='Area Proportion (%)',
        showgrid=True,
        gridcolor='#E5E5E5'
    ),
    legend=dict(
        title=None,
        orientation='h',
        yanchor='bottom',
        y=1.02,
        xanchor='right',
        x=1
    )
)

# Export interactive HTML and static PNG
height_plot.write_html(height_output, config={'responsive': True})
height_plot.write_image(height_output.replace('.html', '.png'), width=800, height=plot_height, scale=10)
end_timing(start_time)
