package com.ruoyi.system.mapper;

import java.util.List;
import com.ruoyi.system.domain.GitSourceRepo;

/**
 * Git 仓库 数据层
 */
public interface GitSourceRepoMapper {
    List<GitSourceRepo> selectRepoList(GitSourceRepo repo);
    GitSourceRepo selectRepoById(String id);
    int insertRepo(GitSourceRepo repo);
    int updateRepo(GitSourceRepo repo);
    int deleteRepoById(String id);
    int deleteRepoByIds(String[] ids);
}
