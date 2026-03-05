package com.ruoyi.system.domain;

import java.util.Date;
import com.fasterxml.jackson.annotation.JsonFormat;

/**
 * 仓库索引状态 repo_index_status（由 RootSeeker 回调更新）
 * 状态流转：未索引->索引中->已索引；已索引->清理中->未索引
 */
public class RepoIndexStatus {
    private String serviceName;
    private String qdrantStatus;   // 未索引|索引中|已索引|清理中
    private Integer qdrantCount;
    private String zoektStatus;   // 未索引|索引中|已索引|清理中
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    private Date updatedAt;

    public String getServiceName() { return serviceName; }
    public void setServiceName(String serviceName) { this.serviceName = serviceName; }
    public String getQdrantStatus() { return qdrantStatus; }
    public void setQdrantStatus(String qdrantStatus) { this.qdrantStatus = qdrantStatus; }
    public Integer getQdrantCount() { return qdrantCount; }
    public void setQdrantCount(Integer qdrantCount) { this.qdrantCount = qdrantCount; }
    public String getZoektStatus() { return zoektStatus; }
    public void setZoektStatus(String zoektStatus) { this.zoektStatus = zoektStatus; }
    public Date getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Date updatedAt) { this.updatedAt = updatedAt; }
}
