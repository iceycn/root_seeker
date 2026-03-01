package com.ruoyi.system.service;

import com.ruoyi.system.domain.GitSourceCredential;

/**
 * Git 凭证 服务层
 */
public interface IGitSourceCredentialService {
    GitSourceCredential getCredential();
    int saveCredential(GitSourceCredential credential);
}
