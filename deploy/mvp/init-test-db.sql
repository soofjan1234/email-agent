-- 独立测试角色不允许连接业务库；禁止测试夹具清空业务数据。
CREATE ROLE email_agent_test LOGIN PASSWORD 'local-test-only';
CREATE DATABASE email_agent_snowflake_test OWNER email_agent_test;
REVOKE CONNECT ON DATABASE email_agent FROM PUBLIC;
GRANT CONNECT ON DATABASE email_agent TO email_agent;
\connect email_agent_snowflake_test
CREATE EXTENSION IF NOT EXISTS vector;
