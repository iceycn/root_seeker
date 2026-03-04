package com.ruoyi.system.service;

import com.ruoyi.system.domain.RepoIndexStatus;
import java.util.List;
import java.util.Map;

/**
 * 仓库索引状态 服务层
 */
public interface IRepoIndexStatusService {
    RepoIndexStatus getByServiceName(String serviceName);
    List<RepoIndexStatus> listAll();
    int upsert(RepoIndexStatus status);
    /** 乐观更新：操作前先改本地状态。qdrantStatus/zoektStatus 为 索引中 或 清理中，null 表示不更新 */
    void setStatus(String serviceName, String qdrantStatus, String zoektStatus);
    /** 根据回调 payload 更新状态 */
    void updateFromCallback(Map<String, Object> payload);

    /**
     * 从 RootSeeker 实时状态同步到本地 repo_index_status。
     * 将 RootSeeker GET /index/status 返回的 repos 列表逐条转换为 callback 格式并调用 updateFromCallback。
     */
    int syncFromRootSeekerStatus(List<Map<String, Object>> repos);
}
