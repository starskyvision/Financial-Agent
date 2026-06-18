-- ============================================
-- 金融多智能体协作系统 - 数据库初始化 (PostgreSQL)
-- ============================================

-- 启用 pgvector 扩展（pgvector/pgvector 镜像自带，标准 postgres 需手动安装）
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector extension not available — vector search disabled';
END $$;

-- 财务数据中心
CREATE TABLE IF NOT EXISTS financial_data (
    id BIGSERIAL PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    metric_value NUMERIC(20, 4),
    source VARCHAR(32) NOT NULL DEFAULT 'akshare',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fd_company_date ON financial_data (company_code, report_date);
CREATE INDEX IF NOT EXISTS idx_fd_metric ON financial_data (metric_name);

COMMENT ON TABLE financial_data IS '财务数据中心';
COMMENT ON COLUMN financial_data.company_code IS '股票代码';
COMMENT ON COLUMN financial_data.report_date IS '报告期';
COMMENT ON COLUMN financial_data.metric_name IS '指标名称';
COMMENT ON COLUMN financial_data.metric_value IS '指标值';
COMMENT ON COLUMN financial_data.source IS '数据来源 akshare/tushare/wind';

-- 文档切片
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    doc_type VARCHAR(32) NOT NULL,
    doc_title VARCHAR(256),
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    content_zh TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_docs_company ON documents (company_code, doc_type);

COMMENT ON TABLE documents IS '文档切片';
COMMENT ON COLUMN documents.company_code IS '关联股票代码';
COMMENT ON COLUMN documents.doc_type IS '文档类型 report/announcement/transcript';

-- 向量列 + 索引（仅 pgvector 扩展可用时添加）
DO $$
BEGIN
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(1024);
    CREATE INDEX IF NOT EXISTS idx_docs_embedding ON documents USING hnsw (embedding vector_cosine_ops);
    COMMENT ON COLUMN documents.embedding IS 'BGE-M3 1024维向量';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector not available — vector column skipped';
END $$;

-- 任务记录
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    company_name VARCHAR(64),
    report_date DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    progress INT DEFAULT 0,
    result JSONB,
    error_log TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_company ON tasks (company_code);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at);

COMMENT ON TABLE tasks IS '任务记录';
COMMENT ON COLUMN tasks.progress IS '进度 0-100';

-- 更新触发器：tasks.updated_at 自动更新
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;
CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
