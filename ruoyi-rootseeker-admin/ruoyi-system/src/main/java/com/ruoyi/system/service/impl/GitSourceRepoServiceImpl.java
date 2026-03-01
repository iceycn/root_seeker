package com.ruoyi.system.service.impl;

import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.ruoyi.system.domain.GitSourceRepo;
import com.ruoyi.system.mapper.GitSourceRepoMapper;
import com.ruoyi.system.service.IGitSourceRepoService;

@Service
public class GitSourceRepoServiceImpl implements IGitSourceRepoService {
    @Autowired
    private GitSourceRepoMapper repoMapper;

    @Override
    public List<GitSourceRepo> selectRepoList(GitSourceRepo repo) {
        return repoMapper.selectRepoList(repo);
    }

    @Override
    public GitSourceRepo selectRepoById(String id) {
        return repoMapper.selectRepoById(id);
    }

    @Override
    public int insertRepo(GitSourceRepo repo) {
        return repoMapper.insertRepo(repo);
    }

    @Override
    public int updateRepo(GitSourceRepo repo) {
        return repoMapper.updateRepo(repo);
    }

    @Override
    public int deleteRepoById(String id) {
        return repoMapper.deleteRepoById(id);
    }

    @Override
    public int deleteRepoByIds(String[] ids) {
        return repoMapper.deleteRepoByIds(ids);
    }
}
