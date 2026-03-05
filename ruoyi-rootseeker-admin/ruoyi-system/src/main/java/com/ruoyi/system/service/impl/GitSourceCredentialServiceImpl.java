package com.ruoyi.system.service.impl;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.ruoyi.system.domain.GitSourceCredential;
import com.ruoyi.system.mapper.GitSourceCredentialMapper;
import com.ruoyi.system.service.IGitSourceCredentialService;

@Service
public class GitSourceCredentialServiceImpl implements IGitSourceCredentialService {
    @Autowired
    private GitSourceCredentialMapper credentialMapper;

    @Override
    public GitSourceCredential getCredential() {
        GitSourceCredential c = credentialMapper.selectById(1);
        if (c == null) {
            c = new GitSourceCredential();
            c.setId(1);
        }
        return c;
    }

    @Override
    public int saveCredential(GitSourceCredential credential) {
        credential.setId(1);
        if (credential.getCloneProtocol() == null || credential.getCloneProtocol().trim().isEmpty()) {
            credential.setCloneProtocol("https");
        }
        GitSourceCredential existing = credentialMapper.selectById(1);
        if (existing == null) {
            return credentialMapper.insert(credential);
        }
        return credentialMapper.update(credential);
    }
}
