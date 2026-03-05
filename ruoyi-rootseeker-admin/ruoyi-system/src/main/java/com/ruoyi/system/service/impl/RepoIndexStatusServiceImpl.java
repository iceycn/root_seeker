package com.ruoyi.system.service.impl;

import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.ruoyi.common.utils.StringUtils;
import com.ruoyi.system.domain.RepoIndexStatus;
import com.ruoyi.system.mapper.RepoIndexStatusMapper;
import com.ruoyi.system.service.IRepoIndexStatusService;
import java.util.Map;

@Service
public class RepoIndexStatusServiceImpl implements IRepoIndexStatusService {
    private static final Logger log = LoggerFactory.getLogger(RepoIndexStatusServiceImpl.class);
    private static final String S_INDEXING = "索引中";
    private static final String S_INDEXED = "已索引";
    private static final String S_REMOVING = "清理中";
    private static final String S_NOT_INDEXED = "未索引";

    @Autowired
    private RepoIndexStatusMapper mapper;

    @Override
    public RepoIndexStatus getByServiceName(String serviceName) {
        return mapper.selectByServiceName(serviceName);
    }

    @Override
    public List<RepoIndexStatus> listAll() {
        return mapper.selectAll();
    }

    @Override
    public int upsert(RepoIndexStatus status) {
        return mapper.insertOrUpdate(status);
    }

    @Override
    public void setStatus(String serviceName, String qdrantStatus, String zoektStatus) {
        if (StringUtils.isNotEmpty(qdrantStatus) && StringUtils.isNotEmpty(zoektStatus)) {
            mapper.updateBothStatus(serviceName, qdrantStatus, zoektStatus);
        } else if (StringUtils.isNotEmpty(qdrantStatus)) {
            mapper.updateQdrantStatus(serviceName, qdrantStatus);
        } else if (StringUtils.isNotEmpty(zoektStatus)) {
            mapper.updateZoektStatus(serviceName, zoektStatus);
        }
    }

    @Override
    public void updateFromCallback(Map<String, Object> payload) {
        if (payload == null) return;
        Object sn = payload.get("service_name");
        if (sn == null || sn.toString().trim().isEmpty()) return;
        String serviceName = sn.toString().trim();

        log.info("[RepoIndexStatus] 回调 service_name={}, task_type={}, status={}",
            serviceName, payload.get("task_type"), payload.get("status"));

        RepoIndexStatus status = getByServiceName(serviceName);
        boolean recordExisted = (status != null);
        if (status == null) {
            status = new RepoIndexStatus();
            status.setServiceName(serviceName);
            status.setQdrantStatus(S_NOT_INDEXED);
            status.setQdrantCount(0);
            status.setZoektStatus(S_NOT_INDEXED);
        }

        String taskType = getStr(payload, "task_type");
        String taskStatus = getStr(payload, "status");

        if ("qdrant".equals(taskType)) {
            if ("completed".equals(taskStatus)) {
                int qc = getInt(payload, "qdrant_count", 0);
                if (recordExisted) {
                    mapper.updateQdrantFromCallback(serviceName, S_INDEXED, qc);
                } else {
                    status.setQdrantStatus(S_INDEXED);
                    status.setQdrantCount(qc);
                    mapper.insertOrUpdate(status);
                }
                log.info("[RepoIndexStatus] qdrant 已索引 service_name={}", serviceName);
                return;
            } else if ("failed".equals(taskStatus)) {
                if (recordExisted) {
                    mapper.updateQdrantFromCallback(serviceName, status.getQdrantStatus(), status.getQdrantCount() != null ? status.getQdrantCount() : 0);
                }
                return;
            }
        } else if ("zoekt".equals(taskType)) {
            if ("completed".equals(taskStatus)) {
                if (recordExisted) {
                    mapper.updateZoektFromCallback(serviceName, S_INDEXED);
                } else {
                    status.setZoektStatus(S_INDEXED);
                    mapper.insertOrUpdate(status);
                }
                log.info("[RepoIndexStatus] zoekt 已索引 service_name={}", serviceName);
                return;
            } else if ("failed".equals(taskStatus)) {
                if (recordExisted) {
                    mapper.updateZoektFromCallback(serviceName, status.getZoektStatus());
                }
                return;
            }
        } else if ("remove_qdrant".equals(taskType) || "remove_zoekt".equals(taskType)) {
            if ("completed".equals(taskStatus)) {
                if ("remove_qdrant".equals(taskType)) {
                    if (!recordExisted) {
                        RepoIndexStatus newStatus = new RepoIndexStatus();
                        newStatus.setServiceName(serviceName);
                        newStatus.setQdrantStatus(S_NOT_INDEXED);
                        newStatus.setQdrantCount(0);
                        newStatus.setZoektStatus(S_NOT_INDEXED);
                        mapper.insertOrUpdate(newStatus);
                    } else {
                        mapper.updateQdrantFromCallback(serviceName, S_NOT_INDEXED, 0);
                    }
                    log.info("[RepoIndexStatus] remove_qdrant 完成 service_name={}", serviceName);
                } else {
                    if (!recordExisted) {
                        RepoIndexStatus newStatus = new RepoIndexStatus();
                        newStatus.setServiceName(serviceName);
                        newStatus.setQdrantStatus(S_NOT_INDEXED);
                        newStatus.setQdrantCount(0);
                        newStatus.setZoektStatus(S_NOT_INDEXED);
                        mapper.insertOrUpdate(newStatus);
                    } else {
                        mapper.updateZoektFromCallback(serviceName, S_NOT_INDEXED);
                    }
                    log.info("[RepoIndexStatus] remove_zoekt 完成 service_name={}", serviceName);
                }
                return;
            } else if ("failed".equals(taskStatus)) {
                if (recordExisted) {
                    if ("remove_qdrant".equals(taskType)) {
                        mapper.updateQdrantFromCallback(serviceName, status.getQdrantStatus(), status.getQdrantCount() != null ? status.getQdrantCount() : 0);
                    } else {
                        mapper.updateZoektFromCallback(serviceName, status.getZoektStatus());
                    }
                }
                return;
            }
        } else if ("resync".equals(taskType)) {
            if ("completed".equals(taskStatus)) {
                int qi = getInt(payload, "qdrant_indexed", 1);
                int qc = getInt(payload, "qdrant_count", 0);
                int zi = getInt(payload, "zoekt_indexed", 1);
                String qs = qi != 0 ? S_INDEXED : S_NOT_INDEXED;
                String zs = zi != 0 ? S_INDEXED : S_NOT_INDEXED;
                if (recordExisted) {
                    mapper.updateQdrantFromCallback(serviceName, qs, qc);
                    mapper.updateZoektFromCallback(serviceName, zs);
                } else {
                    status.setQdrantStatus(qs);
                    status.setQdrantCount(qc);
                    status.setZoektStatus(zs);
                    mapper.insertOrUpdate(status);
                }
                log.info("[RepoIndexStatus] resync 完成 service_name={}", serviceName);
                return;
            } else if ("failed".equals(taskStatus)) {
                if (recordExisted) {
                    mapper.updateQdrantFromCallback(serviceName, status.getQdrantStatus(), status.getQdrantCount() != null ? status.getQdrantCount() : 0);
                    mapper.updateZoektFromCallback(serviceName, status.getZoektStatus());
                }
                return;
            }
        } else if ("sync".equals(taskType)) {
            // 从 RootSeeker 同步：payload 含 qdrant_status, zoekt_status 或 旧格式 qdrant_indexed 等
            String qs = getStr(payload, "qdrant_status");
            if (qs.isEmpty()) {
                boolean qi = parseBool(payload, "qdrant_indexed");
                boolean qiNg = parseBool(payload, "qdrant_indexing");
                boolean qRm = parseBool(payload, "qdrant_removing");
                qs = qRm ? S_REMOVING : (qiNg ? S_INDEXING : (qi ? S_INDEXED : S_NOT_INDEXED));
            }
            String zs = getStr(payload, "zoekt_status");
            if (zs.isEmpty()) {
                boolean zi = parseBool(payload, "zoekt_indexed");
                boolean ziNg = parseBool(payload, "zoekt_indexing");
                boolean zRm = parseBool(payload, "zoekt_removing");
                zs = zRm ? S_REMOVING : (ziNg ? S_INDEXING : (zi ? S_INDEXED : S_NOT_INDEXED));
            }
            Integer qcObj = getIntNullable(payload, "qdrant_count");
            int qc = qcObj != null ? qcObj : 0;
            boolean qUnknown = "未知".equals(qs);
            boolean zUnknown = "未知".equals(zs);
            if (recordExisted) {
                if (!qUnknown) {
                    int keep = status.getQdrantCount() != null ? status.getQdrantCount() : 0;
                    mapper.updateQdrantFromCallback(serviceName, qs, qcObj != null ? qc : keep);
                }
                if (!zUnknown) {
                    mapper.updateZoektFromCallback(serviceName, zs);
                }
            } else {
                status.setQdrantStatus(qUnknown ? S_NOT_INDEXED : qs);
                status.setQdrantCount(qUnknown ? 0 : qc);
                status.setZoektStatus(zUnknown ? S_NOT_INDEXED : zs);
                mapper.insertOrUpdate(status);
            }
            log.info("[RepoIndexStatus] sync 完成 service_name={}", serviceName);
            return;
        }

        mapper.insertOrUpdate(status);
    }

    private static boolean parseBool(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (v == null) return false;
        if (v instanceof Boolean) return (Boolean) v;
        return "true".equalsIgnoreCase(String.valueOf(v));
    }

    @Override
    public int syncFromRootSeekerStatus(List<Map<String, Object>> repos) {
        if (repos == null) return 0;
        int count = 0;
        for (Map<String, Object> r : repos) {
            if (r == null) continue;
            Object sn = r.get("service_name");
            if (sn == null || sn.toString().trim().isEmpty()) continue;
            Map<String, Object> payload = new java.util.HashMap<>(r);
            payload.put("task_type", "sync");
            payload.put("status", "completed");
            updateFromCallback(payload);
            count++;
        }
        return count;
    }

    private static String getStr(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v != null ? v.toString().trim() : "";
    }

    private static int getInt(Map<String, Object> m, String key, int def) {
        Object v = m.get(key);
        if (v == null) return def;
        if (v instanceof Number) return ((Number) v).intValue();
        try {
            return Integer.parseInt(v.toString());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static Integer getIntNullable(Map<String, Object> m, String key) {
        if (m == null || !m.containsKey(key)) return null;
        Object v = m.get(key);
        if (v == null) return null;
        if (v instanceof Number) return ((Number) v).intValue();
        try {
            return Integer.parseInt(v.toString());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
