# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Train and validate random forest multiclassification model
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Train and validate random forest multiclassification model' trains, exports, and validates a random forest classifier for multiple classes.
# ---------------------------------------------------------------------------

# Import packages
import os
import numpy as np
import pandas as pd
import geopandas as gpd
import time
import joblib
from sklearn.utils import shuffle
from sklearn.model_selection import StratifiedKFold
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix
from akutils import *

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
training_geopackage = os.path.join(project_folder, 'data_input/surficial_data/surficial_training_3338.gpkg')
model_folder = os.path.join(project_folder, 'data_output/surficial_model')

# Define input files
training_layer = 'surficial_training_3338'

# Define output files
classifier_output = os.path.join(model_folder, 'surficial_classifier.joblib')
results_output = os.path.join(model_folder, 'surficial_results.csv')
importance_output = os.path.join(model_folder, 'surficial_importances.csv')
metrics_output = os.path.join(model_folder, 'surficial_accuracy_metrics.txt')

# Define covariate sets
predictor_s1 = ['s1_1_vha', 's1_1_vhd', 's1_1_vva', 's1_1_vvd',
                's1_2_vha', 's1_2_vhd', 's1_2_vva', 's1_2_vvd',
                's1_3_vha', 's1_3_vhd', 's1_3_vva', 's1_3_vvd']
predictor_s2 = [f's2_{i}_{band}' for i in range(1, 6) for band in
                ['blue', 'green', 'red', 'redge1', 'redge2', 'redge3', 'nir',
                 'redge4', 'swir1', 'swir2', 'nbr', 'ngrdi', 'ndmi', 'ndsi',
                 'ndvi', 'ndwi']]
predictor_topo = ['coast', 'stream', 'river', 'wetness',
                  'elevation', 'exposure', 'heatload', 'position',
                  'aspect', 'relief', 'roughness', 'slope']
predictor_comp = ['comp_blue', 'comp_green', 'comp_red', 'comp_nir', 'comp_ndvi', 'comp_ndwi']

# Dynamically build predictor_all list from input arguments
predictor_names = ['topo', 's1', 's2', 'comp']
predictor_map = {
    's1': predictor_s1, 's2': predictor_s2, 'topo': predictor_topo, 'comp': predictor_comp
}
predictor_all = []
for name in predictor_names:
    if name in predictor_map:
        predictor_all.extend(predictor_map[name])
    else:
        print(f'Warning: Predictor set {name} not recognized and will be skipped.')
if not predictor_all:
    raise ValueError('No valid predictor sets were provided. Exiting.')

# Define other field sets
obs_class = ['class']
all_variables = predictor_all + obs_class
pred_class = ['pred_class']
outer_split = ['outer_split_n']
outer_columns = all_variables + pred_class + outer_split

# Create a standardized parameter set for a random forest classifier
classifier_params = {'n_estimators': 500,
                     'criterion': 'gini',
                     'max_depth': None,
                     'min_samples_split': 4,
                     'min_samples_leaf': 2,
                     'min_weight_fraction_leaf': 0,
                     'max_features': 'sqrt',
                     'bootstrap': True,
                     'oob_score': False,
                     'warm_start': False,
                     'class_weight': None,
                     'n_jobs': 2,
                     'random_state': 314}

# Define cross validation methods
outer_cv_splits = StratifiedKFold(n_splits=10)
inner_cv_splits = StratifiedKFold(n_splits=10)

#### PREPARE INPUT DATA
####____________________________________________________

# Read input data to data frames
print('Loading input data...')
start_time = time.time()
input_data = gpd.read_file(training_geopackage, layer=training_layer)

# Shuffle data
shuffled_data = shuffle(input_data, random_state=314).copy()
end_timing(start_time)

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# PART 1: TRAIN FINAL MODEL ON FULL DATASET
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #

print('\n' + '=' * 50)
print('PART 1: TRAINING FINAL MODEL')
print('=' * 50)

#### TRAIN AND EXPORT FINAL MODELS
####____________________________________________________
print('Training and exporting final model...')
start_time = time.time()

# Prepare full dataset for training
X_train = shuffled_data[predictor_all].astype(float)
y_class = shuffled_data[obs_class[0]].astype('int32')

# Train final classifier
print('\tTraining final classifier...')
final_classifier = RandomForestClassifier(**classifier_params)
final_classifier.fit(X_train, y_class)

# Export final models and threshold
joblib.dump(final_classifier, classifier_output)
end_timing(start_time)

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# PART 2: PERFORM SPATIAL CROSS-VALIDATION
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #

print('\n' + '=' * 50)
print('PART 2: PERFORMING CROSS-VALIDATION')
print('=' * 50)

#### SETUP CROSS-VALIDATION DATA
####____________________________________________________
print('Creating cross validation splits...')
start_time = time.time()

# Create empty data frames to store results
outer_train = pd.DataFrame()
outer_test = pd.DataFrame()
outer_results = pd.DataFrame()
importance_results = pd.DataFrame()

# Create outer cross validation splits
count = 1
for train_index, test_index in outer_cv_splits.split(
        shuffled_data,
        shuffled_data[obs_class[0]].astype('int32')):
    # Split the data into train and test partitions
    train = shuffled_data.iloc[train_index].assign(outer_split_n=count)
    test = shuffled_data.iloc[test_index].assign(outer_split_n=count)
    # Append to data frames
    outer_train = pd.concat([outer_train, train], ignore_index=True)
    outer_test = pd.concat([outer_test, test], ignore_index=True)
    count += 1
outer_cv_length = count - 1
print(f'Created {outer_cv_length} outer cross-validation group splits.')
end_timing(start_time)

#### CONDUCT MODEL VALIDATION
####____________________________________________________

# Iterate through outer cross validation splits
for outer_cv_i in range(1, outer_cv_length + 1):
    print(f'Conducting outer CV iteration {outer_cv_i} of {outer_cv_length}...')
    iter_start_time = time.time()

    # Partition outer data for this iteration
    outer_train_iter = outer_train[outer_train[outer_split[0]] == outer_cv_i].copy()
    outer_test_iter = outer_test[outer_test[outer_split[0]] == outer_cv_i].copy()

    # Identify X and y outer train splits
    X_train = outer_train_iter[predictor_all].astype(float)
    y_class = outer_train_iter[obs_class[0]].astype('int32')

    # Train classifier
    print('\tTraining outer classifier...')
    outer_classifier = RandomForestClassifier(**classifier_params)
    outer_classifier.fit(X_train, y_class)

    # Harvest feature importances
    classifier_imp = pd.DataFrame({
        'covariate': X_train.columns,
        'importance': outer_classifier.feature_importances_,
        'component': 'classifier',
        'outer_cv_i': outer_cv_i
    })
    importance_results = pd.concat([importance_results, classifier_imp], ignore_index=True)

    # Predict outer test
    print('\tPredicting outer test data...')
    X_test = outer_test_iter[predictor_all].astype(float)
    outer_preds = outer_classifier.predict(X_test)

    # Assign predicted values to outer test data frame
    outer_test_iter = outer_test_iter.assign(pred_class=outer_preds)
    outer_results = pd.concat([outer_results, outer_test_iter], ignore_index=True)

    end_timing(iter_start_time)

#### CALCULATE PERFORMANCE AND STORE VALIDATION RESULTS
####____________________________________________________
print('Calculating performance metrics and storing validation results...')
start_time = time.time()

# Partition observed vs predicted
y_true = outer_results[obs_class[0]].astype('int32')
y_pred = outer_results[pred_class[0]].astype('int32')

# Define classes mappings
class_labels = [1, 2, 3, 4, 5]
class_names = {
    1: 'Alpine Bare',
    2: 'Alpine',
    3: 'Lowland',
    4: 'Bare',
    5: 'Water'
}

# Generate confusion matrix
cm = confusion_matrix(y_true, y_pred, labels=class_labels)

# Calculate precision and recall
with np.errstate(divide='ignore', invalid='ignore'):
    recall = np.nan_to_num(np.diag(cm) / np.sum(cm, axis=1))
    precision = np.nan_to_num(np.diag(cm) / np.sum(cm, axis=0))

# Calculate overall accuracy
overall_acc = np.sum(np.diag(cm)) / np.sum(cm)

# Write metrics to text file
with open(metrics_output, 'w') as f:
    f.write('--- MULTICLASS CLASSIFICATION ACCURACY ---\n')
    f.write(f'Overall Accuracy: {round(overall_acc * 100, 1)}%\n\n')
    for i, label in enumerate(class_labels):
        name = class_names[label]
        recall_exp = round(recall[i] * 100, 1)
        precision_exp = round(precision[i] * 100, 1)
        f.write(f'Class {label} ({name}):\n')
        f.write(f'\tRecall (Producer\'s Accuracy): {recall_exp}%\n')
        f.write(f'\tPrecision (User\'s Accuracy): {precision_exp}%\n\n')

# Store output tabular results
outer_results.to_csv(results_output, header=True, index=False, sep=',', encoding='utf-8')
importance_results.to_csv(importance_output, header=True, index=False, sep=',', encoding='utf-8')

# Print final validation scores to console
print('\n--- Final Validation Metrics ---')
print(f'Overall Accuracy: {round(overall_acc * 100, 1)}%')
end_timing(start_time)
