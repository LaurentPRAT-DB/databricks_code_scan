#!/usr/bin/env python3
"""
Example Python file to test exception patterns.

This file contains both legitimate Unity Catalog usage (should be skipped)
and problematic local writes (should be detected).
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================================
# SECTION 1: GOOD - Should be SKIPPED by exceptions
# ============================================================================

# Good: Unity Catalog Volume paths (EXCEPTION - SKIP)
df = pd.DataFrame({"a": [1, 2, 3]})
df.to_csv("/Volumes/my_catalog/my_schema/exports/output.csv")
df.to_parquet("/Volumes/my_catalog/my_schema/exports/data.parquet")

# Good: Cloud storage paths (EXCEPTION - SKIP)
df.to_csv("s3://my-bucket/data/output.csv")
df.to_csv("abfss://container@account.dfs.core.windows.net/data/output.csv")
df.to_csv("gs://my-bucket/data/output.csv")

# Good: System temp directory (EXCEPTION - SKIP)
df.to_csv("/tmp/temp_processing.csv")
np.save("/tmp/temp_array.npy", np.array([1, 2, 3]))

# Good: DBFS paths (deprecated but intentional - EXCEPTION - SKIP)
df.to_csv("/dbfs/mnt/data/output.csv")
df.to_parquet("dbfs:/mnt/data/processed.parquet")

# Good: Comments with code examples (EXCEPTION - SKIP)
# Example usage: df.to_csv("output.csv")
# To save: model.save("model.h5")

# Good: Docstring examples (EXCEPTION - SKIP)
def save_data():
    """
    Save data to file.

    Example:
        df.to_csv("output.csv")
        np.save("array.npy", data)
    """
    pass

# Good: Variable assignment, not actual file operation (EXCEPTION - SKIP)
output_filename = "results.csv"
model_name = "trained_model.h5"

# Good: f-strings with variables that may be absolute (EXCEPTION - SKIP)
base_path = "/Volumes/catalog/schema/volume"
df.to_csv(f"{base_path}/output.csv")
np.save(f"{base_path}/array.npy", np.array([1, 2, 3]))

# Good: Format strings with variables (EXCEPTION - SKIP)
path = "/Volumes/catalog/schema/volume"
df.to_csv("{}/output.csv".format(path))

# Good: Environment variable paths (EXCEPTION - SKIP)
import os
output_dir = os.environ.get('OUTPUT_PATH', '/default/path')
df.to_csv(f"{output_dir}/results.csv")

# ============================================================================
# SECTION 2: BAD - Should be DETECTED (not exceptions)
# ============================================================================

# Bad: Direct local write to CWD (SHOULD BE DETECTED)
df.to_csv("bad_output.csv")
df.to_parquet("bad_data.parquet")

# Bad: NumPy save to CWD (SHOULD BE DETECTED)
np.save("bad_array.npy", np.array([1, 2, 3]))
np.savez("bad_arrays.npz", a=np.array([1, 2, 3]))

# Bad: open() with relative path (SHOULD BE DETECTED)
with open("bad_file.txt", "w") as f:
    f.write("This is problematic")

# Bad: Path write operations (SHOULD BE DETECTED)
Path("bad_output.json").write_text('{"data": [1, 2, 3]}')
Path("bad_binary.dat").write_bytes(b"binary data")

# Bad: ML model save to CWD (SHOULD BE DETECTED)
# Uncomment to test:
# import tensorflow as tf
# model = tf.keras.Sequential()
# model.save("bad_model.h5")  # SHOULD BE DETECTED

# Bad: Pickle to CWD (SHOULD BE DETECTED)
import pickle
with open("bad_model.pkl", "wb") as f:
    pickle.dump({"model": "data"}, f)

# Bad: Image save to CWD (SHOULD BE DETECTED)
# Uncomment to test:
# import matplotlib.pyplot as plt
# plt.plot([1, 2, 3])
# plt.savefig("bad_chart.png")  # SHOULD BE DETECTED

# Bad: Archive creation in CWD (SHOULD BE DETECTED)
import zipfile
with zipfile.ZipFile("bad_archive.zip", "w") as zf:
    zf.writestr("data.txt", "content")

print("Test file complete")
print(f"Expected detections: ~10 bad patterns")
print(f"Expected skips: ~15+ good patterns (exceptions)")
