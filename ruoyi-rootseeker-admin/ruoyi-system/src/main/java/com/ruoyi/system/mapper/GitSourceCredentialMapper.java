package com.ruoyi.system.mapper;

import com.ruoyi.system.domain.GitSourceCredential;

/**
 * Git 凭证 数据层
 */
public interface GitSourceCredentialMapper {
    GitSourceCredential selectById(Integer id);
    int insert(GitSourceCredential credential);
    int update(GitSourceCredential credential);
}
