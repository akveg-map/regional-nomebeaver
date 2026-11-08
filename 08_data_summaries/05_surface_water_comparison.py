# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Summarize surface water distributions
# Author: Timm Nawrocki
# Last Updated: 2026-10-26
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Summarize surface water distributions" calculates the proportion of each diagnostic species set within the Nome-Beaver map domain and creates a treemap plot.
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
surficial_folder = os.path.join(project_folder, 'data_output/surficial_data')
water_folder = os.path.join(project_folder, 'data_output/water_data')
output_folder = os.path.join(project_folder, 'data_output/summary_data')

# Define input files
type_input = os.path.join(type_folder, 'types_800mmu_2m_3338.tif')
floodplain_input = os.path.join(surficial_folder, 'intermediate_data/floodplain_2m_3338.tif')
water_input = os.path.join(water_folder, 'surface_water_2m_3338.tif')

# Define intermediate files
water_intermediate = os.path.join(output_folder, 'surface_water_distribution.csv')

# Define output files
water_output = os.path.join(output_folder, 'surface_water_distribution.html')

#### CALCULATE WATER DISTRIBUTION TABLE
####____________________________________________________

# Calculate zonal distribution for non-floodplain (domain) and floodplain if table does not exist
if not os.path.exists(water_intermediate):
    print('Calculating surface water distributions...')
    start_time = time.time()

    # Define custom unequal bin edges and display class labels
    bin_edges = [-0.5, 0.5, 10.5, 25.5, 50.5, 90.5, 100.5]
    bin_labels = ['0', '1–10', '11–25', '26–50', '51–90', '91–100']

    # Process water data
    with (rasterio.open(water_input) as water_raster,
          rasterio.open(floodplain_input) as floodplain_raster,
          rasterio.open(type_input) as type_raster):
        # Read data
        water_data = water_raster.read(1)
        floodplain_data = floodplain_raster.read(1)
        type_data = type_raster.read(1)

        # Define 2D boolean type masks
        exclude_mask = np.isin(type_data, [995, 996])
        split_mask = np.isin(type_data, [176, 224, 250, 998])
        type_mask = np.isin(type_data, [212, 213, 214, 221, 222, 223])

        # Extract non-floodplain water values
        print('Extracting domain water pixels...')
        domain_values = water_data[
            (water_data >= 0)
            & ~((split_mask) & (floodplain_data == 1))
            & (~type_mask) & (~exclude_mask)]

        # Compute non-floodplain histogram relative percentages
        domain_counts, _ = np.histogram(domain_values, bins=bin_edges)
        domain_percent = (domain_counts / len(domain_values)) * 100

        # Extract floodplain water values
        print('Extracting floodplain water pixels...')
        floodplain_values = water_data[
            (water_data >= 0)
            & (floodplain_data == 1)
            & ((type_mask) | (split_mask)) & (~exclude_mask)]

        # Compute floodplain histogram relative percentages
        floodplain_counts, _ = np.histogram(floodplain_values, bins=bin_edges)
        floodplain_percent = (floodplain_counts / len(floodplain_values)) * 100

    # Compile surface water distribution data frame
    water_stats = pd.DataFrame({
        'water_class': bin_labels,
        'bin_min_percent': [0, 1, 11, 26, 51, 91],
        'bin_max_percent': [0, 10, 25, 50, 90, 100],
        'domain_percent': np.round(domain_percent, 2),
        'floodplain_percent': np.round(floodplain_percent, 2)
    })

    # Export compiled table to CSV
    water_stats.to_csv(water_intermediate, index=False)
    end_timing(start_time)

#### PLOT SURFACE WATER DISTRIBUTIONS
####____________________________________________________

# Read water stats table
print('Creating surface water distribution bar plot...')
start_time = time.time()
water_stats = pd.read_csv(water_intermediate)

# Reshape data frame for Plotly Express grouped bar plotting
plot_data = pd.melt(
    water_stats,
    id_vars=['water_class'],
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

# Create surface water distribution grouped bar chart
water_plot = px.bar(
    plot_data,
    x='water_class',
    y='proportion_percent',
    color='unit',
    barmode='group',
    color_discrete_map=unit_colors
)

# Update trace styles and hover formatting
water_plot.update_traces(
    hovertemplate='<b>%{fullData.name}</b><br>Water Cover Class: %{x}%<br>Proportion: %{y:.2f}%<extra></extra>'
)

# Update layout for margins, dimensions, axes, and legend
water_plot.update_layout(
    template='plotly_white',
    margin=dict(t=20, l=50, r=20, b=50),
    autosize=True,
    width=None,
    height=plot_height,
    paper_bgcolor='white',
    plot_bgcolor='white',
    xaxis=dict(
        title='Sub-canopy Surface Water Cover Class (%)',
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
water_plot.write_html(water_output, config={'responsive': True})
water_plot.write_image(water_output.replace('.html', '.png'), width=800, height=plot_height, scale=10)
end_timing(start_time)
