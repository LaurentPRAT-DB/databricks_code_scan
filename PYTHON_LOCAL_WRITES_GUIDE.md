# Python Local File Writes Detection Guide

## Overview

This guide explains how to use the `patterns_python_local_writes.yaml` configuration to detect Python code that writes files to the current working directory (CWD) in Databricks workspaces.

## Why This Matters

When Python code writes files to the current working directory in Databricks, the files are saved to the **cluster driver node's ephemeral storage**. This causes several critical issues:

### 🔴 Critical Problems

1. **Data Loss**: Files disappear when the cluster terminates
2. **Limited Storage**: Driver node disk space is limited (can cause cluster crashes)
3. **Not Distributed**: Files aren't accessible from other cluster nodes
4. **No Governance**: Bypasses Unity Catalog security and auditing
5. **Migration Blocker**: Prevents adoption of Unity Catalog best practices

### ✅ Modern Solution: Unity Catalog Volumes

Unity Catalog Volumes provide:
- **Persistent storage**: Files survive cluster termination
- **Governance**: Full Unity Catalog security and audit logging
- **Scalability**: Cloud object storage (S3, ADLS, GCS)
- **Accessibility**: Available across clusters and users
- **Organization**: Structured catalog.schema.volume hierarchy

## Pattern Configuration Files

### YAML Format (Recommended)
```bash
patterns_python_local_writes.yaml
```
- Human-readable with extensive comments
- Includes pattern explanations and risk levels
- Contains migration guide and examples

### JSON Format
```bash
patterns_python_local_writes.json
```
- Machine-readable format
- Same patterns as YAML version
- Useful for programmatic processing

## Quick Start

### 1. Basic Scan

Scan entire workspace for Python local writes:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --config patterns_python_local_writes.yaml \
  --output python_local_writes_scan.txt
```

### 2. Scan Specific Directory

Focus on a specific user or team directory:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --path /Users/data.engineer@company.com \
  --config patterns_python_local_writes.yaml \
  --group-by-type \
  --output user_scan.txt
```

### 3. Combined Security Audit

Scan for both local writes and other security issues:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --config patterns_python_local_writes.yaml \
  --pattern "password" \
  --pattern "api_key" \
  --output comprehensive_security_scan.txt
```

## Pattern Categories

The configuration includes **50+ patterns** organized into 14 categories:

| Category | Pattern Count | Risk Level | Examples |
|----------|---------------|------------|----------|
| Basic File Operations | 8 | High | `open()`, `with open()`, `Path.write_text()` |
| Pandas DataFrame Exports | 9 | High | `to_csv()`, `to_parquet()`, `to_pickle()` |
| NumPy Array Operations | 4 | High | `np.save()`, `np.savez()` |
| Serialization Libraries | 5 | Medium-High | `json.dump()`, `pickle.dump()`, `joblib.dump()` |
| ML Model Persistence | 4 | Critical | `model.save()`, `torch.save()`, TensorFlow saves |
| File Copy/Move | 3 | Medium | `shutil.copy()`, `shutil.move()` |
| CSV Module | 2 | Medium | `csv.writer()`, `csv.DictWriter()` |
| Image Processing | 3 | Medium | `img.save()`, `plt.savefig()`, `cv2.imwrite()` |
| Archives/Compression | 3 | High | `zipfile`, `tarfile`, `gzip` |
| Databricks-Specific | 2 | Critical | `dbutils.fs.put()` with `file:/` |
| Logging to Files | 2 | Low | `logging.FileHandler()` |
| Database Exports | 2 | High | `sqlite3.connect()`, cursor exports |
| Excel Libraries | 2 | Medium | `openpyxl`, `xlsxwriter` |
| Temporary Files | 1 | Low | `tempfile` in CWD |

## Understanding Risk Levels

### 🔴 CRITICAL - Immediate Action Required

**Characteristics:**
- Files can be hundreds of MB to several GB
- Can cause cluster failures
- Data loss is almost certain

**Examples:**
```python
# TensorFlow model (can be 500+ MB)
model.save("trained_model")

# Large ZIP archive
zipfile.ZipFile("data_archive.zip", "w")

# Databricks explicit local write
dbutils.fs.put("file:/tmp/output.csv", content)
```

**Action:** Refactor immediately to Unity Catalog Volumes or object storage.

### 🟠 HIGH - Should Refactor Soon

**Characteristics:**
- Common operations in production code
- Files accumulate over time
- Direct data loss risk

**Examples:**
```python
# Pandas DataFrame export
df.to_csv("results.csv")
df.to_parquet("data.parquet")

# NumPy arrays
np.save("weights.npy", model_weights)

# ML model persistence
joblib.dump(model, "model.pkl")
```

**Action:** Plan refactoring in next sprint, use Unity Catalog Volumes.

### 🟡 MEDIUM - Review and Consider Refactoring

**Characteristics:**
- Smaller files, less immediate risk
- May be in less-critical code paths
- Can still cause issues at scale

**Examples:**
```python
# Excel export
df.to_excel("report.xlsx")

# Image files
img.save("chart.png")

# File copying
shutil.copy(src, "destination.txt")
```

**Action:** Review context, refactor if part of production workflows.

### 🟢 LOW - Monitor But May Be Acceptable

**Characteristics:**
- Small files, typically temporary
- Often cleaned up automatically
- Minimal risk of disk space issues

**Examples:**
```python
# Matplotlib plots
plt.savefig("temp_plot.png")

# Small log files
logging.FileHandler("debug.log")

# Temporary files
tempfile.NamedTemporaryFile(dir=".")
```

**Action:** Document rationale, ensure cleanup, consider alternatives.

## Interpreting Scan Results

### Example Output

```
Pattern Matches (127 total):
================================================================================

/Users/john.doe/ETL_Pipeline (8 matches):
--------------------------------------------------------------------------------
  Line 45: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
    Matched: 'df.to_csv("output.csv")'

  Line 89: model.save("trained_model.h5")
    Pattern: model\.save\s*\(\s*["'][^/][^"']*["']
    Matched: 'model.save("trained_model.h5")'

  Line 156: np.save("embeddings.npy", embeddings)
    Pattern: np\.save\s*\(\s*["'][^/][^"']*["']
    Matched: 'np.save("embeddings.npy", embeddings)'
```

### Triage Process

1. **Classify by Risk Level**
   - Sort findings by pattern category
   - Identify critical issues first (ML models, large files)

2. **Assess Context**
   - Is this production code or experimental?
   - How frequently does this code run?
   - What's the typical file size?

3. **Prioritize Fixes**
   - Critical: Fix before next production deployment
   - High: Include in sprint planning
   - Medium: Add to backlog
   - Low: Document and monitor

4. **Plan Refactoring**
   - Create Unity Catalog Volume
   - Update file paths in code
   - Test thoroughly
   - Deploy to production

## Migration Guide

### Step 1: Create Unity Catalog Volume

```sql
-- Create catalog (if not exists)
CREATE CATALOG IF NOT EXISTS my_data_catalog;

-- Create schema
CREATE SCHEMA IF NOT EXISTS my_data_catalog.data_engineering;

-- Create volume for persistent file storage
CREATE VOLUME IF NOT EXISTS my_data_catalog.data_engineering.ml_models;

-- Create another volume for data exports
CREATE VOLUME IF NOT EXISTS my_data_catalog.data_engineering.exports;

-- Grant permissions
GRANT ALL PRIVILEGES ON VOLUME my_data_catalog.data_engineering.ml_models
  TO data_engineers;
```

### Step 2: Update Python Code

#### Before (Writes to CWD - Ephemeral ❌)

```python
import pandas as pd
import numpy as np
from tensorflow import keras

# Pandas DataFrame export - LOST ON CLUSTER TERMINATION
df.to_csv("daily_results.csv")
df.to_parquet("clean_data.parquet")

# NumPy array save - LOST ON CLUSTER TERMINATION
np.save("embeddings.npy", embeddings)

# ML model save - LOST ON CLUSTER TERMINATION
model.save("trained_model.h5")

# Image save - LOST ON CLUSTER TERMINATION
plt.savefig("analysis_chart.png")
```

#### After (Writes to Unity Catalog Volume - Persistent ✅)

```python
import pandas as pd
import numpy as np
from tensorflow import keras

# Define volume base path
VOLUME_PATH = "/Volumes/my_data_catalog/data_engineering/exports"
MODEL_PATH = "/Volumes/my_data_catalog/data_engineering/ml_models"

# Pandas DataFrame export - PERSISTED TO UNITY CATALOG
df.to_csv(f"{VOLUME_PATH}/daily_results.csv")
df.to_parquet(f"{VOLUME_PATH}/clean_data.parquet")

# NumPy array save - PERSISTED TO UNITY CATALOG
np.save(f"{MODEL_PATH}/embeddings.npy", embeddings)

# ML model save - PERSISTED TO UNITY CATALOG
model.save(f"{MODEL_PATH}/trained_model.h5")

# Image save - PERSISTED TO UNITY CATALOG
plt.savefig(f"{VOLUME_PATH}/analysis_chart.png")
```

### Step 3: For Structured Data, Use Delta Tables (Best Practice ⭐)

Even better than saving to files, use Delta tables for structured data:

#### Before: Pandas CSV Export

```python
# OLD WAY - File in CWD
df.to_csv("processed_data.csv")

# Later, someone needs to find and load this file...
df = pd.read_csv("processed_data.csv")  # Where is it?
```

#### After: Delta Table in Unity Catalog

```python
# BEST PRACTICE - Delta table in Unity Catalog
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# Convert Pandas to Spark DataFrame
spark_df = spark.createDataFrame(df)

# Save as managed Delta table (recommended)
spark_df.write \
    .format("delta") \
    .mode("overwrite") \
    .saveAsTable("my_data_catalog.data_engineering.processed_data")

# Later, anyone can easily access it
df = spark.table("my_data_catalog.data_engineering.processed_data").toPandas()

# Benefits:
# ✅ Versioned (time travel)
# ✅ Governed (Unity Catalog permissions)
# ✅ Discoverable (appears in Data Explorer)
# ✅ Audited (all access logged)
# ✅ Optimized (Delta optimizations apply)
```

### Step 4: Configuration Pattern

Create a configuration module for consistent paths:

```python
# config.py
"""
Databricks storage configuration for Unity Catalog Volumes.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class StorageConfig:
    """Storage paths for Unity Catalog Volumes."""

    catalog: str = "my_data_catalog"
    schema: str = "data_engineering"

    @property
    def exports_volume(self) -> str:
        """Volume for data exports (CSV, Parquet, etc.)."""
        return f"/Volumes/{self.catalog}/{self.schema}/exports"

    @property
    def models_volume(self) -> str:
        """Volume for ML models."""
        return f"/Volumes/{self.catalog}/{self.schema}/ml_models"

    @property
    def images_volume(self) -> str:
        """Volume for images and visualizations."""
        return f"/Volumes/{self.catalog}/{self.schema}/images"

    def get_export_path(self, filename: str) -> str:
        """Get full path for export file."""
        return f"{self.exports_volume}/{filename}"

    def get_model_path(self, model_name: str) -> str:
        """Get full path for model file."""
        return f"{self.models_volume}/{model_name}"

    def get_image_path(self, image_name: str) -> str:
        """Get full path for image file."""
        return f"{self.images_volume}/{image_name}"


# Usage in notebooks:
# storage = StorageConfig()
# df.to_csv(storage.get_export_path("results.csv"))
# model.save(storage.get_model_path("my_model.h5"))
```

## Common Patterns and Solutions

### Pattern 1: Data Export in ETL Pipeline

**Before:**
```python
# ETL notebook - writes to CWD
def export_processed_data(df):
    df.to_csv("processed_data.csv")
    df.to_parquet("processed_data.parquet")
    print("Data exported successfully")
```

**After:**
```python
# ETL notebook - writes to Unity Catalog
def export_processed_data(df, spark):
    # Best: Use Delta table
    spark_df = spark.createDataFrame(df)
    spark_df.write.format("delta").mode("overwrite") \
        .saveAsTable("catalog.schema.processed_data")

    # Alternative: Volume for files
    # volume_path = "/Volumes/catalog/schema/exports"
    # df.to_parquet(f"{volume_path}/processed_data.parquet")

    print("Data saved to Unity Catalog")
```

### Pattern 2: ML Model Training

**Before:**
```python
# Training notebook - model saved to CWD
from sklearn.ensemble import RandomForestClassifier
import joblib

# Train model
model = RandomForestClassifier()
model.fit(X_train, y_train)

# Save model - LOST ON CLUSTER TERMINATION!
joblib.dump(model, "trained_model.pkl")
```

**After (Option 1: Unity Catalog Volume):**
```python
# Training notebook - model saved to Volume
from sklearn.ensemble import RandomForestClassifier
import joblib

# Train model
model = RandomForestClassifier()
model.fit(X_train, y_train)

# Save to Unity Catalog Volume - PERSISTENT!
model_path = "/Volumes/catalog/schema/ml_models/trained_model.pkl"
joblib.dump(model, model_path)

# Log path for reference
print(f"Model saved to: {model_path}")
```

**After (Option 2: MLflow - RECOMMENDED):**
```python
# Training notebook - use MLflow (best practice)
from sklearn.ensemble import RandomForestClassifier
import mlflow
import mlflow.sklearn

# Enable Unity Catalog for MLflow
mlflow.set_registry_uri("databricks-uc")

# Train model
model = RandomForestClassifier()
model.fit(X_train, y_train)

# Log with MLflow - BEST PRACTICE!
with mlflow.start_run():
    mlflow.log_params({"n_estimators": 100})
    mlflow.log_metrics({"accuracy": accuracy_score(y_test, y_pred)})
    mlflow.sklearn.log_model(
        model,
        "model",
        registered_model_name="catalog.schema.my_model"
    )

# Benefits:
# ✅ Versioned automatically
# ✅ Tracked experiments
# ✅ Easy deployment
# ✅ Unity Catalog integration
```

### Pattern 3: Visualization Export

**Before:**
```python
# Analysis notebook - chart saved to CWD
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(data)
plt.title("Daily Trends")
plt.savefig("daily_trends.png")  # LOST!
plt.close()
```

**After:**
```python
# Analysis notebook - chart saved to Volume
import matplotlib.pyplot as plt

volume_path = "/Volumes/catalog/schema/images"

plt.figure(figsize=(10, 6))
plt.plot(data)
plt.title("Daily Trends")
plt.savefig(f"{volume_path}/daily_trends.png")  # PERSISTENT!
plt.close()

# Or display inline (for interactive analysis)
# display(plt.gcf())
```

### Pattern 4: Temporary Files That Need Cleanup

**Before:**
```python
# Processing notebook - temp files in CWD
import tempfile

# Creates temp file in CWD - may not get cleaned up!
with tempfile.NamedTemporaryFile(dir=".", delete=False) as tmp:
    tmp.write(data)
    process_file(tmp.name)
```

**After:**
```python
# Processing notebook - use proper temp directory
import tempfile
import os

# Use system temp directory - auto cleanup
with tempfile.NamedTemporaryFile(delete=True) as tmp:
    tmp.write(data)
    tmp.flush()  # Ensure data is written
    process_file(tmp.name)
# File automatically deleted when context exits

# Or use Databricks tmp directory
dbfs_tmp = "/tmp"  # On driver node, cleaned periodically
tmp_path = f"{dbfs_tmp}/processing_{os.getpid()}.tmp"
try:
    with open(tmp_path, 'wb') as f:
        f.write(data)
    process_file(tmp_path)
finally:
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
```

## False Positives and Edge Cases

### Legitimate Cases to Ignore

1. **Code in Comments/Docstrings**
   ```python
   # Example usage in docstring:
   # df.to_csv("output.csv")  # Don't refactor this!
   ```

2. **Test Code**
   ```python
   # test_export.py
   def test_csv_export():
       """Test CSV export functionality."""
       df.to_csv("/tmp/test_output.csv")  # OK for tests
   ```

3. **Error Handling Examples**
   ```python
   try:
       df.to_csv(volume_path)
   except Exception:
       # Fallback documented in except block
       df.to_csv("fallback.csv")  # May be intentional
   ```

4. **Explicitly Temporary Files**
   ```python
   # Documented temporary file, cleaned up in same cell
   temp_file = "temp_processing.csv"
   df.to_csv(temp_file)
   process_csv(temp_file)
   os.remove(temp_file)  # Cleanup documented
   ```

### How to Handle False Positives

1. **Add Documentation**
   ```python
   # INTENTIONAL: Temporary file for API compatibility
   # This file is processed and deleted in the same execution
   df.to_csv("temp_api_input.csv")
   ```

2. **Use Proper Temp Directory**
   ```python
   # Better: Use /tmp for truly temporary files
   import tempfile
   with tempfile.TemporaryDirectory() as tmpdir:
       temp_path = f"{tmpdir}/processing.csv"
       df.to_csv(temp_path)
   ```

3. **Refactor If Possible**
   ```python
   # Best: Eliminate temp file entirely
   # Use in-memory StringIO instead
   from io import StringIO
   csv_buffer = StringIO()
   df.to_csv(csv_buffer)
   api_call(csv_buffer.getvalue())
   ```

## Best Practices Summary

### ✅ DO

1. **Use Unity Catalog Volumes** for file storage
2. **Use Delta tables** for structured data
3. **Use MLflow** for ML model versioning
4. **Centralize configuration** for storage paths
5. **Document** intentional temporary file usage
6. **Test** thoroughly after refactoring
7. **Monitor** disk usage on clusters

### ❌ DON'T

1. **Don't save to CWD** in production code
2. **Don't use DBFS root** (deprecated)
3. **Don't hardcode paths** - use configuration
4. **Don't ignore warnings** about ephemeral storage
5. **Don't assume files persist** across cluster restarts
6. **Don't bypass Unity Catalog** governance

## Monitoring and Validation

### After Refactoring, Verify

```python
# Verification checklist
import os
from pathlib import Path

# 1. Verify Volume path is accessible
volume_path = "/Volumes/catalog/schema/exports"
assert os.path.exists(volume_path), f"Volume not accessible: {volume_path}"

# 2. Test write permissions
test_file = f"{volume_path}/.write_test"
Path(test_file).touch()
os.remove(test_file)
print("✅ Write permissions verified")

# 3. Test file persistence (run in separate cluster)
# Write file, terminate cluster, start new cluster, verify file exists

# 4. Verify Unity Catalog permissions
# Ensure proper users/groups have access
```

### Automated Scanning

Set up regular scans to catch new issues:

```bash
#!/bin/bash
# weekly_scan.sh - Run weekly scan for local file writes

DATE=$(date +%Y%m%d)
OUTPUT_DIR="/Volumes/catalog/schema/compliance_scans"

uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --config patterns_python_local_writes.yaml \
  --output "${OUTPUT_DIR}/python_local_writes_${DATE}.txt"

# Alert if new issues found
NEW_ISSUES=$(grep "Pattern Matches" "${OUTPUT_DIR}/python_local_writes_${DATE}.txt" | awk '{print $3}')
if [ "$NEW_ISSUES" -gt 0 ]; then
    echo "⚠️  Found ${NEW_ISSUES} local file write patterns"
    # Send alert to team (Slack, email, etc.)
fi
```

## Additional Resources

### Databricks Documentation

- [Unity Catalog Volumes Overview](https://docs.databricks.com/en/volumes/)
- [Files in Databricks](https://docs.databricks.com/en/files/)
- [DBFS to Unity Catalog Migration](https://docs.databricks.com/en/dbfs/unity-catalog.html)
- [MLflow on Databricks](https://docs.databricks.com/en/mlflow/)

### Related Documentation in This Repository

- [README.md](README.md) - Main scanner documentation
- [DBFS_DEPRECATION_NOTICE.md](DBFS_DEPRECATION_NOTICE.md) - DBFS deprecation details
- [PATTERNS_USAGE.md](PATTERNS_USAGE.md) - General pattern configuration guide
- [OUTPUT_EXAMPLES.md](OUTPUT_EXAMPLES.md) - Example scan outputs

## Support and Feedback

- **GitHub Issues**: Report bugs or request features
- **GitHub Discussions**: Ask questions and share experiences
- **Pull Requests**: Contribute additional patterns or improvements

---

**Last Updated:** January 2026

**Status:** Active - Aligned with current Unity Catalog best practices
