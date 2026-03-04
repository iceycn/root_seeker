package com.ruoyi.system.mapper;

import com.ruoyi.system.domain.RepoIndexStatus;
import java.util.List;
import org.apache.ibatis.annotations.Param;

/**
 * 仓库索引状态 数据层
 * 状态：未索引|索引中|已索引|清理中
 */
public interface RepoIndexStatusMapper {
    RepoIndexStatus selectByServiceName(String serviceName);
    List<RepoIndexStatus> selectAll();
    int insertOrUpdate(RepoIndexStatus status);

    /** 乐观更新：操作前先改本地状态（索引中/清理中），可只更新其中一个 */
    int updateQdrantStatus(@Param("serviceName") String serviceName, @Param("qdrantStatus") String qdrantStatus);
    int updateZoektStatus(@Param("serviceName") String serviceName, @Param("zoektStatus") String zoektStatus);
    int updateBothStatus(@Param("serviceName") String serviceName, @Param("qdrantStatus") String qdrantStatus, @Param("zoektStatus") String zoektStatus);

    /** 回调更新 Qdrant 状态 */
    int updateQdrantFromCallback(@Param("serviceName") String serviceName, @Param("qdrantStatus") String qdrantStatus, @Param("qdrantCount") int qdrantCount);

    /** 回调更新 Zoekt 状态 */
    int updateZoektFromCallback(@Param("serviceName") String serviceName, @Param("zoektStatus") String zoektStatus);
}
