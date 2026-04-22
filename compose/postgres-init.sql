-- Initialize local Postgres for CDC demo.
-- Run automatically by docker-entrypoint-initdb.d on first boot.

-- Create dedicated Debezium user
CREATE USER debezium_user WITH REPLICATION PASSWORD 'debezium';
GRANT CONNECT ON DATABASE analytics TO debezium_user;

-- Orders table (the main CDC target)
CREATE SCHEMA IF NOT EXISTS public;

CREATE TABLE IF NOT EXISTS public.orders (
    order_id VARCHAR(36) PRIMARY KEY,
    customer_id VARCHAR(36) NOT NULL,
    product_id VARCHAR(36) NOT NULL,
    qty INT NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    order_ts TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.order_items (
    item_id VARCHAR(36) PRIMARY KEY,
    order_id VARCHAR(36) NOT NULL REFERENCES public.orders(order_id),
    sku VARCHAR(64) NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    qty INT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.customers (
    customer_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(128),
    email VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Grant Debezium user SELECT on replication tables
GRANT USAGE ON SCHEMA public TO debezium_user;
GRANT SELECT ON public.orders TO debezium_user;
GRANT SELECT ON public.order_items TO debezium_user;
GRANT SELECT ON public.customers TO debezium_user;

-- Publication for Debezium to subscribe to
CREATE PUBLICATION debezium_orders_pub FOR TABLE
    public.orders, public.order_items, public.customers;
