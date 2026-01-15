# DBFS Deprecation Notice - Important Update

## 🚨 Critical Information

**DBFS (Databricks File System) is deprecated as of 2026.**

According to official Databricks documentation, both DBFS root and DBFS mounts are deprecated and **new accounts are provisioned without access to these features**.

---

## What Changed?

### ❌ Deprecated (Do NOT Use)

| Feature | Path Format | Status |
|---------|------------|--------|
| DBFS Root | `/dbfs/...` | Deprecated |
| DBFS Mounts | `/mnt/...` | Deprecated |
| DBFS URI | `dbfs:/...` | Deprecated |

**Why deprecated?**
- DBFS bypasses Unity Catalog governance entirely
- No data governance, auditing, or fine-grained access controls
- New security and compliance requirements

### ✅ Current Recommendations (2026)

| Solution | Path Format | Use Case |
|----------|------------|----------|
| **Unity Catalog Volumes** | `/Volumes/catalog/schema/volume/` | **Primary recommendation** - Non-tabular data |
| **Unity Catalog Tables** | `catalog.schema.table` | Structured data (Delta Lake) |
| **External Locations** | Cloud URIs with UC governance | Existing cloud storage |
| **Workspace Files** | `/Workspace/...` | Small files, dev/test only |

---

## Migration Guide

### Step 1: Understanding Unity Catalog Volumes

Unity Catalog Volumes provide governance over non-tabular data files:
- **Managed Volumes**: Databricks manages storage (recommended for most cases)
- **External Volumes**: Add governance to existing cloud storage

### Step 2: Creating a Volume

```sql
-- Create a volume in Unity Catalog
CREATE VOLUME IF NOT EXISTS main.default.data_files;

-- Create with comment
CREATE VOLUME IF NOT EXISTS main.analytics.exports
COMMENT 'Storage for data exports and reports';
```

### Step 3: Update Your Code

#### Before (DBFS - Deprecated):
```python
# ❌ Old way - DBFS (deprecated)
df.to_csv("/dbfs/mnt/data/output.csv")
dbutils.fs.put("dbfs:/data/file.txt", content)
open("/dbfs/tmp/report.txt", "w")
```

#### After (Unity Catalog Volumes):
```python
# ✅ New way - Unity Catalog Volumes
df.to_csv("/Volumes/main/default/data_files/output.csv")

# For text files
with open("/Volumes/main/default/data_files/file.txt", "w") as f:
    f.write(content)

# For larger operations, use Spark
df.write.format("csv").save("/Volumes/main/default/data_files/output/")
```

#### For Structured Data (Recommended):
```python
# ✅ Best practice - Use Delta Lake tables
df.write.format("delta").mode("overwrite").saveAsTable("main.analytics.sales_data")

# Read back
spark.read.table("main.analytics.sales_data")
```

---

## Updated Pattern File Recommendations

The `patterns_cwd_file_writes.yaml` file has been updated to reflect current best practices:

### Old Recommendations (Deprecated):
```python
# ❌ No longer recommended
open("file.txt", "w")  →  open("/dbfs/data/file.txt", "w")
df.to_csv("out.csv")   →  df.write.format("csv").save("dbfs:/path/")
```

### New Recommendations (2026):
```python
# ✅ Current best practice
open("file.txt", "w")  →  open("/Volumes/catalog/schema/volume/file.txt", "w")
df.to_csv("out.csv")   →  df.write.format("delta").saveAsTable("catalog.schema.table")
```

---

## Quick Reference: Path Formats

### Unity Catalog Volumes (Recommended)
```python
# Reading
with open("/Volumes/main/default/my_volume/input.txt", "r") as f:
    data = f.read()

# Writing
with open("/Volumes/main/default/my_volume/output.txt", "w") as f:
    f.write("Hello, World!")

# Pandas
df.to_csv("/Volumes/main/default/my_volume/data.csv")
df = pd.read_csv("/Volumes/main/default/my_volume/data.csv")

# NumPy
np.save("/Volumes/main/default/my_volume/array.npy", my_array)

# Using dbutils (alternative)
dbutils.fs.put("/Volumes/main/default/my_volume/file.txt", "content")
```

### Unity Catalog Tables (For Structured Data)
```python
# Spark DataFrame - Best for structured data
df.write.format("delta").saveAsTable("main.analytics.sales")

# Read back
sales_df = spark.read.table("main.analytics.sales")

# Pandas to Spark to Table
spark_df = spark.createDataFrame(pandas_df)
spark_df.write.format("delta").saveAsTable("main.analytics.data")
```

---

## Benefits of Unity Catalog Volumes

### 1. **Governance & Security**
- Fine-grained access controls (GRANT/REVOKE)
- Audit logging of all file operations
- Data lineage tracking

### 2. **Cross-Workspace Sharing**
- Share data across workspaces securely
- Consistent access policies
- No need for mounts or complex configurations

### 3. **Cloud-Agnostic**
- Works across AWS, Azure, and GCP
- Consistent API regardless of cloud provider
- Easy multi-cloud data management

### 4. **Better Organization**
- Three-level namespace: catalog.schema.volume
- Clear data ownership and organization
- Easier discovery and management

---

## Checking Your Current Usage

### Scan Your Workspace
```bash
# Use the scanner to find files being written to CWD
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --config patterns_cwd_file_writes.yaml \
  --language python \
  --output cwd_files_scan.txt
```

### Common Patterns to Look For
1. `open("file.txt", "w")` - Writing to CWD
2. `df.to_csv("output.csv")` - Pandas exports
3. `"/dbfs/..."` or `"dbfs:/..."` - Deprecated DBFS usage
4. `"/mnt/..."` - Deprecated DBFS mounts

---

## FAQs

### Q: Can I still use `/dbfs/` paths?
**A:** While they may work on older accounts, they are deprecated. New accounts don't have access. Migrate to Unity Catalog Volumes.

### Q: What about temporary files?
**A:** For truly temporary files within a single job, use `/tmp/` with explicit cleanup. For any data that needs persistence, use Unity Catalog Volumes.

### Q: Do I need to migrate all at once?
**A:** No, you can migrate incrementally. Start with new projects using Unity Catalog, then migrate existing code over time.

### Q: What if I don't have Unity Catalog enabled?
**A:** Contact your Databricks workspace administrator to enable Unity Catalog. It's the future of Databricks data governance and is required for modern features.

### Q: Can I use direct cloud storage paths (s3://, etc.)?
**A:** Yes, but using Unity Catalog External Locations provides governance. Direct paths are acceptable for integration with external systems.

---

## Official Documentation References

- **Unity Catalog Volumes Overview:**
  - [AWS](https://docs.databricks.com/aws/en/volumes/)
  - [Azure](https://learn.microsoft.com/en-us/azure/databricks/volumes/)

- **Best Practices for DBFS and Unity Catalog:**
  - [AWS](https://docs.databricks.com/aws/en/dbfs/unity-catalog)
  - [Azure](https://learn.microsoft.com/en-us/azure/databricks/dbfs/unity-catalog)

- **Unity Catalog Best Practices:**
  - [AWS](https://docs.databricks.com/aws/en/data-governance/unity-catalog/best-practices)

- **Work with Files on Databricks:**
  - [AWS](https://docs.databricks.com/aws/en/files/)
  - [Azure](https://learn.microsoft.com/en-us/azure/databricks/files/)

- **DBFS Documentation (includes deprecation notice):**
  - [AWS](https://docs.databricks.com/aws/en/dbfs/)
  - [Azure](https://learn.microsoft.com/en-us/azure/databricks/dbfs/)

---

## Timeline and Action Items

### Immediate Actions
1. ✅ Review patterns file - updated with current recommendations
2. ✅ Understand Unity Catalog Volumes concept
3. ⚠️ Scan your workspace for CWD file writes
4. ⚠️ Identify usage of deprecated DBFS paths

### Short-term (Next Sprint)
1. Create Unity Catalog volumes for your team/project
2. Start using volumes for all new development
3. Update documentation and coding standards

### Medium-term (Next Quarter)
1. Migrate existing code from DBFS to Unity Catalog Volumes
2. Update CI/CD pipelines
3. Train team on Unity Catalog best practices

### Long-term (Ongoing)
1. Phase out all DBFS usage
2. Establish governance policies using Unity Catalog
3. Monitor and audit file access patterns

---

**Last Updated:** January 2026
**Pattern File Version:** Updated for Unity Catalog

For questions or issues, refer to the official Databricks documentation or contact your Databricks support team.
