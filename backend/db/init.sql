-- ============================================
-- 金融多智能体协作系统 - 数据库初始化
-- ============================================

CREATE DATABASE IF NOT EXISTS financial_agent
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE financial_agent;

-- 财务数据中心
CREATE TABLE IF NOT EXISTS financial_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL COMMENT '股票代码',
    report_date DATE NOT NULL COMMENT '报告期',
    metric_name VARCHAR(64) NOT NULL COMMENT '指标名称',
    metric_value DECIMAL(20, 4) COMMENT '指标值',
    metric_unit VARCHAR(16) COMMENT '单位',
    source VARCHAR(32) NOT NULL DEFAULT 'wind' COMMENT '数据来源 wind/pdf/llm',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_company_date (company_code, report_date),
    INDEX idx_metric (metric_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='财务数据中心';

-- 文档切片
CREATE TABLE IF NOT EXISTS documents (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL COMMENT '关联股票',
    doc_type VARCHAR(32) NOT NULL COMMENT '文档类型 report/announcement/transcript',
    doc_title VARCHAR(256) COMMENT '文档标题',
    chunk_index INT NOT NULL COMMENT '切片序号',
    content TEXT NOT NULL COMMENT '原文内容',
    content_zh TEXT COMMENT '中文摘要',
    vector_id VARCHAR(64) COMMENT 'Milvus 向量 ID',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_company_doc (company_code, doc_type),
    INDEX idx_vector (vector_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档切片';

-- 任务记录
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY COMMENT '任务 UUID',
    company_code VARCHAR(10) NOT NULL COMMENT '目标股票',
    company_name VARCHAR(64) COMMENT '公司名称',
    report_date DATE COMMENT '报告期',
    status ENUM('pending', 'running', 'done', 'failed') NOT NULL DEFAULT 'pending',
    progress INT DEFAULT 0 COMMENT '进度 0-100',
    result JSON COMMENT '结果摘要',
    error_log TEXT COMMENT '错误日志',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_company (company_code),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务记录';
