/* -*- coding: utf-8 -*-
---------------------------------------------------------------------------
Inspect segmentation results
Author: Timm Nawrocki, Alaska Center for Conservation Science
Last Updated: 2026-08-29
Usage: Must be executed from the Google Earth Engine code editor.
Description: "Inspect segmentation results" creates a visualization comparing the segment boundaries to the imagery composite within the Google Earth Engine code editor.
---------------------------------------------------------------------------*/

// Load imagery
var image_input = 'gs://akveg-data/regional_nomebeaver/imagery/composite_2m_3338.tif';
var composite_2m = ee.Image.loadGeoTIFF(image_input);
var vis_rgb = {bands: ['red', 'green', 'blue'], min: 0, max: 255};
Map.addLayer(composite_2m, vis_rgb, 'Composite Imagery');
Map.centerObject(composite_2m, 9);

// Load segments
var segment_input = 'gs://akveg-data/regional_nomebeaver/segments/segments_2m_3338.tif'
var segments = ee.Image.loadGeoTIFF(segment_input)
var clusters_outline = ee.Algorithms.CannyEdgeDetector(segments, 0.5);
var clusters_outline_masked = clusters_outline.selfMask();
Map.addLayer(clusters_outline_masked, {palette: 'blue'}, 'Segments');
