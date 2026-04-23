# Polaris module

Apache Polaris on ECS Fargate — Iceberg REST catalog shared across Flink, Spark, Trino.

Usage:

```hcl
module "polaris" {
  source               = "./modules/polaris"
  name_prefix          = var.name_prefix
  vpc_id               = module.vpc.vpc_id
  subnet_ids           = module.vpc.private_subnet_ids
  security_group_ids   = [aws_security_group.polaris.id]
  warehouse_bucket_arn = module.s3.iceberg_warehouse_arn
}
```

## Engine config snippets

### Flink (via `sql-client.sh`)

```sql
CREATE CATALOG polaris WITH (
  'type' = 'iceberg',
  'catalog-impl' = 'org.apache.iceberg.rest.RESTCatalog',
  'uri' = '${rest_catalog_url}',
  'warehouse' = 's3://lakehouse-warehouse/'
);
```

### Spark

```python
spark.conf.set("spark.sql.catalog.polaris", "org.apache.iceberg.spark.SparkCatalog")
spark.conf.set("spark.sql.catalog.polaris.type", "rest")
spark.conf.set("spark.sql.catalog.polaris.uri", "${rest_catalog_url}")
```

### Trino

```properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=${rest_catalog_url}
```
