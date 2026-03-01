package com.ruoyi.system.service;

import java.util.List;
import com.ruoyi.system.domain.GitSourceRepo;

/**
 * Git 仓库 服务层
 */
public interface IGitSourceRepoService {
    List<GitSourceRepo> selectRepoList(GitSourceRepo repo);
    GitSourceRepo selectRepoById(String id);
    int insertRepo(GitSourceRepo repo);
    int updateRepo(GitSourceRepo repo);
    int deleteRepoById(String id);
    int deleteRepoByIds(String[] ids);
}
