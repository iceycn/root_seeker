package com.ruoyi.system.domain;

import java.util.Date;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.ruoyi.common.annotation.Excel;

/**
 * Git 仓库 git_source_repos
 */
public class GitSourceRepo {
    @Excel(name = "仓库ID")
    private String id;
    @Excel(name = "仓库名")
    private String fullName;
    /** 完整路径（org/group/repo），用于 API */
    private String fullPath;
    /** 平台返回的 ID */
    private String platformId;
    @Excel(name = "Git URL")
    private String gitUrl;
    @Excel(name = "默认分支")
    private String defaultBranch;
    private String description;
    /** 选中的分支，JSON 数组格式 */
    private String selectedBranches;
    @Excel(name = "启用", readConverterExp = "0=否,1=是")
    private Integer enabled;
    @Excel(name = "本地目录")
    private String localDir;
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    private Date lastSyncAt;
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    private Date createdAt;
    private String extra;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getFullName() { return fullName; }
    public void setFullName(String fullName) { this.fullName = fullName; }
    public String getFullPath() { return fullPath; }
    public void setFullPath(String fullPath) { this.fullPath = fullPath; }
    public String getPlatformId() { return platformId; }
    public void setPlatformId(String platformId) { this.platformId = platformId; }
    public String getGitUrl() { return gitUrl; }
    public void setGitUrl(String gitUrl) { this.gitUrl = gitUrl; }
    public String getDefaultBranch() { return defaultBranch; }
    public void setDefaultBranch(String defaultBranch) { this.defaultBranch = defaultBranch; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getSelectedBranches() { return selectedBranches; }
    public void setSelectedBranches(String selectedBranches) { this.selectedBranches = selectedBranches; }
    public Integer getEnabled() { return enabled; }
    public void setEnabled(Integer enabled) { this.enabled = enabled; }
    public String getLocalDir() { return localDir; }
    public void setLocalDir(String localDir) { this.localDir = localDir; }
    public Date getLastSyncAt() { return lastSyncAt; }
    public void setLastSyncAt(Date lastSyncAt) { this.lastSyncAt = lastSyncAt; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public String getExtra() { return extra; }
    public void setExtra(String extra) { this.extra = extra; }
}
